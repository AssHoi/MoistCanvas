import json
import uuid
import base64
import urllib.request
import urllib.parse
import urllib.error
import os
import re
import random
import time
import shutil
import asyncio
import subprocess
import sys
import zipfile
import tempfile
import ipaddress
import requests
from typing import List, Dict, Any, Optional
from threading import Lock
import httpx
from PIL import Image
from io import BytesIO
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket 状态管理器 ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if client_id:
            self.user_connections[client_id] = websocket
        print(f"WS Connected. Total: {len(self.active_connections)}")
        await self.broadcast_count()

    async def disconnect(self, websocket: WebSocket, client_id: str = None):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if client_id and client_id in self.user_connections:
            del self.user_connections[client_id]
        print(f"WS Disconnected. Total: {len(self.active_connections)}")
        await self.broadcast_count()

    async def broadcast_count(self):
        count = len(self.active_connections)
        data = json.dumps({"type": "stats", "online_count": count})
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as e:
                print(f"Broadcast error: {e}")
                self.active_connections.remove(connection)

    async def broadcast_new_image(self, image_data: dict):
        data = json.dumps({"type": "new_image", "data": image_data})
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as e:
                print(f"Broadcast image error: {e}")
                self.active_connections.remove(connection)

    async def send_personal_message(self, message: dict, client_id: str):
        ws = self.user_connections.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
            except Exception as e:
                print(f"Personal message error for {client_id}: {e}")

manager = ConnectionManager()
GLOBAL_LOOP = None

@app.on_event("startup")
async def startup_event():
    global GLOBAL_LOOP
    GLOBAL_LOOP = asyncio.get_running_loop()

@app.websocket("/ws/stats")
async def websocket_endpoint(websocket: WebSocket, client_id: str = None):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await manager.disconnect(websocket, client_id)
    except Exception as e:
        print(f"WS Error: {e}")
        await manager.disconnect(websocket, client_id)

# --- 配置区域 ---

CLIENT_ID = str(uuid.uuid4())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
API_ENV_FILE = os.path.join(BASE_DIR, "API", ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
CANVAS_V2_DIR = os.path.join(DATA_DIR, "canvases_v2")
API_PROVIDERS_FILE = os.path.join(DATA_DIR, "api_providers.json")
MODEL_CATALOG_CACHE_FILE = os.path.join(DATA_DIR, "model_catalog_cache.json")
MODEL_CATALOG_CACHE_TTL = 12 * 3600
# Bump this whenever APIMART_FALLBACK_CATALOG schema changes (params / pricing structure).
# Old cache entries with a different version are silently discarded and rebuilt.
MODEL_CATALOG_CACHE_VERSION = 7
PRICING_CACHE_VERSION = 3  # bump when parse logic changes to invalidate stale pricing entries
FX_RATE_CACHE_FILE = os.path.join(DATA_DIR, "fx_rate_cache.json")
FX_RATE_TTL = 24 * 3600
PRICING_CACHE_TTL = 12 * 3600
CANVAS_TRASH_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
APP_PORT = 6767

# ─── In-app auto-update (GitHub Releases) ─────────────────────────────────────
# APP_VERSION is the single source of truth for "what version am I". It travels
# with the code: after an update overwrites main.py, the new file carries the
# new number, so a restart automatically reports the right version — no separate
# VERSION file to keep in sync.
#
# Release flow for the maintainer:
#   1. Bump APP_VERSION below (e.g. "1.1.0").
#   2. Commit + push to GitHub.
#   3. Create a GitHub Release with tag "v1.1.0" and write the changelog in the
#      release body (it is shown to users verbatim).
# Users running an older APP_VERSION will see the new release and can one-click
# update from inside the app (API settings page / canvas banner).
#
# GITHUB_REPO must point at "owner/repo". Set it before your first release
# either by editing the default here or via the MOISTCANVAS_REPO env var.
APP_VERSION = "1.0.6"
GITHUB_REPO = os.getenv("MOISTCANVAS_REPO", "AssHoi/MoistCanvas").strip().strip("/")
GITHUB_API_BASE = "https://api.github.com"
# Temp workspace for downloading/extracting an update. Lives under runtime/
# which is gitignored and on the same volume as the install (fast local copies).
UPDATE_DIR = os.path.join(BASE_DIR, "runtime", "_update")
UPDATE_STATUS_FILE = os.path.join(BASE_DIR, "runtime", "update_status.json")
UPDATE_LOCK = Lock()
_UPDATE_IN_PROGRESS = {"value": False}
# Hard limits for the downloaded/extracted update package. The GitHub source
# zip of this project is a few MB; these ceilings stop a runaway/oversized
# archive (or a zip bomb) from filling the user's disk.
MAX_UPDATE_DOWNLOAD_BYTES = 200 * 1024 * 1024   # 200 MB compressed download cap
MAX_UPDATE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB total extracted cap
MAX_UPDATE_FILE_BYTES = 80 * 1024 * 1024        # 80 MB per-file cap
MAX_UPDATE_FILE_COUNT = 20000                   # entry-count cap

HISTORY_LOCK = Lock()
GLOBAL_CONFIG_LOCK = Lock()
CANVAS_LOCK = Lock()

PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")

def load_env_file():
    if not os.path.exists(API_ENV_FILE):
        return
    try:
        with open(API_ENV_FILE, 'r', encoding='utf-8-sig') as f:
            for raw_line in f.read().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as e:
        print(f"加载 API/.env 失败: {e}")

load_env_file()

AI_BASE_URL = os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/")
AI_API_KEY = os.getenv("COMFLY_API_KEY", "")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
MODELSCOPE_CHAT_BASE_URL = "https://api-inference.modelscope.cn/v1"
MODELSCOPE_CHAT_MODELS = [m.strip() for m in os.getenv("MODELSCOPE_CHAT_MODELS", "Qwen/Qwen3-235B-A22B,MiniMax/MiniMax-M2.7:MiniMax").split(",") if m.strip()]
MODELSCOPE_DEFAULT_IMAGE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
MODELSCOPE_DEFAULT_CHAT_MODEL = "Qwen/Qwen3-235B-A22B"
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
AI_REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "300"))
IMAGE_POLL_INTERVAL = float(os.getenv("IMAGE_POLL_INTERVAL", "2"))
APIMART_STATUS_POLL_INTERVAL = float(os.getenv("APIMART_STATUS_POLL_INTERVAL", "10"))
VIDEO_POLL_TIMEOUT = float(os.getenv("VIDEO_POLL_TIMEOUT", "1800"))

APIMART_JOB_STATUS: Dict[str, Dict[str, Any]] = {}
APIMART_JOB_LOCK = Lock()

# ─── Centralized APIMart model catalog fallback ───────────────────────────────
# This is the single source of truth for model params and pricing status.
# When APIMart exposes a pricing API, update the "pricing" blocks here only.
def _sd2_params(allow_1080p=True):
    res_opts = ["480p", "720p", "1080p"] if allow_1080p else ["480p", "720p"]
    return {
        "duration":          {"type": "select", "label": "视频时长", "title": "生成视频的时长，单位为秒", "options": [4,5,8,10,15], "default": 5},
        "size":              {"type": "select", "label": "画面比例", "title": "视频宽高比", "options": ["16:9","9:16","1:1","4:3","3:4","21:9","adaptive"], "option_labels": {"adaptive": "自适应"}, "default": "16:9"},
        # Official default is 480p per APIMart docs
        "resolution":        {"type": "select", "label": "清晰度", "title": "视频输出清晰度", "options": res_opts, "default": "480p"},
        "seed":              {"type": "number", "label": "随机种子", "title": "用于复现相近结果，留空则随机", "optional": True, "min": 0, "placeholder": "留空随机", "hidden": True},
        "generate_audio":    {"type": "checkbox", "label": "生成音频", "title": "生成带 AI 配音或声音的视频", "default": False},
        "return_last_frame": {"type": "checkbox", "label": "返回尾帧", "title": "返回视频最后一帧图片，用于连续视频生成", "default": False, "hidden": True},
    }

# ── Pricing rule structure ────────────────────────────────────────────────────
# bill_by: "per_image" | "per_second"
# rules:   list of { resolution, per_image | per_second }
#   value None  → price not yet configured (UI shows "价格未配置")
#   value 0.0+  → price known; UI computes and shows the estimate
#
# Product owner: fill in the per_image / per_second values here only.
# No other file needs to change.

def _img_pricing(res_rules: list) -> dict:
    """Build image pricing block. res_rules: [{"resolution": "1k", "per_image": None}, ...]"""
    return {"currency": "USD", "bill_by": "per_image", "rules": res_rules}

def _vid_pricing(res_rules: list) -> dict:
    """Build video pricing block. res_rules: [{"resolution": "480p", "per_second": None}, ...]"""
    return {"currency": "USD", "bill_by": "per_second", "rules": res_rules}

def _vid_duration_pricing(res_duration_rules: list) -> dict:
    """Build video pricing block for models priced by resolution + duration."""
    return {"currency": "USD", "bill_by": "per_video_duration", "rules": res_duration_rules}

def _omni_flash_ext_params() -> dict:
    return {
        "duration":   {"type": "select", "label": "视频时长", "title": "生成视频的时长，单位为秒；使用参考视频时上游会忽略时长", "options": [4,6,8,10], "default": 6},
        "size":       {"type": "select", "label": "画面比例", "title": "视频宽高比", "options": ["16:9","9:16"], "default": "16:9"},
        "resolution": {"type": "select", "label": "清晰度", "title": "视频输出清晰度", "options": ["720p","1080p","4k"], "default": "720p"},
    }

def _nano_banana_pro_params() -> dict:
    return {
        "resolution": {"type": "select", "label": "图片规格", "title": "输出图片规格档位", "options": ["1K", "2K", "4K"], "default": "1K"},
        "size":       {"type": "select", "label": "图片比例", "title": "输出图片宽高比例", "options": ["auto","1:1","2:3","3:2","3:4","4:3","4:5","5:4","9:16","16:9","21:9"], "option_labels": {"auto": "自动"}, "default": "auto"},
        "n":          {"type": "select", "label": "生成张数", "title": "单次生成图片数量", "options": [1,2,3,4], "default": 1},
    }

def _nano_banana_2_params() -> dict:
    return {
        "resolution": {"type": "select", "label": "图片规格", "title": "输出图片规格档位", "options": ["0.5K", "1K", "2K", "4K"], "default": "1K"},
        "size":       {"type": "select", "label": "图片比例", "title": "输出图片宽高比例", "options": ["auto","1:1","3:2","2:3","4:3","3:4","16:9","9:16","5:4","4:5","21:9","1:4","4:1","1:8","8:1"], "option_labels": {"auto": "自动"}, "default": "auto"},
        "n":          {"type": "select", "label": "生成张数", "title": "单次生成图片数量", "options": [1,2,3,4], "default": 1},
    }

