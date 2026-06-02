"""Static checks for video origin labels across canvas lifecycles."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def _fn(source, name):
    needle = f"function {name}"
    start = source.index(needle)
    end = source.find("\nfunction ", start + 1)
    if end < 0:
        end = source.find("\nasync function ", start + 1)
    if end < 0:
        end = len(source)
    return source[start:end]


def test_video_node_accepts_displays_and_stores_origin_label():
    html = _html()
    create = _fn(html, "createVideoNode")

    assert "function createVideoNode(url, name, x, y, restoreId, width, options)" in create
    assert "const originLabel = (options && options.originLabel) ? String(options.originLabel) : '';" in create
    assert "vid-origin-label" in create
    assert "originEl.textContent = originLabel" in create
    assert "originEl.title = originLabel" in create
    assert "if (originEl) el.appendChild(originEl);" in create
    assert "originLabel," in create


def test_video_origin_label_css_matches_image_label_rule():
    html = _html()

    assert ".img-node .img-origin-label,\n    .vid-node .vid-origin-label" in html


def test_external_video_imports_set_origin_label_from_filename():
    html = _html()

    for fn_name in ("uploadImages", "uploadImagesAtPoint", "addExternalImagesAsPromptRefs"):
        block = _fn(html, fn_name)
        assert "createVideoNode(" in block
        assert "{ originLabel: '外部导入：' + (f.name || 'video') }" in block


def test_generated_rerun_and_asset_videos_use_prompt_origin_label():
    html = _html()
    run = _fn(html, "_runGenerationTask")
    rerun = _fn(html, "rerunConversationRequest")
    asset = _fn(html, "insertAssetToCanvas")

    assert "const videoOriginLabel = prompt || ''" in run
    assert "{ originLabel: videoOriginLabel }" in run
    assert "const videoOriginLabel = userMsg.prompt || body.prompt || ''" in rerun
    assert "{ originLabel: videoOriginLabel }" in rerun
    assert "asset.prompt ? { originLabel: asset.prompt } : null" in asset


def test_video_origin_label_save_restore_and_copy_paste():
    html = _html()
    clone = _fn(html, "cloneCanvasNodeForClipboard")
    paste = _fn(html, "pasteCopiedNodes")
    serialize_start = html.index("videoNodes.forEach((n) => {")
    serialize_end = html.index("return {", serialize_start)
    serialize_video = html[serialize_start:serialize_end]

    assert "originLabel: node.originLabel || ''" in clone
    assert "originLabel: item.originLabel || ''" in paste
    assert "originLabel: n.originLabel || ''" in serialize_video
    assert "createVideoNode(n.url, n.name || '', n.x || 0, n.y || 0, n.id, n.width, { originLabel: n.originLabel || '' })" in html


if __name__ == "__main__":
    test_video_node_accepts_displays_and_stores_origin_label()
    test_video_origin_label_css_matches_image_label_rule()
    test_external_video_imports_set_origin_label_from_filename()
    test_generated_rerun_and_asset_videos_use_prompt_origin_label()
    test_video_origin_label_save_restore_and_copy_paste()
    print("OK")
