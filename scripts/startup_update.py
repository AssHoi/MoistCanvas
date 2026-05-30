"""Bounded startup updater for MoistCanvas.

Run before main.py starts. It may update the install, but it must never prevent
the app from launching: all outcomes exit 0 and failures are recorded for the UI.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import httpx  # noqa: E402
import main  # noqa: E402

APP_VERSION = main.APP_VERSION
BASE_DIR = main.BASE_DIR
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
UPDATE_DIR = os.path.join(RUNTIME_DIR, "_startup_update")
UPDATE_STATUS_FILE = os.path.join(RUNTIME_DIR, "update_status.json")
_LAST_RELEASE_INFO = {}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_payload(status, **values):
    payload = {
        "status": status,
        "current": APP_VERSION,
        "latest": "",
        "tag": "",
        "message": "",
        "html_url": "",
        "time": _now_iso(),
    }
    payload.update({k: ("" if v is None else str(v)) for k, v in values.items()})
    return main._public_update_status(payload)


def _write_status(status, **values):
    os.makedirs(os.path.dirname(UPDATE_STATUS_FILE), exist_ok=True)
    payload = _status_payload(status, **values)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(UPDATE_STATUS_FILE),
        prefix=".update_status_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, UPDATE_STATUS_FILE)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return payload


def _sync_main_paths():
    main.BASE_DIR = BASE_DIR
    main.UPDATE_DIR = UPDATE_DIR
    main.UPDATE_STATUS_FILE = UPDATE_STATUS_FILE


def _http_error_message(exc):
    detail = getattr(exc, "detail", None)
    if detail:
        return str(detail)
    return str(exc)


async def _download_zip(zip_url, zip_path):
    headers = {
        "User-Agent": "MoistCanvas-Startup-Updater",
        "Accept": "application/vnd.github+json",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", zip_url, headers=headers) as resp:
            resp.raise_for_status()
            clen = resp.headers.get("content-length")
            if clen and int(clen) > main.MAX_UPDATE_DOWNLOAD_BYTES:
                raise RuntimeError("Update package is too large.")
            downloaded = 0
            with open(zip_path, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    downloaded += len(chunk)
                    if downloaded > main.MAX_UPDATE_DOWNLOAD_BYTES:
                        raise RuntimeError("Update package is too large.")
                    f.write(chunk)


async def _run_update_check():
    global _LAST_RELEASE_INFO
    _sync_main_paths()

    release = await main._github_latest_release()
    info = main._release_summary(release)
    _LAST_RELEASE_INFO = info

    if not main._is_newer(info["tag"], APP_VERSION):
        return _write_status(
            "none",
            current=APP_VERSION,
            latest=info.get("version", ""),
            tag=info.get("tag", ""),
            html_url=info.get("html_url", ""),
        )

    zip_url = info.get("zipball_url") or ""
    if not zip_url:
        raise RuntimeError("Release is missing a source download URL.")

    if os.path.exists(UPDATE_DIR):
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    os.makedirs(UPDATE_DIR, exist_ok=True)
    zip_path = os.path.join(UPDATE_DIR, "update.zip")
    extract_dir = os.path.join(UPDATE_DIR, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        await _download_zip(zip_url, zip_path)
        main._safe_extract_zip(zip_path, extract_dir)
        src_root = main._find_extracted_root(extract_dir)
        written, reqs_changed, deps_done = main._install_deps_then_overlay(src_root)
    finally:
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)

    return _write_status(
        "success",
        current=APP_VERSION,
        latest=info.get("version", ""),
        tag=info.get("tag", ""),
        html_url=info.get("html_url", ""),
        message=f"Updated {len(written)} files. deps_changed={bool(reqs_changed)} deps_reinstalled={bool(deps_done)}",
    )


async def async_main():
    try:
        result = await _run_update_check()
        if isinstance(result, dict) and "status" not in result and result.get("updated") is False:
            result = _write_status(
                "none",
                current=result.get("current", APP_VERSION),
                latest=result.get("latest", ""),
                tag=result.get("tag", ""),
                html_url=result.get("html_url", ""),
            )
        if result.get("status") == "success":
            print(f"[update] Updated MoistCanvas to {result.get('latest') or result.get('tag')}.")
        return 0
    except Exception as exc:
        info = _LAST_RELEASE_INFO or {}
        message = _http_error_message(exc)
        _write_status(
            "failed",
            current=APP_VERSION,
            latest=info.get("version", ""),
            tag=info.get("tag", ""),
            message=message,
            html_url=info.get("html_url", ""),
        )
        print(f"[update warning] Startup update skipped: {message}")
        return 0


def main_cli():
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main_cli())
