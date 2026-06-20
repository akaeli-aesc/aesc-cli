"""MITRE ATT&CK data cache management."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# MITRE ATT&CK Enterprise data URL
ENTERPRISE_ATTACK_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)

# Cache settings
CACHE_DIR = Path.home() / ".aesc" / ".cache" / "mitre-attack"
CACHE_FILE = CACHE_DIR / "enterprise-attack.json"
TIMESTAMP_FILE = CACHE_DIR / "last-update.txt"
UPDATE_INTERVAL = timedelta(days=7)  # Update weekly

# Bundled data location (pre-downloaded in Docker image). Images may stage the
# file under different roots, so check candidates in order and fall back to the
# canonical /app/data path used by the primary Dockerfile.
_BUNDLED_DATA_CANDIDATES = (
    Path("/app/data/mitre-attack/enterprise-attack.json"),
    Path("/opt/aesc/data/mitre-attack/enterprise-attack.json"),
)
BUNDLED_DATA_FILE = next(
    (p for p in _BUNDLED_DATA_CANDIDATES if p.exists()), _BUNDLED_DATA_CANDIDATES[0]
)


class MitreDataError(Exception):
    """Error downloading or parsing MITRE ATT&CK data."""

    pass


def ensure_cache_dir() -> None:
    """Create cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def download_attack_data() -> dict[str, Any]:
    """
    Download MITRE ATT&CK Enterprise data.

    NOTE: This function is synchronous and will block the event loop.
    For production use, the data should be pre-bundled in the Docker image.
    See BUNDLED_DATA_FILE for the pre-bundled location.

    Returns:
        Parsed JSON data as dictionary

    Raises:
        MitreDataError: If download or parsing fails
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(ENTERPRISE_ATTACK_URL, timeout=60) as response:
            data = response.read()
            return json.loads(data)
    except urllib.error.URLError as e:
        raise MitreDataError(f"Network error downloading MITRE data: {e}") from e
    except urllib.error.HTTPError as e:
        raise MitreDataError(f"HTTP error {e.code} downloading MITRE data") from e
    except json.JSONDecodeError as e:
        raise MitreDataError(f"Invalid JSON in MITRE data: {e}") from e
    except TimeoutError as e:
        raise MitreDataError("Timeout downloading MITRE data") from e


def save_cache(data: dict[str, Any]) -> None:
    """
    Save ATT&CK data to cache.

    Args:
        data: MITRE ATT&CK data dictionary
    """
    ensure_cache_dir()

    # Save JSON data
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Save timestamp
    with open(TIMESTAMP_FILE, "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat())


def load_bundled_data() -> dict[str, Any] | None:
    """
    Load pre-bundled ATT&CK data from Docker image.

    Returns:
        Bundled data or None if not available
    """
    if not BUNDLED_DATA_FILE.exists():
        return None

    try:
        with open(BUNDLED_DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_cache() -> dict[str, Any] | None:
    """
    Load ATT&CK data from cache.

    Returns:
        Cached data or None if cache doesn't exist or is corrupt
    """
    if not CACHE_FILE.exists():
        return None

    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt cache or I/O error - treat as missing
        return None


def is_cache_stale() -> bool:
    """
    Check if cache needs updating.

    Returns:
        True if cache is stale or doesn't exist
    """
    if not TIMESTAMP_FILE.exists():
        return True

    try:
        with open(TIMESTAMP_FILE, encoding="utf-8") as f:
            last_update = datetime.fromisoformat(f.read().strip())
            return datetime.now() - last_update > UPDATE_INTERVAL
    except (ValueError, OSError):
        # Invalid timestamp or I/O error - treat as stale
        return True


def get_attack_data(force_update: bool = False) -> dict[str, Any]:
    """
    Get MITRE ATT&CK data (from bundled data, cache, or download).

    Priority order:
    1. User cache (if fresh)
    2. Bundled data (pre-downloaded in Docker image)
    3. Download from GitHub (fallback, may block UI)

    Args:
        force_update: Force download even if cache is fresh

    Returns:
        MITRE ATT&CK data dictionary

    Raises:
        MitreDataError: If no data available from any source
    """
    # 1. Try user cache if available and fresh
    if not force_update and not is_cache_stale():
        cached = load_cache()
        if cached is not None:
            return cached

    # 2. Try bundled data (fast, no network needed)
    bundled = load_bundled_data()
    if bundled is not None:
        return bundled

    # 3. Fallback: download from GitHub (slow, blocks UI)
    # This should rarely happen if Docker image has bundled data
    try:
        data = download_attack_data()
        save_cache(data)
        return data
    except MitreDataError:
        # Last resort: try stale cache
        cached = load_cache()
        if cached is not None:
            return cached
        raise


def get_cache_info() -> dict[str, Any]:
    """
    Get cache information.

    Returns:
        Dictionary with cache stats
    """
    if not CACHE_FILE.exists():
        return {"cached": False, "size": 0, "last_update": None}

    size = CACHE_FILE.stat().st_size
    last_update = None

    if TIMESTAMP_FILE.exists():
        try:
            with open(TIMESTAMP_FILE, encoding="utf-8") as f:
                last_update = f.read().strip()
        except OSError:
            # Can't read timestamp - leave as None
            pass

    return {
        "cached": True,
        "size": size,
        "last_update": last_update,
        "stale": is_cache_stale(),
    }
