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
STARTUP_RELEASES_PER_PAGE = 20


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _github_headers(user_agent="MoistCanvas-Startup-Updater"):
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_version_tuple(tag):
    parsed = main._parse_version(tag)
    if not parsed:
        return ()
    return parsed + (0,) * (4 - len(parsed))


def _select_latest_release(releases):
    candidates = [
        rel for rel in releases
        if isinstance(rel, dict)
        and not rel.get("draft")
        and not rel.get("prerelease")
        and _parse_version_tuple(rel.get("tag_name") or "")
    ]
    if not candidates:
        raise RuntimeError("No published versioned GitHub releases were found.")
    return max(candidates, key=lambda rel: _parse_version_tuple(rel.get("tag_name") or ""))


async def _github_release_candidates():
    if not main._update_configured():
        raise main.HTTPException(
            status_code=400,
            detail="尚未配置 GitHub 仓库（请设置 GITHUB_REPO 或 MOISTCANVAS_REPO 环境变量）。",
        )
    repo = (main.GITHUB_REPO or "").strip().strip("/")
    api_base = getattr(main, "GITHUB_API_BASE", "https://api.github.com")
    url = f"{api_base}/repos/{repo}/releases"
    params = {"per_page": str(STARTUP_RELEASES_PER_PAGE), "_": str(int(time.time()))}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=_github_headers())
    except Exception as exc:
        raise main.HTTPException(status_code=502, detail=f"无法连接 GitHub：{exc}")
    if resp.status_code == 404:
        raise main.HTTPException(status_code=404, detail="该仓库还没有发布任何 Release。")
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise main.HTTPException(status_code=429, detail="GitHub API 速率限制，请稍后再试（或配置 GITHUB_TOKEN）。")
    if resp.status_code != 200:
        raise main.HTTPException(status_code=502, detail=f"GitHub 返回 HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, list):
        raise main.HTTPException(status_code=502, detail="GitHub releases 响应格式异常。")
    return data


async def _github_latest_release_fresh():
    try:
        return _select_latest_release(await _github_release_candidates())
    except Exception:
        # Fallback keeps launch resilient if the releases-list endpoint has a
        # transient problem. async_main records a failure only if both paths fail.
        return await main._github_latest_release()


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
    timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", zip_url, headers=_github_headers()) as resp:
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

    release = await _github_latest_release_fresh()
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
