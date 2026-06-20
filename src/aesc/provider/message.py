"""
Message types for chat providers.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Literal, cast, override

from pydantic import BaseModel, GetCoreSchemaHandler, field_serializer, field_validator
from pydantic_core import core_schema


class MergeableMixin:
    """Mixin for types that can be merged in place during streaming."""

    def merge_in_place(self, other: Any) -> bool:
        """Merge another part into this one. Returns True if successful."""
        return False


class ContentPart(BaseModel, ABC, MergeableMixin):
    """A part of a message content."""

    __content_part_registry: ClassVar[dict[str, type[ContentPart]]] = {}

    type: str
    ...  # to be added by subclasses

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        invalid_subclass_error_msg = (
            f"ContentPart subclass {cls.__name__} must have a `type` field of type `str`"
        )

        type_value = getattr(cls, "type", None)
        if type_value is None or not isinstance(type_value, str):
            raise ValueError(invalid_subclass_error_msg)

        cls.__content_part_registry[type_value] = cls

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        if cls.__name__ == "ContentPart":

            def validate_content_part(value: Any) -> Any:
                if hasattr(value, "__class__") and issubclass(value.__class__, cls):
                    return value

                if isinstance(value, dict) and "type" in value:
                    type_value: Any | None = cast(dict[str, Any], value).get("type")
                    if not isinstance(type_value, str):
                        raise ValueError(f"Cannot validate {value} as ContentPart")
                    target_class = cls.__content_part_registry.get(type_value)
                    if target_class:
                        return target_class.model_validate(value)
                    raise ValueError(f"Unknown ContentPart type: {type_value}")

                raise ValueError(f"Cannot validate {value} as ContentPart")

            return core_schema.no_info_plain_validator_function(validate_content_part)

        return handler(source_type)


class TextPart(ContentPart):
    """Regular text content."""

    type: str = "text"
    text: str

    @override
    def merge_in_place(self, other: Any) -> bool:
        if not isinstance(other, TextPart):
            return False
        self.text += other.text
        return True


class ThinkPart(ContentPart):
    """Thinking/reasoning content with optional encrypted signature (for Gemini 3)."""

    type: str = "think"
    think: str
    encrypted: str | None = None
    """Encrypted thinking content, or thought_signature for Gemini 3."""

    @override
    def merge_in_place(self, other: Any) -> bool:
        if not isinstance(other, ThinkPart):
            return False
        if self.encrypted:
            return False
        self.think += other.think
        if other.encrypted:
            self.encrypted = other.encrypted
        return True


class ImageURLPart(ContentPart):
    """Image URL content part."""

    class ImageURL(BaseModel):
        url: str
        id: str | None = None

    type: str = "image_url"
    image_url: ImageURL


class AudioURLPart(ContentPart):
    """Audio URL content part."""

    class AudioURL(BaseModel):
        url: str
        id: str | None = None

    type: str = "audio_url"
    audio_url: AudioURL


class ToolCall(BaseModel, MergeableMixin):
    """
    A tool call requested by the assistant.

    Includes thought_signature field for Gemini 3 support.
    """

    class FunctionBody(BaseModel):
        name: str
        arguments: str | None

    type: Literal["function"] = "function"
    id: str
    function: FunctionBody
    thought_signature: str | None = None
    """Gemini 3's thought_signature for this tool call."""

    @override
    def merge_in_place(self, other: Any) -> bool:
        if not isinstance(other, ToolCallPart):
            return False
        if self.function.arguments is None:
            self.function.arguments = other.arguments_part
        else:
            self.function.arguments += other.arguments_part or ""
        return True


class ToolCallPart(BaseModel, MergeableMixin):
    """A partial tool call (used during streaming)."""

    arguments_part: str | None = None

    @override
    def merge_in_place(self, other: Any) -> bool:
        if not isinstance(other, ToolCallPart):
            return False
        if self.arguments_part is None:
            self.arguments_part = other.arguments_part
        else:
            self.arguments_part += other.arguments_part or ""
        return True


# Type alias for streamed message parts
StreamedMessagePart = ContentPart | ToolCall | ToolCallPart


class Message(BaseModel):
    """A message in a conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    """The role of the message sender."""

    name: str | None = None

    content: str | list[ContentPart]
    """The content of the message."""

    tool_calls: list[ToolCall] | None = None
    """Tool calls requested by the assistant in this message."""

    tool_call_id: str | None = None
    """The ID of the tool call if this message is a tool response."""

    partial: bool | None = None

    class Config:
        extra = "allow"

    @field_serializer("content")
    def _serialize_content(
        self, content: str | list[ContentPart]
    ) -> str | list[dict[str, Any]] | None:
        if not content:
            return None
        if isinstance(content, str):
            return content
        return [part.model_dump() for part in content]

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_none_content(cls, v: Any | None) -> Any:
        if v is None:
            return ""
        return v

    def to_openai_format(self) -> dict[str, Any]:
        """
        Convert to OpenAI-compatible message format with Gemini 3 thought_signature support.
        """
        result: dict[str, Any] = {"role": self.role}

        # Handle content
        if isinstance(self.content, str):
            result["content"] = self.content
        elif isinstance(self.content, list):
            # Extract text and check for thought_signature
            text_parts = []
            thought_signature = None

            for part in self.content:
                if isinstance(part, TextPart):
                    text_parts.append(part.text)
                elif isinstance(part, ThinkPart) and part.encrypted:
                    thought_signature = part.encrypted

            if text_parts:
                result["content"] = "".join(text_parts)
            else:
                result["content"] = None

            # Handle tool_calls with thought_signature
            if self.tool_calls:
                tool_calls_data = []
                for tc in self.tool_calls:
                    tc_data = {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "",
                        },
                    }
                    # Include thought_signature if present
                    sig = tc.thought_signature or thought_signature
                    if sig:
                        tc_data["extra_content"] = {"google": {"thought_signature": sig}}
                    tool_calls_data.append(tc_data)
                result["tool_calls"] = tool_calls_data
        else:
            result["content"] = self.content

        # Handle standalone tool_calls (not in content list)
        if self.tool_calls and "tool_calls" not in result:
            tool_calls_data = []
            for tc in self.tool_calls:
                tc_data = {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "",
                    },
                }
                if tc.thought_signature:
                    tc_data["extra_content"] = {
                        "google": {"thought_signature": tc.thought_signature}
                    }
                tool_calls_data.append(tc_data)
            result["tool_calls"] = tool_calls_data

        # Tool-specific fields
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.name:
            result["name"] = self.name

        return result
