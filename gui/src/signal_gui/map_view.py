"""Interactive coverage map (Leaflet + QtWebEngineView).

The coverage PNG is embedded as a base64 data URI inside an ImageOverlay over
an OSM basemap. Clicking the map (when "armed" from the sidebar) emits a
``picked`` signal back to Python via an ``app://pick`` URL intercepted by
``PickerPage`` -- used to drop Tx/Rx markers and auto-fill the coordinate
fields.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional, Tuple

from PySide6.QtCore import QBuffer, QIODevice, Qt, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from PySide6.QtWidgets import QApplication

_TEMPLATE = os.path.join(os.path.dirname(__file__), "resources", "map.html")

TX_COLOR = "#ffd400"
RX_COLOR = "#ff00ff"


def _template_html() -> str:
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_pick_url(url: str):
    """Parse an ``app://pick?role=&lat=&lon=`` URL -> (role, lat, lon) or None."""
    u = QUrl(url)
    if u.scheme() != "app" or u.host() != "pick":
        return None
    q = QUrlQuery(u.query())
    role = q.queryItemValue("role") or "tx"
    try:
        lat = float(q.queryItemValue("lat"))
        lon = float(q.queryItemValue("lon"))
    except (TypeError, ValueError):
        return None
    return role, lat, lon


def render_html(template: str, coverage, markers, armed: str) -> str:
    """Build the final HTML string by injecting coverage/markers/armed state.

    ``coverage`` is ``(data_uri, [south, west, north, east])`` or ``None``.
    ``markers`` is a list of dicts with role/lat/lon/color/label.
    """
    if coverage:
        data_uri, bounds = coverage
        s, w, n, e = bounds
        cov_js = "{{dataUri:'{}', bounds:[[{}, {}], [{}, {}]]}}".format(data_uri, s, w, n, e)
    else:
        cov_js = "null"
    markers_js = json.dumps(markers or [])
    inject = (
        f"window.__coverage={cov_js};"
        f"window.__markers={markers_js};"
        f"window.__armedRole='{armed}';"
    )
    return template.replace("/*__DATA__*/", inject)


class PickerPage(QWebEnginePage):
    """Intercepts ``app://pick`` navigations and forwards them to the owner."""

    def __init__(self, owner: "MapView"):
        super().__init__(owner)
        self._owner = owner

    def acceptNavigationRequest(self, url: QUrl, _type, _isMainFrame: bool) -> bool:
        if url.scheme() == "app":
            parsed = parse_pick_url(url.toString())
            if parsed:
                self._owner.picked.emit(*parsed)
            return False  # never actually navigate
        return super().acceptNavigationRequest(url, _type, _isMainFrame)


class MapView(QWebEngineView):
    picked = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self._template = _template_html()
        self._coverage = None            # (data_uri, [s,w,n,e]) or None
        self.tx_pos = None               # (lat, lon) or None
        self.rx_pos = None
        self._armed = "tx"
        self._ready = False              # True once the web page has loaded
        self._focus = None               # (lat, lon) to fly to after load
        self._page = PickerPage(self)
        self.setPage(self._page)
        self.tx_label = "Tx"
        self.rx_label = "Rx"
        self.loadFinished.connect(self._on_loaded)
        self.show_blank()

    # ------------------------------------------------------------------ state
    def _markers_list(self) -> list:
        out = []
        if self.tx_pos:
            out.append({"role": "tx", "lat": self.tx_pos[0], "lon": self.tx_pos[1],
                        "color": TX_COLOR, "label": self.tx_label})
        if self.rx_pos:
            out.append({"role": "rx", "lat": self.rx_pos[0], "lon": self.rx_pos[1],
                        "color": RX_COLOR, "label": self.rx_label})
        return out

    def set_site_labels(self, tx: str = None, rx: str = None) -> None:
        if tx is not None:
            self.tx_label = tx or "Tx"
        if rx is not None:
            self.rx_label = rx or "Rx"
        self._update_markers()

    def arm(self, role: str) -> None:
        self._armed = role
        self.page().runJavaScript(f"window.__armedRole='{role}';")

    def set_tx(self, lat: float, lon: float) -> None:
        self.tx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def set_rx(self, lat: float, lon: float) -> None:
        self.rx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def _update_markers(self) -> None:
        js = "placeMarkers(" + json.dumps(self._markers_list()) + ");"
        self.page().runJavaScript(js)

    def _on_loaded(self, _ok: bool) -> None:
        self._ready = True
        self._update_markers()
        if self._focus is not None:
            lat, lon = self._focus
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        self._ready = False
        html = render_html(self._template, self._coverage, self._markers_list(), self._armed)
        self.setHtml(html)

    def show_blank(self) -> None:
        self._coverage = None
        self._render()

    def show_coverage(self, png_path: str, bbox, color_file: Optional[str] = None) -> None:
        """Display a coverage PNG over the map; ``bbox`` is (N, E, S, W).

        When ``color_file`` is given, its weakest (base) colour is keyed to
        fully transparent so the basemap shows through at the faint edge of
        the coverage (Signal-Server has no native per-band alpha).
        """
        n, e, s, w = bbox
        with open(png_path, "rb") as fh:
            raw = fh.read()
        base = _color_base_rgb(color_file)
        if base is not None:
            raw = _make_base_transparent(raw, base)
        b64 = base64.b64encode(raw).decode("ascii")
        self._coverage = (f"data:image/png;base64,{b64}", [s, w, n, e])
        self._render()


