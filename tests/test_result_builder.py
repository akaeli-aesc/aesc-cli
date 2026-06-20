"""Tests for ToolResultBuilder."""

from __future__ import annotations

from aesc.tools.utils import ToolResultBuilder


def test_basic_functionality():
    """Test basic functionality without limits."""
    builder = ToolResultBuilder(max_chars=50)

    written1 = builder.write("Hello")
    written2 = builder.write(" world")

    assert written1 == 5
    assert written2 == 6

    result = builder.ok("Operation completed")
    assert result.output == "Hello world"
    assert result.message == "Operation completed."
    assert not builder.is_full


def test_char_limit_truncation():
    """Test character limit truncation."""
    builder = ToolResultBuilder(max_chars=10)

    written1 = builder.write("Hello")
    written2 = builder.write(" world!")  # This should trigger truncation

    assert written1 == 5
    assert written2 == 14  # "[...truncated]" marker was added
    assert builder.is_full

    result = builder.ok("Operation completed")
    assert result.output == "Hello[...truncated]"
    assert "Operation completed." in result.message
    assert "Output truncated" in result.message


def test_line_length_limit():
    """Test line length limit functionality."""
    builder = ToolResultBuilder(max_chars=100, max_line_length=20)

    written = builder.write("This is a very long line that should be truncated\n")

    assert written == 20  # Line was truncated to fit marker

    result = builder.ok()
    assert isinstance(result.output, str)
    assert "[...truncated]" in result.output
    assert "Output truncated" in result.message


def test_both_limits():
    """Test both character and line limits together."""
    builder = ToolResultBuilder(max_chars=40, max_line_length=20)

    w1 = builder.write("Line 1\n")  # 7 chars
    w2 = builder.write("This is a very long line that exceeds limit\n")  # 20 chars (truncated)
    w3 = builder.write("This would exceed char limit")  # 14 chars (truncated)

    assert w1 == 7
    assert w2 == 20  # Line truncated to fit limit
    assert w3 == 14  # Line truncated due to char limit
    assert builder.is_full
    # Total might exceed 40 due to truncation markers

    result = builder.ok()
    assert isinstance(result.output, str)
    assert "[...truncated]" in result.output
    assert "Output truncated" in result.message


def test_error_result():
    """Test error result creation."""
    builder = ToolResultBuilder(max_chars=20)

    builder.write("Some output")
    result = builder.error("Something went wrong", brief="Error occurred")

    assert result.output == "Some output"
    assert result.message == "Something went wrong"
    assert result.brief == "Error occurred"


def test_error_with_truncation():
    """Test error result with truncated output."""
    builder = ToolResultBuilder(max_chars=10)

    builder.write("Very long output that exceeds limit")
    result = builder.error("Command failed", brief="Failed")

    assert isinstance(result.output, str)
    assert "[...truncated]" in result.output
    assert "Command failed" in result.message
    assert "Output truncated" in result.message
    assert result.brief == "Failed"


def test_properties():
    """Test builder properties."""
    builder = ToolResultBuilder(max_chars=20, max_line_length=30)

    assert builder.n_chars == 0
    assert builder.n_lines == 0
    assert not builder.is_full

    builder.write("Short\n")
    assert builder.n_chars == 6
    assert builder.n_lines == 1

    builder.write("1\n2\n")
    assert builder.n_chars == 10
    assert builder.n_lines == 3

    builder.write("More text that exceeds")  # Will trigger char truncation
    assert builder.is_full


def test_write_when_full():
    """Test writing when buffer is already full."""
    builder = ToolResultBuilder(max_chars=5)

    written1 = builder.write("Hello")  # Fills buffer exactly
    written2 = builder.write(" world")  # Should write nothing

    assert written1 == 5
    assert written2 == 0
    assert builder.is_full

    result = builder.ok()
    assert result.output == "Hello"


def test_multiline_handling():
    """Test proper multiline text handling."""
    builder = ToolResultBuilder(max_chars=100)

    written = builder.write("Line 1\nLine 2\nLine 3")

    assert written == 20
    assert builder.n_lines == 2  # Two newlines

    result = builder.ok()
    assert result.output == "Line 1\nLine 2\nLine 3"


