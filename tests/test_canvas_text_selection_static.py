from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def _shortcut_block(html):
    shortcut_start = html.index("document.addEventListener('keydown', (e) => {", html.index("Ctrl/Cmd + C"))
    shortcut_end = html.index("document.addEventListener('keyup'", shortcut_start)
    return html[shortcut_start:shortcut_end]


def test_readable_chat_and_request_log_text_is_selectable():
    html = _html()

    assert ".chat-bubble," in html
    assert ".chat-prompt-text," in html
    assert ".req-log-panel," in html
    assert ".req-log-title," in html
    assert ".req-log-pre," in html
    assert "-webkit-user-select: text;" in html
    assert "user-select: text;" in html


def test_canvas_node_drag_suppression_keeps_text_children_selectable():
    html = _html()

    node_start = html.index(".c-node {")
    node_end = html.index(".c-node:active", node_start)
    assert "user-select: none;" in html[node_start:node_end]

    selectable_start = html.index(".chat-bubble,")
    selectable_end = html.index(".chat-msg.user .chat-bubble", selectable_start)
    selectable_css = html[selectable_start:selectable_end]
    for selector in (
        ".c-node h3",
        ".c-node p",
        ".c-node pre",
        ".c-node code",
    ):
        assert selector in selectable_css


def test_ctrl_c_allows_native_text_selection_copy():
    html = _html()

    assert "function hasNativeTextSelection()" in html
    shortcut = _shortcut_block(html)

    assert "if (k === 'c' && hasNativeTextSelection()) return;" in shortcut
    assert "e.preventDefault();" in shortcut
    assert "copySelectedNodes();" in shortcut


def test_ctrl_c_without_native_text_selection_still_copies_canvas_nodes():
    shortcut = _shortcut_block(_html())

    native_selection_guard = shortcut.index("if (k === 'c' && hasNativeTextSelection()) return;")
    copy_branch = shortcut.index("if (k === 'c') {", native_selection_guard)
    undo_branch = shortcut.index("} else if (k === 'z' && !e.shiftKey) {", copy_branch)
    copy_body = shortcut[copy_branch:undo_branch]

    assert "e.preventDefault();" in copy_body
    assert "copySelectedNodes();" in copy_body
    assert copy_body.index("e.preventDefault();") < copy_body.index("copySelectedNodes();")


def test_native_text_selection_guard_only_short_circuits_ctrl_c():
    shortcut = _shortcut_block(_html())

    assert shortcut.count("hasNativeTextSelection()") == 1
    native_selection_guard = shortcut.index("if (k === 'c' && hasNativeTextSelection()) return;")
    copy_branch = shortcut.index("if (k === 'c') {", native_selection_guard)
    undo_branch = shortcut.index("} else if (k === 'z' && !e.shiftKey) {", copy_branch)
    undo_body = shortcut[undo_branch:]

    assert native_selection_guard < copy_branch < undo_branch
    assert "hasNativeTextSelection()" not in undo_body
    assert "e.preventDefault();" in undo_body
    assert "undoCanvas();" in undo_body


if __name__ == "__main__":
    test_readable_chat_and_request_log_text_is_selectable()
    test_canvas_node_drag_suppression_keeps_text_children_selectable()
    test_ctrl_c_allows_native_text_selection_copy()
    test_ctrl_c_without_native_text_selection_still_copies_canvas_nodes()
    test_native_text_selection_guard_only_short_circuits_ctrl_c()
    print("OK")