def _color_base_rgb(color_file: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Return the weakest-band RGB of a Signal-Server colour file (.scf)."""
    if not color_file:
        return None
    scf = os.path.splitext(color_file)[0] + ".scf"
    path = scf if os.path.exists(scf) else (color_file if os.path.exists(color_file) else None)
    if not path:
        return None
    weakest = None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = re.match(r"\s*(-?\d+)\s*:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", line)
                if not m:
                    continue
                lvl = int(m.group(1))
                rgb = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
                if weakest is None or lvl < weakest[0]:
                    weakest = (lvl, rgb)
    except OSError:
        return None
    return weakest[1] if weakest else None


def _make_base_transparent(raw: bytes, base: Tuple[int, int, int]) -> bytes:
    """Key pixels matching ``base`` to alpha 0; return re-encoded PNG bytes."""
    img = QImage()
    if not img.loadFromData(raw):
        return raw
    r, g, b = base
    mask = img.createMaskFromColor(QColor(r, g, b).rgb(), Qt.MaskMode.MaskOutColor)
    img.setAlphaChannel(mask)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.ReadWrite)
    if not img.save(buf, "PNG"):
        return raw
    return bytes(buf.data())


class MapView(QWebEngineView):
    picked = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self._template = _template_html()
        self._coverage = None            # (data_uri, [s,w,n,e]) or None
        self.tx_pos = None               # (lat, lon) or None
        self.rx_pos = None
        self._armed = "tx"
        self._ready = False              # True once the web page has loaded
        self._focus = None               # (lat, lon) to fly to after load
        self._page = PickerPage(self)
        self.setPage(self._page)
        self.tx_label = "Tx"
        self.rx_label = "Rx"
        self.loadFinished.connect(self._on_loaded)
        self.show_blank()

    # ------------------------------------------------------------------ state
    def _markers_list(self) -> list:
        out = []
        if self.tx_pos:
            out.append({"role": "tx", "lat": self.tx_pos[0], "lon": self.tx_pos[1],
                        "color": TX_COLOR, "label": self.tx_label})
        if self.rx_pos:
            out.append({"role": "rx", "lat": self.rx_pos[0], "lon": self.rx_pos[1],
                        "color": RX_COLOR, "label": self.rx_label})
        return out

    def set_site_labels(self, tx: str = None, rx: str = None) -> None:
        if tx is not None:
            self.tx_label = tx or "Tx"
        if rx is not None:
            self.rx_label = rx or "Rx"
        self._update_markers()

    def arm(self, role: str) -> None:
        self._armed = role
        self.page().runJavaScript(f"window.__armedRole='{role}';")

    def set_tx(self, lat: float, lon: float) -> None:
        self.tx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def set_rx(self, lat: float, lon: float) -> None:
        self.rx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def _update_markers(self) -> None:
        js = "placeMarkers(" + json.dumps(self._markers_list()) + ");"
        self.page().runJavaScript(js)

    def _on_loaded(self, _ok: bool) -> None:
        self._ready = True
        self._update_markers()
        if self._focus is not None:
            lat, lon = self._focus
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        self._ready = False
        html = render_html(self._template, self._coverage, self._markers_list(), self._armed)
        self.setHtml(html)

    def show_blank(self) -> None:
        self._coverage = None
        self._render()

    def show_coverage(self, png_path: str, bbox, color_file: Optional[str] = None) -> None:
        """Display a coverage PNG over the map; ``bbox`` is (N, E, S, W).

        When ``color_file`` is given, its weakest (base) colour is keyed to
        fully transparent so the basemap shows through at the faint edge of
        the coverage (Signal-Server has no native per-band alpha).
        """
        n, e, s, w = bbox
        with open(png_path, "rb") as fh:
            raw = fh.read()
        base = _color_base_rgb(color_file)
        if base is not None:
            raw = _make_base_transparent(raw, base)
        b64 = base64.b64encode(raw).decode("ascii")
        self._coverage = (f"data:image/png;base64,{b64}", [s, w, n, e])
        self._render()

    def clear_coverage(self) -> None:
        """Remove the coverage overlay (Tx/Rx markers are kept)."""
        self._coverage = None
        self._render()

    def set_opacity(self, value: int) -> None:
        """Set the coverage overlay opacity (0-100) via JavaScript.

        Can be called directly from a PySide6 QSlider.valueChanged signal
        without reloading the map page.  When no overlay is loaded the call
        is a no-op on the JS side.
        """
        js = (
            f"if (typeof overlay !== 'undefined' && overlay !== null) {{"
            f"  document.getElementById('opacitySlider').value = {value};"
            f"  if (typeof _onZoomOpacity === 'function') _onZoomOpacity();"
            f"}}"
        )
        self.page().runJavaScript(js)

    def get_state(self, callback) -> None:
        """Return the current map state (basemap/adaptive/opacity/center/zoom).

        ``callback`` receives the deserialized dict (or ``None`` if unavailable).
        """
        def _cb(raw):
            try:
                callback(json.loads(raw) if isinstance(raw, str) else raw)
            except (ValueError, TypeError):
                callback(None)
        self.page().runJavaScript("getMapState()", _cb)

    def apply_state(self, state: dict) -> None:
        """Apply a map-state dict previously produced by ``get_state``."""
        if not isinstance(state, dict):
            return
        js = "applyMapState(" + json.dumps(state) + ");"
        self.page().runJavaScript(js)

    def invalidate_size(self) -> None:
        """Tell Leaflet to recompute its size after the container resizes.

        Needed when the QWebEngineView is resized by the splitter/Qt layout
        without the top-level window firing a resize event (Leaflet otherwise
        keeps stale tile bounds).
        """
        self.page().runJavaScript(
            "if (typeof map !== 'undefined' && map) { map.invalidateSize(false); }")

