from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TEXT_FILES_TO_CHECK = [
    ROOT / "main.py",
    ROOT / "static" / "canvas.html",
    ROOT / "static" / "api-settings.html",
    ROOT / "static" / "i18n.js",
    ROOT / "tests" / "test_update_feature.py",
    ROOT / "tests" / "test_canvas_composer_mention_style_static.py",
    ROOT / "tests" / "test_canvas_text_selection_static.py",
]

MOJIBAKE_MARKERS = [
    "\u6d93\u5a43\u7236",  # mojibake for upstream
    "\u93c8",  # common mojibake prefix
    "\u53a4\u7f03",  # common mojibake fragment
    "\u7459\u55db",  # mojibake for video/view
    "\u9225?",  # mojibake curly quote
    "\ufffd",
]

AMBIGUOUS_CONSOLE_PUNCTUATION = [
    "\u2014",
    "\u2192",
    "\u2500",
]


def test_core_source_files_do_not_contain_known_mojibake_markers():
    failures = []
    for path in TEXT_FILES_TO_CHECK:
        text = path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                failures.append(f"{path.relative_to(ROOT)} contains {marker!r}")

    assert not failures, "\n".join(failures)


def test_update_feature_comments_avoid_console_ambiguous_unicode():
    text = (ROOT / "tests" / "test_update_feature.py").read_text(encoding="utf-8")

    for marker in AMBIGUOUS_CONSOLE_PUNCTUATION:
        assert marker not in text


if __name__ == "__main__":
    test_core_source_files_do_not_contain_known_mojibake_markers()
    test_update_feature_comments_avoid_console_ambiguous_unicode()
    print("OK")
