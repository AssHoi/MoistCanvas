import sys
import unittest
import asyncio
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


class ApimartNanoBananaCatalogTests(unittest.TestCase):
    def test_image_catalog_keeps_curated_fallback_models_when_upstream_cache_omits_one(self):
        fallback_ids = [item["id"] for item in main.APIMART_FALLBACK_CATALOG["image"]]
        upstream_ids = [model_id for model_id in fallback_ids if model_id != "gpt-image-2"]

        filtered_ids = [
            item["id"]
            for item in main._filter_catalog_models(upstream_ids, "image")
        ]

        self.assertIn("gpt-image-2", filtered_ids)
        self.assertEqual(filtered_ids, fallback_ids)

    def test_video_catalog_keeps_curated_fallback_models_when_upstream_cache_omits_one(self):
        fallback_ids = [item["id"] for item in main.APIMART_FALLBACK_CATALOG["video"]]
        upstream_ids = [model_id for model_id in fallback_ids if model_id != "Omni-Flash-Ext"]

        filtered_ids = [
            item["id"]
            for item in main._filter_catalog_models(upstream_ids, "video")
        ]

        self.assertIn("Omni-Flash-Ext", filtered_ids)
        self.assertEqual(filtered_ids, fallback_ids)

    def test_image_pricing_uses_model_price_for_missing_resolution_tiers(self):
        fallback = main._img_pricing([
            {"resolution": "1k", "per_image": None},
            {"resolution": "2k", "per_image": None},
            {"resolution": "4k", "per_image": None},
        ])
        raw = {
            "model_name": "gemini-3-pro-image-preview",
            "model_price": 0.05,
            "resolution_prices": {"4K": 0.0625},
        }

        pricing = main._parse_image_pricing(raw, fallback)

        self.assertIsNotNone(pricing)
        rules = {rule["resolution"]: rule["per_image"] for rule in pricing["rules"]}
        self.assertEqual(rules, {"1k": 0.05, "2k": 0.05, "4k": 0.0625})

    def test_nano_banana_models_are_in_fallback_catalog(self):
        image_models = {item["id"]: item for item in main.APIMART_FALLBACK_CATALOG["image"]}

        expected = {
            "gemini-3-pro-image-preview": "Nano Banana Pro",
            "gemini-3-pro-image-preview-official": "Nano Banana Pro Official",
            "gemini-3.1-flash-image-preview": "Nano Banana 2",
            "gemini-3.1-flash-image-preview-official": "Nano Banana 2 Official",
        }
        for model_id, label in expected.items():
            self.assertIn(model_id, image_models)
            self.assertEqual(image_models[model_id]["label"], label)
            self.assertIn(model_id, main._ALLOWED_IMAGE_IDS)

    def test_flash_models_include_half_k_but_no_google_search_params(self):
        image_models = {item["id"]: item for item in main.APIMART_FALLBACK_CATALOG["image"]}

        for model_id in (
            "gemini-3.1-flash-image-preview",
            "gemini-3.1-flash-image-preview-official",
        ):
            params = image_models[model_id]["params"]
            self.assertEqual(params["resolution"]["options"], ["0.5K", "1K", "2K", "4K"])
            self.assertNotIn("google_search", params)
            self.assertNotIn("google_image_search", params)
            self.assertNotIn("official_fallback", params)

    def test_gpt_image_2_official_fallback_catalog_does_not_offer_background(self):
        image_models = {item["id"]: item for item in main.APIMART_FALLBACK_CATALOG["image"]}

        params = image_models["gpt-image-2-official"]["params"]
        serialized_params = json.dumps(params, ensure_ascii=False)

        self.assertNotIn("background", params)
        self.assertNotIn("\u80cc\u666f\u6a21\u5f0f", serialized_params)
        self.assertNotIn("\u900f\u660e", serialized_params)

    def test_gpt_image_2_official_payload_does_not_forward_background(self):
        captured = {}

        class FakeResponse:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": {
                        "result": {
                            "images": [{"url": "https://cdn.example.com/generated.webp"}]
                        }
                    }
                }

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["payload"] = dict(json or {})
                return FakeResponse()

        original_client = main.httpx.AsyncClient
        env_key = main.provider_key_env("apimart-test")
        original_env = os.environ.get(env_key)
        os.environ[env_key] = "test-key"
        main.httpx.AsyncClient = FakeAsyncClient
        try:
            images, _raw = asyncio.run(main.generate_apimart_image(
                "draw an icon",
                "1:1",
                "gpt-image-2-official",
                [],
                {"id": "apimart-test", "base_url": "https://api.apimart.ai"},
                resolution="1k",
                quality="high",
                background="transparent",
                moderation="low",
                output_format="webp",
                output_compression=80,
            ))
        finally:
            main.httpx.AsyncClient = original_client
            if original_env is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = original_env

        payload = captured["payload"]
        self.assertEqual(images[0]["value"], "https://cdn.example.com/generated.webp")
        self.assertEqual(captured["url"], "https://api.apimart.ai/v1/images/generations")
        self.assertNotIn("background", payload)
        self.assertEqual(payload["quality"], "high")
        self.assertEqual(payload["moderation"], "low")
        self.assertEqual(payload["output_format"], "webp")
        self.assertEqual(payload["output_compression"], 80)

    def test_canvas_sends_mask_url_for_nano_banana_pro_official(self):
        html = (ROOT / "static" / "canvas.html").read_text(encoding="utf-8")

        self.assertIn("'gemini-3-pro-image-preview-official'", html)
        self.assertIn("const maskUrlModels = new Set", html)
        self.assertIn("imgPayload.mask_url = maskRes.chosen.alphaUrl", html)

    def test_startup_update_does_not_replace_running_batch_files(self):
        self.assertTrue(main._skip_path_for_update("运行文件.bat"))
        self.assertTrue(main._skip_path_for_update("安装依赖.bat"))
        self.assertTrue(main._skip_path_for_update("nested/script.bat"))

    def test_omni_flash_ext_video_model_is_in_fallback_catalog(self):
        video_models = {item["id"]: item for item in main.APIMART_FALLBACK_CATALOG["video"]}

        self.assertIn("Omni-Flash-Ext", video_models)
        omni = video_models["Omni-Flash-Ext"]
        self.assertEqual(omni["label"], "Omni Flash Ext")
        self.assertEqual(omni["params"]["duration"]["options"], [4, 6, 8, 10])
        self.assertEqual(omni["params"]["duration"]["default"], 6)
        self.assertEqual(omni["params"]["resolution"]["options"], ["720p", "1080p", "4k"])
        self.assertEqual(omni["params"]["size"]["options"], ["16:9", "9:16"])

    def test_video_pricing_supports_resolution_duration_prices(self):
        raw = {
            "billing_type": "resolution_duration",
            "resolution_duration_prices": {
                "720P-4s": 0.1875,
                "720P-6s": 0.2125,
                "4K-10s": 0.5,
            },
            "video_ref_per_second_prices": {
                "720P": 0.042,
                "4K": 0.08,
            },
        }

        pricing = main._parse_video_pricing(raw)

        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["bill_by"], "per_video_duration")
        rules = {
            (rule["resolution"], rule["duration"]): rule["per_video"]
            for rule in pricing["rules"]
        }
        self.assertEqual(rules[("720p", 4)], 0.1875)
        self.assertEqual(rules[("720p", 6)], 0.2125)
        self.assertEqual(rules[("4k", 10)], 0.5)
        ref_rules = {
            rule["resolution"]: rule["input_per_second"]
            for rule in pricing["rules"]
            if "input_per_second" in rule
        }
        self.assertEqual(ref_rules["720p"], 0.042)
        self.assertEqual(ref_rules["4k"], 0.08)

    def test_apimart_video_result_urls_accept_url_arrays(self):
        result_data = {
            "videos": [
                {"url": ["https://cdn.example.com/a.mp4", "", "https://cdn.example.com/a.mp4"]},
                {"link": ["https://cdn.example.com/b.mp4"]},
                {"download_url": ["https://cdn.example.com/c.mp4", None]},
                {"url": []},
                {"url": ["https://cdn.example.com/d.mp4"], "link": "https://cdn.example.com/d-alt.mp4"},
                "https://cdn.example.com/e.mp4",
            ]
        }

        self.assertEqual(
            main.extract_apimart_video_result_urls(result_data),
            [
                "https://cdn.example.com/a.mp4",
                "https://cdn.example.com/b.mp4",
                "https://cdn.example.com/c.mp4",
                "https://cdn.example.com/d.mp4",
                "https://cdn.example.com/d-alt.mp4",
                "https://cdn.example.com/e.mp4",
            ],
        )

    def test_canvas_price_estimate_supports_per_video_duration(self):
        html = (ROOT / "static" / "canvas.html").read_text(encoding="utf-8")

        self.assertIn("pricing.bill_by === 'per_video_duration'", html)

    def test_video_failure_classifier_explains_unsupported_omni_image_count(self):
        detail = main.classify_apimart_video_failure({
            "error": {
                "code": "unsupported_image_count",
                "message": "Passing 2 images returns an unsupported_image_count error.",
            }
        })

        self.assertEqual(detail["code"], "unsupported_image_count")
        self.assertIn("0、1 或 3", detail["message"])

    def test_video_failure_classifier_explains_payment_required(self):
        detail = main.classify_apimart_video_failure({
            "error": {
                "code": "payment_required",
                "message": "Insufficient balance",
            }
        })

        self.assertEqual(detail["code"], "payment_required")
        self.assertIn("余额不足", detail["message"])

    def test_video_task_poll_http_error_is_translated_to_structured_detail(self):
        class FakeResponse:
            status_code = 500
            text = '{"error":{"code":"unsupported_image_count","message":"Passing 2 images returns an unsupported_image_count error."},"request_id":"req_123"}'

            def json(self):
                return {
                    "error": {
                        "code": "unsupported_image_count",
                        "message": "Passing 2 images returns an unsupported_image_count error.",
                    },
                    "request_id": "req_123",
                }

            def raise_for_status(self):
                request = main.httpx.Request("GET", "https://api.apimart.ai/v1/tasks/task_1")
                raise main.httpx.HTTPStatusError("500 Server Error", request=request, response=self)

        class FakeClient:
            async def get(self, *args, **kwargs):
                return FakeResponse()

        async def run():
            original_sleep = main.asyncio.sleep
            main.asyncio.sleep = lambda *args, **kwargs: original_sleep(0)
            try:
                await main.wait_for_apimart_task(
                    FakeClient(),
                    "https://api.apimart.ai",
                    "key",
                    "task_1",
                    timeout=1,
                    failure_classifier=main.classify_apimart_video_failure,
                )
            finally:
                main.asyncio.sleep = original_sleep

        with self.assertRaises(main.HTTPException) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(ctx.exception.detail["code"], "unsupported_image_count")
        self.assertEqual(ctx.exception.detail["request_id"], "req_123")
        self.assertIn("task_info", ctx.exception.detail)

    def test_video_task_failed_status_uses_video_failure_classifier(self):
        class FakeResponse:
            def json(self):
                return {
                    "data": {
                        "status": "failed",
                        "error": {
                            "code": "unsupported_image_count",
                            "message": "Passing 2 images returns an unsupported_image_count error.",
                        },
                    }
                }

            def raise_for_status(self):
                return None

        class FakeClient:
            async def get(self, *args, **kwargs):
                return FakeResponse()

        async def run():
            original_sleep = main.asyncio.sleep
            main.asyncio.sleep = lambda *args, **kwargs: original_sleep(0)
            try:
                await main.wait_for_apimart_task(
                    FakeClient(),
                    "https://api.apimart.ai",
                    "key",
                    "task_1",
                    timeout=1,
                    failure_classifier=main.classify_apimart_video_failure,
                )
            finally:
                main.asyncio.sleep = original_sleep

        with self.assertRaises(main.HTTPException) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(ctx.exception.detail["code"], "unsupported_image_count")

    def test_video_task_poll_network_error_is_translated_to_structured_detail(self):
        class FakeClient:
            async def get(self, *args, **kwargs):
                request = main.httpx.Request("GET", "https://api.apimart.ai/v1/tasks/task_1")
                raise main.httpx.ConnectError("network down", request=request)

        async def run():
            original_sleep = main.asyncio.sleep
            main.asyncio.sleep = lambda *args, **kwargs: original_sleep(0)
            try:
                await main.wait_for_apimart_task(
                    FakeClient(),
                    "https://api.apimart.ai",
                    "key",
                    "task_1",
                    timeout=1,
                    failure_classifier=main.classify_apimart_video_failure,
                )
            finally:
                main.asyncio.sleep = original_sleep

        with self.assertRaises(main.HTTPException) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(ctx.exception.detail["code"], "upstream_video_error")
        self.assertIn("network down", ctx.exception.detail["message"])
        self.assertEqual(ctx.exception.detail["task_info"]["status"], "poll_network_error")

    def test_video_task_poll_invalid_json_is_translated_to_structured_detail(self):
        class FakeResponse:
            text = "not-json from upstream"

            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("bad json")

        class FakeClient:
            async def get(self, *args, **kwargs):
                return FakeResponse()

        async def run():
            original_sleep = main.asyncio.sleep
            main.asyncio.sleep = lambda *args, **kwargs: original_sleep(0)
            try:
                await main.wait_for_apimart_task(
                    FakeClient(),
                    "https://api.apimart.ai",
                    "key",
                    "task_1",
                    timeout=1,
                    failure_classifier=main.classify_apimart_video_failure,
                )
            finally:
                main.asyncio.sleep = original_sleep

        with self.assertRaises(main.HTTPException) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(ctx.exception.detail["code"], "upstream_video_error")
        self.assertIn("invalid JSON", ctx.exception.detail["message"])
        self.assertIn("not-json from upstream", ctx.exception.detail["message"])
        self.assertEqual(ctx.exception.detail["task_info"]["status"], "poll_parse_error")


if __name__ == "__main__":
    unittest.main()
