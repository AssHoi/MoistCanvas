from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_bat_invokes_startup_update_before_main():
    text = (ROOT / "运行文件.bat").read_text(encoding="utf-8", errors="ignore")
    updater = text.find("scripts\\startup_update.py")
    main = text.find('"%PY_EXE%" main.py')
    assert updater != -1
    assert main != -1
    assert updater < main
    assert "Startup update failed; continuing" in text


def test_canvas_gate_fetches_and_renders_update_status_notice():
    text = (ROOT / "static" / "canvas.html").read_text(encoding="utf-8")
    assert 'id="gate-update-notice"' in text
    assert "fetch('/api/update-status'" in text
    assert "cache: 'no-store'" in text
    assert "renderStartupUpdateNotice" in text
    assert "loadStartupUpdateStatus();" in text


def test_clean_package_includes_startup_updater():
    text = (ROOT / "scripts" / "build_clean_zip.ps1").read_text(encoding="utf-8")
    assert '"scripts\\startup_update.py"' in text
    assert "Copy-CleanItem -RelativePath \"scripts\\startup_update.py\"" in text


if __name__ == "__main__":
    test_run_bat_invokes_startup_update_before_main()
    test_canvas_gate_fetches_and_renders_update_status_notice()
    test_clean_package_includes_startup_updater()
    print("OK")
