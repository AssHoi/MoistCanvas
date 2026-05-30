"""Tests for the in-app GitHub auto-update feature in main.py.

Covers:
- Version comparison (_is_newer) across normal/edge cases.
- _skip_path_for_update protects every user-data path and keeps every code path.
- _overlay_code_files actually preserves user data when run against a synthetic
  install dir (monkeypatched BASE_DIR — never touches the real install).
- The HTTP endpoints exist and behave sanely with the default (unconfigured) repo.
"""

import os
import sys
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


def test_app_port_is_6767():
    assert main.APP_PORT == 6767


def test_is_newer():
    cases = [
        ("v1.1.0", "1.0.0", True),
        ("v1.0.0", "1.0.0", False),
        ("1.0.0", "1.0.1", False),
        ("v1.2", "1.2.0", False),       # padded equal
        ("v2.0.0", "1.9.9", True),
        ("v1.0.10", "1.0.9", True),     # numeric, not lexical
        ("1.0.0-beta", "1.0.0", False), # suffix dropped
        ("garbage", "1.0.0", False),    # unparseable → not newer
        ("", "1.0.0", False),
    ]
    for latest, cur, exp in cases:
        assert main._is_newer(latest, cur) is exp, (latest, cur, exp)


def test_skip_path_protects_user_data_and_keeps_code():
    protected = [
        "API/.env", "API\\.env",
        "output/x.png", "output/sub/y.mp4",
        "runtime/python/python.exe",
        "data/canvases_v2/abc.json",
        "data/model_catalog_cache.json",
        "data/api_providers.json",          # user-owned at runtime
        "history.json",
        "server.err.log", "server.out.log",
        ".git/config",
        "static/__pycache__/x.pyc",
        "dist/MoistCanvas.zip",
    ]
    for p in protected:
        assert main._skip_path_for_update(p) is True, f"should skip {p}"

    code = [
        "main.py",
        "static/canvas.html", "static/index.html", "static/api-settings.html",
        "static/i18n.js", "static/theme.js",
        "requirements.txt", "README.md", "README-FIRST.txt",
        "scripts/build_clean_zip.ps1",
        "data",  # bare top dir name still skipped (it's protected) — guarded below
    ]
    # main.py and static/* must be writable; data (dir) is protected.
    for p in code[:-1]:
        assert main._skip_path_for_update(p) is False, f"should keep {p}"
    assert main._skip_path_for_update("data") is True


