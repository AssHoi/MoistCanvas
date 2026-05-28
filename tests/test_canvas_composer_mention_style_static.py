from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def test_composer_mention_text_is_rendered_by_overlay():
    html = _html()

    assert ".composer-mid .mention-layer {" in html
    assert "padding: 8px clamp(8px, 2.5vw, 12px);" in html
    assert "color: var(--text);" in html

    textarea_start = html.index(".composer-mid textarea#prompt-input {")
    textarea_end = html.index(".composer-mid textarea#prompt-input:focus", textarea_start)
    textarea_css = html[textarea_start:textarea_end]

    assert "padding: 8px clamp(8px, 2.5vw, 12px);" in textarea_css
    assert "font-size: 15px;" in textarea_css
    assert "color: transparent;" in textarea_css
    assert "caret-color: var(--text);" in textarea_css


def test_composer_mentions_are_red_and_roomier():
    html = _html()

    composer_start = html.index("#composer {")
    composer_end = html.index("#composer:focus-within", composer_start)
    composer_css = html[composer_start:composer_end]
    assert "padding: 16px clamp(16px, 4vw, 20px) 12px;" in composer_css

    mention_start = html.index(".composer-mid .mention-layer .mention-tok {")
    mention_end = html.index(".composer-mid .mention-layer .mention-tok.tok-marker", mention_start)
    mention_css = html[mention_start:mention_end]

    assert "color: #dc2626;" in mention_css
    assert "background: rgba(220, 38, 38, 0.08);" in mention_css
    assert "box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.26) inset;" in mention_css

    pmi_start = html.index(".pop-mention-item .pmi-tag {")
    pmi_end = html.index(".pop-mention-item .pmi-name", pmi_start)
    pmi_css = html[pmi_start:pmi_end]

    assert "color: #dc2626;" in pmi_css
    assert "font-size: 12px;" in pmi_css


if __name__ == "__main__":
    test_composer_mention_text_is_rendered_by_overlay()
    test_composer_mentions_are_red_and_roomier()
    print("OK")
