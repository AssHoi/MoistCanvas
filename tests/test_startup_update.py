"""Tests for the bounded startup updater.

These keep the network and real install tree out of the test path. The updater
is allowed to fail, but failure must be recorded and must never block launch.
"""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

startup_update = importlib.import_module("scripts.startup_update")


def test_failure_status_is_written_and_exit_code_is_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(startup_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(startup_update, "RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(startup_update, "UPDATE_STATUS_FILE", str(tmp_path / "runtime" / "update_status.json"))

    async def boom():
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(startup_update, "_run_update_check", boom)

    code = asyncio.run(startup_update.async_main())

    assert code == 0
    body = json.loads((tmp_path / "runtime" / "update_status.json").read_text(encoding="utf-8"))
    assert body["status"] == "failed"
    assert body["current"] == startup_update.APP_VERSION
    assert body["message"] == "network unavailable"


def test_no_update_clears_status_and_exits_zero(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime" / "update_status.json"
    status_file.parent.mkdir(parents=True)
    status_file.write_text('{"status":"failed"}', encoding="utf-8")
    monkeypatch.setattr(startup_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(startup_update, "RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(startup_update, "UPDATE_STATUS_FILE", str(status_file))

    async def no_update():
        return {"updated": False, "current": startup_update.APP_VERSION, "latest": startup_update.APP_VERSION}

    monkeypatch.setattr(startup_update, "_run_update_check", no_update)

    code = asyncio.run(startup_update.async_main())

    assert code == 0
    body = json.loads(status_file.read_text(encoding="utf-8"))
    assert body["status"] == "none"
    assert body["current"] == startup_update.APP_VERSION


def test_startup_zip_download_bypasses_http_caches(monkeypatch):
    captured = {}

    class _Stream:
        headers = {}
        def raise_for_status(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def aiter_bytes(self, _size):
            if False:
                yield b""

    class _Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def stream(self, method, url, headers=None):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers or {}
            return _Stream()

    monkeypatch.setattr(startup_update.httpx, "AsyncClient", _Client)

    asyncio.run(startup_update._download_zip("https://example.test/update.zip", os.devnull))

    assert captured["headers"]["Cache-Control"] == "no-cache"
    assert captured["headers"]["Pragma"] == "no-cache"


def test_startup_release_selection_uses_highest_semver_tag():
    releases = [
        {
            "tag_name": "v1.0.7",
            "name": "v1.0.7",
            "draft": False,
            "prerelease": False,
            "zipball_url": "https://example.invalid/107.zip",
        },
        {
            "tag_name": "v1.0.8",
            "name": "v1.0.8",
            "draft": False,
            "prerelease": False,
            "zipball_url": "https://example.invalid/108.zip",
        },
    ]

    selected = startup_update._select_latest_release(releases)

    assert selected["tag_name"] == "v1.0.8"


if __name__ == "__main__":
    import tempfile

    class _MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)
        def undo(self):
            for obj, name, val in reversed(self._undo):
                setattr(obj, name, val)

    def _run_with_tmp(fn):
        with tempfile.TemporaryDirectory() as d:
            mp = _MP()
            try:
                fn(Path(d), mp)
            finally:
                mp.undo()

    _run_with_tmp(test_failure_status_is_written_and_exit_code_is_zero)
    _run_with_tmp(test_no_update_clears_status_and_exits_zero)
    test_startup_zip_download_bypasses_http_caches(_MP())
    test_startup_release_selection_uses_highest_semver_tag()
    print("OK")
