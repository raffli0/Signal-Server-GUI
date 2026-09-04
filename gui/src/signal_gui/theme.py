"""Centralized Theme and Color Design Tokens for Signal-Server GUI."""

# Backgrounds
BG_APP = "#121518"
BG_PANEL = "#1B1E22"
BG_CARD = "#21262B"
BG_INPUT = "#1B1E22"

# Borders
BORDER_DEFAULT = "#3F474F"
BORDER_LIGHT = "#4A5568"
BORDER_SUBTLE = "#2D3748"

# Primary / Accent Colors
PRIMARY_BLUE = "#0088CC"
PRIMARY_HOVER = "#0099E6"
ACCENT_TEAL = "#319795"
ACCENT_CYAN = "#3182CE"

# Semantic Colors
COLOR_SUCCESS = "#38A169"
COLOR_WARNING = "#D69E2E"
COLOR_DANGER = "#E53E3E"
COLOR_INFO = "#3182CE"

# Typography / Text Colors
TEXT_PRIMARY = "#E2E8F0"
TEXT_SECONDARY = "#CBD5E0"
TEXT_MUTED = "#A0AEC0"
TEXT_DISABLED = "#718096"

# Common Widget Stylesheets
BUTTON_SECONDARY_STYLE = (
    f"background: {BG_PANEL}; color: {TEXT_SECONDARY}; "
    f"border: 1px solid {BORDER_DEFAULT}; border-radius: 3px; padding: 4px 8px; font-size: 11px;"
)

LINE_EDIT_STYLE = (
    f"background: {BG_INPUT}; color: {TEXT_PRIMARY}; "
    f"border: 1px solid {BORDER_DEFAULT}; border-radius: 3px; padding: 3px 6px; font-size: 11px;"
)
