from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def test_composer_uses_contenteditable_chips_with_hidden_canonical_textarea():
    html = _html()

    assert 'id="prompt-editor"' in html
    assert 'contenteditable="true"' in html
    assert 'textarea id="prompt-input"' in html
    assert 'class="prompt-hidden-canonical"' in html

    assert ".composer-mid .prompt-editor {" in html
    assert ".composer-mid textarea#prompt-input.prompt-hidden-canonical {" in html
def test_reference_chip_style_has_thumbnail_and_neutral_label():
    html = _html()

    chip_start = html.index(".prompt-ref-chip {")
    chip_end = html.index(".prompt-ref-chip .prc-thumb", chip_start)
    chip_css = html[chip_start:chip_end]

    assert "display: inline-flex;" in chip_css
    assert "font-size: 13px;" in chip_css
    assert "color: var(--muted);" in chip_css
    assert "#dc2626" not in chip_css
    assert "#f87171" not in chip_css

    thumb_start = html.index(".prompt-ref-chip .prc-thumb {")
    thumb_end = html.index(".prompt-ref-chip .prc-thumb img", thumb_start)
    thumb_css = html[thumb_start:thumb_end]
    assert "width: 22px;" in thumb_css
    assert "height: 22px;" in thumb_css

    label_start = html.index(".prompt-ref-chip .prc-label {")
    label_end = html.index(".prompt-ref-chip.is-missing", label_start)
    label_css = html[label_start:label_end]
    assert "font-size: 12px;" in label_css
    assert "color: var(--muted);" in label_css

    assert "body.theme-dark .composer-mid .prompt-ref-chip" in html
    assert "body.theme-dark .pop-mention-item .pmi-tag { color: var(--muted); }" in html
    pmi_start = html.index(".pop-mention-item .pmi-tag {")
    pmi_end = html.index(".pop-mention-item .pmi-name", pmi_start)
    pmi_css = html[pmi_start:pmi_end]
    assert "color: var(--muted);" in pmi_css
    assert "#dc2626" not in pmi_css


def test_manual_at_anchors_mention_popover_to_composer_not_icon():
    html = _html()

    assert "function showAtMenu(query, source)" in html
    assert "openPop('mention', _mentionComposerAnchor())" in html
    assert "function _mentionComposerAnchor()" in html
    assert "function togglePop(name, anchorEl)" in html
    assert "openPop(name, anchorEl)" in html
    assert "togglePop('mention', this)" in html


def test_insert_ref_creates_chip_and_keeps_canonical_prompt_value():
    html = _html()

    assert "function insertAtRef(label)" in html
    fn_start = html.index("function insertAtRef(label)")
    fn_end = html.index("\nfunction ", fn_start + 1)
    fn = html[fn_start:fn_end]

    assert "_insertRefChipAtSelection(label)" in fn
    assert "_syncPromptFromEditor()" in fn
    assert "promptInput.value" in html[html.index("function _insertRefChipAtSelection(label)"):html.index("\nfunction ", html.index("function _insertRefChipAtSelection(label)") + 1)]

    assert "function _syncPromptFromEditor()" in html
    sync_start = html.index("function _syncPromptFromEditor()")
    sync_end = html.index("\nfunction ", sync_start + 1)
    sync_fn = html[sync_start:sync_end]
    assert "dataset.label" in sync_fn
    assert "'@' + label" in sync_fn
    assert "promptInput.value = text" in sync_fn

    assert "function _createPromptRefChip(label)" in html
    create_start = html.index("function _createPromptRefChip(label)")
    create_end = html.index("\nfunction ", create_start + 1)
    create_fn = html[create_start:create_end]
    assert "prompt-ref-chip" in create_fn
    assert "_appendPromptChipThumb(chip, ref)" in create_fn
    assert "prc-thumb" in html
    assert "prc-label" in create_fn


def test_contenteditable_sync_preserves_block_newlines():
    html = _html()

    sync_start = html.index("function _syncPromptFromEditor()")
    sync_end = html.index("\nfunction ", sync_start + 1)
    sync_fn = html[sync_start:sync_end]

    assert "function isBlockNode(node)" in sync_fn
    assert "appendNewlineIfNeeded()" in sync_fn
    assert "text = text.replace(/\\n+$/, '')" in sync_fn


def test_generation_syncs_visual_editor_before_ref_resolution():
    html = _html()

    gen_start = html.index("function handleGenerate()")
    gen_end = html.index("\nfunction ", gen_start + 1)
    gen_fn = html[gen_start:gen_end]

    assert "_syncPromptFromEditor();" in gen_fn
    assert gen_fn.index("_syncPromptFromEditor();") < gen_fn.index("const prompt = promptInput.value.trim();")
    assert "getRefsUsedByPrompt(prompt, refs)" in gen_fn


def test_reference_menu_only_stays_open_for_bare_at():
    html = _html()

    input_start = html.index("function handlePromptInput()")
    input_end = html.index("\nfunction ", input_start + 1)
    input_fn = html[input_start:input_end]

    assert "isBareAtBeforeCaret" in input_fn
    assert "atIdx === pos - 1" in input_fn
    assert "showAtMenu('', 'composer')" in input_fn
    assert "before.slice(atIdx + 1).toLowerCase()" not in input_fn


def test_old_textarea_overlay_path_removed():
    html = _html()

    assert "mention-layer" not in html
    assert "mention-tok" not in html
    assert "_legacyInsertAtRefCommentAnchor" not in html
    assert "promptInput.selectionStart" not in html


if __name__ == "__main__":
    test_composer_uses_contenteditable_chips_with_hidden_canonical_textarea()
    test_reference_chip_style_has_thumbnail_and_neutral_label()
    test_manual_at_anchors_mention_popover_to_composer_not_icon()
    test_insert_ref_creates_chip_and_keeps_canonical_prompt_value()
    test_contenteditable_sync_preserves_block_newlines()
    test_generation_syncs_visual_editor_before_ref_resolution()
    test_reference_menu_only_stays_open_for_bare_at()
    test_old_textarea_overlay_path_removed()
    print("OK")
