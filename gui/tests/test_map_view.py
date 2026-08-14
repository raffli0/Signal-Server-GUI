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


def test_parse_pick_url():
    assert map_view.parse_pick_url("app://pick?role=tx&lat=51.5&lon=-2.2") == ("tx", 51.5, -2.2)
    assert map_view.parse_pick_url("app://pick?role=rx&lat=-33.0&lon=151.0") == ("rx", -33.0, 151.0)
    assert map_view.parse_pick_url("https://example.com") is None
    assert map_view.parse_pick_url("app://pick?role=tx&lat=bad&lon=1") is None
