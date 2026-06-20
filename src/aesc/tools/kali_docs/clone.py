"""Kali documentation GitLab clone management."""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# GitLab repository
KALI_DOCS_REPO = "https://gitlab.com/kalilinux/documentation/kali-tools.git"

# Cache settings
CACHE_DIR = Path.home() / ".aesc" / ".cache" / "kali-docs"
REPO_DIR = CACHE_DIR / "kali-tools"
TIMESTAMP_FILE = CACHE_DIR / "last-update.txt"
UPDATE_INTERVAL = timedelta(days=7)  # Update weekly


def ensure_cache_dir() -> None:
    """Create cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def clone_repo() -> None:
    """
    Clone Kali documentation repository.

    Raises:
        Exception: If clone fails
    """
    ensure_cache_dir()

    try:
        # Clone with depth=1 for faster cloning
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                KALI_DOCS_REPO,
                str(REPO_DIR),
            ],
            check=True,
            capture_output=True,
            timeout=120,  # 2 minute timeout
        )

        # Save timestamp
        with open(TIMESTAMP_FILE, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())

    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to clone Kali docs: {e.stderr.decode()}") from e
    except subprocess.TimeoutExpired as e:
        raise Exception("Clone timeout (exceeded 2 minutes)") from e


def update_repo() -> None:
    """
    Update Kali documentation repository.

    Raises:
        Exception: If update fails
    """
    if not REPO_DIR.exists():
        raise Exception("Repository not cloned yet")

    try:
        # Pull latest changes
        subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            timeout=60,  # 1 minute timeout
        )

        # Save timestamp
        with open(TIMESTAMP_FILE, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())

    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to update Kali docs: {e.stderr.decode()}") from e
    except subprocess.TimeoutExpired as e:
        raise Exception("Update timeout (exceeded 1 minute)") from e


def is_repo_cloned() -> bool:
    """
    Check if repository is cloned.

    Returns:
        True if repository exists
    """
    return REPO_DIR.exists() and (REPO_DIR / ".git").exists()


def is_update_needed() -> bool:
    """
    Check if repository needs updating.

    Returns:
        True if update is needed
    """
    if not TIMESTAMP_FILE.exists():
        return True

    try:
        with open(TIMESTAMP_FILE, encoding="utf-8") as f:
            last_update = datetime.fromisoformat(f.read().strip())
            return datetime.now() - last_update > UPDATE_INTERVAL
    except Exception:
        return True


def get_repo_path() -> Path:
    """
    Get Kali docs repository path, cloning if needed.

    Returns:
        Path to repository directory

    Raises:
        Exception: If clone/update fails
    """
    # Clone if not exists
    if not is_repo_cloned():
        clone_repo()
    # Update if stale
    elif is_update_needed():
        try:
            update_repo()
        except Exception:
            # If update fails, continue with existing cache
            pass

    return REPO_DIR


def get_cache_info() -> dict[str, any]:
    """
    Get cache information.

    Returns:
        Dictionary with cache stats
    """
    if not is_repo_cloned():
        return {"cloned": False, "path": None, "last_update": None}

    last_update = None
    if TIMESTAMP_FILE.exists():
        try:
            with open(TIMESTAMP_FILE, encoding="utf-8") as f:
                last_update = f.read().strip()
        except Exception:
            pass

    # Count markdown files
    md_count = len(list(REPO_DIR.rglob("*.md"))) if REPO_DIR.exists() else 0

    return {
        "cloned": True,
        "path": str(REPO_DIR),
        "last_update": last_update,
        "stale": is_update_needed(),
        "md_files": md_count,
    }
