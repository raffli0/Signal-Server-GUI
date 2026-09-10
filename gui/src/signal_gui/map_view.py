"""Interactive coverage map (Leaflet + QtWebEngineView).

The coverage PNG is embedded as a base64 data URI inside an ImageOverlay over
an OSM basemap. Clicking the map (when "armed" from the sidebar) emits a
``picked`` signal back to Python via an ``app://pick`` URL intercepted by
``PickerPage`` -- used to drop Tx/Rx markers and auto-fill the coordinate
fields.
"""

from __future__ import annotations
from typing import Optional

import base64

import json
import os
import re

from PySide6.QtCore import Qt, QUrl, QUrlQuery, Signal
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


def render_html(template: str, coverage, markers, armed: str,
                cov_palette=None, points_locked: bool = False) -> str:
    """Build the final HTML string by injecting coverage/markers/armed state.

    ``coverage`` is ``(data_uri, [south, west, north, east])`` or ``None``.
    ``markers`` is a list of dicts with role/lat/lon/color/label.
    ``cov_palette`` is ``{"colors": [[r,g,b]...], "levels": [dBm...]}``
    (strongest band first) powering the hover-dBm tooltip and the per-band
    layer menu; injected as ``window.__covPalette``.
    """
    if coverage:
        data_uri, bounds = coverage
        s, w, n, e = bounds
        cov_js = "{{dataUri:'{}', bounds:[[{}, {}], [{}, {}]]}}".format(data_uri, s, w, n, e)
    else:
        cov_js = "null"
    markers_js = json.dumps(markers or [])
    palette_js = ""
    if cov_palette:
        palette_js = "window.__covPalette=" + json.dumps(cov_palette) + ";"
    locked_js = f"window.__pointsLocked={'true' if points_locked else 'false'};"
    inject = (
        f"window.__coverage={cov_js};"
        f"window.__markers={markers_js};"
        f"window.__armedRole='{armed}';"
        + locked_js
        + palette_js
    )
    return template.replace("/*__DATA__*/", inject)


def palette_from_color_file(color_file: Optional[str]):
    """Parse the engine colour table into a hover-palette dict.

    Returns ``{"colors": [[r,g,b], ...], "levels": [dBm, ...]}`` strongest band
    first, or ``None`` when no colour table can be read (the JS side then falls
    back to its built-in defaults).
    """
    from . import rm_style

    candidates = [
        color_file,
        os.path.join(os.path.dirname(__file__), "resources", "radiomobile.dcf"),
    ]
    text = None
    for cand in candidates:
        if cand and os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                break
            except OSError:
                continue
    if not text:
        return None
    bands = rm_style.parse_dcf_levels(text)
    if not bands:
        return None
    return {
        "colors": [list(rgb) for _lvl, rgb in bands],
        "levels": [float(lvl) for lvl, _rgb in bands],
    }


class PickerPage(QWebEnginePage):
    """Intercepts ``app://pick``, ``app://toggle_lock``, and ``app://swap`` navigations and forwards them to the owner."""

    def __init__(self, owner: "MapView"):
        super().__init__(owner)
        self._owner = owner

    def acceptNavigationRequest(self, url: QUrl, _type, _isMainFrame: bool) -> bool:
        if url.scheme() == "app":
            url_str = url.toString()
            if url.host() == "toggle_lock" or "toggle_lock" in url_str:
                self._owner.lock_toggled.emit()
                return False
            if url.host() == "swap" or "swap" in url_str:
                self._owner.swap_requested.emit()
                return False
            parsed = parse_pick_url(url_str)
            if parsed:
                self._owner.picked.emit(*parsed)
            return False  # never actually navigate
        return super().acceptNavigationRequest(url, _type, _isMainFrame)


