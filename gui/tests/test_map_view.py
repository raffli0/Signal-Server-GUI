import os

from signal_gui import map_view

TEMPLATE = os.path.join(os.path.dirname(map_view.__file__), "resources", "map.html")


def _tpl():
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_render_html_injects_handler_and_no_placeholder():
    html = map_view.render_html(_tpl(), None, [], "tx")
    assert "app://pick" in html
    assert "window.__armedRole='tx'" in html
    assert "/*__DATA__*/" not in html


def test_render_html_markers():
    markers = [{"role": "tx", "lat": 51.849, "lon": -2.2299,
                "color": map_view.TX_COLOR, "label": "Tx"}]
    html = map_view.render_html(_tpl(), None, markers, "tx")
    assert '"label": "Tx"' in html
    assert map_view.TX_COLOR in html
    assert '"role": "tx"' in html


def test_render_html_coverage_bounds():
    uri = "data:image/png;base64,AAAA"
    html = map_view.render_html(_tpl(), (uri, [51.5, -2.3, 52.1, -1.7]), [], "tx")
    assert uri in html
    # bounds emitted as [[south, west], [north, east]]
    assert "[[51.5, -2.3], [52.1, -1.7]]" in html


def test_render_html_cov_palette_injection():
    pal = {"colors": [[255, 0, 0], [0, 100, 255]], "levels": [-60.0, -120.0]}
    html = map_view.render_html(_tpl(), None, [], "tx", cov_palette=pal)
    assert "window.__covPalette=" in html
    assert "[255, 0, 0]" in html and "-120.0" in html


def test_render_html_no_palette_by_default():
    html = map_view.render_html(_tpl(), None, [], "tx")
    assert "window.__covPalette=" not in html


def test_palette_from_color_file_bundled_dcf():
    pal = map_view.palette_from_color_file(None)  # falls back to bundled .dcf
    assert pal is not None
    assert pal["colors"][0] == [255, 0, 0]        # strongest band is red
    assert pal["levels"][0] == -60.0
    assert pal["levels"][-1] == -120.0
    assert len(pal["colors"]) == len(pal["levels"]) == 6


def test_palette_from_missing_color_file_falls_back(tmp_path):
    missing = str(tmp_path / "nope.dcf")
    pal = map_view.palette_from_color_file(missing)
    assert pal is not None                        # still serves the bundled table
    assert pal["levels"][0] == -60.0


def test_parse_pick_url():
    assert map_view.parse_pick_url("app://pick?role=tx&lat=51.5&lon=-2.2") == ("tx", 51.5, -2.2)
    assert map_view.parse_pick_url("app://pick?role=rx&lat=-33.0&lon=151.0") == ("rx", -33.0, 151.0)
    assert map_view.parse_pick_url("https://example.com") is None
    assert map_view.parse_pick_url("app://pick?role=tx&lat=bad&lon=1") is None


def test_draw_link_js_accepts_color():
    html = _tpl()
    # The Tx->Rx link/LOS polyline overlay is intentionally disabled so the
    # coverage map stays free of the link line. drawLink must still be defined
    # (no-op) but must not create a polyline layer.
    assert "function drawLink(txLat, txLon, rxLat, rxLon, color)" in html
    body = html.split("function drawLink", 1)[1]
    assert "L.polyline" not in body.split("function clearLink", 1)[0]
