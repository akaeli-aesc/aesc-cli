"""
Native Vertex AI provider for Gemini 3 models.

This provider directly calls the Vertex AI REST API, correctly handling
the 'global' location which LiteLLM doesn't support properly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any, Self

import httpx
from loguru import logger

try:
    import google.auth
    import google.auth.transport.requests

    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    logger.warning("google-auth not available - install with: pip install google-auth")
    GOOGLE_AUTH_AVAILABLE = False

from aesc.provider.base import ChatProvider, StreamedMessage, ThinkingEffort
from aesc.provider.errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
)
from aesc.provider.message import (
    ContentPart,
    Message,
    TextPart,
    ToolCall,
)
from aesc.provider.tool import Tool
from aesc.provider.usage import TokenUsage


class VertexNativeProvider(ChatProvider):
    """
    Native Vertex AI provider for Gemini 3 models.

    Directly calls the Vertex AI REST API with proper handling for
    the 'global' location required by Gemini 3 models.
    """

    name = "vertex_native"

    def __init__(
        self,
        *,
        model: str,
        project_id: str | None = None,
        location: str = "global",
        stream: bool = True,
        **kwargs: Any,
    ):
        if not GOOGLE_AUTH_AVAILABLE:
            raise ImportError("google-auth is required. Install with: pip install google-auth")

        self.model = model
        self.location = location
        self.stream = stream
        self.kwargs = kwargs

        # Get credentials and project
        self._creds, default_project = google.auth.default()
        self.project_id = project_id or default_project

        if not self.project_id:
            raise ValueError("project_id must be provided or available from default credentials")

        # Build base URL - handle 'global' location specially
        if location == "global":
            self._base_url = (
                f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/global"
            )
        else:
            self._base_url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{location}"

        logger.info(
            f"VertexNativeProvider initialized: model={model}, project={self.project_id}, location={location}"
        )

    def _get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if not self._creds.valid:
            auth_req = google.auth.transport.requests.Request()
            self._creds.refresh(auth_req)
        return self._creds.token

    def _build_url(self, streaming: bool = False) -> str:
        """Build the API URL for the model."""
        action = "streamGenerateContent" if streaming else "generateContent"
        return f"{self._base_url}/publishers/google/models/{self.model}:{action}"

    @property
    def model_name(self) -> str:
        return self.model

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> VertexNativeStreamedMessage:
        """Generate a response using native Vertex AI API."""

        # Build contents array
        contents = []
        for msg in history:
            vertex_msg = self._convert_message(msg)
            if vertex_msg:
                contents.append(vertex_msg)

        # Build request body
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": 8192,
            },
        }

        # Add system instruction if provided
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        # Add tools if provided
        if tools:
            body["tools"] = [{"functionDeclarations": [self._convert_tool(t) for t in tools]}]

        url = self._build_url(streaming=self.stream)
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        if self.stream:
            headers["Accept"] = "text/event-stream"

        logger.debug(f"Vertex AI request to {url}")

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                if self.stream:
                    # Streaming request
                    async with client.stream("POST", url, headers=headers, json=body) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            raise APIStatusError(response.status_code, error_text.decode())

                        return VertexNativeStreamedMessage(response, stream=True)
                else:
                    # Non-streaming request
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code != 200:
                        raise APIStatusError(response.status_code, response.text)

                    return VertexNativeStreamedMessage(response.json(), stream=False)

        except httpx.TimeoutException as e:
            raise APITimeoutError(str(e)) from e
        except httpx.ConnectError as e:
            raise APIConnectionError(str(e)) from e
        except Exception as e:
            if isinstance(e, (APIStatusError, APITimeoutError, APIConnectionError)):
                raise
            raise ChatProviderError(f"Vertex AI error: {e}") from e

    def _convert_message(self, msg: Message) -> dict[str, Any] | None:
        """Convert our Message to Vertex AI format."""
        role = "user" if msg.role == "user" else "model"
        parts = []

        for part in msg.content:
            if isinstance(part, TextPart):
                parts.append({"text": part.text})
            elif isinstance(part, ToolCall):
                parts.append(
                    {
                        "functionCall": {
                            "name": part.function.name,
                            "args": json.loads(part.function.arguments)
                            if part.function.arguments
                            else {},
                        }
                    }
                )
            elif hasattr(part, "tool_call_id"):
                # Tool result
                parts.append(
                    {
                        "functionResponse": {
                            "name": getattr(part, "name", "unknown"),
                            "response": {"result": getattr(part, "content", "")},
                        }
                    }
                )

        if not parts:
            return None

        return {"role": role, "parts": parts}

    def _convert_tool(self, tool: Tool) -> dict[str, Any]:
        """Convert our Tool to Vertex AI function declaration format."""
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        """Gemini 3 has built-in thinking, no special config needed."""
        return self

    @property
    def model_parameters(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "project_id": self.project_id,
            "location": self.location,
        }


class VertexNativeStreamedMessage(StreamedMessage):
    """Streamed message from Vertex AI."""

    def __init__(self, response: Any, stream: bool = True):
        self._stream = stream
        self._response = response
        self._id = str(uuid.uuid4())
        self._usage: dict | None = None
        self._iter: AsyncIterator[ContentPart] | None = None

    def __aiter__(self) -> AsyncIterator[ContentPart]:
        if self._stream:
            self._iter = self._stream_response()
        else:
            self._iter = self._non_stream_response()
        return self

    async def __anext__(self) -> ContentPart:
        if self._iter is None:
            raise StopAsyncIteration
        return await self._iter.__anext__()

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def usage(self) -> TokenUsage | None:
        if self._usage:
            return TokenUsage(
                input_other=self._usage.get("promptTokenCount", 0),
                output=self._usage.get("candidatesTokenCount", 0),
            )
        return None

    async def _non_stream_response(self) -> AsyncIterator[ContentPart]:
        """Process non-streaming response."""
        data = self._response

        if "usageMetadata" in data:
            self._usage = data["usageMetadata"]

        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    yield TextPart(text=part["text"])
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    yield ToolCall(
                        id=str(uuid.uuid4()),
                        function=ToolCall.FunctionBody(
                            name=fc["name"],
                            arguments=json.dumps(fc.get("args", {})),
                        ),
                    )

    async def _stream_response(self) -> AsyncIterator[ContentPart]:
        """Process streaming response."""
        buffer = ""

        async for line in self._response.aiter_lines():
            line = line.strip()
            if not line:
                continue

            # Handle SSE format
            if line.startswith("data: "):
                line = line[6:]

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                buffer += line
                try:
                    data = json.loads(buffer)
                    buffer = ""
                except json.JSONDecodeError:
                    continue

            if "usageMetadata" in data:
                self._usage = data["usageMetadata"]

            for candidate in data.get("candidates", []):
                content = candidate.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part:
                        yield TextPart(text=part["text"])
                    elif "functionCall" in part:
                        fc = part["functionCall"]
                        yield ToolCall(
                            id=str(uuid.uuid4()),
                            function=ToolCall.FunctionBody(
                                name=fc["name"],
                                arguments=json.dumps(fc.get("args", {})),
                            ),
                        )
