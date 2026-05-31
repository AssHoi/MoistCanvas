import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


class ApimartNanoBananaCatalogTests(unittest.TestCase):
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

    def test_canvas_price_estimate_supports_per_video_duration(self):
        html = (ROOT / "static" / "canvas.html").read_text(encoding="utf-8")

        self.assertIn("pricing.bill_by === 'per_video_duration'", html)


if __name__ == "__main__":
    unittest.main()
