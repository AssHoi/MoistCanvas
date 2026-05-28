from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def test_canvas_has_external_clipboard_paste_handler():
    html = CANVAS_HTML.read_text(encoding="utf-8")

    assert "function extractClipboardImageFiles" in html
    assert "function canvasPastePoint" in html
    assert "function initCanvasPaste" in html
    assert "document.addEventListener('paste'" in html
    assert "await uploadImagesAtPoint(images, point.wx, point.wy)" in html


def test_keydown_does_not_block_native_paste_event():
    html = CANVAS_HTML.read_text(encoding="utf-8")
    keydown_start = html.index("Ctrl/Cmd + C / V / Z keyboard shortcuts")
    keydown_end = html.index("document.addEventListener('keyup'", keydown_start)
    keydown_block = html[keydown_start:keydown_end]

    assert "pasteCopiedNodes();" not in keydown_block


if __name__ == "__main__":
    test_canvas_has_external_clipboard_paste_handler()
    test_keydown_does_not_block_native_paste_event()
