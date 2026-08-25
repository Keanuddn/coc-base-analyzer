"""HTTP wrapper around infer JSON — no YOLO load in unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "scripts"))

from analyze_server import create_app  # noqa: E402


def _fake_infer(*_args, **kwargs):
    overlay_path = kwargs.get("overlay_path")
    if overlay_path:
        Path(overlay_path).write_bytes(b"\xff\xd8\xff\xd9")
    return {
        "image": "tmp.png",
        "town_hall": kwargs.get("town_hall"),
        "town_hall_source": "cli" if kwargs.get("town_hall") else "none",
        "th_gate": {
            "th": kwargs.get("town_hall"),
            "source": "cli" if kwargs.get("town_hall") else "none",
            "applied": False,
            "notes": ["test"],
        },
        "summary": {
            "by_class": {"cannon": 2},
            "counts": {"cannon": 2},
            "defenses_targeting": {
                "air": 0,
                "ground": 2,
                "both": 0,
                "unknown": 0,
                "none": 0,
            },
        },
        "buildings": [],
    }


class TestAnalyzeServer(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(infer_fn=_fake_infer))

    def test_health_and_index(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Base Analyzer", page.text)

    def test_analyze_rejects_bad_type(self) -> None:
        res = self.client.post("/analyze", files={"image": ("x.gif", b"GIF89a", "image/gif")})
        self.assertEqual(res.status_code, 400)

    def test_analyze_png_and_th(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        res = self.client.post(
            "/analyze",
            files={"image": ("base.png", png, "image/png")},
            data={"th": "16"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["summary"]["by_class"]["cannon"], 2)
        self.assertEqual(body["th_gate"]["th"], 16)
        self.assertIn("overlay_jpeg_base64", body)
        self.assertTrue(body["overlay_jpeg_base64"])


if __name__ == "__main__":
    unittest.main()