APIMART_FALLBACK_CATALOG: Dict[str, list] = {
    "image": [
        {
            "id": "gpt-image-2",
            "label": "GPT-Image-2",
            "params": {
                "resolution": {"type": "select", "label": "图片规格", "title": "输出图片规格档位", "options": ["1k","2k","4k"], "default": "1k"},
                "size":       {"type": "select", "label": "图片比例", "title": "输出图片宽高比例", "options": ["auto","1:1","3:2","2:3","4:3","3:4","5:4","4:5","16:9","9:16","2:1","1:2","3:1","1:3","21:9","9:21"], "option_labels": {"auto": "自动"}, "default": "1:1"},
                "n":          {"type": "select", "label": "生成张数", "title": "gpt-image-2 仅支持单张生成", "options": [1], "default": 1, "disabled": True, "hidden": True},
            },
            # APIMart bills by resolution tier. Fill per_image (USD) when prices are known.
            "pricing": _img_pricing([
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "gpt-image-2-official",
            "label": "GPT-Image-2 Official",
            "params": {
                "resolution":          {"type": "select", "label": "图片规格", "title": "输出图片规格档位", "options": ["1k","2k","4k"], "default": "1k"},
                "size":                {"type": "select", "label": "图片比例", "title": "输出图片宽高比例", "options": ["auto","1:1","3:2","2:3","4:3","3:4","5:4","4:5","16:9","9:16","2:1","1:2","3:1","1:3","21:9","9:21"], "option_labels": {"auto": "自动"}, "default": "1:1"},
                "output_format":       {"type": "select", "label": "图片格式", "title": "输出文件格式", "options": ["png","jpeg","webp"], "default": "png"},
                "background":          {"type": "select", "label": "背景模式", "title": "背景处理方式：auto 自动，opaque 不透明，transparent 透明", "options": ["auto","opaque","transparent"], "option_labels": {"auto": "自动", "opaque": "不透明", "transparent": "透明"}, "default": "auto"},
                "moderation":          {"type": "select", "label": "审核强度", "title": "内容安全审核强度：auto 默认，low 较宽松", "options": ["auto","low"], "option_labels": {"auto": "默认", "low": "较宽松"}, "default": "low", "hidden": True},
                "n":                   {"type": "select", "label": "生成张数", "title": "单次生成图片数量", "options": [1,2,3,4], "default": 1},
                "quality":             {"type": "select", "label": "图片质量", "title": "输出图片质量", "options": ["auto","low","medium","high"], "option_labels": {"auto": "自动", "low": "低", "medium": "中", "high": "高"}, "default": "auto", "full_width": True},
                "output_compression":  {"type": "number", "label": "压缩质量", "title": "仅 jpeg/webp 的高级参数，界面默认隐藏", "min": 0, "max": 100, "optional": True, "hidden": True},
            },
            # Fill per_image (USD) per resolution tier when prices are known.
            "pricing": _img_pricing([
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "gemini-3-pro-image-preview",
            "label": "Nano Banana Pro",
            "params": _nano_banana_pro_params(),
            "pricing": _img_pricing([
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "gemini-3-pro-image-preview-official",
            "label": "Nano Banana Pro Official",
            "params": _nano_banana_pro_params(),
            "pricing": _img_pricing([
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "gemini-3.1-flash-image-preview",
            "label": "Nano Banana 2",
            "params": _nano_banana_2_params(),
            "pricing": _img_pricing([
                {"resolution": "0.5k", "per_image": None},
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "gemini-3.1-flash-image-preview-official",
            "label": "Nano Banana 2 Official",
            "params": _nano_banana_2_params(),
            "pricing": _img_pricing([
                {"resolution": "0.5k", "per_image": None},
                {"resolution": "1k", "per_image": None},
                {"resolution": "2k", "per_image": None},
                {"resolution": "4k", "per_image": None},
            ]),
            "source": "fallback",
        },
    ],
    "video": [
        {
            "id": "doubao-seedance-2.0",
            "label": "Seedance 2.0",
            "params": _sd2_params(True),
            # Fill per_second (USD) per resolution tier when prices are known.
            "pricing": _vid_pricing([
                {"resolution": "480p",  "per_second": None},
                {"resolution": "720p",  "per_second": None},
                {"resolution": "1080p", "per_second": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "doubao-seedance-2.0-fast",
            "label": "Seedance 2.0 Fast",
            "params": _sd2_params(False),
            "pricing": _vid_pricing([
                {"resolution": "480p", "per_second": None},
                {"resolution": "720p", "per_second": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "doubao-seedance-2.0-face",
            "label": "Seedance 2.0 Face",
            "params": _sd2_params(True),
            "pricing": _vid_pricing([
                {"resolution": "480p",  "per_second": None},
                {"resolution": "720p",  "per_second": None},
                {"resolution": "1080p", "per_second": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "doubao-seedance-2.0-fast-face",
            "label": "Seedance 2.0 Fast Face",
            "params": _sd2_params(False),
            "pricing": _vid_pricing([
                {"resolution": "480p", "per_second": None},
                {"resolution": "720p", "per_second": None},
            ]),
            "source": "fallback",
        },
        {
            "id": "Omni-Flash-Ext",
            "label": "Omni Flash Ext",
            "params": _omni_flash_ext_params(),
            "pricing": _vid_duration_pricing([
                {"resolution": "720p",  "duration": 4,  "per_video": None},
                {"resolution": "720p",  "duration": 6,  "per_video": None},
                {"resolution": "720p",  "duration": 8,  "per_video": None},
                {"resolution": "720p",  "duration": 10, "per_video": None},
                {"resolution": "1080p", "duration": 4,  "per_video": None},
                {"resolution": "1080p", "duration": 6,  "per_video": None},
                {"resolution": "1080p", "duration": 8,  "per_video": None},
                {"resolution": "1080p", "duration": 10, "per_video": None},
                {"resolution": "4k",    "duration": 4,  "per_video": None},
                {"resolution": "4k",    "duration": 6,  "per_video": None},
                {"resolution": "4k",    "duration": 8,  "per_video": None},
                {"resolution": "4k",    "duration": 10, "per_video": None},
            ]),
            "source": "fallback",
        },
    ],
}

def classify_model_kind(model_id: str) -> str:
    """Best-effort grouping for upstream /v1/models results."""
    lc = str(model_id or "").strip().lower().replace("_", "-")
    normalized = lc.replace(".", "-")

    # Some APIMart image models include "seedance" in their ids even though
    # the docs list them under Seedream image generation.
    image_patterns = [
        r"^doubao-seedance-4[-.]?[05]\b",
        r"^doubao-seedream-",
    ]
    if any(re.search(pattern, lc) or re.search(pattern, normalized) for pattern in image_patterns):
        return "image"

    image_keys = [
        "image", "seedream", "dalle", "dall-e", "imagen", "flux", "stable",
        "sdxl", "midjourney", "nano-banana", "ideogram", "fal-ai",
        "z-image", "qwen-image", "klein",
    ]
    if any(k in lc for k in image_keys):
        return "image"

    video_patterns = [
        r"^doubao-seedance-(1|2)(\.|-)",
        r"^doubao-1",
    ]
    if any(re.search(pattern, normalized) for pattern in video_patterns):
        return "video"

    video_keys = [
        "veo", "sora", "wan2", "wanx", "kling", "hailuo", "video", "omni-flash",
        "t2v-", "i2v-", "s2v",
    ]
    if any(k in lc for k in video_keys):
        return "video"

    return "chat"

def group_model_ids(model_ids: List[str]) -> Dict[str, List[str]]:
    grouped = {"image": [], "chat": [], "video": []}
    for mid in model_ids:
        grouped[classify_model_kind(mid)].append(mid)
    return grouped

def provider_key_env(provider_id):
    if provider_id == "comfly":
        return "COMFLY_API_KEY"
    if provider_id == "modelscope":
        return "MODELSCOPE_API_KEY"
    return f"API_PROVIDER_{re.sub(r'[^A-Za-z0-9]', '_', provider_id).upper()}_KEY"

def mask_secret(value):
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return f"••••••••{tail}"

def default_api_providers():
    # ModelScope is no longer a default platform. Users can still add it
    # manually; the ModelScope-specific support code (provider_key_env,
    # normalize_provider protocol pinning, chat/image helpers) is kept intact.
    return [
        {
            "id": "apimart",
            "name": "APIMart",
            "base_url": "https://api.apimart.ai",
            "protocol": "apimart",
            "enabled": True,
            "primary": True,
            "image_models": [
                "gpt-image-2",
                "gpt-image-2-official",
                "gemini-3-pro-image-preview",
                "gemini-3-pro-image-preview-official",
                "gemini-3.1-flash-image-preview",
                "gemini-3.1-flash-image-preview-official",
            ],
            "chat_models": [],
            "video_models": ["doubao-seedance-2.0", "doubao-seedance-2.0-fast", "doubao-seedance-2.0-face", "doubao-seedance-2.0-fast-face", "Omni-Flash-Ext"],
        },
    ]

def merge_default_api_providers(providers):
    merged = [dict(item) for item in providers]
    defaults = default_api_providers()
    # 强制保留 APIMart（首选默认平台）
    am_default = next((d for d in defaults if d["id"] == "apimart"), None)
    if am_default:
        current_am = next((item for item in merged if item.get("id") == "apimart"), None)
        if not current_am:
            merged.insert(0, dict(am_default))
        else:
            if not current_am.get("base_url"):
                current_am["base_url"] = am_default["base_url"]
            if not current_am.get("protocol"):
                current_am["protocol"] = "apimart"
            if not current_am.get("image_models"):
                current_am["image_models"] = list(am_default["image_models"])
            else:
                current_am["image_models"] = model_list_from_values([
                    *current_am.get("image_models", []),
                    *am_default["image_models"],
                ])
            if not current_am.get("video_models"):
                current_am["video_models"] = list(am_default["video_models"])
            else:
                current_am["video_models"] = model_list_from_values([
                    *current_am.get("video_models", []),
                    *am_default["video_models"],
                ])
    # ModelScope is intentionally NOT force-injected anymore. If the user has
    # added it manually it is left exactly as configured.
    return merged

def normalize_model_list(values):
    return model_list_from_values(values)

def model_list_from_values(values):
    deduped = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in deduped:
            selected_model(item, item)
            deduped.append(item)
    return deduped

def normalize_provider(item):
    provider_id = str(item.get("id") or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise HTTPException(status_code=400, detail=f"API 平台 ID 不合法：{provider_id or '(empty)'}")
    name = re.sub(r"\s+", " ", str(item.get("name") or provider_id).strip())[:60] or provider_id
    base_url = str(item.get("base_url") or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail=f"{name} 的 Base URL 需要以 http:// 或 https:// 开头")
    proto = str(item.get("protocol") or "openai").strip().lower()
    if proto not in ("openai", "apimart"):
        proto = "openai"
    if provider_id == "modelscope":
        proto = "openai"
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "protocol": proto,
        "enabled": bool(item.get("enabled", True)),
        "primary": bool(item.get("primary", False)),
        "image_models": model_list_from_values(item.get("image_models") or []),
        "chat_models": model_list_from_values(item.get("chat_models") or []),
        "video_models": model_list_from_values(item.get("video_models") or []),
    }

def load_api_providers():
    defaults = default_api_providers()
    if not os.path.exists(API_PROVIDERS_FILE):
        return defaults
    try:
        with open(API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        providers = [normalize_provider(item) for item in raw if isinstance(item, dict)]
        return merge_default_api_providers(providers or defaults)
    except Exception as e:
        print(f"加载 API 平台配置失败: {e}")
        return defaults

def save_api_providers(providers):
    os.makedirs(DATA_DIR, exist_ok=True)
    with GLOBAL_CONFIG_LOCK:
        with open(API_PROVIDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(providers, f, ensure_ascii=False, indent=2)

def public_provider(provider):
    key = os.getenv(provider_key_env(provider["id"]), "")
    return {
        **provider,
        "has_key": bool(key),
        "key_preview": mask_secret(key),
        "key_env": provider_key_env(provider["id"]),
    }

def get_primary_provider_id(providers=None):
    """返回当前首选 provider 的 id；优先 primary=True 的，否则取第一个启用的，再次取第一个。"""
    providers = providers if providers is not None else load_api_providers()
    primary = next((p for p in providers if p.get("primary") and p.get("enabled", True)), None)
    if primary:
        return primary["id"]
    enabled = next((p for p in providers if p.get("enabled", True)), None)
    if enabled:
        return enabled["id"]
    return providers[0]["id"] if providers else "apimart"

def get_api_provider(provider_id="comfly"):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    # 兼容旧的 "comfly" 硬编码：若 comfly 不存在或未指定，回退到首选 provider
    if not target or not any(p["id"] == target for p in providers):
        target = get_primary_provider_id(providers)
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台：{target}")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API 平台已禁用：{provider.get('name') or target}")
    return provider

def env_quote(value):
    text = str(value or "")
    if not text or re.search(r"\s|#|['\"]", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text

def update_env_values(updates):
    os.makedirs(os.path.dirname(API_ENV_FILE), exist_ok=True)
    lines = []
    if os.path.exists(API_ENV_FILE):
        with open(API_ENV_FILE, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    seen = set()
    next_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            next_lines.append(f"{key}={env_quote(updates[key])}")
            os.environ[key] = str(updates[key] or "")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={env_quote(value)}")
            os.environ[key] = str(value or "")
    with open(API_ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(next_lines).rstrip() + "\n")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(CANVAS_V2_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# --- Pydantic 模型 ---

class DeleteHistoryRequest(BaseModel):
    timestamp: float

class AIReference(BaseModel):
    url: str = ""
    name: str = ""

class OnlineImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    provider_id: str = "comfly"
    model: str = ""
    size: str = "1:1"
    quality: str = "auto"
    reference_images: List[AIReference] = []
    # APIMart extended fields
    resolution: str = ""
    n: int = 1
    background: str = ""
    moderation: str = ""
    output_format: str = ""
    output_compression: Optional[int] = None
    # Per-image mask routing. Only honoured when model == "gpt-image-2-official"
    # (the only channel APIMart currently exposes mask_url on). When set,
    # main.py uploads /output/... paths through the APIMart upload endpoint
    # and forwards the resulting public URL as mask_url. Other models ignore
    # this field — they get a visual mask reference image instead, baked in
    # by the frontend.
    mask_url: str = ""

class CanvasVideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    provider_id: str = "comfly"
    model: str = "veo3-fast"
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = ""
    size: str = ""
    images: List[AIReference] = []
    videos: List[str] = []
    enhance_prompt: bool = False
    enable_upsample: bool = False
    watermark: bool = False
    seed: Optional[int] = None
    camerafixed: bool = False
    return_last_frame: bool = False
    generate_audio: bool = False

class ApiProviderPayload(BaseModel):
    id: str = ""
    name: str = ""
    base_url: str = ""
    enabled: bool = True
    primary: bool = False
    protocol: str = "openai"
    image_models: List[str] = []
    chat_models: List[str] = []
    video_models: List[str] = []
    api_key: Optional[str] = None

class CanvasCreateRequest(BaseModel):
    title: str = "未命名画布"
    icon: str = "🧩"

class CanvasV2SaveRequest(BaseModel):
    version: int = 2
    id: str = "default"
    title: str = "Moist Canvas"
    updated_at: int = 0
    viewport: Dict[str, Any] = {}
    nodes: List[Dict[str, Any]] = []
    refs: List[Dict[str, Any]] = []
    conversation_messages: List[Dict[str, Any]] = []

# --- 辅助工具 ---

def save_to_history(record):
    with HISTORY_LOCK:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except: pass
        if "timestamp" not in record:
            record["timestamp"] = time.time()
        history.insert(0, record)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history[:5000], f, ensure_ascii=False, indent=4)

def now_ms():
    return int(time.time() * 1000)


def canvas_v2_path(canvas_id):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", canvas_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid canvas ID")
    return os.path.join(CANVAS_V2_DIR, f"{cleaned}.json")

def empty_canvas_v2(canvas_id="default", title="Moist Canvas"):
    return {
        "version": 2,
        "id": canvas_id,
        "title": title or "Moist Canvas",
        "created_at": 0,
        "updated_at": 0,
        "viewport": {},
        "nodes": [],
        "refs": [],
        "conversation_messages": [],
    }

def save_canvas_v2_data(data):
    canvas_id = re.sub(r"[^a-zA-Z0-9_-]", "", data.get("id") or "default")
    data["id"] = canvas_id
    data["version"] = int(data.get("version") or 2)
    data["title"] = (data.get("title") or "Moist Canvas")[:80]
    if not data.get("created_at"):
        data["created_at"] = now_ms()
    data["updated_at"] = now_ms()
    with CANVAS_LOCK:
        with open(canvas_v2_path(canvas_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data

def load_canvas_v2_data(canvas_id, include_deleted=False):
    path = canvas_v2_path(canvas_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Canvas not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("id", canvas_id)
        data.setdefault("title", "Moist Canvas")
        data.setdefault("version", 2)
        data.setdefault("nodes", [])
        data.setdefault("refs", [])
        data.setdefault("viewport", {})
        data.setdefault("conversation_messages", [])
        if data.get("deleted_at") and not include_deleted:
            raise HTTPException(status_code=404, detail="画布已在回收站")
        return data
    except HTTPException:
        raise
    except Exception as e:
        print(f"Read canvas_v2 failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _canvas_v2_preview_url(nodes):
    """
    Pick a preview URL for a canvas card.
    Priority:
      1. First image node whose filename looks generated (online_/generated_).
      2. First image node regardless of source.
      3. None.
    Never raises; tolerates legacy nodes that lack fields.
    """
    if not isinstance(nodes, list):
        return None
    first_any = None
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("type") != "image":
            continue
        url = n.get("url") or ""
        if not url:
            continue
        if first_any is None:
            first_any = url
        # filename heuristic for "generated by this app"
        tail = url.rsplit("/", 1)[-1].lower()
        if tail.startswith("online_") or tail.startswith("generated_"):
            return url
    return first_any

def canvas_v2_record(data):
    return {
        "id": data.get("id") or "default",
        "title": data.get("title") or "Moist Canvas",
        "created_at": data.get("created_at", 0),
        "updated_at": data.get("updated_at", 0),
        "deleted_at": data.get("deleted_at", 0),
        "node_count": len(data.get("nodes") or []),
        "preview_url": _canvas_v2_preview_url(data.get("nodes")),
    }

def cleanup_expired_canvas_v2_trash():
    cutoff = now_ms() - CANVAS_TRASH_RETENTION_MS
    with CANVAS_LOCK:
        for filename in os.listdir(CANVAS_V2_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(CANVAS_V2_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deleted_at = int(data.get("deleted_at") or 0)
                if deleted_at and deleted_at < cutoff:
                    os.remove(path)
            except Exception:
                continue

def list_canvases_v2(include_deleted=False):
    cleanup_expired_canvas_v2_trash()
    records = []
    for filename in os.listdir(CANVAS_V2_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(CANVAS_V2_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        is_deleted = bool(data.get("deleted_at"))
        if include_deleted != is_deleted:
            continue
        records.append(canvas_v2_record(data))
    if include_deleted:
        return sorted(records, key=lambda item: item.get("deleted_at") or 0, reverse=True)
    return sorted(records, key=lambda item: item.get("updated_at") or 0, reverse=True)

def new_canvas_v2(title="Moist Canvas"):
    canvas = empty_canvas_v2(uuid.uuid4().hex, (title or "Moist Canvas")[:80])
    return save_canvas_v2_data(canvas)

def write_canvas_v2_raw(canvas_id, data):
    """Write a Canvas V2 record without touching updated_at — used by trash/restore."""
    path = canvas_v2_path(canvas_id)
    data["id"] = re.sub(r"[^a-zA-Z0-9_-]", "", canvas_id or "") or canvas_id
    with CANVAS_LOCK:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data

def api_headers(json_body=True, provider=None):
    if provider:
        key_env = provider_key_env(provider["id"])
        api_key = os.getenv(key_env, "")
        provider_name = provider.get("name") or provider["id"]
        if not api_key:
            raise HTTPException(status_code=400, detail=f"未配置 {provider_name} 的 API Key，请在 API 平台管理中填写。")
    else:
        api_key = AI_API_KEY
        if not api_key:
            raise HTTPException(status_code=400, detail="未配置 COMFLY_API_KEY，请在 API/.env 中填写。")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

def selected_model(requested, fallback):
    model = (requested or fallback).strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if len(model) > 120 or not re.fullmatch(r"[a-zA-Z0-9_.:/+-]+", model):
        raise HTTPException(status_code=400, detail=f"模型名称不合法：{model}")
    return model

def extract_image(data):
    # APIMart task result: { code, data: { id, status, result: { images: [{ url: ["..."] }] } } }
    outer_data = data.get("data")
    if isinstance(outer_data, dict):
        result_section = (outer_data.get("result") or {})
        if isinstance(result_section, dict):
            images_am = result_section.get("images") or []
            if images_am and isinstance(images_am[0], dict):
                url_field = images_am[0].get("url")
                if isinstance(url_field, list) and url_field:
                    return {"type": "url", "value": url_field[0]}
                if isinstance(url_field, str) and url_field:
                    return {"type": "url", "value": url_field}
    # Standard nested: { data: { data: { data: [...] } } }
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), dict):
        data = data["data"]["data"]
    images = data.get("data") or []
    if not isinstance(images, list) or not images:
        raise HTTPException(status_code=502, detail="生图接口没有返回图片数据")
    first = images[0]
    if isinstance(first, dict):
        if first.get("url"):
            return {"type": "url", "value": first["url"]}
        if first.get("b64_json"):
            return {"type": "b64", "value": first["b64_json"]}
    raise HTTPException(status_code=502, detail="无法识别生图接口返回格式")

def extract_task_id(data):
    if data.get("task_id"):
        return str(data["task_id"])
    if data.get("id") and str(data.get("id", "")).startswith("task"):
        return str(data["id"])
    nested = data.get("data")
    if isinstance(nested, dict):
        return extract_task_id(nested)
    return None

async def wait_for_image_task(client, task_id, provider=None):
    base_url = (provider.get("base_url") if provider else AI_BASE_URL).rstrip("/")
    task_url = f"{base_url}/images/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/images/tasks/{task_id}"
    deadline = time.monotonic() + AI_REQUEST_TIMEOUT
    last_payload = {}
    while time.monotonic() < deadline:
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        last_payload = response.json()
        task_data = last_payload.get("data") if isinstance(last_payload.get("data"), dict) else last_payload
        status = str(task_data.get("status", "")).upper()
        if status == "SUCCESS":
            return last_payload
        if status == "FAILURE":
            reason = task_data.get("fail_reason") or last_payload.get("message") or "生图任务失败"
            raise HTTPException(status_code=502, detail=f"生图任务失败：{reason}")
        await asyncio.sleep(IMAGE_POLL_INTERVAL)
    raise HTTPException(status_code=504, detail=f"生图任务超时，task_id={task_id}")

def output_file_from_url(url):
    if not url or not url.startswith("/output/"):
        return None
    filename = os.path.basename(urllib.parse.unquote(url.split("?", 1)[0]))
    path = os.path.abspath(os.path.join(OUTPUT_DIR, filename))
    output_root = os.path.abspath(OUTPUT_DIR)
    if os.path.commonpath([output_root, path]) != output_root or not os.path.exists(path):
        return None
    return path

def content_type_for_path(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return "image/png"

def convert_output_to_jpg(url, quality=88):
    path = output_file_from_url(url)
    if not path:
        return url
    root, ext = os.path.splitext(path)
    if ext.lower() in [".jpg", ".jpeg"]:
        return url
    jpg_path = f"{root}.jpg"
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(jpg_path, "JPEG", quality=quality, optimize=True)
        return f"/output/{os.path.basename(jpg_path)}"
    except Exception as e:
        print(f"转换 JPG 失败: {e}")
        return url

def reference_to_data_url(ref, max_size=None):
    """把本地输出文件转为 data URL（base64）。max_size 限制最长边像素，避免 payload 过大。"""
    path = output_file_from_url(ref.get("url", ""))
    if not path:
        return ref.get("url", "")
    if max_size:
        try:
            with Image.open(path) as img:
                img.load()
                w, h = img.size
                if max(w, h) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = BytesIO()
                fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                img.save(buf, format=fmt, quality=88 if fmt == "JPEG" else None)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            print(f"reference resize failed, fallback to raw: {e}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{content_type_for_path(path)};base64,{encoded}"

async def save_ai_image_to_output(image_data, prefix="online_"):
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    path = os.path.join(OUTPUT_DIR, filename)
    if image_data["type"] == "b64":
        with open(path, "wb") as f:
            f.write(base64.b64decode(image_data["value"]))
        return f"/output/{filename}"
    value = image_data["value"]
    if value.startswith("/output/"):
        return value
    try:
        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(value)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                filename = filename[:-4] + ".jpg"
                path = os.path.join(OUTPUT_DIR, filename)
            elif "webp" in content_type:
                filename = filename[:-4] + ".webp"
                path = os.path.join(OUTPUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(response.content)
            return f"/output/{filename}"
    except Exception as e:
        print(f"保存上游图片失败: {e}")
        return value

async def save_remote_video_to_output(url, prefix="video_"):
    if not url:
        return ""
    if url.startswith("/output/"):
        return url
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.mp4"
    path = os.path.join(OUTPUT_DIR, filename)
    try:
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").lower()
            clean_path = urllib.parse.urlparse(url).path
            ext = os.path.splitext(clean_path)[1].lower()
            if ext in {".mp4", ".webm", ".mov"}:
                filename = filename[:-4] + ext
                path = os.path.join(OUTPUT_DIR, filename)
            elif "webm" in content_type:
                filename = filename[:-4] + ".webm"
                path = os.path.join(OUTPUT_DIR, filename)
            elif "quicktime" in content_type or "mov" in content_type:
                filename = filename[:-4] + ".mov"
                path = os.path.join(OUTPUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(response.content)
            return f"/output/{filename}"
    except Exception as e:
        print(f"保存上游视频失败: {e}")
        return url

APIMART_VIDEO_SIZES = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}

def apimart_api_root(base_url):
    """Strip trailing /v1 so callers can safely append /v1/... without doubling."""
    root = str(base_url or "https://api.apimart.ai").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root

async def upload_to_apimart(client, base_url, api_key, local_path):
    """Upload a local image to APIMart /v1/uploads/images, return HTTPS URL."""
    root = apimart_api_root(base_url)
    upload_url = f"{root}/v1/uploads/images"
    with open(local_path, "rb") as f:
        content = f.read()
    ext = os.path.splitext(local_path)[1].lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    filename = os.path.basename(local_path)
    resp = await client.post(
        upload_url,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (filename, content, mime)},
    )
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url") or (data.get("data") or {}).get("url") or ""
    if not url:
        raise HTTPException(status_code=502, detail=f"APIMart 图片上传失败，未返回 URL：{str(data)[:200]}")
    return url

# ─── APIMart Error Classification ─────────────────────────────────────────────
# Upstream APIMart / OpenAI safety-rejection responses come in several shapes.
# We collapse them into a short friendly Chinese message + optional request_id,
# so the frontend can show the cause clearly without dumping raw JSON at users.

_APIMART_SAFETY_KEYWORDS_CN = (
    "审核被阻止", "安全系统拒绝", "安全系统", "敏感内容", "违规内容", "不当内容",
)
_APIMART_SAFETY_KEYWORDS_EN = (
    "safety", "moderation", "blocked", "rejected by safety",
    "content_policy", "policy_violation", "content policy",
)
# Both English and (occasionally seen) Chinese field names for error blobs.
_APIMART_ERROR_FIELD_KEYS = (
    "code", "message", "msg", "error", "detail", "reason",
    "错误", "消息", "代码",
)

def _flatten_apimart_error(error_obj) -> str:
    """Flatten APIMart error shapes (str | dict | list | None) into a single short string."""
    if error_obj is None:
        return ""
    if isinstance(error_obj, str):
        return error_obj
    if isinstance(error_obj, dict):
        parts = []
        for k in _APIMART_ERROR_FIELD_KEYS:
            v = error_obj.get(k)
            if isinstance(v, str) and v:
                parts.append(v)
            elif isinstance(v, dict):
                parts.append(_flatten_apimart_error(v))
        return " ".join(p for p in parts if p) or json.dumps(error_obj, ensure_ascii=False)[:200]
    if isinstance(error_obj, list):
        return " ".join(_flatten_apimart_error(item) for item in error_obj if item)[:200]
    return str(error_obj)[:200]

def _extract_request_id(*sources) -> Optional[str]:
    """Walk dicts looking for a request_id (also checks nested .data)."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in ("request_id", "requestId", "req_id"):
            v = src.get(k)
            if isinstance(v, str) and v:
                return v
        nested = src.get("data") if isinstance(src.get("data"), dict) else None
        if nested:
            rid = _extract_request_id(nested)
            if rid:
                return rid
    return None

def classify_apimart_failure(error_obj, raw_response=None) -> dict:
    """
    Map an APIMart task-failure or upstream HTTP error into a structured friendly detail
    for HTTPException(detail=...). Returns dict: { message, code, request_id }.
    Never include the raw upstream JSON in `message`.
    """
    text = _flatten_apimart_error(error_obj)
    lower = text.lower()
    request_id = _extract_request_id(error_obj, raw_response)
    if "multipart/form-data" in lower and "application/json" in lower:
        # Neutral wording on purpose: this classifier doesn't know whether
        # any fallback has been attempted yet. The stage-aware wording is
        # added by generate_apimart_image at the terminal failure points
        # (content_type_mismatch_no_fallback / _official_retry_failed /
        # _fallback_failed / _mask_locked).
        return {
            "message": "APIMart 官方图生图通道返回 Content-Type 错误：上游把请求当成 multipart 发送，但该接口只接受 JSON。",
            "code": "content_type_mismatch",
            "request_id": request_id,
        }
    safety = (
        any(kw in text  for kw in _APIMART_SAFETY_KEYWORDS_CN)
        or any(kw in lower for kw in _APIMART_SAFETY_KEYWORDS_EN)
    )
    if safety:
        return {
            "message": "内容被上游安全审核拦截，请调整提示词或参考图后重试。",
            "code": "safety_blocked",
            "request_id": request_id,
        }
    short = (text[:160] + "…") if len(text) > 160 else (text or "未知错误")
    return {
        "message": f"上游生图失败：{short}",
        "code": "upstream_error",
        "request_id": request_id,
    }


def _http_detail_text(detail) -> str:
    if isinstance(detail, dict):
        return " ".join(str(v) for v in detail.values() if v is not None)
    return str(detail or "")


def _is_content_type_mismatch_text(text: str) -> bool:
    lower = str(text or "").lower()
    return "multipart/form-data" in lower and "application/json" in lower


def _is_content_type_mismatch_detail(detail) -> bool:
    return _is_content_type_mismatch_text(_http_detail_text(detail))


def _is_transient_upstream_5xx_text(text: str) -> bool:
    lower = str(text or "").lower()
    return (
        "cloudflare" in lower
        or "bad gateway" in lower
        or "http 502" in lower
        or "http 503" in lower
        or "http 504" in lower
        or "错误网关" in lower
    )


def _should_fallback_official_ref_error(detail) -> bool:
    text = _http_detail_text(detail)
    return _is_content_type_mismatch_text(text) or _is_transient_upstream_5xx_text(text)


def _apimart_task_data(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}

def _apimart_task_info(task_id: str, payload: dict, status_override: str = "", extra: Optional[dict] = None) -> dict:
    task_data = _apimart_task_data(payload)
    info = {
        "taskId": task_id or task_data.get("task_id") or task_data.get("id") or "",
        "status": status_override or task_data.get("status") or "",
        "progress": task_data.get("progress"),
        "estimatedTime": task_data.get("estimated_time"),
        "actualTime": task_data.get("actual_time"),
        "cost": task_data.get("cost"),
        "message": task_data.get("message") or "",
        "updatedAt": int(time.time() * 1000),
    }
    if isinstance(extra, dict):
        info.update(extra)
    return {k: v for k, v in info.items() if v is not None and v != ""}

def _set_apimart_job_status(client_job_id: str, info: dict):
    if not client_job_id:
        return
    with APIMART_JOB_LOCK:
        current = APIMART_JOB_STATUS.get(client_job_id, {})
        merged = dict(current)
        merged.update(info or {})
        merged["clientJobId"] = client_job_id
        merged["updatedAt"] = int(time.time() * 1000)
        APIMART_JOB_STATUS[client_job_id] = merged

def _get_apimart_job_status(client_job_id: str) -> dict:
    with APIMART_JOB_LOCK:
        return dict(APIMART_JOB_STATUS.get(client_job_id) or {})

@app.get("/api/apimart-job/{client_job_id}")
async def apimart_job_status(client_job_id: str):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", client_job_id or "")
    if not cleaned or cleaned != client_job_id:
        raise HTTPException(status_code=400, detail="Invalid job id")
    info = _get_apimart_job_status(cleaned)
    if not info:
        raise HTTPException(status_code=404, detail="APIMart job not found")
    return info


async def wait_for_apimart_task(client, base_url, api_key, task_id, timeout=None, client_job_id=""):
    """Poll APIMart /v1/tasks/{task_id}?language=zh until completed or failed."""
    root = apimart_api_root(base_url)
    poll_url = f"{root}/v1/tasks/{task_id}?language=zh"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    effective_timeout = timeout or AI_REQUEST_TIMEOUT
    started_at = time.monotonic()
    deadline = time.monotonic() + effective_timeout
    delay = max(1.0, APIMART_STATUS_POLL_INTERVAL)
    last_payload = {}
    _set_apimart_job_status(client_job_id, {
        "taskId": task_id,
        "status": "submitted",
        "progress": 0,
        "pollCount": 0,
        "elapsedSeconds": 0,
    })
    poll_count = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        resp = await client.get(poll_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        last_payload = data
        task_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        status = str(task_data.get("status") or "").lower()
        poll_count += 1
        elapsed = int(time.monotonic() - started_at)
        _set_apimart_job_status(client_job_id, _apimart_task_info(task_id, data, extra={
            "pollCount": poll_count,
            "elapsedSeconds": elapsed,
        }))
        if status in ("completed", "success"):
            return data
        if status in ("failed", "failure", "error", "cancelled"):
            error_obj = task_data.get("error") or task_data.get("message") or task_data
            info = classify_apimart_failure(error_obj, raw_response=data)
            task_info = _apimart_task_info(task_id, data, status_override=status, extra={
                "pollCount": poll_count,
                "elapsedSeconds": elapsed,
            })
            _set_apimart_job_status(client_job_id, {
                "taskId": task_id,
                "status": status,
                "error": info,
                "pollCount": poll_count,
                "elapsedSeconds": elapsed,
            })
            if isinstance(info, dict):
                info = dict(info)
                info["task_info"] = task_info
            raise HTTPException(status_code=502, detail=info)
    timeout_info = {
        "taskId": task_id,
        "status": "timeout",
        "message": f"已等待 {int(effective_timeout)} 秒，APIMart 仍未返回完成状态",
        "pollCount": poll_count,
        "elapsedSeconds": int(time.monotonic() - started_at),
    }
    _set_apimart_job_status(client_job_id, timeout_info)
    raise HTTPException(status_code=504, detail={
        "message": f"APIMart 任务超时：已等待 {int(effective_timeout)} 秒，APIMart 仍未返回完成状态，task_id={task_id}",
        "code": "apimart_task_timeout",
        "task_info": _get_apimart_job_status(client_job_id) or timeout_info,
    })

def extract_apimart_image_results(data) -> list:
    """Extract all image URLs from APIMart task result, returns list of image_data dicts."""
    outer_data = data.get("data")
    results = []
    if isinstance(outer_data, dict):
        result_section = outer_data.get("result") or {}
        images = result_section.get("images") or []
        for img in images:
            if not isinstance(img, dict):
                continue
            url_field = img.get("url")
            if isinstance(url_field, list) and url_field:
                results.append({"type": "url", "value": url_field[0]})
            elif isinstance(url_field, str) and url_field:
                results.append({"type": "url", "value": url_field})
    if not results:
        raise HTTPException(status_code=502, detail=f"无法从 APIMart 任务结果中提取图片 URL：{str(data)[:300]}")
    return results

def extract_apimart_image_result(data):
    """Single-image compat shim — returns first result from extract_apimart_image_results."""
    return extract_apimart_image_results(data)[0]

async def generate_apimart_image(prompt, size, model, reference_images, provider,
                                  resolution="", n=1, quality="", background="",
                                  moderation="", output_format="", output_compression=None,
                                  mask_url="",
                                  allow_official_ref_fallback=True,
                                  client_job_id=""):
    """APIMart async image generation: submit → poll /v1/tasks/{task_id}."""
    root = apimart_api_root(provider.get("base_url") or "https://api.apimart.ai")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {provider.get('name') or provider['id']} 的 API Key，请在 API 设置中填写。")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def retry_non_official_json_refs():
        print(f"APIMart image fallback: {model} reference request -> gpt-image-2 JSON channel")
        images, fallback_raw = await generate_apimart_image(
            prompt, size, "gpt-image-2", reference_images, provider,
            resolution=resolution,
            n=1,
            allow_official_ref_fallback=False,
            client_job_id=client_job_id,
        )
        if isinstance(fallback_raw, dict):
            fallback_raw["_fallback_from_model"] = model
            fallback_raw["_model_used"] = "gpt-image-2"
        return images, fallback_raw

    async def submit_payload(client, root, headers, payload, image_urls, ref_shape):
        # Log the upstream POST. ONLY field NAMES from the payload are
        # included — never values (so prompts/URLs aren't dumped). Headers
        # are not logged (contain Bearer api_key).
        print(
            "APIMart image submit: "
            f"model={payload.get('model')}, refs={len(image_urls)}, ref_shape={ref_shape}, "
            f"size={payload.get('size')}, resolution={payload.get('resolution', '')}, "
            f"n={payload.get('n', 1)}, has_mask_url={('mask_url' in payload)}, "
            f"keys={','.join(sorted(payload.keys()))}"
        )
        submit_resp = await client.post(f"{root}/v1/images/generations", headers=headers, json=payload)
        submit_resp.raise_for_status()
        raw = submit_resp.json()
        # { code: 200, data: [{ status: "submitted", task_id: "..." }] }
        data_list = raw.get("data") if isinstance(raw.get("data"), list) else []
        task_id = data_list[0].get("task_id") if data_list and isinstance(data_list[0], dict) else None
        if not task_id:
            task_id = raw.get("task_id")
        if not task_id:
            return extract_apimart_image_results(raw), raw
        result = await wait_for_apimart_task(client, root, api_key, task_id, client_job_id=client_job_id)
        return extract_apimart_image_results(result), result

    async def retry_official_object_refs(client, root, headers, payload, image_urls):
        object_payload = dict(payload)
        object_payload["image_urls"] = [{"url": u} for u in image_urls]
        images, object_raw = await submit_payload(
            client, root, headers, object_payload, image_urls, "objects"
        )
        if isinstance(object_raw, dict):
            object_raw["_reference_shape_used"] = "objects"
        return images, object_raw

    # ── Error-classification helpers used by the stage machine below ──
    def _exc_text(exc):
        """Best-effort raw error text from either kind of exception."""
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                return exc.response.text or ""
            except Exception:
                return ""
        if isinstance(exc, HTTPException):
            return _http_detail_text(exc.detail)
        return str(exc or "")

    def _exc_parsed_dict(exc):
        """If the exception carries a JSON response, parse it. Else None."""
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                return exc.response.json()
            except Exception:
                return None
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            return exc.detail
        return None

    def _is_mismatch_exc(exc):
        """True if this is a Content-Type/multipart-vs-JSON mismatch
        (or a transient 5xx we treat the same way)."""
        parsed = _exc_parsed_dict(exc)
        if isinstance(parsed, dict) and parsed.get("code") == "content_type_mismatch":
            return True
        return _should_fallback_official_ref_error(_exc_text(exc))

    def _exc_status(exc, default=502):
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code
        if isinstance(exc, HTTPException):
            return exc.status_code or default
        return default

    def _short(text, n=200):
        text = str(text or "")
        return text[:n] + ("…" if len(text) > n else "")

    def _build_mismatch_detail(initial_text, object_refs_text, fallback_text, request_id, has_mask):
        """Stage-aware terminal detail for content-type-mismatch failures.
        Caller decides which `*_text` arguments are non-None based on which
        stages it actually attempted.
        """
        tried_object   = object_refs_text is not None
        tried_fallback = fallback_text   is not None
        if has_mask:
            return {
                "message": (
                    "APIMart 官方图生图通道返回 Content-Type 错误（上游把请求当成 multipart）。"
                    "因为本次使用 mask_url，不能降级到 gpt-image-2，否则蒙版会丢失。"
                    "请稍后重试，或临时关闭蒙版后再生成。"
                ),
                "code":       "content_type_mismatch_mask_locked",
                "request_id": request_id,
            }
        if tried_fallback:
            return {
                "message": (
                    "APIMart 官方图生图通道失败（Content-Type 错误）。"
                    "已自动尝试切换到 gpt-image-2，但 fallback 也失败：" + _short(fallback_text)
                ),
                "code":       "content_type_mismatch_fallback_failed",
                "request_id": request_id,
            }
        if tried_object:
            return {
                "message": (
                    "APIMart 官方图生图通道返回 Content-Type 错误。"
                    "已尝试切换 image_urls 为 object 形式，但仍失败：" + _short(object_refs_text) +
                    " 可临时切换到 gpt-image-2 模型。"
                ),
                "code":       "content_type_mismatch_official_retry_failed",
                "request_id": request_id,
            }
        # No fallback attempted (e.g. no refs, or caller disallowed fallback).
        return {
            "message": (
                "APIMart 官方图生图通道返回 Content-Type 错误（上游把请求当成 multipart）。"
                "本次未尝试自动 fallback。可临时切换到 gpt-image-2 模型。"
            ),
            "code":       "content_type_mismatch_no_fallback",
            "request_id": request_id,
        }

    async with httpx.AsyncClient(timeout=AI_REQUEST_TIMEOUT) as client:
        image_urls = []
        for ref in (reference_images or [])[:16]:
            if not ref.get("url"):
                continue
            local_path = output_file_from_url(ref["url"])
            if local_path:
                remote_url = await upload_to_apimart(client, root, api_key, local_path)
                image_urls.append(remote_url)
        model_lc = str(model or "").strip().lower()
        is_official = model_lc.endswith("-official")
        supports_mask_url = model_lc in {
            "gpt-image-2-official",
            "gemini-3-pro-image-preview-official",
        }
        supports_gpt_image_options = model_lc == "gpt-image-2-official"

        # ── Mask routing (gpt-image-2-official only) ────────────────────
        # Resolve a frontend-provided mask_url into a remote URL that
        # APIMart's official channel can fetch. Two accepted shapes:
        #   * /output/<filename>  → upload through APIMart's /v1/uploads/images
        #   * http(s)://…         → pass through as-is (caller-hosted)
        # Anything else is rejected with a 400 so misconfigured frontends
        # fail loudly instead of silently dropping the mask.
        remote_mask_url = ""
        if mask_url:
            mask_url = str(mask_url).strip()
        if supports_mask_url and mask_url:
            if not image_urls:
                raise HTTPException(
                    status_code=400,
                    detail="mask_url 必须与参考图一起使用：当前请求没有任何 reference_images。",
                )
            local_mask_path = output_file_from_url(mask_url)
            if local_mask_path:
                remote_mask_url = await upload_to_apimart(client, root, api_key, local_mask_path)
            elif mask_url.lower().startswith(("http://", "https://")):
                remote_mask_url = mask_url
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"无法解析 mask_url：{mask_url[:160]}。请提供 /output 本地路径或 http(s) 远程地址。",
                )

        payload: Dict[str, Any] = {"prompt": prompt.strip(), "model": model, "size": size or "1:1"}
        if n and n > 1:
            payload["n"] = int(n)
        if resolution:
            payload["resolution"] = resolution
        if supports_gpt_image_options and quality:
            payload["quality"] = quality
        if supports_gpt_image_options and background:
            payload["background"] = background
        if supports_gpt_image_options and moderation:
            payload["moderation"] = moderation
        if supports_gpt_image_options and output_format:
            payload["output_format"] = output_format
        if supports_gpt_image_options and output_compression is not None and (output_format or "").lower() != "png":
            payload["output_compression"] = output_compression
        if image_urls:
            payload["image_urls"] = image_urls
        if remote_mask_url:
            payload["mask_url"] = remote_mask_url

        # ── Stage 1: initial official submit (image_urls as bare strings) ─
        try:
            return await submit_payload(client, root, headers, payload, image_urls, "strings")
        except (httpx.HTTPStatusError, HTTPException) as initial_exc:
            initial_text  = _exc_text(initial_exc)
            initial_mismatch = _is_mismatch_exc(initial_exc)
            parsed_initial   = _exc_parsed_dict(initial_exc) or {}
            # Surface request_id from whichever path carried it.
            request_id = (
                (isinstance(parsed_initial, dict) and parsed_initial.get("request_id"))
                or _extract_request_id(parsed_initial if isinstance(parsed_initial, dict) else {})
            )
            can_retry = (
                allow_official_ref_fallback
                and is_official
                and bool(image_urls)
                and initial_mismatch
            )
            print(
                "APIMart official initial submit failed: "
                f"is_mismatch={initial_mismatch}, is_official={is_official}, "
                f"refs={len(image_urls)}, has_mask_url={bool(remote_mask_url)}, "
                f"allow_fallback={allow_official_ref_fallback}, will_retry={can_retry}"
            )
            if not can_retry:
                # Either ineligible for retry, or not a mismatch — let the
                # original exception propagate (online_image will produce
                # the friendly Chinese message via classify_apimart_failure).
                raise

        # ── Stage 2: official retry with object-shaped image_urls ──
        # Same model, same channel, same mask_url — just reshape image_urls
        # so APIMart's serializer is less likely to multipart-encode them.
        print(
            "APIMart official retry: reshape image_urls to objects "
            f"(refs={len(image_urls)}, has_mask_url={bool(remote_mask_url)})"
        )
        object_refs_text = None
        try:
            return await retry_official_object_refs(client, root, headers, payload, image_urls)
        except (httpx.HTTPStatusError, HTTPException) as retry_exc:
            object_refs_text = _exc_text(retry_exc)
            if not _is_mismatch_exc(retry_exc):
                # Object-refs retry failed for a different reason — propagate.
                print(
                    "APIMart official object-refs retry failed with non-mismatch error; "
                    "propagating original exception"
                )
                raise

        # ── Stage 3: mask gate — never silently fall back when mask_url is set ──
        if remote_mask_url:
            print(
                "APIMart official failed twice (initial + object-refs). "
                "Refusing gpt-image-2 fallback because mask_url is in use "
                "(non-official channel has no mask_url support — fallback would silently lose the mask)."
            )
            raise HTTPException(
                status_code=502,
                detail=_build_mismatch_detail(
                    initial_text, object_refs_text, None, request_id, has_mask=True
                ),
            )

        # ── Stage 4: non-official gpt-image-2 fallback ──
        print(
            "APIMart official failed twice; falling back to gpt-image-2 "
            f"(refs={len(image_urls)}, no mask present)"
        )
        try:
            return await retry_non_official_json_refs()
        except (httpx.HTTPStatusError, HTTPException) as fallback_exc:
            fallback_text = _exc_text(fallback_exc)
            fb_status     = _exc_status(fallback_exc, default=502)
            print(
                f"APIMart non-official gpt-image-2 fallback also failed: {_short(fallback_text, 160)}"
            )
            raise HTTPException(
                status_code=fb_status,
                detail=_build_mismatch_detail(
                    initial_text, object_refs_text, fallback_text, request_id, has_mask=False
                ),
            ) from fallback_exc

async def apimart_canvas_video(payload, provider, client_job_id=""):
    """APIMart async video generation: upload refs → submit → poll → return local URLs."""
    root = apimart_api_root(provider.get("base_url") or "https://api.apimart.ai")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {provider.get('name') or provider['id']} 的 API Key，请在 API 设置中填写。")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
        image_urls = []
        for ref in payload.images[:9]:
            if ref.url:
                local_path = output_file_from_url(ref.url)
                if local_path:
                    remote_url = await upload_to_apimart(client, root, api_key, local_path)
                    image_urls.append(remote_url)
        # 从 aspect_ratio 或 size 派生，只允许 APIMart 合法值
        raw_ar = payload.aspect_ratio or payload.size or "16:9"
        ar = raw_ar if raw_ar in APIMART_VIDEO_SIZES else "16:9"
        size = payload.size if payload.size in APIMART_VIDEO_SIZES else ar
        resolution = payload.resolution or "720p"
        selected_video_model = selected_model(payload.model, "")
        is_omni_flash_ext = selected_video_model.strip().lower() == "omni-flash-ext"
        body = {
            "prompt": payload.prompt,
            "model": selected_video_model,
            "size": size,
            "aspect_ratio": ar,
            "resolution": resolution,
        }
        if not (is_omni_flash_ext and payload.videos):
            body["duration"] = payload.duration
        if image_urls:
            body["image_urls"] = image_urls[:3] if is_omni_flash_ext else image_urls
        if payload.videos:
            body["video_urls"] = [v for v in payload.videos[:1 if is_omni_flash_ext else 3] if v]
        if payload.generate_audio:
            body["generate_audio"] = True
        if payload.return_last_frame:
            body["return_last_frame"] = True
        if payload.seed is not None:
            body["seed"] = payload.seed
        submit_resp = await client.post(f"{root}/v1/videos/generations", headers=headers, json=body)
        submit_resp.raise_for_status()
        raw = submit_resp.json()
        data_list = raw.get("data") if isinstance(raw.get("data"), list) else []
        task_id = data_list[0].get("task_id") if data_list and isinstance(data_list[0], dict) else None
        if not task_id:
            task_id = raw.get("task_id")
        if not task_id:
            raise HTTPException(status_code=502, detail=f"APIMart 视频提交未返回 task_id：{str(raw)[:300]}")
        result = await wait_for_apimart_task(client, root, api_key, task_id, timeout=AI_REQUEST_TIMEOUT, client_job_id=client_job_id)
        outer_data = result.get("data")
        result_data = (outer_data.get("result") or {}) if isinstance(outer_data, dict) else {}
        videos_raw = result_data.get("videos") or []
        urls = []
        for v in videos_raw:
            if isinstance(v, str):
                urls.append(v)
            elif isinstance(v, dict):
                u = v.get("url") or v.get("link") or v.get("download_url") or ""
                if u:
                    urls.append(u)
        if not urls:
            raise HTTPException(status_code=502, detail=f"APIMart 视频生成成功但没有返回视频 URL：{str(result)[:300]}")
        local_urls = [await save_remote_video_to_output(u) for u in urls]
        return local_urls, task_id, result

def parse_size_pair(size):
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", str(size or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))

GPT_IMAGE2_MAX_EDGE = 3840
GPT_IMAGE2_MAX_PIXELS = 8_294_400
GPT_IMAGE2_MIN_PIXELS = 655_360

def is_gpt_image_2_model(model):
    return str(model or "").strip().lower() == "gpt-image-2"

def normalize_gpt_image_2_size(size):
    width, height = parse_size_pair(size)
    if not width or not height:
        return size or "auto"
    if width == height and (width > 2048 or width * height > 4_194_304):
        return "3840x2160"
    ratio = width / height
    if ratio > 3:
        width = height * 3
    elif ratio < 1 / 3:
        height = width * 3
    scale = min(
        1.0,
        GPT_IMAGE2_MAX_EDGE / max(width, height),
        (GPT_IMAGE2_MAX_PIXELS / max(1, width * height)) ** 0.5,
    )
    width = max(16, int((width * scale) // 16) * 16)
    height = max(16, int((height * scale) // 16) * 16)
    if width * height < GPT_IMAGE2_MIN_PIXELS:
        grow = (GPT_IMAGE2_MIN_PIXELS / max(1, width * height)) ** 0.5
        width = int((width * grow + 15) // 16) * 16
        height = int((height * grow + 15) // 16) * 16
    return f"{width}x{height}"

async def generate_modelscope_provider_image(prompt, size, model, reference_images=None, provider=None):
    clean_token = MODELSCOPE_API_KEY.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="未配置 ModelScope API Key，请在 API 设置中填写。")
    width, height = parse_size_pair(size)
    refs = []
    for ref in (reference_images or [])[:4]:
        if not ref.get("url"):
            continue
        # 把参考图压到 1024px 长边以内，避免 base64 payload 过大导致 MS 内部任务失败
        refs.append(reference_to_data_url(ref, max_size=1024))
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true",
    }
    payload = {
        "model": selected_model(model, "Tongyi-MAI/Z-Image-Turbo"),
        "prompt": prompt.strip(),
    }
    if width and height:
        payload["width"] = width
        payload["height"] = height
        payload["size"] = f"{width}x{height}"
    if refs:
        payload["image_url"] = refs

    base_root = ((provider or {}).get("base_url") or MODELSCOPE_CHAT_BASE_URL).rstrip("/")
    api_root = base_root if base_root.endswith("/v1") else f"{base_root}/v1"
    async with httpx.AsyncClient(timeout=AI_REQUEST_TIMEOUT) as client:
        submit_res = await client.post(f"{api_root}/images/generations", headers=headers, json=payload)
        submit_res.raise_for_status()
        raw = submit_res.json()
        task_id = raw.get("task_id")
        if not task_id:
            try:
                return extract_image(raw), raw
            except HTTPException:
                raise HTTPException(status_code=502, detail=f"ModelScope 未返回 task_id：{raw}")

        deadline = time.monotonic() + AI_REQUEST_TIMEOUT
        last_payload = raw
        while time.monotonic() < deadline:
            await asyncio.sleep(IMAGE_POLL_INTERVAL)
            result = await client.get(
                f"{api_root}/tasks/{task_id}",
                headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
            )
            result.raise_for_status()
            data = result.json()
            last_payload = data
            status = str(data.get("task_status") or "").upper()
            if status == "SUCCEED":
                images = data.get("output_images") or []
                if not images:
                    raise HTTPException(status_code=502, detail=f"ModelScope 成功但没有返回图片：{data}")
                return {"type": "url", "value": images[0]}, data
            if status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}:
                detail = data.get("error_info") or data.get("message") or data.get("detail") or str(data)
                raise HTTPException(status_code=502, detail=f"ModelScope 任务失败：{detail}")
        raise HTTPException(status_code=504, detail=f"ModelScope 生图任务超时：{last_payload}")

async def generate_ai_image(prompt, size, quality, model, reference_images=None, provider_id="comfly"):
    provider = get_api_provider(provider_id)
    if provider["id"] == "modelscope":
        return await generate_modelscope_provider_image(prompt, size, model, reference_images, provider)
    if provider.get("protocol") == "apimart":
        images, raw = await generate_apimart_image(prompt, size, model, reference_images, provider)
        return images[0], raw
    is_gpt2 = is_gpt_image_2_model(model)
    if is_gpt_image_2_model(model):
        size = normalize_gpt_image_2_size(size)
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    gen_url = f"{base_url}/images/generations" if base_url.endswith("/v1") else f"{base_url}/v1/images/generations"
    edit_url = f"{base_url}/images/edits" if base_url.endswith("/v1") else f"{base_url}/v1/images/edits"
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    request_timeout = httpx.Timeout(connect=20.0, read=600.0, write=120.0, pool=20.0) if is_gpt2 else AI_REQUEST_TIMEOUT
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = None
        if is_gpt2:
            body = {"model": model, "prompt": prompt, "size": size}
            if quality:
                body["quality"] = quality
            if refs:
                body["image"] = [reference_to_data_url(ref, max_size=1536) for ref in refs[:4]]
            response = await client.post(gen_url, headers=api_headers(provider=provider), json=body)
        elif refs:
            # 1) 先用 multipart 提交到 /images/edits（OpenAI / Comfly 风格）
            files = []
            opened = []
            edit_failed_status = None
            edit_failed_text = ""
            try:
                for ref in refs[:4]:
                    path = output_file_from_url(ref.get("url", ""))
                    if not path:
                        continue
                    fh = open(path, "rb")
                    opened.append(fh)
                    files.append(("image", (os.path.basename(path), fh, content_type_for_path(path))))
                data = {"model": model, "prompt": prompt, "size": size, "quality": quality, "response_format": "url", "n": "1"}
                try:
                    response = await client.post(edit_url, headers=api_headers(json_body=False, provider=provider), data=data, files=files)
                    if response.status_code >= 400:
                        edit_failed_status = response.status_code
                        edit_failed_text = response.text[:500]
                        response = None
                except httpx.HTTPError as e:
                    edit_failed_status = -1
                    edit_failed_text = str(e)
                    response = None
            finally:
                for fh in opened:
                    fh.close()
            # 2) edits 失败 → 回退到 /images/generations + JSON image:[urls/base64]（grsai 风格）
            if response is None:
                print(f"/images/edits failed ({edit_failed_status}): {edit_failed_text[:200]} → 回退到 /images/generations + image:[] JSON")
                image_payload = [reference_to_data_url(ref, max_size=1536) for ref in refs[:4]]
                body = {
                    "model": model, "prompt": prompt, "size": size,
                    "quality": quality, "response_format": "url", "n": 1,
                    "image": image_payload,
                }
                response = await client.post(gen_url, headers=api_headers(provider=provider), json=body)
        else:
            response = await client.post(
                gen_url,
                headers=api_headers(provider=provider),
                json={"model": model, "prompt": prompt, "size": size, "quality": quality, "response_format": "url", "n": 1},
            )
        response.raise_for_status()
        raw = response.json()
        try:
            return extract_image(raw), raw
        except HTTPException:
            task_id = extract_task_id(raw)
            if not task_id:
                raise
        task_result = await wait_for_image_task(client, task_id, provider)
        return extract_image(task_result), task_result

# --- 路由接口 ---

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/download-output")
def download_output(url: str, name: str = ""):
    path = output_file_from_url(url)
    if not path:
        raise HTTPException(status_code=404, detail="文件不存在")
    filename = os.path.basename(name) if name else os.path.basename(path)
    return FileResponse(path, media_type=content_type_for_path(path), filename=filename)

@app.post("/api/open-output-folder")
def open_output_folder():
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(OUTPUT_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", OUTPUT_DIR])
        else:
            subprocess.Popen(["xdg-open", OUTPUT_DIR])
        return {"success": True, "path": OUTPUT_DIR}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开输出文件夹失败：{e}")

@app.post("/api/ai/upload")
async def upload_ai_reference(files: List[UploadFile] = File(...)):
    uploaded = []
    for file in files:
        content = await file.read()
        if not content:
            continue
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
            content_type = (file.content_type or "").lower()
            ext = ".jpg" if "jpeg" in content_type else ".webp" if "webp" in content_type else ".png"
        filename = f"ai_ref_{uuid.uuid4().hex[:12]}{ext}"
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "wb") as f:
            f.write(content)
        uploaded.append({"url": f"/output/{filename}", "name": file.filename or filename})
    return {"files": uploaded}

@app.get("/api/providers")
async def api_providers():
    return {"providers": [public_provider(p) for p in load_api_providers()]}

@app.put("/api/providers")
async def save_providers(payload: List[ApiProviderPayload]):
    providers = []
    env_updates = {}
    # 收集每个 item 的 primary 字段
    raw_primary_flags = [bool(getattr(item, "primary", False)) for item in payload]
    for item in payload:
        provider = normalize_provider(item.dict(exclude={"api_key"}))
        if provider["id"] == "modelscope":
            if MODELSCOPE_DEFAULT_IMAGE_MODEL not in provider["image_models"]:
                provider["image_models"] = [MODELSCOPE_DEFAULT_IMAGE_MODEL, *provider["image_models"]]
            if MODELSCOPE_DEFAULT_CHAT_MODEL not in provider["chat_models"]:
                provider["chat_models"] = [MODELSCOPE_DEFAULT_CHAT_MODEL, *provider["chat_models"]]
        if any(existing["id"] == provider["id"] for existing in providers):
            raise HTTPException(status_code=400, detail=f"API 平台 ID 重复：{provider['id']}")
        providers.append(provider)
        if item.api_key is not None:
            env_updates[provider_key_env(provider["id"])] = item.api_key.strip()
        if provider["id"] == "comfly":
            env_updates["COMFLY_BASE_URL"] = provider["base_url"]
        if provider["id"] == "modelscope":
            env_updates["MODELSCOPE_CHAT_MODELS"] = ",".join(provider["chat_models"])
    if not providers:
        raise HTTPException(status_code=400, detail="至少保留一个 API 平台")
    # 强制最多一个 primary（取最后被标记的；都没标记则保持原样不强制）
    primary_indices = [i for i, flag in enumerate(raw_primary_flags) if flag]
    if primary_indices:
        winner = primary_indices[-1]
        for i, p in enumerate(providers):
            p["primary"] = (i == winner)
    save_api_providers(providers)
    if env_updates:
        update_env_values(env_updates)
    return {"providers": [public_provider(p) for p in providers]}

# --- 在线生图 (COMFLY) ---

class TestConnectionPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""

@app.post("/api/providers/test-connection")
async def test_provider_connection(payload: TestConnectionPayload):
    """测试请求地址是否可用：调上游 /v1/models。验证通过时同时把模型清单按类别返回，避免再调一次拉取接口。"""
    base_url = (payload.base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    if not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail="请求地址必须以 http:// 或 https:// 开头")
    api_key = (payload.api_key or "").strip()
    if not api_key and payload.provider_id:
        api_key = os.getenv(provider_key_env(payload.provider_id), "")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写或保存 API Key")
    url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
        data = resp.json() if resp.text else {}
        items = (data.get("data") if isinstance(data, dict) else None) or []
        # 抽取模型 id
        ids = []
        for it in items:
            if isinstance(it, str):
                ids.append(it)
            elif isinstance(it, dict):
                mid = it.get("id") or it.get("name") or it.get("model")
                if mid:
                    ids.append(str(mid))
        ids = sorted(set(ids))
        grouped = group_model_ids(ids)
        return {"ok": True, "status": resp.status_code, "model_count": len(ids), "image_models": grouped["image"], "chat_models": grouped["chat"], "video_models": grouped["video"], "all": ids}
    except httpx.HTTPError as e:
        return {"ok": False, "status": 0, "message": str(e)[:300]}

@app.get("/api/providers/{provider_id}/fetch-models")
async def fetch_upstream_models(provider_id: str):
    """从上游 OpenAI 兼容接口拉取 /v1/models 列表，按名称智能分类为 image/chat/video。"""
    provider = get_api_provider(provider_id)
    base_url = (provider.get("base_url") or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider_id} 未配置 Base URL")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider_id} 未配置 API Key")
    url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=f"上游 /v1/models 失败：{resp.text[:300]}")
            raw = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"请求上游模型列表失败：{e}")
    # 兼容多种返回结构：{data:[{id:...},...]} 或 {models:[...]}
    items = raw.get("data") if isinstance(raw, dict) else None
    if not items and isinstance(raw, dict):
        items = raw.get("models") or raw.get("list") or []
    if not isinstance(items, list):
        items = []
    ids = []
    for it in items:
        if isinstance(it, str):
            ids.append(it)
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
            if mid:
                ids.append(str(mid))
    ids = sorted(set(ids))
    grouped = group_model_ids(ids)
    return {"total": len(ids), "image_models": grouped["image"], "chat_models": grouped["chat"], "video_models": grouped["video"], "all": ids}

# ─── APIMart Pricing Fetch ────────────────────────────────────────────────────

async def _fetch_apimart_pricing_raw(model_id: str) -> Optional[dict]:
    """Fetch raw pricing from APIMart public pricing endpoint. No auth required."""
    url = f"https://apimart.ai/api/pricing/model?model={urllib.parse.quote(model_id)}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None

def _parse_image_pricing(raw: dict, fallback_pricing: dict = None) -> Optional[dict]:
    """Convert resolution_prices → per_image rules (non-official image models)."""
    res_prices = raw.get("resolution_prices")
    model_price = raw.get("model_price")
    if not res_prices and not isinstance(model_price, (int, float)):
        return None
    key_map = {"1k": "1k", "2k": "2k", "4k": "4k"}
    rules_by_resolution: Dict[str, float] = {}
    for k, v in (res_prices or {}).items():
        if not isinstance(v, (int, float)):
            continue
        mapped = key_map.get(k.lower(), k.lower())
        rules_by_resolution[mapped] = float(v)
    if isinstance(model_price, (int, float)):
        fallback_rules = (fallback_pricing or {}).get("rules") or []
        for rule in fallback_rules:
            resolution = str(rule.get("resolution") or "").lower()
            if resolution and resolution not in rules_by_resolution:
                rules_by_resolution[resolution] = float(model_price)
        if not rules_by_resolution:
            rules_by_resolution["1k"] = float(model_price)
    rules = [
        {"resolution": resolution, "per_image": price}
        for resolution, price in rules_by_resolution.items()
    ]
    return {"currency": "USD", "bill_by": "per_image", "source": "apimart-pricing-api", "rules": rules} if rules else None

def _parse_official_image_pricing(raw: dict) -> Optional[dict]:
    """Convert size_quality_prices → per_image_size_quality rules (gpt-image-2-official)."""
    sq_prices = raw.get("size_quality_prices")
    if not sq_prices:
        return None
    rules = []
    for size_key, qualities in sq_prices.items():
        if "@" in size_key:
            parts = size_key.split("@", 1)
            size, resolution = parts[0], parts[1].lower()
        else:
            size, resolution = size_key, "1k"
        if not isinstance(qualities, dict):
            continue
        for quality, price in qualities.items():
            if isinstance(price, (int, float)):
                rules.append({"size": size, "resolution": resolution, "quality": quality, "per_image": float(price)})
    return {"currency": "USD", "bill_by": "per_image_size_quality", "source": "apimart-pricing-api", "rules": rules} if rules else None

def _parse_video_pricing(raw: dict) -> Optional[dict]:
    """Convert APIMart video pricing payloads into UI pricing rules."""
    duration_prices = raw.get("resolution_duration_prices")
    if duration_prices:
        input_prices: Dict[str, float] = {}
        for k, v in (raw.get("video_ref_per_second_prices") or {}).items():
            if isinstance(v, (int, float)):
                input_prices[str(k or "").lower()] = float(v)
        rules = []
        for k, v in duration_prices.items():
            if not isinstance(v, (int, float)):
                continue
            match = re.match(r"^(.+)-(\d+)s$", str(k or "").strip(), re.IGNORECASE)
            if not match:
                continue
            resolution = match.group(1).lower()
            duration = int(match.group(2))
            rule: Dict[str, Any] = {
                "resolution": resolution,
                "duration": duration,
                "per_video": float(v),
            }
            if resolution in input_prices:
                rule["input_per_second"] = input_prices[resolution]
            rules.append(rule)
        return {"currency": "USD", "bill_by": "per_video_duration", "source": "apimart-pricing-api", "rules": rules} if rules else None

    res_prices = raw.get("resolution_prices")
    if not res_prices:
        return None
    main_prices: Dict[str, float] = {}
    input_prices: Dict[str, float] = {}
    for k, v in res_prices.items():
        if not isinstance(v, (int, float)):
            continue
        k_lower = k.lower()
        if k_lower.endswith("-input"):
            input_prices[k_lower[:-len("-input")]] = float(v)
        else:
            main_prices[k_lower] = float(v)
    rules = []
    for res, price in main_prices.items():
        rule: Dict[str, Any] = {"resolution": res, "per_second": price}
        if res in input_prices:
            rule["input_per_second"] = input_prices[res]
        rules.append(rule)
    return {"currency": "USD", "bill_by": "per_second", "source": "apimart-pricing-api", "rules": rules} if rules else None

async def _get_model_pricing(model_id: str, fallback_pricing: dict) -> dict:
    """Fetch and cache APIMart live pricing for a single model. Falls back to fallback_pricing on any error."""
    cache = _load_catalog_cache()
    cache_key = f"pricing_{model_id}"
    cached = cache.get(cache_key)
    now = int(time.time())
    if (cached
            and cached.get("pricing_version") == PRICING_CACHE_VERSION
            and (now - cached.get("fetched_at", 0)) < PRICING_CACHE_TTL):
        return cached.get("pricing") or fallback_pricing
    raw = await _fetch_apimart_pricing_raw(model_id)
    pricing = None
    if raw:
        # APIMart returns { "success": true, "data": { ... } } — unwrap the inner payload.
        payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        billing_type = payload.get("billing_type", "")
        res_prices = payload.get("resolution_prices") or {}
        if billing_type == "size_quality":
            pricing = _parse_official_image_pricing(payload)
        elif (billing_type in ("per_second", "resolution_duration")
              or payload.get("resolution_duration_prices")
              or any(k.lower().endswith("-input") for k in res_prices)):
            pricing = _parse_video_pricing(payload)
        else:
            pricing = _parse_image_pricing(payload, fallback_pricing)
    if pricing:
        cache[cache_key] = {"fetched_at": now, "pricing_version": PRICING_CACHE_VERSION, "pricing": pricing}
        _save_catalog_cache(cache)
        return pricing
    return fallback_pricing

async def _enrich_models_pricing(models: list) -> list:
    """Replace each model's pricing with live APIMart pricing (cached PRICING_CACHE_TTL). Falls back to existing pricing."""
    result = []
    for m in models:
        fallback_pricing = m.get("pricing") or {}
        live_pricing = await _get_model_pricing(m["id"], fallback_pricing)
        result.append({**m, "pricing": live_pricing})
    return result

# ─── Model Catalog ────────────────────────────────────────────────────────────

_CATALOG_LOCK = Lock()

def _load_catalog_cache() -> Dict[str, Any]:
    if not os.path.exists(MODEL_CATALOG_CACHE_FILE):
        return {}
    try:
        with open(MODEL_CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_catalog_cache(data: Dict[str, Any]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with _CATALOG_LOCK:
        try:
            with open(MODEL_CATALOG_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存 catalog 缓存失败: {e}")

def _catalog_fallback(kind: str, provider_id: str) -> Dict[str, Any]:
    models = APIMART_FALLBACK_CATALOG.get(kind, [])
    return {
        "kind": kind,
        "provider_id": provider_id,
        "sync_status": "fallback",
        "last_checked": int(time.time()),
        "models": models,
    }

async def _try_fetch_apimart_models(provider: Dict[str, Any], kind: str) -> Optional[list]:
    """
    Attempt to pull model list from APIMart /v1/models.
    Returns list of model ids on success, None on failure.
    Pricing/params always come from APIMART_FALLBACK_CATALOG, not from this response.
    """
    root = apimart_api_root(provider.get("base_url") or "https://api.apimart.ai")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        return None
    url = f"{root}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        if resp.status_code >= 400:
            return None
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return None
        ids = []
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else (it if isinstance(it, str) else None)
            if mid:
                ids.append(str(mid))
        return ids
    except Exception:
        return None

_ALLOWED_IMAGE_IDS = {
    "gpt-image-2",
    "gpt-image-2-official",
    "gemini-3-pro-image-preview",
    "gemini-3-pro-image-preview-official",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-image-preview-official",
}
_ALLOWED_VIDEO_PREFIXES = ("doubao-seedance-2.0",)

def _filter_catalog_models(upstream_ids: Optional[list], kind: str) -> list:
    """
    Build model list from fallback catalog, optionally confirming existence via upstream_ids.
    Always returns fallback params since APIMart doesn't expose them via API.
    """
    fallback = APIMART_FALLBACK_CATALOG.get(kind, [])
    if upstream_ids is None:
        return fallback
    upstream_set = set(upstream_ids)
    filtered = [m for m in fallback if m["id"] in upstream_set]
    return filtered if filtered else fallback

async def _build_catalog(kind: str) -> Dict[str, Any]:
    """
    Build catalog response.

    Cache stores only upstream_ids + catalog_version, NOT the model list itself.
    Models are always rebuilt from current APIMART_FALLBACK_CATALOG so that
    changes to params/pricing take effect immediately on restart without needing
    a manual cache clear or a TTL expiry.

    Cache is invalidated when:
      - catalog_version in cache != MODEL_CATALOG_CACHE_VERSION
      - entry is older than MODEL_CATALOG_CACHE_TTL
    """
    if kind not in ("image", "video"):
        kind = "image"
    cache = _load_catalog_cache()
    cache_key = f"{kind}_apimart"
    cached_entry = cache.get(cache_key)
    now = int(time.time())

    upstream_ids: Optional[list] = None
    sync_status = "fallback"

    use_cache = (
        cached_entry is not None
        and cached_entry.get("catalog_version") == MODEL_CATALOG_CACHE_VERSION
        and (now - cached_entry.get("last_checked", 0)) < MODEL_CATALOG_CACHE_TTL
    )
    if use_cache:
        upstream_ids = cached_entry.get("upstream_ids")
        sync_status = cached_entry.get("sync_status", "fallback")
    else:
        providers = load_api_providers()
        apimart = next((p for p in providers if p["id"] == "apimart" and p.get("enabled", True)), None)
        if not apimart:
            result = _catalog_fallback(kind, "apimart")
            result["models"] = await _enrich_models_pricing(result["models"])
            return result

        upstream_ids = await _try_fetch_apimart_models(apimart, kind)
        sync_status = "ok" if upstream_ids is not None else "fallback"
        if sync_status == "ok":
            cache[cache_key] = {
                "catalog_version": MODEL_CATALOG_CACHE_VERSION,
                "last_checked": now,
                "sync_status": sync_status,
                "upstream_ids": upstream_ids,
            }
            _save_catalog_cache(cache)

    # Always rebuild from current APIMART_FALLBACK_CATALOG, then enrich with live APIMart pricing.
    models = _filter_catalog_models(upstream_ids, kind)
    models = await _enrich_models_pricing(models)
    return {
        "kind": kind,
        "provider_id": "apimart",
        "sync_status": sync_status,
        "last_checked": now,
        "models": models,
    }

@app.get("/api/model-catalog")
async def model_catalog(kind: str = "image"):
    """
    Return model catalog for 'image' or 'video'.
    Model IDs are confirmed via APIMart /v1/models when possible (upstream_ids cached 12 h).
    Params and pricing are always rebuilt from APIMART_FALLBACK_CATALOG on each request,
    so price/param changes in code take effect on the next server start without cache clear.
    """
    try:
        result = await _build_catalog(kind)
    except Exception as e:
        print(f"model-catalog build error: {e}")
        result = _catalog_fallback(kind, "apimart")
        result["sync_status"] = "failed"
    return result

# ─── FX Rate ──────────────────────────────────────────────────────────────────

def _load_fx_cache() -> Dict[str, Any]:
    if not os.path.exists(FX_RATE_CACHE_FILE):
        return {}
    try:
        with open(FX_RATE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_fx_cache(data: Dict[str, Any]):
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(FX_RATE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存汇率缓存失败: {e}")

async def _fetch_fx_rate_fresh() -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD", headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            return None
        data = resp.json()
        rate = (data.get("rates") or {}).get("CNY")
        return float(rate) if rate is not None else None
    except Exception:
        return None

@app.get("/api/fx-rate")
async def fx_rate_endpoint(base: str = "USD", target: str = "CNY"):
    """
    Return exchange rate for base → target (only USD→CNY is implemented).
    Rate is fetched from open.er-api.com and cached for 24 h in data/fx_rate_cache.json.
    Falls back to stale cache on fetch failure; returns rate: null if no cache exists.
    """
    cache = _load_fx_cache()
    cache_key = f"{base}_{target}"
    cached = cache.get(cache_key)
    now = int(time.time())
    if cached and (now - cached.get("fetched_at", 0)) < FX_RATE_TTL:
        return {"base": base, "target": target, "rate": cached["rate"],
                "source": cached.get("source", "open.er-api.com"), "updated_at": cached["fetched_at"], "stale": False}
    rate = await _fetch_fx_rate_fresh()
    if rate is not None:
        cache[cache_key] = {"rate": rate, "fetched_at": now, "source": "open.er-api.com"}
        _save_fx_cache(cache)
        return {"base": base, "target": target, "rate": rate, "source": "open.er-api.com", "updated_at": now, "stale": False}
    if cached:
        return {"base": base, "target": target, "rate": cached["rate"],
                "source": cached.get("source", "open.er-api.com"), "updated_at": cached["fetched_at"], "stale": True}
    return {"base": base, "target": target, "rate": None, "source": None, "updated_at": None, "stale": True}

# ─── Online Image ──────────────────────────────────────────────────────────────

@app.post("/api/online-image")
async def online_image(payload: OnlineImageRequest, request: Request):
    provider = get_api_provider(payload.provider_id)
    default_model = (provider.get("image_models") or [IMAGE_MODEL])[0]
    model = selected_model(payload.model, default_model)
    refs = [ref.dict() for ref in payload.reference_images if ref.url]
    try:
        if provider.get("protocol") == "apimart":
            # Returns list of image_data (one per n); n=1 for gpt-image-2, 1-4 for official.
            image_data_list, raw = await generate_apimart_image(
                payload.prompt, payload.size, model, refs, provider,
                resolution=payload.resolution,
                n=max(1, payload.n),
                quality=payload.quality or "auto",
                background=payload.background,
                moderation=payload.moderation,
                output_format=payload.output_format,
                output_compression=payload.output_compression,
                mask_url=payload.mask_url,
                client_job_id=request.headers.get("x-client-job-id", ""),
            )
            local_urls = [await save_ai_image_to_output(d, prefix="online_") for d in image_data_list]
        else:
            image_data, raw = await generate_ai_image(payload.prompt, payload.size, payload.quality, model, refs, provider["id"])
            local_urls = [await save_ai_image_to_output(image_data, prefix="online_")]
    except httpx.HTTPStatusError as exc:
        text = exc.response.text or ''
        # First, try structured parsing — catches APIMart safety/moderation rejections
        # before they fall through to the looser English keyword mapping below.
        parsed = None
        try:
            parsed = exc.response.json()
        except Exception:
            pass
        if isinstance(parsed, dict):
            err_node = parsed.get("error") or parsed.get("data") or parsed
            info = classify_apimart_failure(err_node, raw_response=parsed)
            if info.get("code") == "safety_blocked":
                raise HTTPException(status_code=exc.response.status_code, detail=info) from exc

        # 把上游英文错误转成中文友好提示
        friendly = None
        m = re.search(r"longest edge must be less than or equal to (\d+)", text)
        if m:
            limit = m.group(1)
            friendly = f"该模型不支持当前分辨率：最长边超过 {limit}px。请把图片分辨率调低（例如换到 2K 或更小），或更换支持高分辨率的模型。"
        elif "Invalid size" in text or "invalid_value" in text:
            friendly = f"该模型不支持当前尺寸：{payload.size}。请尝试更换分辨率或模型。"
        elif "rate limit" in text.lower() or "429" in text:
            friendly = "请求过于频繁，已被上游限流，请稍后再试。"
        elif "Unauthorized" in text or "401" in text:
            friendly = "API Key 无效或已过期，请到「API 设置」检查 Key。"
        elif "model_not_found" in text or "channel not found" in text:
            friendly = f"上游平台找不到模型「{model}」可用通道。可能该模型未在此账号开通，请换一个已开通的模型。"
        detail = friendly or f"上游生图接口错误：{text[:300]}"
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"请求上游生图接口失败：{exc}") from exc

    model_used = raw.get("_model_used") if isinstance(raw, dict) else None
    result_model = model_used or model
    result = {
        "prompt": payload.prompt,
        "images": local_urls,
        "timestamp": time.time(),
        "type": "online",
        "model": result_model,
        "requested_model": model if result_model != model else "",
        "provider_id": provider["id"],
        "provider_name": provider.get("name") or provider["id"],
        "params": {"provider_id": provider["id"], "model": result_model, "requested_model": model if result_model != model else "", "size": payload.size,
                   "resolution": payload.resolution, "quality": payload.quality, "reference_images": refs},
        "raw_usage": (raw.get("usage") or (raw.get("data") or {}).get("cost")) if isinstance(raw, dict) else None,
        "task_info": _apimart_task_info((raw.get("data") or {}).get("task_id") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else "", raw) if provider.get("protocol") == "apimart" and isinstance(raw, dict) else {},
    }
    save_to_history(result)
    if GLOBAL_LOOP:
        asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), GLOBAL_LOOP)
    return result

# --- Canvas Video ---

def video_output_urls(raw):
    data = raw.get("data") if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        data = {}
    urls = []
    output = data.get("output") or raw.get("output")
    outputs = data.get("outputs") or raw.get("outputs") or []
    if isinstance(output, str) and output:
        urls.append(output)
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, str) and item:
                urls.append(item)
            elif isinstance(item, dict):
                value = item.get("url") or item.get("output")
                if value:
                    urls.append(value)
    deduped = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped

def video_api_root(provider):
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if base_url.endswith("/v1") or base_url.endswith("/v2"):
        base_url = base_url.rsplit("/", 1)[0]
    return base_url

async def wait_for_video_task(client, provider, task_id):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    task_url = f"{base_url}/v2/videos/generations/{task_id}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        raw = response.json()
        last_payload = raw
        status = str(raw.get("status") or "").upper()
        if status == "SUCCESS":
            return raw
        if status in {"FAILURE", "FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT"}:
            reason = raw.get("fail_reason") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=f"视频生成任务失败：{reason}")
        delay = min(delay * 1.6, 12)
    raise HTTPException(status_code=504, detail=f"视频生成任务超时：{last_payload or task_id}")

@app.post("/api/canvas-video")
async def canvas_video(payload: CanvasVideoRequest, request: Request):
    provider = get_api_provider(payload.provider_id)
    if provider.get("protocol") == "apimart":
        local_urls, task_id, result = await apimart_canvas_video(payload, provider, client_job_id=request.headers.get("x-client-job-id", ""))
        _vid_model = selected_model(payload.model, "")
        save_to_history({
            "prompt": payload.prompt,
            "videos": local_urls,
            "timestamp": time.time(),
            "type": "video",
            "model": _vid_model,
            "provider_id": provider["id"],
            "provider_name": provider.get("name") or provider["id"],
            "params": {
                "provider_id": provider["id"], "model": _vid_model,
                "duration": payload.duration, "size": payload.size or payload.aspect_ratio,
                "resolution": payload.resolution, "generate_audio": payload.generate_audio,
                "return_last_frame": payload.return_last_frame,
            },
            "raw_usage": (result.get("data") or {}).get("cost") if isinstance(result, dict) else None,
        })
        return {"videos": local_urls, "task_id": task_id, "raw": result, "task_info": _apimart_task_info(task_id, result) if isinstance(result, dict) else {}}
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {provider.get('name') or provider['id']} 的 API Key，请在 API 设置中填写。")
    submit_url = f"{base_url}/v2/videos/generations"
    image_payload = []
    for ref in payload.images[:4]:
        if ref.url:
            image_payload.append(reference_to_data_url(ref.dict(), max_size=1536))
    body = {
        "prompt": payload.prompt,
        "model": selected_model(payload.model, "veo3-fast"),
        "duration": payload.duration,
        "watermark": payload.watermark,
    }
    if payload.aspect_ratio:
        body["aspect_ratio"] = payload.aspect_ratio
        body["ratio"] = payload.aspect_ratio
    if payload.size:
        body["size"] = payload.size
    if payload.resolution:
        body["resolution"] = payload.resolution
    if image_payload:
        body["images"] = image_payload
    if payload.videos:
        body["videos"] = [v for v in payload.videos if v]
    if payload.enhance_prompt:
        body["enhance_prompt"] = True
    if payload.enable_upsample:
        body["enable_upsample"] = True
    if payload.seed is not None:
        body["seed"] = payload.seed
    if payload.camerafixed:
        body["camerafixed"] = True
    if payload.return_last_frame:
        body["return_last_frame"] = True
    if payload.generate_audio:
        body["generate_audio"] = True
    try:
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            response = await client.post(submit_url, headers=api_headers(provider=provider), json=body)
            response.raise_for_status()
            raw = response.json()
            task_id = raw.get("task_id") or raw.get("id")
            result = raw
            if task_id and not video_output_urls(raw):
                result = await wait_for_video_task(client, provider, task_id)
            urls = video_output_urls(result)
            if not urls:
                raise HTTPException(status_code=502, detail=f"视频生成成功但没有返回视频：{result}")
            local_urls = [await save_remote_video_to_output(url) for url in urls]
            _vid_model = selected_model(payload.model, "veo3-fast")
            save_to_history({
                "prompt": payload.prompt,
                "videos": local_urls,
                "timestamp": time.time(),
                "type": "video",
                "model": _vid_model,
                "provider_id": provider["id"],
                "provider_name": provider.get("name") or provider["id"],
                "params": {
                    "provider_id": provider["id"],
                    "model": _vid_model,
                    "duration": payload.duration,
                    "aspect_ratio": payload.aspect_ratio,
                },
            })
            return {"videos": local_urls, "task_id": task_id, "raw": result}
    except httpx.HTTPStatusError as exc:
        text = exc.response.text
        requested_model = body.get("model", "")
        provider_name = provider.get('name') or provider['id']
        # 1) 模型名不在上游支持范围 → 从错误信息里抽取合法列表展示
        valid_models_match = re.search(r"not in\s*\[([^\]]+)\]", text)
        if valid_models_match:
            valid_models = [m.strip() for m in valid_models_match.group(1).split(",") if m.strip()]
            sample = valid_models[:30]
            more = f"（共 {len(valid_models)} 个，仅显示前 {len(sample)} 个）" if len(valid_models) > len(sample) else ""
            hint = (
                f"上游「{provider_name}」不识别模型「{requested_model}」。\n\n"
                f"上游支持的视频模型清单{more}：\n  {', '.join(sample)}\n\n"
                f"请到「API 设置」里把视频模型改成上面列表中的一个。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        # 2) 模型名合法但账号没开通通道
        if "channel not found" in text or "model_not_found" in text:
            hint = (
                f"上游「{provider_name}」识别了模型「{requested_model}」，但你的 API Key 账号下**没有该模型的可用通道**。\n\n"
                f"原因：你的账号没开通这个模型的访问权限（付费/订阅相关）。\n\n"
                f"解决方法：\n"
                f"  1. 登录 {provider.get('base_url') or '上游平台'} 控制台，开通该模型 / 充值；\n"
                f"  2. 或在「API 设置」里把视频模型改成你账号已开通的型号（如 veo3-fast / veo2-fast / sora-2 等）。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        raise HTTPException(status_code=exc.response.status_code, detail=f"上游视频接口错误：{text}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"请求上游视频接口失败：{exc}") from exc


# --- Canvas V2 保存与恢复 ---

@app.get("/api/canvases-v2")
async def canvases_v2():
    return {"canvases": list_canvases_v2()}

@app.get("/api/canvases-v2/trash")
async def canvases_v2_trash():
    return {"canvases": list_canvases_v2(include_deleted=True), "retention_days": 30}

@app.post("/api/canvases-v2")
async def create_canvas_v2(payload: CanvasCreateRequest):
    return {"canvas": new_canvas_v2(payload.title or "Moist Canvas")}

@app.get("/api/canvases-v2/{canvas_id}")
async def get_canvas_v2(canvas_id: str):
    return load_canvas_v2_data(canvas_id)

@app.put("/api/canvases-v2/{canvas_id}")
async def save_canvas_v2(canvas_id: str, req: CanvasV2SaveRequest):
    # Refuse to overwrite a trashed canvas (resurrection should go through /restore).
    path = canvas_v2_path(canvas_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("deleted_at"):
                raise HTTPException(status_code=404, detail="画布已在回收站")
        except HTTPException:
            raise
        except Exception:
            pass  # corrupted existing file — fall through and overwrite
    data = req.dict()
    data["id"] = canvas_id
    data.pop("deleted_at", None)
    try:
        saved = save_canvas_v2_data(data)
        return {"success": True, "canvas": canvas_v2_record(saved)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Save canvas_v2 failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/canvases-v2/{canvas_id}")
async def trash_canvas_v2(canvas_id: str):
    data = load_canvas_v2_data(canvas_id, include_deleted=True)
    if not data.get("deleted_at"):
        data["deleted_at"] = now_ms()
        write_canvas_v2_raw(canvas_id, data)
    return {"ok": True}

@app.post("/api/canvases-v2/{canvas_id}/restore")
async def restore_canvas_v2(canvas_id: str):
    data = load_canvas_v2_data(canvas_id, include_deleted=True)
    if data.get("deleted_at"):
        data.pop("deleted_at", None)
        write_canvas_v2_raw(canvas_id, data)
    return {"ok": True, "canvas": canvas_v2_record(data)}

@app.delete("/api/canvases-v2/{canvas_id}/purge")
async def purge_canvas_v2(canvas_id: str):
    path = canvas_v2_path(canvas_id)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}

# --- 历史记录 ---

@app.get("/api/history")
async def get_history_api(type: str = None):
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if type:
                    data = [item for item in data if item.get("type", "zimage") == type]
                data = [item for item in data if
                        (item.get("images") and len(item["images"]) > 0) or
                        (item.get("videos") and len(item["videos"]) > 0)]

                def sort_key(item):
                    ts = item.get("timestamp", 0)
                    if isinstance(ts, (int, float)):
                        return float(ts)
                    return 0

                data.sort(key=sort_key, reverse=True)
                return data
        except Exception as e:
            print(f"读取历史文件失败: {e}")
            return []
    return []

@app.post("/api/history/delete")
async def delete_history(req: DeleteHistoryRequest):
    if not os.path.exists(HISTORY_FILE):
        return {"success": False, "message": "History file not found"}
    try:
        with HISTORY_LOCK:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
            target_record = None
            new_history = []
            for item in history:
                is_match = False
                item_ts = item.get("timestamp", 0)
                if isinstance(req.timestamp, (int, float)) and isinstance(item_ts, (int, float)):
                    if abs(float(item_ts) - float(req.timestamp)) < 0.001:
                        is_match = True
                elif str(item_ts) == str(req.timestamp):
                    is_match = True
                if is_match:
                    target_record = item
                else:
                    new_history.append(item)
            if target_record:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(new_history, f, ensure_ascii=False, indent=4)

        if target_record:
            media_urls = (target_record.get("images") or []) + (target_record.get("videos") or [])
            for media_url in media_urls:
                if media_url.startswith("/output/"):
                    filename = media_url.split("/")[-1]
                    file_path = os.path.join(OUTPUT_DIR, filename)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print(f"Failed to delete file {file_path}: {e}")
            return {"success": True}
        else:
            return {"success": False, "message": "Record not found"}
    except Exception as e:
        print(f"Delete history error: {e}")
        return {"success": False, "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# IN-APP AUTO-UPDATE (GitHub Releases)
# ═══════════════════════════════════════════════════════════════════════════
# Strategy: the running app asks GitHub for the latest release tag, compares it
# to APP_VERSION, and (on user confirmation) downloads the release source zip,
# overlays ONLY the code files onto the install dir, and reinstalls deps if
# requirements.txt changed. User data is never touched — see _skip_path_for_update.
#
# Why this is safe by construction: the GitHub source archive is built from the
# git tree, and .gitignore excludes every user-data path (API/.env, output/,
# runtime/, history.json, data/canvases_v2/, data/*_cache.json), so those files
# physically cannot be in the archive. _skip_path_for_update is a second guard.

def _parse_version(tag):
    """'v1.2.3' / '1.2.3' → (1, 2, 3). Non-numeric suffixes are dropped so a
    pre-release like '1.2.0-beta' compares as (1, 2, 0). Returns () on garbage."""
    if not tag:
        return ()
    s = str(tag).strip().lstrip("vV").strip()
    parts = []
    for chunk in s.split("."):
        m = re.match(r"\d+", chunk)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts)


def _is_newer(latest_tag, current_version):
    """True when latest_tag represents a strictly newer version than current."""
    lv = _parse_version(latest_tag)
    cv = _parse_version(current_version)
    if not lv:
        return False
    # Pad to equal length so (1,2) vs (1,2,0) compare equal.
    n = max(len(lv), len(cv))
    lv += (0,) * (n - len(lv))
    cv += (0,) * (n - len(cv))
    return lv > cv


# Top-level path segments that are PURE user/runtime state and must never be
# overwritten or created from an update archive. Mirrors .gitignore + the
# build_clean_zip forbidden list. Note: the entire data/ dir is protected —
# api_providers.json is seeded on fresh install but becomes user-owned at
# runtime, and merge_default_api_providers() re-applies code defaults anyway.
_UPDATE_PROTECTED_TOP = {"output", "runtime", "API", ".git", "__pycache__", "dist", "data", ".venv", "venv", "env"}
_UPDATE_PROTECTED_FILES = {"history.json", ".env", "server.err.log", "server.out.log"}


def _skip_path_for_update(rel_path):
    """rel_path is POSIX-style relative to the install root. True → do not write."""
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel:
        return True
    first = rel.split("/", 1)[0]
    if first in _UPDATE_PROTECTED_TOP:
        return True
    name = rel.rsplit("/", 1)[-1]
    if name in _UPDATE_PROTECTED_FILES:
        return True
    if name.endswith((".log", ".pyc", ".pyo", ".bat")):
        return True
    return False


def _update_configured():
    """False when GITHUB_REPO is still the placeholder."""
    repo = (GITHUB_REPO or "").strip()
    return bool(repo) and "your-github-username" not in repo and "/" in repo


async def _github_latest_release():
    """Fetch the latest published release. Returns the parsed dict or raises
    HTTPException with a friendly message."""
    if not _update_configured():
        raise HTTPException(status_code=400, detail="尚未配置 GitHub 仓库（请设置 GITHUB_REPO 或 MOISTCANVAS_REPO 环境变量）。")
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MoistCanvas-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 GitHub：{e}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="该仓库还没有发布任何 Release。")
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise HTTPException(status_code=429, detail="GitHub API 速率限制，请稍后再试（或配置 GITHUB_TOKEN）。")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub 返回 HTTP {resp.status_code}")
    return resp.json()


def _release_summary(release):
    tag = release.get("tag_name") or ""
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "name": release.get("name") or tag,
        "notes": release.get("body") or "",
        "published_at": release.get("published_at") or "",
        "html_url": release.get("html_url") or "",
        "zipball_url": release.get("zipball_url") or "",
    }


def _default_update_status():
    return {
        "status": "none",
        "current": APP_VERSION,
        "latest": "",
        "tag": "",
        "message": "",
        "html_url": "",
        "time": "",
    }


def _public_update_status(data=None):
    status = _default_update_status()
    if isinstance(data, dict):
        for key in status.keys():
            if key in data:
                status[key] = str(data.get(key) or "")
    if not status["current"]:
        status["current"] = APP_VERSION
    return status


@app.get("/api/app-version")
async def app_version():
    return {
        "version": APP_VERSION,
        "repo": GITHUB_REPO,
        "configured": _update_configured(),
    }


@app.get("/api/update-status")
async def update_status():
    """Expose bounded startup-update status for the canvas gate notice."""
    try:
        with open(UPDATE_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = None
    return _public_update_status(data)


@app.get("/api/check-update")
async def check_update():
    """Compare APP_VERSION against the latest GitHub release."""
    release = await _github_latest_release()
    info = _release_summary(release)
    has_update = _is_newer(info["tag"], APP_VERSION)
    return {
        "current": APP_VERSION,
        "latest": info["version"],
        "tag": info["tag"],
        "has_update": has_update,
        "name": info["name"],
        "notes": info["notes"],
        "published_at": info["published_at"],
        "html_url": info["html_url"],
    }


def _find_extracted_root(extract_dir):
    """GitHub zipballs wrap everything in a single '<owner>-<repo>-<sha>/' dir.
    Return the dir that actually contains main.py."""
    if os.path.exists(os.path.join(extract_dir, "main.py")):
        return extract_dir
    entries = [os.path.join(extract_dir, n) for n in os.listdir(extract_dir)]
    dirs = [p for p in entries if os.path.isdir(p)]
    if len(dirs) == 1 and os.path.exists(os.path.join(dirs[0], "main.py")):
        return dirs[0]
    # Fallback: any nested dir with main.py
    for p in dirs:
        if os.path.exists(os.path.join(p, "main.py")):
            return p
    raise HTTPException(status_code=502, detail="更新包结构异常：未找到 main.py。")


def _overlay_code_files(src_root):
    """Copy every non-protected file from src_root onto BASE_DIR, atomically and
    with rollback, so a mid-way failure (disk full, permission error, a file
    locked by another process) can't leave a half-new / half-old install.

    Per-file write is atomic: the new bytes are streamed into a temp file in the
    SAME directory, then `os.replace()` swaps it into place in one step. So the
    real destination is only ever the intact OLD file or the complete NEW file —
    never a truncated/partial one, even if the copy fails halfway. Before each
    swap the existing file is snapshotted into UPDATE_DIR/backup; if any later
    file fails, every already-swapped file is restored and every newly-created
    one removed (newest first), then we raise. Returns the relative paths written."""
    backup_root = os.path.join(UPDATE_DIR, "backup")
    if os.path.exists(backup_root):
        shutil.rmtree(backup_root, ignore_errors=True)
    os.makedirs(backup_root, exist_ok=True)

    written = []
    # Each entry: (dst_file, backup_path_or_None, existed_before) — only files
    # whose atomic swap fully COMPLETED are recorded here.
    done = []
    try:
        for dirpath, dirnames, filenames in os.walk(src_root):
            # Prune protected directories so we never descend into them.
            rel_dir = os.path.relpath(dirpath, src_root).replace("\\", "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            dirnames[:] = [
                d for d in dirnames
                if not _skip_path_for_update((rel_dir + "/" + d) if rel_dir else d)
            ]
            for fname in filenames:
                rel = (rel_dir + "/" + fname) if rel_dir else fname
                if _skip_path_for_update(rel):
                    continue
                src_file = os.path.join(dirpath, fname)
                dst_file = os.path.join(BASE_DIR, rel.replace("/", os.sep))
                dst_dir = os.path.dirname(dst_file)
                os.makedirs(dst_dir, exist_ok=True)
                existed = os.path.exists(dst_file)

                # Snapshot the old file BEFORE touching the destination.
                backup_path = None
                if existed:
                    backup_path = os.path.join(backup_root, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    shutil.copy2(dst_file, backup_path)

                # Stage into a temp file in the same dir, then atomically swap.
                # A failure here only dirties the temp; dst_file is untouched.
                tmp_fd, tmp_path = tempfile.mkstemp(dir=dst_dir, prefix=".upd_", suffix=".tmp")
                os.close(tmp_fd)
                try:
                    shutil.copy2(src_file, tmp_path)
                    os.replace(tmp_path, dst_file)  # atomic on same filesystem
                except Exception:
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    raise

                done.append((dst_file, backup_path, existed))
                written.append(rel)
        return written
    except Exception as e:
        # Roll back fully-completed swaps, newest first, to restore prior state.
        for dst_file, backup_path, existed in reversed(done):
            try:
                if existed and backup_path and os.path.exists(backup_path):
                    os.replace(backup_path, dst_file)
                elif not existed and os.path.exists(dst_file):
                    os.remove(dst_file)
            except Exception:
                pass  # best-effort; keep restoring the rest
        raise HTTPException(
            status_code=500,
            detail=f"更新写入失败，已回滚到旧版本（未改动依赖以外的任何东西）：{e}",
        )


def _read_file_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""


def _is_loopback_ip(ip):
    """True if ip is a loopback address (127.0.0.0/8 or ::1, incl. IPv4-mapped).

    Used on the REAL connection peer (request.client.host), which — unlike the
    Host header — the client cannot spoof."""
    ip = (ip or "").strip().strip("[]")
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _assert_same_origin(request):
    """Locality + CSRF guard for the powerful update / restart endpoints.

    Two independent checks:

      1. LOCALITY — the real TCP peer (request.client.host) must be loopback.
         This is the actual connection address from the ASGI scope; unlike the
         Host / Origin / Referer headers it cannot be forged by the client. The
         server binds 0.0.0.0, so without this a LAN machine could call these
         endpoints while spoofing `Host: localhost:6767`. Gating on the peer IP
         (not the Host header) closes that bypass — and it must gate ALL calls,
         because the Origin check below is itself defeatable by a non-browser
         client that simply sends a matching Origin header.

      2. CSRF — if a browser supplied Origin/Referer, it must be same-origin as
         Host. A malicious page on the *local* machine connects from loopback
         too (passing check 1), so this is what blocks drive-by web CSRF.

    A local non-browser client (curl on this machine, no Origin) passes both.
    Trade-off: update / restart cannot be triggered from another machine's
    browser. That is intentional — these replace code and restart the server,
    so we keep them strictly local.
    """
    peer = (getattr(request, "client", None).host if getattr(request, "client", None) else "") or ""
    if not _is_loopback_ip(peer):
        raise HTTPException(status_code=403, detail="更新 / 重启接口只能从本机访问。")

    origin = request.headers.get("origin") or ""
    referer = request.headers.get("referer") or ""
    src_netloc = ""
    if origin:
        src_netloc = urllib.parse.urlparse(origin).netloc
    elif referer:
        src_netloc = urllib.parse.urlparse(referer).netloc
    if src_netloc:
        host = (request.headers.get("host") or "").lower()
        if src_netloc.lower() != host:
            raise HTTPException(
                status_code=403,
                detail="跨站请求被拒绝：更新 / 重启接口仅接受本应用页面发起的请求。",
            )


def _safe_extract_zip(zip_path, dest_dir):
    """Extract a zip with zip-slip protection and size/count ceilings.

    Rejects absolute paths and '..' traversal, and aborts before writing if the
    archive exceeds MAX_UPDATE_* limits — so a malformed/oversized release can't
    escape dest_dir or fill the disk."""
    dest_root = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_UPDATE_FILE_COUNT:
            raise HTTPException(status_code=502, detail="更新包文件数量异常，已取消。")
        total = 0
        for info in infos:
            name = info.filename
            # Normalise + reject traversal / absolute paths (zip-slip).
            if name.startswith("/") or name.startswith("\\") or ".." in name.replace("\\", "/").split("/"):
                raise HTTPException(status_code=502, detail=f"更新包包含非法路径，已取消：{name}")
            if info.file_size > MAX_UPDATE_FILE_BYTES:
                raise HTTPException(status_code=502, detail="更新包含超大文件，已取消。")
            total += info.file_size
            if total > MAX_UPDATE_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=502, detail="更新包解压后体积超限，已取消。")
        # Validation passed → extract member-by-member, double-checking the
        # resolved destination stays inside dest_root.
        for info in infos:
            target = os.path.abspath(os.path.join(dest_root, info.filename))
            if os.path.commonpath([dest_root, target]) != dest_root:
                raise HTTPException(status_code=502, detail="更新包路径越界，已取消。")
            zf.extract(info, dest_root)


def _pip_install_requirements(requirements_path):
    """Run pip install -r against the running (portable) interpreter. Returns
    (ok: bool, error_tail: str)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", requirements_path,
             "--no-warn-script-location"],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout or "")[-500:]
    except Exception as e:
        return False, str(e)


def _install_deps_then_overlay(src_root):
    """Given an extracted release root, install changed deps FIRST, then overlay
    code — never the reverse. Raises HTTPException (and overlays NOTHING) when
    dependency installation fails, so a failed update can never leave the install
    in a "new code + old deps" state. Returns (written, reqs_changed, deps_done).

    This is the safety-critical ordering from the review; it's factored out so it
    can be unit-tested without the network/download path."""
    old_reqs = _read_file_bytes(os.path.join(BASE_DIR, "requirements.txt"))
    new_reqs = _read_file_bytes(os.path.join(src_root, "requirements.txt"))
    reqs_changed = bool(new_reqs) and (new_reqs.strip() != old_reqs.strip())

    # STEP 1 — dependencies, from the STAGED requirements (not yet copied in).
    deps_reinstalled = False
    if reqs_changed:
        ok, deps_error = _pip_install_requirements(os.path.join(src_root, "requirements.txt"))
        if not ok:
            raise HTTPException(
                status_code=502,
                detail=("依赖安装失败，已取消本次更新（未改动任何代码，当前版本仍可正常使用）。"
                        "请检查网络后重试，或手动运行 安装依赖.bat。\n" + (deps_error or "")),
            )
        deps_reinstalled = True

    # STEP 2 — only now is it safe to swap code in.
    written = _overlay_code_files(src_root)
    return written, reqs_changed, deps_reinstalled


@app.post("/api/apply-update")
async def apply_update(request: Request):
    """Download the latest release source, then — in this order — install any
    changed dependencies FIRST, and only overlay code if that succeeds. Never
    touches user data.

    Ordering rationale: the dangerous failure is "new code + old deps", which can
    crash on the next launch. By installing deps from the staged package before
    swapping any code, a pip failure aborts the whole update with the install
    left untouched (old code + old requirements still on disk, still runnable),
    and the frontend never offers a restart."""
    # CSRF guard — block cross-site web pages from triggering an update.
    _assert_same_origin(request)
    # Single-flight guard: reject a second concurrent update.
    with UPDATE_LOCK:
        if _UPDATE_IN_PROGRESS["value"]:
            raise HTTPException(status_code=409, detail="已有更新正在进行中。")
        _UPDATE_IN_PROGRESS["value"] = True
    try:
        release = await _github_latest_release()
        info = _release_summary(release)
        if not _is_newer(info["tag"], APP_VERSION):
            return {"ok": True, "updated": False, "message": "已是最新版本。", "current": APP_VERSION}

        zip_url = info["zipball_url"]
        if not zip_url:
            raise HTTPException(status_code=502, detail="Release 缺少源码下载地址。")

        # Fresh temp workspace.
        if os.path.exists(UPDATE_DIR):
            shutil.rmtree(UPDATE_DIR, ignore_errors=True)
        os.makedirs(UPDATE_DIR, exist_ok=True)
        zip_path = os.path.join(UPDATE_DIR, "update.zip")
        extract_dir = os.path.join(UPDATE_DIR, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        headers = {"User-Agent": "MoistCanvas-Updater", "Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Download the source zipball with a hard size cap (abort mid-stream if
        # it blows past MAX_UPDATE_DOWNLOAD_BYTES).
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0), follow_redirects=True) as client:
                async with client.stream("GET", zip_url, headers=headers) as resp:
                    resp.raise_for_status()
                    clen = resp.headers.get("content-length")
                    if clen and int(clen) > MAX_UPDATE_DOWNLOAD_BYTES:
                        raise HTTPException(status_code=502, detail="更新包过大，已取消下载。")
                    downloaded = 0
                    with open(zip_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            downloaded += len(chunk)
                            if downloaded > MAX_UPDATE_DOWNLOAD_BYTES:
                                raise HTTPException(status_code=502, detail="更新包过大，已取消下载。")
                            f.write(chunk)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"下载更新包失败：{e}")

        # Extract with zip-slip + size/count protection.
        try:
            _safe_extract_zip(zip_path, extract_dir)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"解压更新包失败：{e}")

        src_root = _find_extracted_root(extract_dir)

        # Deps-first, then code-overlay (raises and overlays nothing if pip
        # fails — see _install_deps_then_overlay).
        written, reqs_changed, deps_reinstalled = _install_deps_then_overlay(src_root)

        return {
            "ok": True,
            "updated": True,
            "from": APP_VERSION,
            "to": info["version"],
            "files_written": len(written),
            "deps_changed": reqs_changed,
            "deps_reinstalled": deps_reinstalled,
            "restart_required": True,
        }
    finally:
        # Always clean the temp workspace and release the single-flight guard,
        # whether we succeeded or aborted (e.g. on a deps-install failure).
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
        with UPDATE_LOCK:
            _UPDATE_IN_PROGRESS["value"] = False


@app.post("/api/restart-app")
async def restart_app(request: Request):
    """Relaunch the run script in a fresh window, then exit this process. A short
    delay in the relauncher lets the app port free up before the new server binds.
    Windows-only auto-restart; other platforms just report unsupported so the
    user restarts manually."""
    # CSRF guard — a web page must not be able to kill/restart the local server.
    _assert_same_origin(request)
    if not sys.platform.startswith("win"):
        raise HTTPException(status_code=400, detail="自动重启仅支持 Windows，请手动重启。")

    # Find the run .bat by its marker (same heuristic build_clean_zip uses).
    run_bat = None
    for name in os.listdir(BASE_DIR):
        if name.lower().endswith(".bat"):
            try:
                with open(os.path.join(BASE_DIR, name), "r", encoding="utf-8", errors="ignore") as f:
                    if "MoistCanvas - run" in f.read():
                        run_bat = name
                        break
            except Exception:
                continue
    if not run_bat:
        raise HTTPException(status_code=404, detail="未找到启动脚本，请手动重启。")

    relauncher = os.path.join(UPDATE_DIR, "_relaunch.bat")
    os.makedirs(UPDATE_DIR, exist_ok=True)
    with open(relauncher, "w", encoding="utf-8") as f:
        # chcp 65001 switches the console to UTF-8 so the (possibly non-ASCII)
        # run-script path is interpreted correctly regardless of system locale.
        f.write(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'cd /d "{BASE_DIR}"\r\n'
            f'start "" "{os.path.join(BASE_DIR, run_bat)}"\r\n'
        )

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    try:
        subprocess.Popen(
            ["cmd", "/c", relauncher],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重启失败：{e}")

    # Give the HTTP response a beat to flush, then hard-exit so the port frees.
    def _bye():
        time.sleep(1.0)
        os._exit(0)
    import threading
    threading.Thread(target=_bye, daemon=True).start()
    return {"ok": True, "message": "正在重启，请稍候几秒后刷新页面。"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)
