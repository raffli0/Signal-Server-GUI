"""Embedded SVG icon set for the Signal GUI.

All icons use a 24x24 viewBox with stroke-based (Lucide-style) geometry. The
``{C}`` token inside each path is replaced by the requested colour so the same
definition works for both Qt widgets and inline HTML (via ``currentColor``).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICONS: dict[str, str] = {
    "wifi": (
        '<path d="M2 8.5a16 16 0 0 1 20 0"/>'
        '<path d="M5 12a11 11 0 0 1 14 0"/>'
        '<path d="M8.5 15.5a6 6 0 0 1 7 0"/>'
        '<circle cx="12" cy="19" r="1" fill="{C}"/>'
    ),
    "tower": (
        '<path d="M7 21 12 5l5 16"/>'
        '<path d="M9 13h6"/>'
        '<path d="M8 17h8"/>'
        '<path d="M12 5V3"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
        '<path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
        '<path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'
    ),
    "antenna": (
        '<circle cx="12" cy="14" r="2"/>'
        '<path d="M12 12V6"/>'
        '<path d="M9.5 8a5 5 0 0 1 5 0"/>'
        '<path d="M7.5 6a8.5 8.5 0 0 1 9 0"/>'
        '<path d="M6 18l-1.5 3"/>'
        '<path d="M18 18l1.5 3"/>'
    ),
    "radio": (
        '<rect x="3" y="10" width="18" height="9" rx="1.5"/>'
        '<path d="M7 10V6.5a5 5 0 0 1 10 0V10"/>'
        '<circle cx="8.5" cy="14.5" r="1.3" fill="{C}"/>'
        '<path d="M12 13.5v3"/>'
        '<path d="M12 13.5h4"/>'
    ),
    "share": (
        '<circle cx="18" cy="5" r="3"/>'
        '<circle cx="6" cy="12" r="3"/>'
        '<circle cx="18" cy="19" r="3"/>'
        '<path d="M8.6 13.5l6.8 4"/>'
        '<path d="M15.4 6.5l-6.8 4"/>'
    ),
    "leaf": (
        '<path d="M11 20A7 7 0 0 1 4 13C4 7 11 4 20 4c0 9-3 16-9 16z"/>'
        '<path d="M4 20c4-4 7-7 12-9"/>'
    ),
    "layers": (
        '<path d="M12 2l9 5-9 5-9-5 9-5z"/>'
        '<path d="M3 12l9 5 9-5"/>'
        '<path d="M3 17l9 5 9-5"/>'
    ),
    "trash": (
        '<path d="M3 6h18"/>'
        '<path d="M8 6V4h8v2"/>'
        '<path d="M6 6l1 14h10l1-14"/>'
        '<path d="M10 10v6"/>'
        '<path d="M14 10v6"/>'
    ),
    "download": (
        '<path d="M12 3v12"/>'
        '<path d="M7 11l5 5 5-5"/>'
        '<path d="M5 21h14"/>'
    ),
    "upload": (
        '<path d="M12 21V9"/>'
        '<path d="M7 13l5-5 5 5"/>'
        '<path d="M5 3h14"/>'
    ),
    "user": (
        '<circle cx="12" cy="8" r="4"/>'
        '<path d="M4 21c0-4 4-6.5 8-6.5s8 2.5 8 6.5"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/>'
        '<path d="M12 17h.01" stroke-linecap="round"/>'
    ),
    "maximize": (
        '<path d="M3 9V3h6"/>'
        '<path d="M21 9V3h-6"/>'
        '<path d="M3 15v6h6"/>'
        '<path d="M21 15v6h-6"/>'
    ),
    "lock": (
        '<rect x="5" y="11" width="14" height="9" rx="1.5"/>'
        '<path d="M8 11V8a4 4 0 0 1 8 0v3"/>'
    ),
    "play": (
        '<path d="M7 4l13 8-13 8z" fill="{C}" stroke="{C}"/>'
    ),
    "search": (
        '<circle cx="11" cy="11" r="7"/>'
        '<path d="M21 21l-4.3-4.3"/>'
    ),
    "home": (
        '<path d="M3 11l9-8 9 8"/>'
        '<path d="M5 10v10h14V10"/>'
    ),
    "map": (
        '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/>'
        '<path d="M9 4v14"/>'
        '<path d="M15 6v14"/>'
    ),
    "contrast": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 3v18"/>'
        '<path d="M12 3a9 9 0 0 1 0 18z" fill="{C}" stroke="none"/>'
    ),
    "pencil": (
        '<path d="M12 20h9"/>'
        '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'
    ),
    "palette": (
        '<path d="M12 3a9 9 0 1 0 0 18c1.7 0 2-1.2 2-2.2 0-1.2-1-1.4-1-2.6 0-.9.8-1.6 1.7-1.6H17a4 4 0 0 0 4-4c0-5-4.5-9-9-9z"/>'
        '<circle cx="7.5" cy="11" r="1" fill="{C}"/>'
        '<circle cx="11" cy="7.5" r="1" fill="{C}"/>'
        '<circle cx="16" cy="8.5" r="1" fill="{C}"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 11v5"/>'
        '<path d="M12 8h.01" stroke-linecap="round"/>'
    ),
}


def svg_str(name: str, color: str = "#CBD5E0", size: int = 24) -> str:
    """Return a standalone SVG document for ``name`` coloured with ``color``."""
    inner = _ICONS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    ).replace("{C}", color)


def pixmap(name: str, size: int = 24, color: str = "#CBD5E0") -> QPixmap:
    """Render an icon to a transparent ``QPixmap`` of ``size`` x ``size``."""
    svg = QByteArray(svg_str(name, color, size).encode("utf-8"))
    renderer = QSvgRenderer(svg)
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def icon(name: str, size: int = 24, color: str = "#CBD5E0") -> QIcon:
    """Return a ``QIcon`` for ``name`` coloured with ``color``."""
    return QIcon(pixmap(name, size, color))
