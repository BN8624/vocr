from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from serve_review import ReviewRequestHandler, ReviewServer


DEFAULT_PORT = 8012


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one PDF and show the PC/iPhone review links."
    )
    parser.add_argument("pdf", help="PDF file to convert.")
    parser.add_argument(
        "--output",
        default="",
        help="Output folder. Default: output/<pdf-name>",
    )
    parser.add_argument("--config", default="config.yaml", help="YAML config path.")
    parser.add_argument("--dry-run", action="store_true", help="Reuse cache and skip API calls.")
    parser.add_argument("--force", action="store_true", help="Rebuild pages and chunks.")
    parser.add_argument("--force-vision", action="store_true", help="Call Vision again instead of cache.")
    parser.add_argument("--limit-chunks", type=int, default=None, help="Vision smoke test chunk limit.")
    parser.add_argument("--skip-total-pass", action="store_true", help="Skip total/summary extraction.")
    parser.add_argument(
        "--mapping-profile",
        action="append",
        default=[],
        help="Apply a saved mapping profile. Can be passed more than once.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Review server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Review server port.")
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Only convert and print links; do not start a review server.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    pdf_path = Path(args.pdf).expanduser()
    output_dir = Path(args.output).expanduser() if args.output else repo_root / "output" / _safe_output_name(pdf_path)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    exit_code = _run_pipeline(repo_root, pdf_path, output_dir, args)
    if exit_code != 0:
        return exit_code

    _print_review_links(repo_root, output_dir, args.port)
    if args.no_server:
        return 0

    if _port_is_busy(args.port):
        print(f"\nReview server already seems to be running on port {args.port}.")
        print("Open the link above from PC or iPhone.")
        return 0

    print(f"\nStarting review server on port {args.port}.")
    print("Leave this window open while checking from iPhone. Press Ctrl+C to stop.")
    server = ReviewServer((args.host, args.port), ReviewRequestHandler, repo_root, repo_root / "profiles")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping review server.")
    finally:
        server.server_close()
    return 0


def _run_pipeline(repo_root: Path, pdf_path: Path, output_dir: Path, args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(repo_root / "main.py"),
        "--input",
        str(pdf_path),
        "--output",
        str(output_dir),
        "--config",
        str(Path(args.config).expanduser()),
    ]
    if args.dry_run:
        command.append("--dry-run")
    if args.force:
        command.append("--force")
    if args.force_vision:
        command.append("--force-vision")
    if args.limit_chunks is not None:
        command.extend(["--limit-chunks", str(args.limit_chunks)])
    if args.skip_total_pass:
        command.append("--skip-total-pass")
    for profile in args.mapping_profile:
        command.extend(["--mapping-profile", str(Path(profile).expanduser())])

    print(f"Converting: {pdf_path}", flush=True)
    print(f"Output: {output_dir}", flush=True)
    return subprocess.run(command, cwd=repo_root).returncode


def _print_review_links(repo_root: Path, output_dir: Path, port: int) -> None:
    path = _review_url_path(repo_root, output_dir)
    print("\nReview links")
    print(f"PC:     http://127.0.0.1:{port}/{path}")
    tailscale_ip = _tailscale_ip()
    if tailscale_ip:
        print(f"iPhone: http://{tailscale_ip}:{port}/{path}")
    else:
        print("iPhone: Tailscale IP was not detected. Use http://<tailscale-ip>:" f"{port}/{path}")
    print(f"Excel:  {output_dir / 'result.xlsx'}")


def _review_url_path(repo_root: Path, output_dir: Path) -> str:
    review_path = output_dir.resolve() / "review.html"
    try:
        relative = review_path.relative_to(repo_root.resolve())
    except ValueError:
        relative = review_path
    return quote(relative.as_posix())


def _safe_output_name(pdf_path: Path) -> str:
    stem = pdf_path.stem.strip() or "statement"
    safe = []
    for char in stem:
        if char.isalnum() or char in {"-", "_"}:
            safe.append(char)
        elif char.isspace() or char in {".", "(", ")", "[", "]"}:
            safe.append("_")
    value = "".join(safe).strip("_")
    return value or "statement"


def _port_is_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _tailscale_ip() -> str:
    try:
        output = subprocess.check_output(["ipconfig"], text=True, encoding="utf-8", errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return ""
    return _pick_tailscale_ip(output)


def _pick_tailscale_ip(text: str) -> str:
    addresses = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
    for address in addresses:
        if _is_tailscale_address(address):
            return address
    return ""


def _is_tailscale_address(address: str) -> bool:
    parts = address.split(".")
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return first == 100 and 64 <= second <= 127


if __name__ == "__main__":
    raise SystemExit(main())