def test_empty_write():
    """Test writing empty string."""
    builder = ToolResultBuilder(max_chars=50)

    written = builder.write("")

    assert written == 0
    assert builder.n_chars == 0
    assert not builder.is_full


# --- New tests for output limiting features ---


def test_total_chars_received_within_limit():
    """Test total_chars_received when output fits in buffer."""
    builder = ToolResultBuilder(max_chars=100)
    builder.write("Hello world")

    assert builder.total_chars_received == 11
    assert builder.n_chars == 11


def test_total_chars_received_exceeds_limit():
    """Test total_chars_received tracks all input including overflow."""
    builder = ToolResultBuilder(max_chars=10)
    builder.write("Hello")  # 5 chars, fits
    builder.write(" world! This is overflow text that goes way beyond the limit.")

    assert builder.total_chars_received == 66  # All input counted
    assert builder.is_full
    # Buffer only has ~10 chars (plus truncation marker)
    assert builder.n_chars <= 24  # marker adds chars


def test_truncation_message_includes_char_counts():
    """Test that truncation message shows character counts."""
    builder = ToolResultBuilder(max_chars=10)
    builder.write("Hello world, this is a very long string that gets truncated heavily")

    result = builder.ok("Done")
    assert "showing" in result.message
    assert "total chars" in result.message
    assert "Done." in result.message


def test_truncation_message_no_truncation():
    """Test no truncation message when output fits."""
    builder = ToolResultBuilder(max_chars=100)
    builder.write("Short")

    result = builder.ok("Done")
    assert result.message == "Done."
    assert "truncated" not in result.message


def test_tool_hint_in_truncation():
    """Test that tool_hint appears in truncation message."""
    builder = ToolResultBuilder(max_chars=10)
    builder.write("Hello world, overflow text here that exceeds the limit")

    result = builder.ok("Done", tool_hint="Use 'head -n 50' to paginate.")
    assert "head -n 50" in result.message


def test_tool_hint_not_shown_without_truncation():
    """Test that tool_hint is not shown when output fits."""
    builder = ToolResultBuilder(max_chars=100)
    builder.write("Short")

    result = builder.ok("Done", tool_hint="Use 'head -n 50' to paginate.")
    assert "head -n 50" not in result.message


def test_error_with_tool_hint():
    """Test tool_hint in error results."""
    builder = ToolResultBuilder(max_chars=10)
    builder.write("Very long output that exceeds the character limit")

    result = builder.error("Failed", brief="Error", tool_hint="Pipe through head.")
    assert "Pipe through head." in result.message
    assert "Failed" in result.message


def test_env_var_override(monkeypatch):
    """Test AESC_TOOL_MAX_OUTPUT env var overrides default."""
    monkeypatch.setenv("AESC_TOOL_MAX_OUTPUT", "5000")
    builder = ToolResultBuilder()
    assert builder.max_chars == 5000


def test_env_var_override_floor(monkeypatch):
    """Test env var floor of 500 chars."""
    monkeypatch.setenv("AESC_TOOL_MAX_OUTPUT", "100")
    builder = ToolResultBuilder()
    assert builder.max_chars == 500


def test_env_var_invalid_falls_back(monkeypatch):
    """Test invalid env var falls back to default."""
    monkeypatch.setenv("AESC_TOOL_MAX_OUTPUT", "not_a_number")
    builder = ToolResultBuilder()
    assert builder.max_chars == 12_000  # DEFAULT_MAX_CHARS


def test_explicit_max_chars_overrides_env(monkeypatch):
    """Test that explicit max_chars parameter overrides env var."""
    monkeypatch.setenv("AESC_TOOL_MAX_OUTPUT", "5000")
    builder = ToolResultBuilder(max_chars=100)
    assert builder.max_chars == 100


def test_default_max_chars_without_env(monkeypatch):
    """Test default value when no env var is set."""
    monkeypatch.delenv("AESC_TOOL_MAX_OUTPUT", raising=False)
    builder = ToolResultBuilder()
    assert builder.max_chars == 12_000