class MapView(QWebEngineView):
    picked = Signal(str, float, float)
    lock_toggled = Signal()
    swap_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self._template = _template_html()
        self._coverage = None            # (data_uri, [s,w,n,e]) or None
        self._cov_palette = None         # hover-palette dict for the live page
        self.tx_pos = None               # (lat, lon) or None
        self.rx_pos = None
        self.tx_saved_pos = None         # Tx used by the last finished run
        self._armed = "tx"
        self._ready = False              # True once the web page has loaded
        self._focus = None               # (lat, lon) to fly to after load
        self.points_locked = False
        self._page = PickerPage(self)
        self.setPage(self._page)
        self.tx_label = "Tx"
        self.rx_label = "Rx"
        self.loadFinished.connect(self._on_loaded)
        self.show_blank()

    # ------------------------------------------------------------------ state
    def _markers_list(self) -> list:
        out = []
        if self.tx_saved_pos and self.tx_saved_pos != self.tx_pos:
            out.append({"role": "tx_saved", "lat": self.tx_saved_pos[0],
                        "lon": self.tx_saved_pos[1], "label": self.tx_label})
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

    def set_tx(self, lat: float, lon: float, fly: bool = False) -> None:
        self.tx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            if fly:
                self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def set_rx(self, lat: float, lon: float, fly: bool = False) -> None:
        self.rx_pos = (lat, lon)
        self._focus = (lat, lon)
        if self._ready:
            self._update_markers()
            if fly:
                self.page().runJavaScript(f"flyToSite({lat},{lon});")

    def mark_tx_saved(self, lat: float, lon: float) -> None:
        """Flag the Tx position used by the last finished propagation run.

        The saved Tx stays visible as a black pin while the active Tx moves on
        (e.g. after an accidental map click), so the user can see where the
        displayed coverage was computed.
        """
        self.tx_saved_pos = (lat, lon)
        if self._ready:
            self._update_markers()

    def clear_tx_saved(self) -> None:
        """Remove the black 'saved' Tx indicator."""
        if self.tx_saved_pos is None:
            return
        self.tx_saved_pos = None
        if self._ready:
            self._update_markers()

    def _update_markers(self) -> None:
        js = "placeMarkers(" + json.dumps(self._markers_list()) + ");"
        self.page().runJavaScript(js)

    def set_points_locked(self, locked: bool) -> None:
        self.points_locked = bool(locked)
        if self._ready:
            js_bool = "true" if self.points_locked else "false"
            self.page().runJavaScript(f"if (typeof setPointsLocked === 'function') setPointsLocked({js_bool});")

    def _on_loaded(self, _ok: bool) -> None:
        self._ready = True
        self._update_markers()
        if self.points_locked:
            self.page().runJavaScript("if (typeof setPointsLocked === 'function') setPointsLocked(true);")
        # When a coverage overlay is shown, loadCoverage() already fitBounds() to
        # it -- don't clobber that with a forced zoom-14 fly-to (which would hide
        # a large (e.g. 100 km) result). Only auto-fly on the blank initial load.
        if self._coverage is None and self._focus is not None:
            lat, lon = self._focus
            self.page().runJavaScript(f"flyToSite({lat},{lon});")

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        self._ready = False
        html = render_html(self._template, self._coverage, self._markers_list(),
                           self._armed, cov_palette=self._cov_palette,
                           points_locked=self.points_locked)
        self.setHtml(html)

    def show_blank(self) -> None:
        self._coverage = None
        self._cov_palette = None
        self._render()

    def show_coverage(self, png_path: str, bbox, color_file: Optional[str] = None,
                      contour_mode: Optional[int] = None) -> None:
        """Display a coverage PNG over the map; ``bbox`` is (N, E, S, W).

        The PNG is shown as-is so every palette band keeps its exact colour
        (matching Radio Mobile). Transparency comes solely from the engine's
        white background, already keyed during PPM->PNG conversion. The colour
        table is also parsed so the hover tooltip can report the dBm band at
        the cursor position.
        """
        if contour_mode is not None:
            self._contour_mode = int(contour_mode)
        cur_mode = getattr(self, "_contour_mode", 0)
        n, e, s, w = bbox
        with open(png_path, "rb") as fh:
            raw = fh.read()
        b64 = base64.b64encode(raw).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        self._coverage = (data_uri, [s, w, n, e])
        self._cov_palette = palette_from_color_file(color_file)
        if self._ready:
            pal_js = f"window.__covPalette = {json.dumps(self._cov_palette)};" if self._cov_palette else ""
            mode_js = f"if (typeof setContourMode === 'function') setContourMode({cur_mode});"
            js = f"{pal_js} {mode_js} loadCoverage('{data_uri}', [[{s}, {w}], [{n}, {e}]]);"
            self.page().runJavaScript(js)
        else:
            self._render()

    def clear_coverage(self) -> None:
        """Remove the coverage overlay + link line from the live map (Tx/Rx
        markers are kept).

        Removes the layers via JavaScript instead of re-rendering the page, so
        the map stays exactly where the user panned/zoomed it. A full
        ``_render()`` would reinitialize Leaflet at the default center — the
        unwanted "snap to initial coordinates" on Clear.
        """
        self._coverage = None
        self._cov_palette = None
        self._focus = None
        self.clear_tx_saved()
        if self._ready:
            js = (
                "if (typeof overlay !== 'undefined' && overlay) {"
                "  map.removeLayer(overlay); overlay = null; }"
                "if (typeof clearLink === 'function') { clearLink(); }"
                "if (typeof hideCovTip === 'function') { hideCovTip(); }"
            )
            self.page().runJavaScript(js)
        else:
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

    def draw_link(self, tx_lat: float, tx_lon: float, rx_lat: float, rx_lon: float,
                  color: str = "#00e600") -> None:
        """Draw the Tx->Rx Radio Link polyline on the map (color = link grade)."""
        self.page().runJavaScript(
            f"drawLink({tx_lat},{tx_lon},{rx_lat},{rx_lon},'{color}');")

    def set_link_cursor(self, lat: float, lon: float, dist_km: float = 0.0,
                        amsl_m: float = 0.0, agl_m: float = 0.0, ground_m: float = 0.0) -> None:
        """Move the interactive tracking marker along the Tx->Rx link on the map with 2D altitude/AGL."""
        self.page().runJavaScript(
            f"setLinkCursor({lat},{lon},{dist_km},{amsl_m},{agl_m},{ground_m});")

    def clear_link(self) -> None:
        """Remove the Radio Link polyline and tracking cursor from the map."""
        self.page().runJavaScript("clearLink();")

    def set_contour_mode(self, mode: int) -> None:
        """Switch contour relief mode on the live map: 0=subtle, 1=flat, 2=full."""
        self._contour_mode = int(mode)
        if self._ready:
            self.page().runJavaScript(f"if (typeof setContourMode === 'function') setContourMode({int(mode)});")

    def toggle_contour(self) -> None:
        """Toggle the 3D terrain relief / contour texture of the coverage overlay in real time."""
        self.page().runJavaScript("if (typeof toggleContour === 'function') toggleContour();")

    def set_contour(self, enabled: bool) -> None:
        """Set whether 3D terrain relief / contour is shown on the coverage overlay."""
        mode = 0 if enabled else 1
        self.set_contour_mode(mode)

    def toggle_transparent_holes(self) -> None:
        """Toggle whether unpainted / blocked terrain shadow holes are transparent in real time."""
        self.page().runJavaScript("if (typeof toggleHoles === 'function') toggleHoles();")

    def set_transparent_holes(self, enabled: bool) -> None:
        """Set whether unpainted / blocked terrain shadow holes are transparent."""
        self.page().runJavaScript(f"if (typeof setTransparentHoles === 'function') setTransparentHoles({str(enabled).lower()});")


