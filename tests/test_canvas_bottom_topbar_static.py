"""Static checks for the canvas bottom info bar layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def _css_block(html, selector):
    start = html.index(selector)
    end = html.index("}", start) + 1
    return html[start:end]


def test_bottom_toolbar_is_removed_from_canvas_dom():
    html = _html()

    assert 'id="canvas-toolbar"' not in html
    assert 'id="tool-select"' not in html
    assert 'id="tool-img"' not in html


def test_canvas_topbar_sits_in_bottom_toolbar_position():
    html = _html()
    topbar_css = _css_block(html, "#canvas-topbar {")

    assert "bottom: 32px" in topbar_css
    assert "left: 50%" in topbar_css
    assert "transform: translateX(-50%)" in topbar_css
    assert "top: 14px" not in topbar_css


def test_canvas_topbar_keeps_status_and_actions():
    html = _html()

    assert 'id="canvas-topbar"' in html
    assert 'id="canvas-title-label"' in html
    assert 'id="save-status"' in html
    assert 'id="zoom-label"' in html
    assert 'id="topbar-reset"' in html
    assert 'id="topbar-assets"' in html


def test_hidden_file_input_and_upload_entrypoint_remain():
    html = _html()

    assert '<input type="file" id="file-input"' in html
    assert 'style="display:none"' in html
    assert "function triggerUpload()" in html


if __name__ == "__main__":
    test_bottom_toolbar_is_removed_from_canvas_dom()
    test_canvas_topbar_sits_in_bottom_toolbar_position()
    test_canvas_topbar_keeps_status_and_actions()
    test_hidden_file_input_and_upload_entrypoint_remain()
    print("OK")
