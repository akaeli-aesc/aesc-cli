"""Tests for aesc.soul.compaction module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aesc.provider.message import Message, TextPart
from aesc.soul.compaction import (
    CompactionError,
    CompactionResult,
    SimpleCompaction,
    clear_token_cache,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear token cache before each test to ensure isolation."""
    clear_token_cache()
    yield
    clear_token_cache()


class TestTokenEstimation:
    """Tests for token estimation utilities."""

    def test_estimate_tokens_empty(self):
        """Empty string should have 0 tokens."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_short(self):
        """Short text should estimate tokens correctly."""
        # 12 characters / 4 = 3 tokens
        assert estimate_tokens("Hello World!") == 3

    def test_estimate_tokens_long(self):
        """Longer text should scale proportionally."""
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_estimate_message_tokens_string_content(self):
        """Should handle string content."""
        msg = Message(role="user", content="Hello World!")
        assert estimate_message_tokens(msg) == 3

    def test_estimate_message_tokens_list_content(self):
        """Should handle list of content parts."""
        msg = Message(role="user", content=[TextPart(text="Hello World!")])
        assert estimate_message_tokens(msg) == 3

    def test_estimate_messages_tokens(self):
        """Should sum tokens across messages."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        total = estimate_messages_tokens(messages)
        # "Hello" = 1 token, "Hi there" = 2 tokens
        assert total == 3


class TestCompactionResult:
    """Tests for CompactionResult dataclass."""

    def test_compaction_result_creation(self):
        """Should create result with all fields."""
        messages = [Message(role="user", content="test")]
        result = CompactionResult(
            messages=messages,
            summary="Test summary",
            full_summary="Full test summary content",
            original_token_estimate=100,
            compacted_token_estimate=50,
            compression_ratio=0.5,
        )
        assert result.messages == messages
        assert result.summary == "Test summary"
        assert result.full_summary == "Full test summary content"
        assert result.compression_ratio == 0.5


class TestSimpleCompaction:
    """Tests for SimpleCompaction class."""

    @pytest.fixture
    def compaction(self) -> SimpleCompaction:
        return SimpleCompaction()

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.chat_provider = MagicMock()
        llm.max_context_size = 100000
        return llm

    @pytest.mark.asyncio
    async def test_compact_empty_messages(self, compaction: SimpleCompaction, mock_llm):
        """Empty messages should return empty result."""
        result = await compaction.compact_with_result([], mock_llm)
        assert len(result.messages) == 0
        assert result.compression_ratio == 1.0

    @pytest.mark.asyncio
    async def test_compact_few_messages_unchanged(self, compaction: SimpleCompaction, mock_llm):
        """Should not compact if not enough messages."""
        messages = [Message(role="user", content="test")]
        result = await compaction.compact_with_result(messages, mock_llm)
        assert result.messages == messages
        assert "Not enough messages" in result.summary

    @pytest.mark.asyncio
    async def test_compact_preserves_recent_messages(self, compaction: SimpleCompaction, mock_llm):
        """Should preserve MAX_PRESERVED_MESSAGES recent messages."""
        with patch("aesc.soul.compaction.generate") as mock_generate:
            # Setup mock response - must be smaller than input to pass validation
            # Input: 4 messages with ~100 chars each = ~400 chars = ~100 tokens
            # Output: should be less than that
            mock_result = MagicMock()
            mock_result.message = Message(role="assistant", content="Summary of conversation")
            mock_result.usage = MagicMock(input=50, output=20)
            mock_generate.return_value = mock_result

            # Create long messages to make compaction worthwhile
            messages = [
                Message(
                    role="user",
                    content="This is a fairly long message number one with lots of content " * 5,
                ),
                Message(
                    role="assistant",
                    content="This is a fairly long response number one with lots of content " * 5,
                ),
                Message(role="user", content="This is message two"),
                Message(role="assistant", content="This is response two"),
            ]

            result = await compaction.compact_with_result(messages, mock_llm)

            # Should have compacted + preserved messages
            assert len(result.messages) >= SimpleCompaction.MAX_PRESERVED_MESSAGES
            # Compression should be effective
            assert result.compression_ratio < 1.0

    @pytest.mark.asyncio
    async def test_compact_validation_size_increase(self, compaction: SimpleCompaction, mock_llm):
        """Should raise error if compaction increases size."""
        with patch("aesc.soul.compaction.generate") as mock_generate:
            # Setup mock response that's much larger than input
            mock_result = MagicMock()
            mock_result.message = Message(role="assistant", content="x" * 10000)  # Very large
            mock_result.usage = MagicMock(input=50, output=200)
            mock_generate.return_value = mock_result

            # Small input messages
            messages = [
                Message(role="user", content="Hi"),
                Message(role="assistant", content="Hello"),
                Message(role="user", content="Bye"),
            ]

            with pytest.raises(CompactionError, match="increased size"):
                await compaction.compact_with_result(messages, mock_llm)

    @pytest.mark.asyncio
    async def test_compact_validation_max_context(self, compaction: SimpleCompaction, mock_llm):
        """Should raise error if compacted exceeds context limit."""
        with patch("aesc.soul.compaction.generate") as mock_generate:
            # Setup mock response - reasonable size but will exceed tiny limit
            mock_result = MagicMock()
            mock_result.message = Message(role="assistant", content="Short summary")
            mock_result.usage = MagicMock(input=50, output=20)
            mock_generate.return_value = mock_result

            # Long input messages that need compaction
            messages = [
                Message(role="user", content="a" * 1000),
                Message(role="assistant", content="b" * 1000),
                Message(role="user", content="c" * 100),  # Preserved
                Message(role="assistant", content="d" * 100),  # Preserved
            ]

            with pytest.raises(CompactionError, match="exceeds context limit"):
                await compaction.compact_with_result(
                    messages,
                    mock_llm,
                    max_context_tokens=10,  # Very small limit
                )


class TestCompactionBackwardCompatibility:
    """Test that the compact() method still works for backward compatibility."""

    @pytest.fixture
    def compaction(self) -> SimpleCompaction:
        return SimpleCompaction()

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.chat_provider = MagicMock()
        return llm

    @pytest.mark.asyncio
    async def test_compact_returns_messages(self, compaction: SimpleCompaction, mock_llm):
        """compact() should return just messages."""
        messages = [Message(role="user", content="test")]
        result = await compaction.compact(messages, mock_llm)
        assert isinstance(result, list) or hasattr(result, "__len__")


# Import truncate_output from tool_call_display if it exists there
try:
    from aesc.ui.widgets.tool_call_display import truncate_output
except ImportError:
    truncate_output = None


@pytest.mark.skipif(truncate_output is None, reason="truncate_output not available")
class TestTruncateOutput:
    """Tests for output truncation utility."""

    def test_truncate_empty(self):
        """Empty string should return empty."""
        assert truncate_output("") == ""

    def test_truncate_short_text(self):
        """Short text should not be truncated."""
        text = "Short text"
        assert truncate_output(text) == text

    def test_truncate_long_lines(self):
        """Should truncate by line count."""
        lines = ["line " + str(i) for i in range(200)]
        text = "\n".join(lines)
        result = truncate_output(text, max_lines=50)
        assert "lines omitted" in result

    def test_truncate_long_chars(self):
        """Should truncate by character count."""
        text = "x" * 50000
        result = truncate_output(text, max_chars=1000)
        assert "characters omitted" in result
        assert len(result) < 50000
