"""MITRE ATT&CK knowledge base tool for aesc."""

from typing import Any, Literal, override

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolReturnType
from aesc.tools.utils import ToolResultBuilder

from . import cache, query

# Global index cache to avoid re-parsing on every query
_INDEX_CACHE: dict[str, Any] | None = None


class Params(BaseModel):
    """Parameters for MITRE ATT&CK queries."""

    query_text: str = Field(
        description=(
            "The search query. Can be:\n"
            "- Technique ID (e.g., 'T1003')\n"
            "- Technique name (e.g., 'OS Credential Dumping')\n"
            "- Tactic name (e.g., 'Initial Access', 'Persistence')\n"
            "- Group name (e.g., 'APT29', 'Lazarus Group')\n"
            "- Software name (e.g., 'Mimikatz', 'Cobalt Strike')\n"
            "- Keyword search (e.g., 'credential dumping')"
        ),
        alias="query",
    )

    query_type: Literal["auto", "technique", "tactic", "group", "software", "keyword"] = Field(
        description=(
            "Type of query:\n"
            "- 'auto': Auto-detect (default)\n"
            "- 'technique': Look up specific technique\n"
            "- 'tactic': List techniques by tactic\n"
            "- 'group': Look up threat group\n"
            "- 'software': Look up malware/tool\n"
            "- 'keyword': Search by keyword"
        ),
        default="auto",
        alias="type",
    )


class MitreAttack(CallableTool2[Params]):
    """
    MITRE ATT&CK knowledge base tool.

    Query the MITRE ATT&CK framework for tactics, techniques, groups, and software.
    Data is cached locally and updated weekly.
    """

    name: str = "MitreAttack"
    description: str = (
        "Query the MITRE ATT&CK framework for information about attack tactics, "
        "techniques, threat groups, and malware/tools. Use this to understand "
        "attack patterns, lookup technique details, or find information about "
        "threat actors and their tools."
    )
    params: type[Params] = Params

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        builder = ToolResultBuilder()

        try:
            # Get and index ATT&CK data
            index = await self._get_index()

            # Auto-detect query type if needed
            query_type = params.query_type
            if query_type == "auto":
                query_type = self._detect_query_type(params.query_text)

            # Execute query based on type
            result = self._execute_query(index, params.query_text, query_type)

            if result:
                builder.write(result)
                return builder.ok("Query executed successfully.")
            else:
                return builder.error(
                    f"No results found for query: {params.query_text}",
                    brief="No results found",
                )

        except Exception as e:
            return builder.error(
                f"Failed to query MITRE ATT&CK: {str(e)}",
                brief="Query failed",
            )

    async def _get_index(self) -> dict[str, Any]:
        """Get indexed ATT&CK data (cached)."""
        global _INDEX_CACHE

        if _INDEX_CACHE is None:
            # Load/download ATT&CK data
            data = cache.get_attack_data()

            # Index the data
            _INDEX_CACHE = query.index_attack_data(data)

        return _INDEX_CACHE

    def _detect_query_type(self, query_text: str) -> str:
        """
        Auto-detect query type from query text.

        Args:
            query_text: The query string

        Returns:
            Detected query type
        """
        query_text = query_text.strip()

        # Check if it's a technique ID (T####)
        if query_text.upper().startswith("T") and query_text[1:5].isdigit():
            return "technique"

        # Check if it's a known tactic
        known_tactics = [
            "reconnaissance",
            "resource development",
            "initial access",
            "execution",
            "persistence",
            "privilege escalation",
            "defense evasion",
            "credential access",
            "discovery",
            "lateral movement",
            "collection",
            "command and control",
            "exfiltration",
            "impact",
        ]

        if query_text.lower() in known_tactics:
            return "tactic"

        # Check if it contains "APT" or "Group" (likely a group query)
        if "apt" in query_text.lower() or "group" in query_text.lower():
            return "group"

        # Default to keyword search
        return "keyword"

    def _execute_query(self, index: dict[str, Any], query_text: str, query_type: str) -> str | None:
        """
        Execute query based on type.

        Args:
            index: Indexed ATT&CK data
            query_text: Query string
            query_type: Type of query

        Returns:
            Formatted result string or None
        """
        if query_type == "technique":
            technique = query.query_technique(index, query_text)
            if technique:
                return query.format_technique(technique)

        elif query_type == "tactic":
            techniques = query.query_tactic(index, query_text)
            if techniques:
                result = f"📋 Techniques for tactic: {query_text.title()}\n\n"
                for tech in techniques[:15]:  # Limit to 15
                    # Get technique ID
                    tech_id = "?"
                    for ref in tech.get("external_references", []):
                        if ref.get("source_name") == "mitre-attack":
                            tech_id = ref.get("external_id", "?")
                            break

                    name = tech.get("name", "Unknown")
                    result += f"• {tech_id} - {name}\n"

                if len(techniques) > 15:
                    result += f"\n... and {len(techniques) - 15} more\n"

                return result

        elif query_type == "group":
            group = query.query_group(index, query_text)
            if group:
                return query.format_group(group)

        elif query_type == "software":
            software = query.query_software(index, query_text)
            if software:
                return query.format_software(software)

        elif query_type == "keyword":
            results = query.search_keyword(index, query_text)
            if results:
                output = f"🔍 Search results for: {query_text}\n\n"
                for tech in results[:10]:  # Limit to 10
                    # Get technique ID
                    tech_id = "?"
                    for ref in tech.get("external_references", []):
                        if ref.get("source_name") == "mitre-attack":
                            tech_id = ref.get("external_id", "?")
                            break

                    name = tech.get("name", "Unknown")
                    desc = tech.get("description", "")[:100] + "..."

                    output += f"• {tech_id} - {name}\n  {desc}\n\n"

                if len(results) > 10:
                    output += f"... and {len(results) - 10} more results\n"

                return output

        return None


# Export the tool
__all__ = ["MitreAttack"]
