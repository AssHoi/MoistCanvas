"""Tests for the bounded startup updater.

These keep the network and real install tree out of the test path. The updater
is allowed to fail, but failure must be recorded and must never block launch.
"""

import asyncio
import importlib
import json
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
    print("OK")
