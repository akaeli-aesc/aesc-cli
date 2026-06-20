"""AESC UI Theme - Unified design system for all widgets.

Claude Code inspired design with akæli brand colors.
"""

# Brand Colors - akæli purple palette
BRAND = "#a855f7"  # Primary purple
BRAND_DIM = "#7c3aed"  # Muted purple
BRAND_LIGHT = "#c084fc"  # Light purple

# Semantic Colors - soft, professional
SUCCESS = "#4ade80"  # Soft green (not harsh)
ERROR = "#f87171"  # Soft red (not alarming)
WARNING = "#fbbf24"  # Amber
INFO = "#60a5fa"  # Soft blue

# Text Colors - zinc palette
TEXT = "#fafafa"  # Primary text (zinc-50)
TEXT_MUTED = "#a1a1aa"  # Secondary text (zinc-400)
TEXT_DIM = "#71717a"  # Tertiary text (zinc-500)
TEXT_SUBTLE = "#52525b"  # Subtle text (zinc-600)

# Background Colors - dark theme
BG_SURFACE = "#09090b"  # Main background (zinc-950)
BG_PANEL = "#18181b"  # Panel background (zinc-900)
BG_ELEVATED = "#27272a"  # Elevated/hover (zinc-800)
BG_HIGHLIGHT = "#3f3f46"  # Highlighted (zinc-700)

# Border Colors
BORDER = "#3f3f46"  # Default border (zinc-700)
BORDER_DIM = "#27272a"  # Subtle border (zinc-800)

# Status Indicators - using dots (●) like Claude Code
INDICATOR_RUNNING = INFO  # Blue dot for running
INDICATOR_SUCCESS = SUCCESS  # Green dot for success
INDICATOR_ERROR = ERROR  # Red dot for error
INDICATOR_PENDING = WARNING  # Amber dot for pending

# Full color dict for backward compatibility
COLORS = {
    "brand": BRAND,
    "brand_dim": BRAND_DIM,
    "success": SUCCESS,
    "error": ERROR,
    "warning": WARNING,
    "info": INFO,
    "running": INFO,
    "text": TEXT,
    "muted": TEXT_MUTED,
    "dim": TEXT_DIM,
    "subtle": TEXT_SUBTLE,
    "label": TEXT_MUTED,
    "surface": BG_SURFACE,
    "panel": BG_PANEL,
    "elevated": BG_ELEVATED,
    "border": BORDER,
}

# Icons - consistent symbols
ICON_RUNNING = "●"  # Running state
ICON_SUCCESS = "●"  # Success (with green color)
ICON_ERROR = "●"  # Error (with red color)
ICON_PENDING = "△"  # Pending/waiting
ICON_THINKING = "○"  # Thinking/processing
ICON_BRAND = "◆"  # AESC brand marker
ICON_EXPAND = "∨"  # Expand indicator
ICON_COLLAPSE = "∧"  # Collapse indicator

# Spinner frames - smooth braille animation
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
