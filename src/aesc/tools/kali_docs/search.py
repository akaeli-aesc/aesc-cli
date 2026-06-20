"""Kali documentation search interface."""

import re
from pathlib import Path


def search_docs(repo_path: Path, query: str, tool_name: str | None = None) -> list[dict[str, any]]:
    """
    Search Kali documentation using simple file search.

    Args:
        repo_path: Path to Kali docs repository
        query: Search query
        tool_name: Optional specific tool name to search

    Returns:
        List of search results with file paths and content
    """
    results = []

    # Determine search pattern
    search_pattern = query.lower()

    # If tool_name specified, look for that specific file
    if tool_name:
        # Try to find tool-specific markdown file
        tool_file = repo_path / f"{tool_name.lower()}.md"
        if tool_file.exists():
            content = tool_file.read_text(encoding="utf-8", errors="ignore")
            results.append(
                {
                    "file": str(tool_file.relative_to(repo_path)),
                    "content": content,
                    "matches": content.lower().count(search_pattern),
                }
            )
            return results

    # Search all markdown files
    for md_file in repo_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")

            # Check if query matches
            if search_pattern in content.lower():
                results.append(
                    {
                        "file": str(md_file.relative_to(repo_path)),
                        "content": content,
                        "matches": content.lower().count(search_pattern),
                    }
                )
        except Exception:
            continue

    # Sort by number of matches (most relevant first)
    results.sort(key=lambda x: x["matches"], reverse=True)

    return results[:10]  # Limit to top 10 results


def format_search_result(result: dict[str, any], query: str) -> str:
    """
    Format a single search result.

    Args:
        result: Search result dictionary
        query: Original query

    Returns:
        Formatted string
    """
    file_name = result["file"]
    content = result["content"]
    matches = result["matches"]

    # Extract title from markdown (first # heading)
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else file_name

    # Find relevant excerpts around query
    query_lower = query.lower()
    content_lower = content.lower()

    excerpts = []
    pos = 0
    while len(excerpts) < 3:  # Max 3 excerpts per file
        pos = content_lower.find(query_lower, pos)
        if pos == -1:
            break

        # Extract context (100 chars before and after)
        start = max(0, pos - 100)
        end = min(len(content), pos + len(query) + 100)
        excerpt = content[start:end]

        # Clean up excerpt
        excerpt = excerpt.replace("\n", " ").strip()
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt = excerpt + "..."

        excerpts.append(excerpt)
        pos = end

    result_text = f"\n{'=' * 70}\n"
    result_text += f"📄 {title}\n"
    result_text += f"File: {file_name} ({matches} matches)\n"
    result_text += f"{'=' * 70}\n\n"

    for excerpt in excerpts:
        result_text += f"  {excerpt}\n\n"

    return result_text


def extract_tool_info(content: str) -> dict[str, str]:
    """
    Extract key information from tool documentation.

    Args:
        content: Markdown content

    Returns:
        Dictionary with extracted info
    """
    info = {
        "title": "",
        "description": "",
        "usage": "",
        "examples": "",
    }

    # Extract title
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        info["title"] = title_match.group(1).strip()

    # Extract description (text after title, before ## heading)
    desc_match = re.search(
        r"^#\s+.+?\n\n(.+?)(?=\n##|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if desc_match:
        desc = desc_match.group(1).strip()
        # Limit to first 300 chars
        info["description"] = desc[:300] + ("..." if len(desc) > 300 else "")

    # Extract usage section
    usage_match = re.search(
        r"##\s+Usage\s*\n+(.+?)(?=\n##|\Z)",
        content,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if usage_match:
        usage = usage_match.group(1).strip()
        # Extract code blocks if present
        code_blocks = re.findall(r"```(?:\w+)?\n(.+?)```", usage, re.DOTALL)
        if code_blocks:
            info["usage"] = "\n".join(code_blocks[:2])  # First 2 code blocks
        else:
            info["usage"] = usage[:300]

    # Extract examples
    examples_match = re.search(
        r"##\s+Examples?\s*\n+(.+?)(?=\n##|\Z)",
        content,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if examples_match:
        examples = examples_match.group(1).strip()
        # Extract code blocks
        code_blocks = re.findall(r"```(?:\w+)?\n(.+?)```", examples, re.DOTALL)
        if code_blocks:
            info["examples"] = "\n".join(code_blocks[:3])  # First 3 examples
        else:
            # Look for lines starting with $ or #
            example_lines = re.findall(r"^[$#]\s+(.+)$", examples, re.MULTILINE)
            if example_lines:
                info["examples"] = "\n".join(f"$ {line}" for line in example_lines[:5])

    return info


def format_tool_doc(content: str, file_name: str) -> str:
    """
    Format tool documentation for display.

    Args:
        content: Markdown content
        file_name: File name

    Returns:
        Formatted string
    """
    info = extract_tool_info(content)

    output = f"📚 Kali Docs: {info['title'] or file_name}\n"
    output += f"{'=' * 70}\n\n"

    if info["description"]:
        output += f"Description:\n{info['description']}\n\n"

    if info["usage"]:
        output += f"Usage:\n{info['usage']}\n\n"

    if info["examples"]:
        output += f"Examples:\n{info['examples']}\n\n"

    # Add file reference
    output += f"{'─' * 70}\n"
    output += f"Source: {file_name}\n"

    return output
