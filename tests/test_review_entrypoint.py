from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import review


def main() -> int:
    assert review._safe_output_name(Path("삼성카드 1.pdf")) == "삼성카드_1"
    assert review._safe_output_name(Path("!!!.pdf")) == "statement"

    root = Path("C:/work/vocr")
    output_dir = root / "output" / "삼성카드_1"
    assert (
        review._review_url_path(root, output_dir)
        == "output/%EC%82%BC%EC%84%B1%EC%B9%B4%EB%93%9C_1/review.html"
    )

    sample_ipconfig = """
Ethernet adapter Tailscale:
   IPv4 Address. . . . . . . . . . . : 100.89.73.83

Ethernet adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 192.168.0.20
"""
    assert review._pick_tailscale_ip(sample_ipconfig) == "100.89.73.83"
    assert review._pick_tailscale_ip("IPv4 Address: 192.168.0.20") == ""

    print("review entrypoint test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
