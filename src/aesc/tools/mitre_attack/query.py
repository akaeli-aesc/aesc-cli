"""MITRE ATT&CK data query interface."""

from typing import Any


def index_attack_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Index MITRE ATT&CK data for fast queries.

    Args:
        data: MITRE ATT&CK STIX bundle

    Returns:
        Indexed data structure with techniques, tactics, groups, etc.
    """
    index = {
        "techniques": {},  # ID -> technique
        "tactics": {},  # name -> list of techniques
        "groups": {},  # name -> group
        "software": {},  # name -> software
        "mitigations": {},  # ID -> mitigation
    }

    objects = data.get("objects", [])

    for obj in objects:
        obj_type = obj.get("type")

        # Index attack patterns (techniques)
        if obj_type == "attack-pattern":
            # Get technique ID (e.g., T1003)
            tech_id = None
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack":
                    tech_id = ref.get("external_id")
                    break

            if tech_id:
                index["techniques"][tech_id] = obj
                index["techniques"][obj.get("name", "").lower()] = obj

            # Index by tactic (kill chain phase)
            for phase in obj.get("kill_chain_phases", []):
                tactic_name = phase.get("phase_name", "")
                if tactic_name:
                    if tactic_name not in index["tactics"]:
                        index["tactics"][tactic_name] = []
                    index["tactics"][tactic_name].append(obj)

        # Index intrusion sets (groups)
        elif obj_type == "intrusion-set":
            name = obj.get("name", "").lower()
            if name:
                index["groups"][name] = obj

        # Index malware and tools (software)
        elif obj_type in ("malware", "tool"):
            name = obj.get("name", "").lower()
            if name:
                index["software"][name] = obj

        # Index course of action (mitigations)
        elif obj_type == "course-of-action":
            # Get mitigation ID (e.g., M1028)
            mit_id = None
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack":
                    mit_id = ref.get("external_id")
                    break

            if mit_id:
                index["mitigations"][mit_id] = obj

    return index


def query_technique(index: dict[str, Any], query: str) -> dict[str, Any] | None:
    """
    Query a technique by ID or name.

    Args:
        index: Indexed ATT&CK data
        query: Technique ID (T1003) or name

    Returns:
        Technique object or None if not found
    """
    query = query.strip().upper() if query.startswith("T") else query.strip().lower()
    return index["techniques"].get(query)


def query_tactic(index: dict[str, Any], tactic: str) -> list[dict[str, Any]]:
    """
    Query techniques by tactic.

    Args:
        index: Indexed ATT&CK data
        tactic: Tactic name (e.g., "initial-access", "persistence")

    Returns:
        List of technique objects
    """
    tactic = tactic.strip().lower().replace(" ", "-")
    return index["tactics"].get(tactic, [])


def query_group(index: dict[str, Any], group: str) -> dict[str, Any] | None:
    """
    Query a group by name.

    Args:
        index: Indexed ATT&CK data
        group: Group name (e.g., "APT29", "Lazarus Group")

    Returns:
        Group object or None if not found
    """
    group = group.strip().lower()
    return index["groups"].get(group)


def query_software(index: dict[str, Any], software: str) -> dict[str, Any] | None:
    """
    Query software by name.

    Args:
        index: Indexed ATT&CK data
        software: Software name (e.g., "Mimikatz", "Cobalt Strike")

    Returns:
        Software object or None if not found
    """
    software = software.strip().lower()
    return index["software"].get(software)


def search_keyword(index: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
    """
    Search techniques by keyword in name or description.

    Args:
        index: Indexed ATT&CK data
        keyword: Search keyword

    Returns:
        List of matching technique objects
    """
    keyword = keyword.lower()
    results = []

    for technique in index["techniques"].values():
        # Skip duplicates (we index by both ID and name)
        if technique in results:
            continue

        name = technique.get("name", "").lower()
        description = technique.get("description", "").lower()

        if keyword in name or keyword in description:
            results.append(technique)

    return results[:20]  # Limit to 20 results


def format_technique(technique: dict[str, Any]) -> str:
    """
    Format technique data for display.

    Args:
        technique: Technique object

    Returns:
        Formatted string
    """
    # Get technique ID
    tech_id = "Unknown"
    for ref in technique.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            tech_id = ref.get("external_id", "Unknown")
            break

    name = technique.get("name", "Unknown")
    description = technique.get("description", "No description available.")

    # Get tactics
    tactics = []
    for phase in technique.get("kill_chain_phases", []):
        tactic = phase.get("phase_name", "")
        if tactic:
            tactics.append(tactic.replace("-", " ").title())

    # Get platforms
    platforms = technique.get("x_mitre_platforms", [])

    # Format output
    output = f"🎯 MITRE ATT&CK: {tech_id} - {name}\n\n"

    if tactics:
        output += f"Tactics: {', '.join(tactics)}\n"

    if platforms:
        output += f"Platforms: {', '.join(platforms)}\n"

    output += f"\nDescription:\n{description}\n"

    # Get URL
    for ref in technique.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            url = ref.get("url")
            if url:
                output += f"\nMore info: {url}\n"
            break

    return output


def format_group(group: dict[str, Any]) -> str:
    """
    Format group data for display.

    Args:
        group: Group object

    Returns:
        Formatted string
    """
    # Get group ID
    group_id = "Unknown"
    for ref in group.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            group_id = ref.get("external_id", "Unknown")
            break

    name = group.get("name", "Unknown")
    description = group.get("description", "No description available.")
    aliases = group.get("aliases", [])

    output = f"👥 MITRE ATT&CK Group: {group_id} - {name}\n\n"

    if aliases:
        output += f"Aliases: {', '.join(aliases)}\n\n"

    output += f"Description:\n{description}\n"

    # Get URL
    for ref in group.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            url = ref.get("url")
            if url:
                output += f"\nMore info: {url}\n"
            break

    return output


def format_software(software: dict[str, Any]) -> str:
    """
    Format software data for display.

    Args:
        software: Software object

    Returns:
        Formatted string
    """
    # Get software ID
    soft_id = "Unknown"
    for ref in software.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            soft_id = ref.get("external_id", "Unknown")
            break

    name = software.get("name", "Unknown")
    description = software.get("description", "No description available.")
    software_type = software.get("type", "").replace("-", " ").title()

    output = f"🛠️  MITRE ATT&CK {software_type}: {soft_id} - {name}\n\n"
    output += f"Description:\n{description}\n"

    # Get URL
    for ref in software.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            url = ref.get("url")
            if url:
                output += f"\nMore info: {url}\n"
            break

    return output
