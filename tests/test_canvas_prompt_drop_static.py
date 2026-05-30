"""Static-source checks for the "drop external image into the prompt area"
feature.

Verifies:
- A right-panel drop handler exists and is wired with preventDefault.
- The helper uploads via /api/ai/upload then creates a canvas image node —
  the file is NEVER inserted as a base64 <img> in the contenteditable.
- New refs are pushed with `label: ''` first, then renumberRefs() runs, and
  insertAtRef(ref.label) is called only AFTER renumbering — that is the
  invariant that guarantees a pre-existing @图1 stays @图1 and the new
  drop becomes @图2.
- No code path overwrites an existing token (no assignments like
  `ref.label = '图1'` from inside the helper).
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _helper_block():
    html = CANVAS_HTML.read_text(encoding="utf-8")
    start = html.index("async function addExternalImagesAsPromptRefs(files)")
    # Helper ends just before the IIFE initPromptDrop.
    end = html.index("(function initPromptDrop()", start)
    return html, html[start:end]


def test_drop_handler_attached_to_right_panel():
    html = CANVAS_HTML.read_text(encoding="utf-8")
    assert "function initPromptDrop()" in html
    init_start = html.index("function initPromptDrop()")
    init_end   = html.index("})();", init_start) + len("})();")
    init_block = html[init_start:init_end]

    # Attached to right-panel and reads dataTransfer.files.
    assert "document.getElementById('right-panel')" in init_block
    for evt in ("dragenter", "dragover", "dragleave", "drop"):
        assert f"addEventListener('{evt}'" in init_block, (
            f"initPromptDrop missing '{evt}' listener"
        )
    # Default browser content-editable insertion is suppressed.
    assert "e.preventDefault()" in init_block
    # Canvas-area drop handler must not double-fire.
    assert "e.stopPropagation()" in init_block
    # Hint class added on dragover, cleared on drop/leave.
    assert "drop-target-active" in init_block
    assert "addExternalImagesAsPromptRefs" in init_block
    assert "clearExternalImageDragHighlights" in html
    assert "canvas-area" in init_block
    assert "classList.remove('dragover')" in init_block


def test_helper_uploads_then_creates_canvas_node_then_renumbers_then_inserts():
    html, helper = _helper_block()

    # 1) Real upload — same endpoint /api/ai/upload as the canvas drop.
    assert "fetch('/api/ai/upload'" in helper
    assert "FormData" in helper

    # 2) A canvas image node is created (so the asset behaves like every
    #    other image — persisted, moveable, exportable).
    assert "createImageNode(" in helper
    assert "originLabel: '外部导入：'" in helper

    # 3) The file is NEVER inserted as a base64 <img> into contenteditable.
    #    We forbid Image / FileReader / document.execCommand('insertImage',
    #    or src-by-data URI construction from inside this helper.
    for forbidden in (
        "FileReader",
        "execCommand('insertImage'",
        "createObjectURL(",
        "innerHTML",
        "data:image",
    ):
        assert forbidden not in helper, (
            f"addExternalImagesAsPromptRefs must not use '{forbidden}' "
            "— the image must end up as a real canvas node, not a base64 "
            "blob inside the contenteditable."
        )

    # 4) ORDER MATTERS: push refs with empty label → renumberRefs() →
    #    insertAtRef(ref.label). Any other order would either clobber an
    #    existing @图1 or assign a duplicate label.
    push_idx     = helper.find("refs.push(ref);")
    renumber_idx = helper.find("renumberRefs();")
    insert_idx   = helper.find("insertAtRef(ref.label)")
    assert push_idx     >= 0, "Helper must push a ref with empty label"
    assert renumber_idx >= 0, "Helper must call renumberRefs() to allocate labels"
    assert insert_idx   >= 0, "Helper must insertAtRef(ref.label) AFTER renumbering"
    assert push_idx < renumber_idx < insert_idx, (
        "Order is violated. Required: refs.push (empty label) → "
        "renumberRefs() → insertAtRef(ref.label)."
    )

    # 5) The pushed ref carries an EMPTY label (so renumberRefs can pick the
    #    smallest unused slot). The helper must not assign '图1' itself.
    assert "label: ''" in helper
    # Defensive: no hard-coded label assignment that would clobber state.
    assert "ref.label = '图" not in helper

    # 6) Placement uses the shared "near viewport, no overlap" helper.
    assert "placeMediaGroupNearViewport(" in helper


def test_helper_handles_upload_failure_cleanly():
    _, helper = _helper_block()
    # Network / non-2xx errors must surface a toast and bail BEFORE we touch
    # refs or insert any chip. The whole upload step is wrapped in try/catch
    # and the catch path returns without creating refs.
    upload_try = helper.index("try {")
    upload_catch = helper.index("} catch (err) {", upload_try)
    catch_body = helper[upload_catch:helper.index("}", upload_catch + 16)]
    assert "上传失败" in catch_body
    assert "return" in catch_body


def test_drop_hint_css_present():
    html = CANVAS_HTML.read_text(encoding="utf-8")
    assert "#right-panel.drop-target-active" in html
    # Subtle hint label so users know the drop will create a ref chip and
    # NOT a chat attachment.
    assert "松开鼠标添加为参考图" in html


def test_drag_highlights_are_cleared_globally():
    html = CANVAS_HTML.read_text(encoding="utf-8")
    assert "function clearDragHighlights()" in html
    assert "window.clearExternalImageDragHighlights = clearDragHighlights" in html
    assert "document.addEventListener('dragend', clearDragHighlights)" in html
    assert "document.addEventListener('drop', clearDragHighlights)" in html
    assert "if (e.target === area || !area.contains(e.relatedTarget)) area.classList.remove('dragover')" in html


if __name__ == "__main__":
    test_drop_handler_attached_to_right_panel()
    test_helper_uploads_then_creates_canvas_node_then_renumbers_then_inserts()
    test_helper_handles_upload_failure_cleanly()
    test_drop_hint_css_present()
    test_drag_highlights_are_cleared_globally()
    print("OK")
