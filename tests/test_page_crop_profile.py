from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import apply_page_crop_profile
from serve_review import ReviewRequestHandler, ReviewServer
from src.chunk_builder import build_chunks, build_total_chunks
from src.page_renderer import PageImage


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        page_path = root / "page_001.png"
        _write_blank_page(page_path)
        page = PageImage(page_number=1, image_path=page_path, width=100, height=100, dpi=100, reused=False)
        profile = {
            "pages": {
                "1": {
                    "chunking": {
                        "header_ratio": 0.2,
                        "body_start_ratio": 0.3,
                        "body_end_ratio": 0.6,
                    },
                    "total_extraction": {
                        "header_ratio": 0.2,
                        "summary_start_ratio": 0.7,
                        "summary_end_ratio": 0.9,
                    },
                }
            }
        }

        chunks = build_chunks(
            pages=[page],
            chunks_dir=root / "chunks",
            config=apply_page_crop_profile(
                {
                    "header_ratio": 0.12,
                    "body_start_ratio": 0.12,
                    "body_end_ratio": 0.95,
                    "chunk_height_ratio": 0.35,
                    "overlap_ratio": 0.25,
                    "attach_header": True,
                },
                profile,
                "chunking",
            ),
            force=True,
        )
        assert chunks[0].header_y_end == 20
        assert chunks[0].source_y_start == 30
        assert chunks[-1].source_y_end == 60

        total_chunks = build_total_chunks(
            pages=[page],
            chunks_dir=root / "total_chunks",
            config=apply_page_crop_profile(
                {
                    "header_ratio": 0.12,
                    "summary_start_ratio": 0.62,
                    "summary_end_ratio": 0.98,
                    "attach_header": True,
                },
                profile,
                "total_extraction",
            ),
            force=True,
        )
        assert total_chunks[0].header_y_end == 20
        assert total_chunks[0].source_y_start == 70
        assert total_chunks[0].source_y_end == 90

        _assert_server_saves_crop_profile(root)

    print("page crop profile test passed")
    return 0


def _assert_server_saves_crop_profile(root: Path) -> None:
    output_dir = root / "served" / "output"
    (output_dir / "merged").mkdir(parents=True)
    server = ReviewServer(("127.0.0.1", 0), ReviewRequestHandler, root / "served", root / "profiles")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _post_json(
            f"http://127.0.0.1:{server.server_port}/api/page-crop-profile",
            {
                "state_path": "/output/merged/page_crop_profile.json",
                "page_number": 2,
                "crop": {
                    "header_ratio": 0.11,
                    "body_start_ratio": 0.22,
                    "body_end_ratio": 0.88,
                    "summary_start_ratio": 0.66,
                    "summary_end_ratio": 0.99,
                },
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response["ok"] is True
    saved = json.loads((output_dir / "merged" / "page_crop_profile.json").read_text(encoding="utf-8"))
    assert saved["pages"]["2"]["chunking"]["body_start_ratio"] == 0.22
    assert saved["pages"]["2"]["total_extraction"]["summary_end_ratio"] == 0.99


def _write_blank_page(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for this test") from exc
    Image.new("RGB", (100, 100), "white").save(path)


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
