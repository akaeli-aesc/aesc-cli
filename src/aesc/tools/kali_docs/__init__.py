"""Kali documentation search tool for aesc."""

from typing import Any, override

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolReturnType
from aesc.tools.utils import ToolResultBuilder

from . import clone, search


class Params(BaseModel):
    """Parameters for Kali docs search."""

    query: str = Field(
        description=(
            "Search query for Kali documentation. Can be:\n"
            "- Tool name (e.g., 'nmap', 'sqlmap', 'metasploit')\n"
            "- Topic (e.g., 'web scanning', 'password cracking')\n"
            "- Command syntax (e.g., 'how to use nikto')\n"
            "- Technique (e.g., 'SQL injection', 'brute force')"
        )
    )

    tool: str | None = Field(
        description="Optional: Specific tool name to search for",
        default=None,
    )


class KaliDocs(CallableTool2[Params]):
    """
    Kali documentation search tool.

    Search official Kali Linux tool documentation for usage information,
    examples, and syntax. Documentation is cloned from GitLab and cached
    locally, with weekly updates.
    """

    name: str = "KaliDocs"
    description: str = (
        "Search Kali Linux tool documentation for usage information, examples, "
        "and command syntax. Use this to learn how to use security tools like "
        "nmap, sqlmap, metasploit, nikto, gobuster, and hundreds of other Kali tools."
    )
    params: type[Params] = Params

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        builder = ToolResultBuilder()

        try:
            # Get repository path (clone if needed)
            builder.write("Loading Kali documentation...")
            repo_path = clone.get_repo_path()
            builder.write(" ✅\n\n")

            # Search documentation
            results = search.search_docs(repo_path, params.query, params.tool)

            if not results:
                return builder.error(
                    f"No documentation found for: {params.query}",
                    brief="No results found",
                )

            # Format results
            if len(results) == 1:
                # Single result - show full documentation
                result = results[0]
                formatted = search.format_tool_doc(result["content"], result["file"])
                builder.write(formatted)
            else:
                # Multiple results - show summaries
                builder.write(f"Found {len(results)} results for '{params.query}':\n\n")

                for idx, result in enumerate(results[:5], 1):  # Show top 5
                    formatted = search.format_search_result(result, params.query)
                    builder.write(formatted)

                if len(results) > 5:
                    builder.write(f"\n... and {len(results) - 5} more results\n")
                    builder.write(
                        "\nTip: Use the 'tool' parameter to search for a specific tool.\n"
                    )

            return builder.ok("Search completed successfully.")

        except Exception as e:
            error_msg = str(e)

            # Provide helpful error messages
            if "Failed to clone" in error_msg:
                return builder.error(
                    f"Failed to download Kali documentation: {error_msg}\n\n"
                    "This may be a network issue. Please check your internet connection "
                    "and try again.",
                    brief="Clone failed",
                )
            elif "Repository not cloned" in error_msg:
                return builder.error(
                    "Kali documentation not available. Attempting to download...\n"
                    "Please try your query again in a moment.",
                    brief="Repo not ready",
                )
            else:
                return builder.error(
                    f"Failed to search Kali docs: {error_msg}",
                    brief="Search failed",
                )


# Export the tool
__all__ = ["KaliDocs"]
