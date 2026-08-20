"""Path-profile chart view (HTML canvas + QtWebEngineView).

Renders the Radio-Link path profile computed from Signal-Server PPA output:
terrain, line-of-sight, and the 60% first-Fresnel zone, plus obstruction
highlighting (mirrors a Radio Mobile path profile).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView

_TEMPLATE = os.path.join(os.path.dirname(__file__), "resources", "profile.html")


def _template_html() -> str:
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


class ProfileView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._template = _template_html()
        self._profile = None
        self._obstructed = False
        self._ready = False
        self.loadFinished.connect(self._on_loaded)
        self._render()

    def _render(self) -> None:
        self._ready = False
        inject = "window.__profile=" + json.dumps(self._profile or None) + ";"
        html = self._template.replace("/*__DATA__*/", inject)
        self.setHtml(html, QUrl("file:///"))

    def _on_loaded(self, _ok: bool) -> None:
        self._ready = True
        if self._profile:
            self._draw()

    def set_profile(self, profile: Optional[dict], obstructed: bool = False) -> None:
        self._profile = profile
        self._obstructed = obstructed
        if self._ready:
            self._draw()

    def _draw(self) -> None:
        js = (
            "drawProfile("
            + json.dumps(self._profile or {})
            + ","
            + ("true" if self._obstructed else "false")
            + ");"
        )
        self.page().runJavaScript(js)

    def clear(self) -> None:
        self._profile = None
        self._obstructed = False
        if self._ready:
            self.page().runJavaScript("clearProfile();")
