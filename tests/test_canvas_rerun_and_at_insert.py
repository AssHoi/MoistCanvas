"""Static-source checks for the "再次生成" button and the insertAtRef fix.

These do NOT execute the JavaScript — they just verify that the expected
shapes are present in canvas.html so a future refactor can't silently
regress either feature.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def test_rerun_helper_exists_and_uses_requestlog_verbatim():
    html = CANVAS_HTML.read_text(encoding="utf-8")

    # Helper is defined.
    assert "function rerunConversationRequest(userMsg)" in html

    # Helper reads endpoint / body / method from the saved requestLog —
    # i.e. it does NOT re-read the current UI to build a fresh payload.
    helper_start = html.index("function rerunConversationRequest(userMsg)")
    helper_end   = html.index("// ═══════════════════════════════════════════════\n"
                              "// STATUS & TOAST", helper_start)
    helper = html[helper_start:helper_end]

    assert "userMsg.requestLog" in helper
    assert "log.endpoint" in helper
    assert "log.method" in helper
    assert "log.body" in helper

    # The actual fetch must serialize the captured body, not a freshly
    # built one. We don't allow the helper to call buildFinalPromptFromRefs,
    # collectImageRefUrlsFromRefs, resolveActiveMask, getRefsUsedByPrompt,
    # getParamValues, or parseModelValue — those would mean it's rebuilding
    # the payload from current UI state.
    assert "JSON.stringify(body)" in helper
    for forbidden in (
        "buildFinalPromptFromRefs",
        "collectImageRefUrlsFromRefs",
        "resolveActiveMask",
        "getRefsUsedByPrompt",
        "getParamValues(",
        "parseModelValue(",
        "promptInput.value",
    ):
        assert forbidden not in helper, (
            "rerunConversationRequest must replay the saved requestLog "
            f"verbatim and must not call {forbidden}"
        )

    # In-flight guard so a double-click can't fire two parallel requests.
    assert "_rerunInFlight" in helper


def test_rerun_appends_user_bubble_then_pending_assistant():
    """Conversation flow must look like the user re-sent the same prompt:
    a fresh role:'user' bubble appears first, then the pending assistant
    bubble underneath. Pure 静态 source check — relies on the literal order
    of appendConversationMessage call sites inside the helper.
    """
    html = CANVAS_HTML.read_text(encoding="utf-8")
    helper_start = html.index("function rerunConversationRequest(userMsg)")
    helper_end   = html.index("// ═══════════════════════════════════════════════\n"
                              "// STATUS & TOAST", helper_start)
    helper = html[helper_start:helper_end]

    user_append_idx = helper.find("appendConversationMessage({\n    role: 'user',")
    asst_append_idx = helper.find("appendConversationMessage({\n    role: 'assistant',")

    assert user_append_idx >= 0, (
        "rerunConversationRequest must appendConversationMessage a fresh "
        "role:'user' bubble before the pending assistant."
    )
    assert asst_append_idx >= 0, (
        "rerunConversationRequest must appendConversationMessage a pending "
        "role:'assistant' bubble."
    )
    assert user_append_idx < asst_append_idx, (
        "The new user bubble must be appended BEFORE the pending assistant "
        "bubble so the conversation order is user → pending → done."
    )

    # The new user message must preserve requestLog so its own (!) and
    # 再次生成 buttons remain functional on subsequent renders.
    user_block_end = helper.find("});", user_append_idx)
    user_block = helper[user_append_idx:user_block_end]
    assert "requestLog: userMsg.requestLog" in user_block, (
        "The cloned user bubble must carry the original requestLog forward."
    )

    # And it must propagate prompt/model/params/refUrls/mode so the visible
    # bubble looks like a real resend.
    for field in ("prompt:", "model:", "params:", "refUrls:", "mode:"):
        assert field in user_block, (
            f"Cloned user bubble missing field: {field}"
        )


def test_rerun_endpoint_allowlist():
    """Replay must refuse any endpoint outside the two generation routes."""
    html = CANVAS_HTML.read_text(encoding="utf-8")
    assert "_RERUN_ALLOWED_ENDPOINTS" in html
    assert "'/api/online-image'" in html
    assert "'/api/canvas-video'" in html

    helper_start = html.index("function rerunConversationRequest(userMsg)")
    helper_end   = html.index("// ═══════════════════════════════════════════════\n"
                              "// STATUS & TOAST", helper_start)
    helper = html[helper_start:helper_end]
    assert "_RERUN_ALLOWED_ENDPOINTS.has(endpoint)" in helper


def test_rerun_inflight_guard_uses_shared_requestlog_key():
    """All user bubbles cloned from the same requestLog must share one lock."""
    html = CANVAS_HTML.read_text(encoding="utf-8")
    assert "function _rerunKeyForMessage(m)" in html

    key_start = html.index("function _rerunKeyForMessage(m)")
    key_end = html.index("\nfunction ", key_start + 1)
    key_helper = html[key_start:key_end]
    assert "m && m.requestLog" in key_helper
    assert "log.endpoint" in key_helper
    assert "log.capturedAt" in key_helper
    assert "JSON.stringify(log.body || {})" in key_helper

    builder_start = html.index("function _buildChatRerunIcon(m)")
    builder_end = html.index("\nfunction ", builder_start + 1)
    builder = html[builder_start:builder_end]
    assert "const rerunKey = _rerunKeyForMessage(m)" in builder
    assert "_rerunInFlight.has(rerunKey)" in builder
    assert "_rerunInFlight.has(m.id)" not in builder

    helper_start = html.index("function rerunConversationRequest(userMsg)")
    helper_end   = html.index("\nfunction showToast", helper_start)
    helper = html[helper_start:helper_end]
    assert "const rerunKey = _rerunKeyForMessage(userMsg)" in helper
    assert "_rerunInFlight.has(rerunKey)" in helper
    assert "_rerunInFlight.add(rerunKey)" in helper
    assert "_rerunInFlight.delete(rerunKey)" in helper
    for id_based_lock in (
        "_rerunInFlight.has(uid)",
        "_rerunInFlight.add(uid)",
        "_rerunInFlight.delete(uid)",
        "_rerunInFlight.has(userMsg.id)",
        "_rerunInFlight.add(userMsg.id)",
        "_rerunInFlight.delete(userMsg.id)",
    ):
        assert id_based_lock not in helper, (
            "rerunConversationRequest must lock by requestLog key, "
            f"not by message id: {id_based_lock}"
        )


def test_rerun_icon_builder_and_wiring():
    html = CANVAS_HTML.read_text(encoding="utf-8")

    # Icon builder exists and reuses .chat-log-icon for styling.
    assert "function _buildChatRerunIcon(m)" in html
    assert "chat-rerun-icon" in html

    # It must be appended next to the copy + log icons in the user branch
    # of buildConversationItem.
    item_fn_start = html.index("function buildConversationItem(m)")
    user_actions_idx = html.index(
        "actions.appendChild(_buildChatLogIcon(m));", item_fn_start
    )
    after_log = html[user_actions_idx:user_actions_idx + 400]
    assert "actions.appendChild(_buildChatRerunIcon(m));" in after_log, (
        "Rerun icon must be appended right after the log icon in the user "
        "message action row."
    )

    # The icon must be disabled when there's no requestLog to replay.
    builder_start = html.index("function _buildChatRerunIcon(m)")
    builder_end   = html.index("\nfunction ", builder_start + 1)
    builder = html[builder_start:builder_end]
    assert "hasLog" in builder
    assert "btn.disabled = true" in builder


def test_insert_at_ref_does_not_blindly_replace_last_at():
    html = CANVAS_HTML.read_text(encoding="utf-8")

    fn_start = html.index("function insertAtRef(label)")
    fn_end   = html.index("\nfunction ", fn_start + 1)
    fn = html[fn_start:fn_end]

    # The old buggy line "before.slice(0, atIdx) + inserted + after" used the
    # raw lastIndexOf('@') as the replacement start unconditionally. The fix
    # must gate replacement on the absence of whitespace after that '@'.
    assert "lastIndexOf('@')" in fn
    assert "isLiveQuery" in fn
    assert "/\\s/.test(before.slice(lastAt + 1))" in fn

    # When NOT a live query, replacement start must be the cursor position
    # rather than the (now stale) '@' index.
    assert "replaceStart = isLiveQuery ? lastAt : pos" in fn

    # The composer's mention overlay must be refreshed after insertion so
    # the freshly inserted @token immediately gets the styled chip.
    assert "renderMentionLayer()" in fn


if __name__ == "__main__":
    test_rerun_helper_exists_and_uses_requestlog_verbatim()
    test_rerun_appends_user_bubble_then_pending_assistant()
    test_rerun_endpoint_allowlist()
    test_rerun_inflight_guard_uses_shared_requestlog_key()
    test_rerun_icon_builder_and_wiring()
    test_insert_at_ref_does_not_blindly_replace_last_at()
    print("OK")
