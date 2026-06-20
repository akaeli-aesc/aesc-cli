"""Tests for aesc.soul.context module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aesc.provider.message import Message
from aesc.soul.context import Context


@pytest.fixture
def context_file(tmp_path: Path) -> Path:
    """Create a temporary context file."""
    return tmp_path / "context.jsonl"


@pytest.fixture
def context(context_file: Path) -> Context:
    """Create a Context instance with temporary file."""
    return Context(context_file)


class TestContextInit:
    """Test Context initialization."""

    def test_empty_context(self, context: Context):
        """New context should have empty history."""
        assert len(context.history) == 0
        assert context.token_count == 0
        assert context.n_checkpoints == 0

    def test_file_backend_path(self, context: Context, context_file: Path):
        """Context should store the file backend path."""
        assert context._file_backend == context_file


class TestContextRestore:
    """Test context restoration from file."""

    @pytest.mark.asyncio
    async def test_restore_empty_file(self, context: Context, context_file: Path):
        """Restoring from non-existent file should return False."""
        result = await context.restore()
        assert result is False
        assert len(context.history) == 0

    @pytest.mark.asyncio
    async def test_restore_empty_content(self, context: Context, context_file: Path):
        """Restoring from empty file should return False."""
        context_file.touch()
        result = await context.restore()
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_user_message(self, context: Context, context_file: Path):
        """Should restore user messages correctly."""
        message = Message(role="user", content="test input")
        context_file.write_text(message.model_dump_json() + "\n")

        result = await context.restore()
        assert result is True
        assert len(context.history) == 1
        assert context.history[0].role == "user"
        assert context.history[0].content == "test input"

    @pytest.mark.asyncio
    async def test_restore_with_token_count(self, context: Context, context_file: Path):
        """Should restore token count."""
        lines = [
            json.dumps({"role": "user", "content": "test"}),
            json.dumps({"role": "_usage", "token_count": 100}),
        ]
        context_file.write_text("\n".join(lines) + "\n")

        await context.restore()
        assert context.token_count == 100

    @pytest.mark.asyncio
    async def test_restore_with_checkpoint(self, context: Context, context_file: Path):
        """Should restore checkpoint count."""
        lines = [
            json.dumps({"role": "_checkpoint", "id": 0}),
            json.dumps({"role": "user", "content": "test"}),
            json.dumps({"role": "_checkpoint", "id": 1}),
        ]
        context_file.write_text("\n".join(lines) + "\n")

        await context.restore()
        assert context.n_checkpoints == 2

    @pytest.mark.asyncio
    async def test_restore_skips_corrupted_lines(self, context: Context, context_file: Path):
        """Should skip corrupted JSON lines."""
        lines = [
            json.dumps({"role": "user", "content": "first"}),
            "not valid json",
            json.dumps({"role": "user", "content": "second"}),
        ]
        context_file.write_text("\n".join(lines) + "\n")

        result = await context.restore()
        assert result is True
        assert len(context.history) == 2

    @pytest.mark.asyncio
    async def test_restore_skips_invalid_role(self, context: Context, context_file: Path):
        """Should skip entries without role."""
        lines = [
            json.dumps({"role": "user", "content": "valid"}),
            json.dumps({"content": "no role"}),  # Missing role
        ]
        context_file.write_text("\n".join(lines) + "\n")

        await context.restore()
        assert len(context.history) == 1


class TestContextAppend:
    """Test appending messages to context."""

    @pytest.mark.asyncio
    async def test_append_single_message(self, context: Context, context_file: Path):
        """Should append single message to history and file."""
        message = Message(role="user", content="test")
        await context.append_message(message)

        assert len(context.history) == 1
        assert context.history[0].content == "test"

        # Check file was written
        content = context_file.read_text()
        assert "test" in content

    @pytest.mark.asyncio
    async def test_append_multiple_messages(self, context: Context, context_file: Path):
        """Should append multiple messages at once."""
        messages = [
            Message(role="user", content="first"),
            Message(role="assistant", content="second"),
        ]
        await context.append_message(messages)

        assert len(context.history) == 2

        lines = context_file.read_text().strip().split("\n")
        assert len(lines) == 2


class TestContextCheckpoint:
    """Test checkpointing functionality."""

    @pytest.mark.asyncio
    async def test_checkpoint_increments_id(self, context: Context):
        """Checkpoints should have incrementing IDs."""
        assert context.n_checkpoints == 0

        await context.checkpoint(add_user_message=False)
        assert context.n_checkpoints == 1

        await context.checkpoint(add_user_message=False)
        assert context.n_checkpoints == 2

    @pytest.mark.asyncio
    async def test_checkpoint_with_user_message(self, context: Context):
        """Checkpoint with user message should add to history."""
        await context.checkpoint(add_user_message=True)

        assert len(context.history) == 1
        assert context.history[0].role == "user"


class TestContextTokenCount:
    """Test token count updates."""

    @pytest.mark.asyncio
    async def test_update_token_count(self, context: Context, context_file: Path):
        """Should update token count in memory and file."""
        await context.update_token_count(500)

        assert context.token_count == 500

        content = context_file.read_text()
        assert '"token_count": 500' in content


class TestContextRevert:
    """Test checkpoint reversion."""

    @pytest.mark.asyncio
    async def test_revert_to_checkpoint(self, context: Context, context_file: Path):
        """Should revert to specified checkpoint."""
        # Build some history
        await context.checkpoint(add_user_message=False)  # checkpoint 0
        await context.append_message(Message(role="user", content="first"))
        await context.checkpoint(add_user_message=False)  # checkpoint 1
        await context.append_message(Message(role="user", content="second"))

        # Revert to checkpoint 1 (removes checkpoint 1 and everything after)
        await context.revert_to(1)

        assert len(context.history) == 1
        assert context.history[0].content == "first"
        assert context.n_checkpoints == 1

    @pytest.mark.asyncio
    async def test_revert_invalid_checkpoint_raises(self, context: Context):
        """Should raise error for invalid checkpoint ID."""
        with pytest.raises(ValueError, match="does not exist"):
            await context.revert_to(999)
