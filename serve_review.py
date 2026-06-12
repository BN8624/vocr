from __future__ import annotations

import argparse
import json
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote


MAX_BODY_BYTES = 1_000_000


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    server: "ReviewServer"

    def do_POST(self) -> None:
        if self.path != "/api/mapping-profile":
            self.send_error(404, "Not found")
            return

        try:
            payload = self._read_json_body()
            saved_path = self._save_mapping_profile(payload)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Could not save profile: {exc}"}, status=500)
            return

        self._send_json(
            {
                "ok": True,
                "path": str(saved_path),
                "filename": saved_path.name,
            }
        )

    def _read_json_body(self) -> dict[str, Any]:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0:
            raise ValueError("Empty request body")
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large")

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Profile payload must be a JSON object")
        if not isinstance(payload.get("table_groups"), list):
            raise ValueError("Profile payload must include table_groups[]")
        return payload

    def _save_mapping_profile(self, payload: dict[str, Any]) -> Path:
        profiles_dir = self.server.profiles_dir
        profiles_dir.mkdir(parents=True, exist_ok=True)

        filename = _safe_filename(str(payload.get("filename", "")).strip())
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"mapping-profile-{timestamp}.json"
        if not filename.endswith(".json"):
            filename += ".json"

        target = (profiles_dir / filename).resolve()
        if not _is_within(target, profiles_dir.resolve()):
            raise ValueError("Invalid profile filename")

        payload = dict(payload)
        payload.pop("filename", None)
        payload["status"] = "user_confirmed_saved"
        payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def translate_path(self, path: str) -> str:
        path = unquote(path.split("?", 1)[0].split("#", 1)[0])
        parts = [part for part in path.split("/") if part and part not in {".", ".."}]
        resolved = self.server.root_dir
        for part in parts:
            resolved = resolved / part
        return str(resolved)


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[ReviewRequestHandler], root_dir: Path, profiles_dir: Path):
        super().__init__(server_address, handler_class)
        self.root_dir = root_dir.resolve()
        self.profiles_dir = profiles_dir.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve review.html and save mapping profiles from the browser.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind. Use 0.0.0.0 for Tailscale/iPhone access.")
    parser.add_argument("--port", type=int, default=8012, help="Port to bind. Avoid 8000 and 8400 if already in use.")
    parser.add_argument("--root", default=".", help="Repository root to serve static files from.")
    parser.add_argument("--profiles-dir", default="profiles", help="Folder where mapping profiles will be saved.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root_dir = Path(args.root).expanduser().resolve()
    profiles_dir = Path(args.profiles_dir).expanduser()
    if not profiles_dir.is_absolute():
        profiles_dir = root_dir / profiles_dir

    if not root_dir.exists():
        print(f"Root folder not found: {root_dir}")
        return 2

    server = ReviewServer((args.host, args.port), ReviewRequestHandler, root_dir, profiles_dir)
    print(f"Serving {root_dir} at http://{args.host}:{args.port}/")
    print(f"Mapping profiles will be saved to {profiles_dir.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping review server.")
    finally:
        server.server_close()
    return 0


def _safe_filename(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
    return "".join(allowed)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
