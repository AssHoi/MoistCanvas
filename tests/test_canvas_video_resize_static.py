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


def _css_block(source, selector):
    start = source.index(selector)
    end = source.index("}", start) + 1
    return source[start:end]


def test_video_css_scales_16_9_without_fixed_135px_height():
    html = _html()

    node_css = _css_block(html, ".vid-node {")
    video_css = _css_block(html, ".vid-node video {")

    assert "width: 240px;" not in node_css
    assert "height: 135px;" not in video_css
    assert "aspect-ratio: 16 / 9;" in video_css
    assert "height: auto;" in video_css


def test_create_video_node_accepts_and_stores_width():
    html = _html()
    create_video = _fn(html, "createVideoNode")

    assert "function createVideoNode(url, name, x, y, restoreId, width, options)" in create_video
    assert "const videoWidth = Math.max(80, Math.min(1200, Number(width) || 240));" in create_video
    assert "el.style.width = videoWidth + 'px';" in create_video
    assert "width: videoWidth" in create_video


def test_single_resize_can_target_video_nodes():
    html = _html()
    render_overlay = _fn(html, "renderSelectionOverlay")
    begin_resize = _fn(html, "beginOverlayResize")
    update_single = _fn(html, "updateSingleResize")

    single_selection = render_overlay[
        render_overlay.index("if (selRects.length === 1)") :
        render_overlay.index("// Multi-select")
    ]
    assert "nodeEntryById(only.id)" in single_selection or "videoNodes.has(only.id)" in single_selection
    assert "const entry = nodeEntryById(id);" in begin_resize
    assert "imageNodes.get(id)" not in begin_resize[begin_resize.index("if (mode === 'single')") : begin_resize.index("} else {")]
    assert "st.entry.width = newW;" in update_single
    assert "st.entry.naturalWidth" in update_single


def test_group_resize_scales_video_widths_too():
    html = _html()
    update_group = _fn(html, "updateGroupResize")

    assert "video keeps its fixed CSS size" not in update_group
    assert "if (!it.isImage) return;" not in update_group
    assert "if ((it.isImage || it.isVideo) && it.entry)" in update_group
    assert "it.entry.width = newW;" in update_group


def test_save_restore_and_copy_paste_preserve_video_width():
    html = _html()
    clone = _fn(html, "cloneCanvasNodeForClipboard")
    paste = _fn(html, "pasteCopiedNodes")
    serialize_start = html.index("videoNodes.forEach((n) => {")
    serialize_end = html.index("return {", serialize_start)
    serialize_video = html[serialize_start:serialize_end]

    assert "width:  node.width || 240" in clone
    assert "createVideoNode(item.url, item.name, tx_, ty_, null, item.width" in paste
    assert "width: n.width || 240" in serialize_video
    assert "createVideoNode(n.url, n.name || '', n.x || 0, n.y || 0, n.id, n.width" in html


if __name__ == "__main__":
    test_video_css_scales_16_9_without_fixed_135px_height()
    test_create_video_node_accepts_and_stores_width()
    test_single_resize_can_target_video_nodes()
    test_group_resize_scales_video_widths_too()
    test_save_restore_and_copy_paste_preserve_video_width()
    print("OK")
