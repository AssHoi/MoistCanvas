"""Static checks for image origin labels and non-overlapping generated media."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def _fn(html, name):
    needle = f"function {name}"
    start = html.index(needle)
    end = html.index("\nfunction ", start + 1)
    return html[start:end]


def test_origin_label_flows_through_image_lifecycle():
    html = _html()
    create = _fn(html, "createImageNode")
    serialize = _fn(html, "serializeCanvasV2")
    restore_start = html.index("function restoreCanvasV2(data)")
    restore_end = html.find("\nfunction ", restore_start + 1)
    if restore_end < 0:
        restore_end = len(html)
    restore = html[restore_start:restore_end]
    clone = _fn(html, "cloneCanvasNodeForClipboard")
    paste = _fn(html, "pasteCopiedNodes")

    assert "originLabel" in create
    assert "img-origin-label" in create
    assert "originLabel," in create
    assert "originLabel: n.originLabel" in serialize
    assert "originLabel: n.originLabel || ''" in restore
    assert "originLabel: node.originLabel || ''" in clone
    assert "originLabel: item.originLabel || ''" in paste


def test_external_imports_set_origin_label_from_filename():
    html = _html()
    upload = _fn(html, "uploadImagesAtPoint")
    assert "外部导入：" in upload
    assert "originLabel: '外部导入：' + (f.name ||" in upload
    assert "createImageNode(" in upload


def test_generation_and_rerun_use_user_prompt_as_origin_label():
    html = _html()
    run = _fn(html, "_runGenerationTask")
    rerun = _fn(html, "rerunConversationRequest")

    assert "const imageOriginLabel = prompt || ''" in run
    assert "originLabel: imageOriginLabel" in run
    assert "const imageOriginLabel = userMsg.prompt || body.prompt || ''" in rerun
    assert "originLabel: imageOriginLabel" in rerun


def test_generated_media_uses_nearby_free_placement():
    html = _html()
    assert "function findNearbyFreePlacement(" in html
    assert "function mediaRectsOverlap(" in html

    run = _fn(html, "_runGenerationTask")
    rerun = _fn(html, "rerunConversationRequest")
    assert "placeMediaGroupNearViewport(" in run
    assert "placeMediaGroupNearViewport(" in rerun


if __name__ == "__main__":
    test_origin_label_flows_through_image_lifecycle()
    test_external_imports_set_origin_label_from_filename()
    test_generation_and_rerun_use_user_prompt_as_origin_label()
    test_generated_media_uses_nearby_free_placement()
    print("OK")