def test_overlay_preserves_user_data(tmp_path, monkeypatch):
    # Synthetic "downloaded release" tree.
    src = tmp_path / "src"
    (src / "static").mkdir(parents=True)
    (src / "API").mkdir()
    (src / "output").mkdir()
    (src / "data" / "canvases_v2").mkdir(parents=True)
    (src / "main.py").write_text("NEW_MAIN\n", encoding="utf-8")
    (src / "static" / "canvas.html").write_text("NEW_CANVAS\n", encoding="utf-8")
    (src / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    # Hostile extras that must NOT clobber user data even if present in archive:
    (src / "API" / ".env").write_text("COMFLY_API_KEY=ATTACKER\n", encoding="utf-8")
    (src / "output" / "evil.png").write_text("evil", encoding="utf-8")
    (src / "data" / "canvases_v2" / "seed.json").write_text("{}", encoding="utf-8")

    # Synthetic install dir with existing user data + old code.
    install = tmp_path / "install"
    (install / "static").mkdir(parents=True)
    (install / "API").mkdir()
    (install / "output").mkdir()
    (install / "data" / "canvases_v2").mkdir(parents=True)
    (install / "main.py").write_text("OLD_MAIN\n", encoding="utf-8")
    (install / "static" / "canvas.html").write_text("OLD_CANVAS\n", encoding="utf-8")
    (install / "API" / ".env").write_text("COMFLY_API_KEY=USER_SECRET\n", encoding="utf-8")
    (install / "output" / "keep.png").write_text("user-image", encoding="utf-8")
    (install / "data" / "canvases_v2" / "mycanvas.json").write_text('{"mine":1}', encoding="utf-8")

    monkeypatch.setattr(main, "BASE_DIR", str(install))
    monkeypatch.setattr(main, "UPDATE_DIR", str(tmp_path / "upd"))  # backups → tmp
    written = main._overlay_code_files(str(src))

    # Code files updated.
    assert (install / "main.py").read_text(encoding="utf-8") == "NEW_MAIN\n"
    assert (install / "static" / "canvas.html").read_text(encoding="utf-8") == "NEW_CANVAS\n"
    assert (install / "requirements.txt").read_text(encoding="utf-8") == "fastapi\n"

    # User secrets / data PRESERVED — never overwritten by the archive copies.
    assert (install / "API" / ".env").read_text(encoding="utf-8") == "COMFLY_API_KEY=USER_SECRET\n"
    assert (install / "output" / "keep.png").read_text(encoding="utf-8") == "user-image"
    assert (install / "data" / "canvases_v2" / "mycanvas.json").read_text(encoding="utf-8") == '{"mine":1}'

    # The archive's user-data files were NOT created in the install.
    assert not (install / "output" / "evil.png").exists()
    assert not (install / "data" / "canvases_v2" / "seed.json").exists()

    # written list contains only code-relative paths.
    assert "main.py" in written
    assert any(w.replace("\\", "/") == "static/canvas.html" for w in written)
    assert all("API/" not in w.replace("\\", "/") and not w.replace("\\", "/").startswith("output/") for w in written)


def test_endpoints_present_and_safe_default():
    from fastapi.testclient import TestClient
    # Loopback peer + Host so a no-Origin local client (curl on the same machine)
    # passes the locality/CSRF guard.
    client = TestClient(main.app, base_url="http://127.0.0.1:6767", client=("127.0.0.1", 5555))

    # app-version always works and reports the configured repository.
    r = client.get("/api/app-version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == main.APP_VERSION
    assert body["repo"] == main.GITHUB_REPO

    old_repo = main.GITHUB_REPO
    main.GITHUB_REPO = "your-github-username/MoistCanvas"
    try:
        # check-update on an unconfigured repo must fail clearly (not 500-crash).
        r = client.get("/api/check-update")
        assert r.status_code == 400
        assert "GITHUB_REPO" in r.json()["detail"] or "仓库" in r.json()["detail"]

        # apply-update from a local (loopback) no-Origin client passes the CSRF
        # guard, then is rejected cleanly because the repo is unconfigured.
        r = client.post("/api/apply-update")
        assert r.status_code == 400
    finally:
        main.GITHUB_REPO = old_repo


def test_update_status_endpoint_defaults_without_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "UPDATE_STATUS_FILE", str(tmp_path / "missing.json"))
    client = TestClient(main.app, base_url="http://127.0.0.1:6767", client=("127.0.0.1", 5555))

    r = client.get("/api/update-status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "none",
        "current": main.APP_VERSION,
        "latest": "",
        "tag": "",
        "message": "",
        "html_url": "",
        "time": "",
    }


def test_update_status_endpoint_sanitizes_status_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import json as _json

    status_file = tmp_path / "update_status.json"
    status_file.write_text(_json.dumps({
        "status": "failed",
        "current": "1.0.1",
        "latest": "1.0.2",
        "tag": "v1.0.2",
        "message": "boom",
        "html_url": "https://github.com/AssHoi/MoistCanvas/releases/tag/v1.0.2",
        "time": "2026-05-30T00:00:00Z",
        "secret": "do-not-return",
    }), encoding="utf-8")
    monkeypatch.setattr(main, "UPDATE_STATUS_FILE", str(status_file))
    client = TestClient(main.app, base_url="http://127.0.0.1:6767", client=("127.0.0.1", 5555))

    r = client.get("/api/update-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["current"] == "1.0.1"
    assert body["latest"] == "1.0.2"
    assert body["tag"] == "v1.0.2"
    assert body["message"] == "boom"
    assert body["html_url"].startswith("https://github.com/AssHoi/MoistCanvas/releases/")
    assert body["time"] == "2026-05-30T00:00:00Z"
    assert "secret" not in body


# ── Review fix #2: locality (peer IP) + CSRF guard ───────────────────────────
class _Client:
    def __init__(self, host): self.host = host


class _FakeReq:
    def __init__(self, headers, peer="127.0.0.1"):
        self.headers = headers
        self.client = _Client(peer)


def _expect_403(req):
    try:
        main._assert_same_origin(req)
    except main.HTTPException as e:
        assert e.status_code == 403
        return
    raise AssertionError("expected 403")


def test_is_loopback_ip():
    assert main._is_loopback_ip("127.0.0.1") is True
    assert main._is_loopback_ip("127.5.6.7") is True
    assert main._is_loopback_ip("::1") is True
    assert main._is_loopback_ip("[::1]") is True
    assert main._is_loopback_ip("192.168.1.5") is False
    assert main._is_loopback_ip("10.0.0.1") is False
    assert main._is_loopback_ip("") is False
    assert main._is_loopback_ip("garbage") is False


def test_assert_same_origin():
    # (A) Local browser, malicious page: peer is loopback but Origin=evil → 403.
    _expect_403(_FakeReq({"host": "127.0.0.1:6767", "origin": "http://evil.com"}, peer="127.0.0.1"))

    # (B) Local browser, same-origin → passes.
    main._assert_same_origin(_FakeReq({"host": "127.0.0.1:6767", "origin": "http://127.0.0.1:6767"}, peer="127.0.0.1"))
    main._assert_same_origin(_FakeReq({"host": "localhost:6767", "origin": "http://localhost:6767"}, peer="::1"))
    # Referer fallback when Origin missing.
    main._assert_same_origin(_FakeReq({"host": "127.0.0.1:6767", "referer": "http://127.0.0.1:6767/static/api-settings.html"}, peer="127.0.0.1"))
    # Local non-browser client (curl on this machine, no Origin) → passes.
    main._assert_same_origin(_FakeReq({"host": "127.0.0.1:6767"}, peer="127.0.0.1"))

    # (C) The KEY fix: a LAN machine cannot bypass by spoofing the Host header —
    # the real peer IP is what's checked. Even with a perfectly forged
    # Host+Origin pair, a non-loopback peer is rejected.
    _expect_403(_FakeReq({"host": "localhost:6767", "origin": "http://localhost:6767"}, peer="192.168.1.50"))
    _expect_403(_FakeReq({"host": "localhost:6767"}, peer="192.168.1.50"))
    # (D) LAN browser to the server's LAN IP → also rejected (intentional: these
    # endpoints are strictly local).
    _expect_403(_FakeReq({"host": "192.168.1.5:6767", "origin": "http://192.168.1.5:6767"}, peer="192.168.1.9"))


def test_apply_update_rejects_cross_site_origin():
    from fastapi.testclient import TestClient
    # Local browser peer, but evil cross-site Origin → 403 at the guard, before
    # any GitHub/download work.
    local = TestClient(main.app, base_url="http://127.0.0.1:6767", client=("127.0.0.1", 5555))
    r = local.post("/api/apply-update", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    r = local.post("/api/restart-app", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    # Matching origin from loopback passes the guard (then 400, repo unconfigured).
    old_repo = main.GITHUB_REPO
    main.GITHUB_REPO = "your-github-username/MoistCanvas"
    try:
        r = local.post("/api/apply-update", headers={"Origin": "http://127.0.0.1:6767"})
        assert r.status_code == 400
    finally:
        main.GITHUB_REPO = old_repo

    # Non-loopback peer (LAN/remote) is rejected outright, regardless of headers.
    remote = TestClient(main.app, base_url="http://127.0.0.1:6767", client=("192.168.1.50", 5555))
    r = remote.post("/api/apply-update", headers={"Origin": "http://127.0.0.1:6767"})
    assert r.status_code == 403
    r = remote.post("/api/restart-app")
    assert r.status_code == 403


# ── Review fix #3: safe extraction (zip-slip + caps) ─────────────────────────
def test_safe_extract_rejects_zip_slip(tmp_path):
    import zipfile as _zip
    bad = tmp_path / "bad.zip"
    with _zip.ZipFile(bad, "w") as zf:
        zf.writestr("ok.txt", "fine")
        zf.writestr("../escape.txt", "evil")  # path traversal
    dest = tmp_path / "out"
    dest.mkdir()
    try:
        main._safe_extract_zip(str(bad), str(dest))
        assert False, "zip-slip entry should have been rejected"
    except main.HTTPException as e:
        assert e.status_code == 502
    # Nothing escaped the destination.
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_normal_ok(tmp_path):
    import zipfile as _zip
    good = tmp_path / "good.zip"
    with _zip.ZipFile(good, "w") as zf:
        zf.writestr("pkg/main.py", "print(1)")
        zf.writestr("pkg/static/x.html", "<html></html>")
    dest = tmp_path / "out"
    dest.mkdir()
    main._safe_extract_zip(str(good), str(dest))
    assert (dest / "pkg" / "main.py").read_text() == "print(1)"
    assert (dest / "pkg" / "static" / "x.html").exists()


# ── Review fix #1: deps-first, abort-on-failure (no "new code + old deps") ────
def _make_release_tree(tmp_path, req_text):
    src = tmp_path / "src"
    (src / "static").mkdir(parents=True)
    (src / "main.py").write_text("NEW_MAIN\n", encoding="utf-8")
    (src / "static" / "canvas.html").write_text("NEW_CANVAS\n", encoding="utf-8")
    (src / "requirements.txt").write_text(req_text, encoding="utf-8")
    return src


def _make_install(tmp_path, req_text):
    inst = tmp_path / "install"
    (inst / "static").mkdir(parents=True)
    (inst / "main.py").write_text("OLD_MAIN\n", encoding="utf-8")
    (inst / "static" / "canvas.html").write_text("OLD_CANVAS\n", encoding="utf-8")
    (inst / "requirements.txt").write_text(req_text, encoding="utf-8")
    return inst


def test_deps_failure_aborts_without_touching_code(tmp_path, monkeypatch):
    # New requirements differ → pip will run; force it to FAIL.
    src = _make_release_tree(tmp_path, "fastapi\nnew-dep\n")
    inst = _make_install(tmp_path, "fastapi\n")
    monkeypatch.setattr(main, "BASE_DIR", str(inst))
    monkeypatch.setattr(main, "_pip_install_requirements", lambda p: (False, "boom: no network"))

    raised = False
    try:
        main._install_deps_then_overlay(str(src))
    except main.HTTPException as e:
        raised = True
        assert e.status_code == 502
        assert "依赖安装失败" in e.detail
    assert raised, "deps failure must raise"
    # CRITICAL: code was NOT swapped — old main.py is intact.
    assert (inst / "main.py").read_text(encoding="utf-8") == "OLD_MAIN\n"
    assert (inst / "static" / "canvas.html").read_text(encoding="utf-8") == "OLD_CANVAS\n"


def test_deps_success_then_code_overlaid(tmp_path, monkeypatch):
    src = _make_release_tree(tmp_path, "fastapi\nnew-dep\n")
    inst = _make_install(tmp_path, "fastapi\n")
    monkeypatch.setattr(main, "BASE_DIR", str(inst))
    monkeypatch.setattr(main, "UPDATE_DIR", str(tmp_path / "upd"))
    calls = {"pip": 0}
    def _ok(p):
        calls["pip"] += 1
        return True, ""
    monkeypatch.setattr(main, "_pip_install_requirements", _ok)
    written, reqs_changed, deps_done = main._install_deps_then_overlay(str(src))
    assert reqs_changed is True and deps_done is True and calls["pip"] == 1
    # Code swapped only after deps succeeded.
    assert (inst / "main.py").read_text(encoding="utf-8") == "NEW_MAIN\n"
    assert "main.py" in written


def test_no_dep_change_skips_pip(tmp_path, monkeypatch):
    # Identical requirements → pip must NOT run, code still overlaid.
    src = _make_release_tree(tmp_path, "fastapi\n")
    inst = _make_install(tmp_path, "fastapi\n")
    monkeypatch.setattr(main, "BASE_DIR", str(inst))
    monkeypatch.setattr(main, "UPDATE_DIR", str(tmp_path / "upd"))
    def _boom(p):
        raise AssertionError("pip should not run when requirements are unchanged")
    monkeypatch.setattr(main, "_pip_install_requirements", _boom)
    written, reqs_changed, deps_done = main._install_deps_then_overlay(str(src))
    assert reqs_changed is False and deps_done is False
    assert (inst / "main.py").read_text(encoding="utf-8") == "NEW_MAIN\n"


# ── Review fix (P2): atomic overlay with backup + rollback ───────────────────
def test_overlay_rolls_back_on_write_failure(tmp_path, monkeypatch):
    # Release tree: an existing file (main.py) plus a NEW file (static/BOOM.html)
    # whose copy will fail mid-overlay.
    src = tmp_path / "src"
    (src / "static").mkdir(parents=True)
    (src / "main.py").write_text("NEW_MAIN\n", encoding="utf-8")
    (src / "static" / "BOOM.html").write_text("NEW_BOOM\n", encoding="utf-8")

    inst = tmp_path / "install"
    (inst / "static").mkdir(parents=True)
    (inst / "main.py").write_text("OLD_MAIN\n", encoding="utf-8")  # exists → backed up

    monkeypatch.setattr(main, "BASE_DIR", str(inst))
    monkeypatch.setattr(main, "UPDATE_DIR", str(tmp_path / "upd"))

    # Make the copy of BOOM.html fail (simulates disk-full / locked file), while
    # all other copies (incl. backup + rollback restores) work normally.
    real_copy2 = main.shutil.copy2
    def flaky_copy2(s, d, *a, **k):
        if os.path.basename(str(s)) == "BOOM.html":
            raise OSError("simulated disk full")
        return real_copy2(s, d, *a, **k)
    monkeypatch.setattr(main.shutil, "copy2", flaky_copy2)

    raised = False
    try:
        main._overlay_code_files(str(src))
    except main.HTTPException as e:
        raised = True
        assert e.status_code == 500
        assert "回滚" in e.detail
    assert raised, "a mid-overlay write failure must raise"

    # Rolled back: the pre-existing file is restored to its OLD content...
    assert (inst / "main.py").read_text(encoding="utf-8") == "OLD_MAIN\n"
    # ...and the partially-written NEW file is gone (not left half-applied).
    assert not (inst / "static" / "BOOM.html").exists()


def test_overlay_destination_never_corrupted_on_midwrite_failure(tmp_path, monkeypatch):
    """The P1 path: a write that fails AFTER the destination would normally be
    truncated. With temp-file + os.replace, the real file is never touched until
    a complete copy succeeds, so the old file survives intact."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("NEW_MAIN\n", encoding="utf-8")
    inst = tmp_path / "install"
    inst.mkdir()
    (inst / "main.py").write_text("OLD_MAIN_INTACT\n", encoding="utf-8")
    monkeypatch.setattr(main, "BASE_DIR", str(inst))
    monkeypatch.setattr(main, "UPDATE_DIR", str(tmp_path / "upd"))

    real_copy2 = main.shutil.copy2
    def flaky_copy2(s, d, *a, **k):
        # Fail while writing the STAGING temp file, after leaving partial bytes
        # in it — models a disk-full mid-write. Backup copies (dst not .tmp)
        # still succeed.
        if str(d).endswith(".tmp"):
            with open(d, "wb") as f:
                f.write(b"PARTIAL-GARBAGE")
            raise OSError("simulated disk full mid-write")
        return real_copy2(s, d, *a, **k)
    monkeypatch.setattr(main.shutil, "copy2", flaky_copy2)

    raised = False
    try:
        main._overlay_code_files(str(src))
    except main.HTTPException as e:
        raised = True
        assert e.status_code == 500
    assert raised, "mid-write failure must raise"

    # CRITICAL: the real destination is the intact OLD file — never truncated,
    # never filled with the partial garbage that went to the temp.
    assert (inst / "main.py").read_text(encoding="utf-8") == "OLD_MAIN_INTACT\n"
    # No staging temp left behind in the install dir.
    leftovers = [p.name for p in inst.iterdir() if ".upd_" in p.name or p.name.endswith(".tmp")]
    assert leftovers == [], f"temp residue left behind: {leftovers}"


if __name__ == "__main__":
    # Minimal pytest-free runner: provides tmp_path + monkeypatch shims so the
    # file is runnable directly (the maintainer reported no pytest installed).
    import tempfile

    class _MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)
        def undo(self):
            for obj, name, val in reversed(self._undo):
                setattr(obj, name, val)

    def _run_with_tmp(fn, needs_mp=False):
        with tempfile.TemporaryDirectory() as d:
            if needs_mp:
                mp = _MP()
                try: fn(Path(d), mp)
                finally: mp.undo()
            else:
                fn(Path(d))

    test_app_port_is_6767()
    test_is_newer()
    test_skip_path_protects_user_data_and_keeps_code()
    _run_with_tmp(test_overlay_preserves_user_data, needs_mp=True)
    test_endpoints_present_and_safe_default()
    _run_with_tmp(test_update_status_endpoint_defaults_without_file, needs_mp=True)
    _run_with_tmp(test_update_status_endpoint_sanitizes_status_file, needs_mp=True)
    test_is_loopback_ip()
    test_assert_same_origin()
    test_apply_update_rejects_cross_site_origin()
    _run_with_tmp(test_safe_extract_rejects_zip_slip)
    _run_with_tmp(test_safe_extract_normal_ok)
    _run_with_tmp(test_deps_failure_aborts_without_touching_code, needs_mp=True)
    _run_with_tmp(test_deps_success_then_code_overlaid, needs_mp=True)
    _run_with_tmp(test_no_dep_change_skips_pip, needs_mp=True)
    _run_with_tmp(test_overlay_rolls_back_on_write_failure, needs_mp=True)
    _run_with_tmp(test_overlay_destination_never_corrupted_on_midwrite_failure, needs_mp=True)
    print("OK")

