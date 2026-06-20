from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import aiofiles
import aiofiles.os

from aesc.provider import Message
from aesc.soul.message import system
from aesc.utils.logging import logger
from aesc.utils.path import next_available_rotation


class Context:
    def __init__(self, file_backend: Path):
        self._file_backend = file_backend
        self._history: list[Message] = []
        self._token_count: int = 0
        self._next_checkpoint_id: int = 0
        """The ID of the next checkpoint, starting from 0, incremented after each checkpoint."""

    async def restore(self) -> bool:
        logger.debug("Restoring context from file: {file_backend}", file_backend=self._file_backend)
        if self._history:
            logger.error("The context storage is already modified")
            raise RuntimeError("The context storage is already modified")
        if not self._file_backend.exists():
            logger.debug("No context file found, skipping restoration")
            return False
        if self._file_backend.stat().st_size == 0:
            logger.debug("Empty context file, skipping restoration")
            return False

        async with aiofiles.open(self._file_backend, encoding="utf-8") as f:
            async for line in f:
                if not line.strip():
                    continue
                try:
                    line_json = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Skip corrupted lines

                role = line_json.get("role")
                if role == "_usage":
                    self._token_count = line_json.get("token_count", 0)
                    continue
                if role == "_checkpoint":
                    checkpoint_id = line_json.get("id", 0)
                    self._next_checkpoint_id = checkpoint_id + 1
                    continue
                if role is None:
                    continue  # Skip invalid entries

                message = Message.model_validate(line_json)
                self._history.append(message)

        return True

    @property
    def history(self) -> Sequence[Message]:
        return self._history

    @property
    def token_count(self) -> int:
        return self._token_count

    @property
    def n_checkpoints(self) -> int:
        return self._next_checkpoint_id

    @property
    def has_restored_content(self) -> bool:
        """Returns True if context was restored with existing messages."""
        return len(self._history) > 0

    def get_session_summary(self) -> str:
        """
        Extract a brief summary of the restored session context.

        Looks for compacted context (indicated by system messages about compaction)
        or creates a summary from recent messages.
        """
        if not self._history:
            return ""

        # Look for compacted context marker
        for msg in self._history:
            if msg.role == "assistant":
                content = self._extract_text(msg)
                if "<system>Previous context has been compacted" in content:
                    # Extract the compacted summary (everything after the system tag)
                    parts = content.split("</system>", 1)
                    if len(parts) > 1:
                        return parts[1].strip()

        # No compacted context - create a brief summary from recent messages
        summary_parts = []
        for msg in self._history[-5:]:  # Last 5 messages
            content = self._extract_text(msg)
            if content:
                brief = content[:200] + "..." if len(content) > 200 else content
                summary_parts.append(f"[{msg.role}]: {brief}")

        return "\n".join(summary_parts) if summary_parts else ""

    def _extract_text(self, msg: Message) -> str:
        """Extract text content from a message."""
        if isinstance(msg.content, str):
            return msg.content
        text_parts = []
        for part in msg.content:
            if hasattr(part, "text"):
                text_parts.append(str(part.text))
        return "\n".join(text_parts)

    async def checkpoint(self, add_user_message: bool):
        checkpoint_id = self._next_checkpoint_id
        self._next_checkpoint_id += 1
        logger.debug("Checkpointing, ID: {id}", id=checkpoint_id)

        async with aiofiles.open(self._file_backend, "a", encoding="utf-8") as f:
            await f.write(json.dumps({"role": "_checkpoint", "id": checkpoint_id}) + "\n")
        if add_user_message:
            await self.append_message(
                Message(role="user", content=[system(f"CHECKPOINT {checkpoint_id}")])
            )

    async def revert_to(self, checkpoint_id: int):
        """
        Revert the context to the specified checkpoint.
        After this, the specified checkpoint and all subsequent content will be
        removed from the context. File backend will be rotated.

        Args:
            checkpoint_id (int): The ID of the checkpoint to revert to. 0 is the first checkpoint.

        Raises:
            ValueError: When the checkpoint does not exist.
            RuntimeError: When no available rotation path is found.
        """

        logger.debug("Reverting checkpoint, ID: {id}", id=checkpoint_id)
        if checkpoint_id >= self._next_checkpoint_id:
            logger.error("Checkpoint {checkpoint_id} does not exist", checkpoint_id=checkpoint_id)
            raise ValueError(f"Checkpoint {checkpoint_id} does not exist")

        # rotate the history file
        rotated_file_path = await next_available_rotation(self._file_backend)
        if rotated_file_path is None:
            logger.error("No available rotation path found")
            raise RuntimeError("No available rotation path found")
        await aiofiles.os.rename(self._file_backend, rotated_file_path)
        logger.debug(
            "Rotated history file: {rotated_file_path}", rotated_file_path=rotated_file_path
        )

        # restore the context until the specified checkpoint
        self._history.clear()
        self._token_count = 0
        self._next_checkpoint_id = 0
        async with (
            aiofiles.open(rotated_file_path, encoding="utf-8") as old_file,
            aiofiles.open(self._file_backend, "w", encoding="utf-8") as new_file,
        ):
            async for line in old_file:
                if not line.strip():
                    continue

                line_json = json.loads(line)
                if line_json["role"] == "_checkpoint" and line_json["id"] == checkpoint_id:
                    break

                await new_file.write(line)
                if line_json["role"] == "_usage":
                    self._token_count = line_json["token_count"]
                elif line_json["role"] == "_checkpoint":
                    self._next_checkpoint_id = line_json["id"] + 1
                else:
                    message = Message.model_validate(line_json)
                    self._history.append(message)

    async def append_message(self, message: Message | Sequence[Message]):
        logger.debug("Appending message(s) to context: {message}", message=message)
        messages = message if isinstance(message, Sequence) else [message]
        self._history.extend(messages)

        async with aiofiles.open(self._file_backend, "a", encoding="utf-8") as f:
            for message in messages:
                await f.write(message.model_dump_json(exclude_none=True) + "\n")

    async def update_token_count(self, token_count: int):
        logger.debug("Updating token count in context: {token_count}", token_count=token_count)
        self._token_count = token_count

        async with aiofiles.open(self._file_backend, "a", encoding="utf-8") as f:
            await f.write(json.dumps({"role": "_usage", "token_count": token_count}) + "\n")
