from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from src.excel_exporter import export_excel
from src.normalizer import build_transactions, load_normalization_output
from src.profile_store import load_mapping_suggestions
from src.row_merger import load_merge_output
from src.validator import build_validation
from src.vision_extractor import VisionResult


MAX_BODY_BYTES = 1_000_000


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    server: "ReviewServer"

    def do_POST(self) -> None:
        if self.path == "/api/mapping-profile":
            self._handle_mapping_profile()
            return
        if self.path == "/api/review-state":
            self._handle_review_state()
            return
        if self.path == "/api/page-crop-profile":
            self._handle_page_crop_profile()
            return
        self.send_error(404, "Not found")

    def _handle_mapping_profile(self) -> None:
        try:
            payload = self._read_json_body()
            saved_path = self._save_mapping_profile(payload)
            refresh = self._refresh_mapping_outputs(payload)
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
                "refresh": refresh,
            }
        )

    def _handle_review_state(self) -> None:
        try:
            payload = self._read_json_body(require_table_groups=False)
            saved_path = self._save_review_state(payload)
            refresh = self._refresh_review_state_outputs(saved_path)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Could not save review state: {exc}"}, status=500)
            return

        self._send_json(
            {
                "ok": True,
                "path": str(saved_path),
                "filename": saved_path.name,
                "refresh": refresh,
            }
        )

    def _handle_page_crop_profile(self) -> None:
        try:
            payload = self._read_json_body(require_table_groups=False)
            saved_path = self._save_page_crop_profile(payload)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Could not save page crop profile: {exc}"}, status=500)
            return

        self._send_json(
            {
                "ok": True,
                "path": str(saved_path),
                "filename": saved_path.name,
                "message": "페이지 자르기 설정을 저장했습니다.",
            }
        )

    def _refresh_review_state_outputs(self, state_path: Path) -> dict[str, Any]:
        merged_dir = state_path.parent
        output_dir = merged_dir.parent
        normalization_output = load_normalization_output(merged_dir)
        if not normalization_output:
            return {
                "ok": False,
                "message": "정규화 결과가 없어 검산을 즉시 갱신하지 못했습니다. CLI를 다시 실행해 주세요.",
            }

        vision_results = _load_cached_vision_results(output_dir / "cache")
        validation_output = build_validation(
            normalization_output=normalization_output,
            vision_results=vision_results,
            merged_dir=merged_dir,
            expected_chunk_count=_expected_chunk_count(output_dir),
            review_state=_read_json_object(state_path),
        )
        if not validation_output:
            return {
                "ok": False,
                "message": "검증 결과를 즉시 갱신하지 못했습니다. CLI를 다시 실행해 주세요.",
            }

        excel_output = _refresh_excel(output_dir, validation_output)
        _update_run_summary(output_dir, validation_output, excel_output=excel_output)
        checksum = validation_output.summary.get("checksum", {})
        if not isinstance(checksum, dict):
            checksum = {}
        return {
            "ok": True,
            "message": "검산 결과와 Excel을 즉시 갱신했습니다." if excel_output else "검산 결과를 즉시 갱신했습니다.",
            "checksum": checksum,
            "checksum_status": validation_output.checksum_status,
            "checksum_difference": validation_output.checksum_difference,
            "validation_summary": str(validation_output.summary_path),
            "excel_path": str(excel_output.workbook_path) if excel_output else "",
        }

    def _refresh_mapping_outputs(self, payload: dict[str, Any]) -> dict[str, Any]:
        mapping_path = str(payload.get("mapping_path", "")).strip()
        if not mapping_path:
            return {
                "ok": False,
                "message": "현재 output 경로가 없어 매핑 저장 후 산출물을 즉시 갱신하지 않았습니다.",
            }

        suggestions_path = self._resolve_served_path(mapping_path)
        if suggestions_path.name != "mapping_suggestions.json":
            raise ValueError("Mapping path filename must be mapping_suggestions.json")
        if suggestions_path.parent.name != "merged":
            raise ValueError("Mapping path must be saved under a merged folder")

        _apply_mapping_payload_to_suggestions(suggestions_path, payload)
        merged_dir = suggestions_path.parent
        output_dir = merged_dir.parent
        merge_output = load_merge_output(merged_dir)
        mapping_output = load_mapping_suggestions(output_dir, self.server.profiles_dir)
        if not merge_output or not mapping_output:
            return {
                "ok": False,
                "message": "행 병합 또는 매핑 결과가 없어 산출물을 즉시 갱신하지 못했습니다.",
            }

        normalization_output = build_transactions(
            merge_output=merge_output,
            mapping_output=mapping_output,
            merged_dir=merged_dir,
        )
        if not normalization_output:
            return {
                "ok": False,
                "message": "거래 정규화 결과를 즉시 갱신하지 못했습니다.",
            }

        validation_output = build_validation(
            normalization_output=normalization_output,
            vision_results=_load_cached_vision_results(output_dir / "cache"),
            merged_dir=merged_dir,
            expected_chunk_count=_expected_chunk_count(output_dir),
            review_state=_read_json_object(merged_dir / "review_state.json"),
        )
        if not validation_output:
            return {
                "ok": False,
                "message": "검증 결과를 즉시 갱신하지 못했습니다.",
            }

        excel_output = _refresh_excel(output_dir, validation_output, source_rows_path=merge_output.rows_merged_path)
        _update_run_summary(output_dir, validation_output, normalization_output=normalization_output, excel_output=excel_output)
        return {
            "ok": bool(excel_output),
            "message": "매핑, 검증, Excel을 즉시 갱신했습니다." if excel_output else "매핑과 검증은 갱신했지만 Excel은 갱신하지 못했습니다.",
            "transaction_count": normalization_output.transaction_count,
            "checksum_status": validation_output.checksum_status,
            "excel_path": str(excel_output.workbook_path) if excel_output else "",
        }

    def _read_json_body(self, require_table_groups: bool = True) -> dict[str, Any]:
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
            raise ValueError("Payload must be a JSON object")
        if require_table_groups and not isinstance(payload.get("table_groups"), list):
            raise ValueError("Profile payload must include table_groups[]")
        return payload

    def _save_review_state(self, payload: dict[str, Any]) -> Path:
        state_path = str(payload.get("state_path", "")).strip()
        if not state_path:
            raise ValueError("Review state payload must include state_path")

        target = self._resolve_served_path(state_path)
        if target.name != "review_state.json":
            raise ValueError("Review state filename must be review_state.json")
        if target.parent.name != "merged":
            raise ValueError("Review state must be saved under a merged folder")

        checksum = payload.get("checksum", {})
        if not isinstance(checksum, dict):
            raise ValueError("Review state payload must include checksum object")
        selected_total_id = str(checksum.get("selected_total_id", "")).strip()
        if not selected_total_id:
            raise ValueError("Select a source total before saving")

        target.parent.mkdir(parents=True, exist_ok=True)
        review_state = {
            "schema_version": "1.0",
            "status": "user_confirmed_review_state",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "checksum": {
                "selected_total_id": selected_total_id,
                "selected_total": checksum.get("selected_total", {}),
            },
        }
        target.write_text(json.dumps(review_state, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def _save_page_crop_profile(self, payload: dict[str, Any]) -> Path:
        state_path = str(payload.get("state_path", "")).strip()
        if not state_path:
            raise ValueError("Crop profile payload must include state_path")

        target = self._resolve_served_path(state_path)
        if target.name != "page_crop_profile.json":
            raise ValueError("Crop profile filename must be page_crop_profile.json")
        if target.parent.name != "merged":
            raise ValueError("Crop profile must be saved under a merged folder")

        page_number = str(payload.get("page_number", "")).strip()
        if not page_number.isdigit() or int(page_number) <= 0:
            raise ValueError("Crop profile payload must include a positive page_number")
        crop = payload.get("crop", {})
        if not isinstance(crop, dict):
            raise ValueError("Crop profile payload must include crop object")

        page_crop = _validated_page_crop(crop)
        existing = _read_json_object(target)
        pages = existing.get("pages", {}) if isinstance(existing.get("pages"), dict) else {}
        pages[str(int(page_number))] = page_crop

        target.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "schema_version": "1.0",
            "status": "user_confirmed_page_crop_profile",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "pages": pages,
        }
        target.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def _resolve_served_path(self, request_path: str) -> Path:
        request_path = unquote(request_path.split("?", 1)[0].split("#", 1)[0])
        parts = [part for part in request_path.split("/") if part and part not in {".", ".."}]
        resolved = self.server.root_dir
        for part in parts:
            resolved = resolved / part
        resolved = resolved.resolve()
        if not _is_within(resolved, self.server.root_dir):
            raise ValueError("Invalid path")
        return resolved

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
        payload.pop("mapping_path", None)
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


def _load_cached_vision_results(cache_dir: Path) -> list[VisionResult]:
    if not cache_dir.exists():
        return []

    results: list[VisionResult] = []
    seen: set[str] = set()
    for cache_path in sorted(cache_dir.glob("*.vision.json")):
        data = _read_json_object(cache_path)
        chunk_id = str(data.get("chunk_id") or _strip_known_suffix(cache_path.name, ".vision.json"))
        seen.add(chunk_id)
        results.append(
            VisionResult(
                chunk_id=chunk_id,
                page_number=_page_number(chunk_id, data.get("page")),
                cache_path=cache_path,
                status="cached",
                data=data,
                reused=True,
            )
        )

    for error_path in sorted(cache_dir.glob("*.error.json")):
        chunk_id = _strip_known_suffix(error_path.name, ".error.json")
        if chunk_id in seen:
            continue
        results.append(
            VisionResult(
                chunk_id=chunk_id,
                page_number=_page_number(chunk_id, None),
                cache_path=cache_dir / f"{chunk_id}.vision.json",
                status="error",
                data=None,
                error_path=error_path,
                raw_text_path=None,
                reused=True,
            )
        )
    return results


def _validated_page_crop(crop: dict[str, Any]) -> dict[str, Any]:
    header_ratio = _ratio(crop, "header_ratio")
    body_start_ratio = _ratio(crop, "body_start_ratio")
    body_end_ratio = _ratio(crop, "body_end_ratio")
    summary_start_ratio = _ratio(crop, "summary_start_ratio")
    summary_end_ratio = _ratio(crop, "summary_end_ratio")

    if body_start_ratio >= body_end_ratio:
        raise ValueError("Body start must be smaller than body end")
    if summary_start_ratio >= summary_end_ratio:
        raise ValueError("Summary start must be smaller than summary end")

    return {
        "chunking": {
            "header_ratio": header_ratio,
            "body_start_ratio": body_start_ratio,
            "body_end_ratio": body_end_ratio,
        },
        "total_extraction": {
            "header_ratio": header_ratio,
            "summary_start_ratio": summary_start_ratio,
            "summary_end_ratio": summary_end_ratio,
        },
    }


def _ratio(crop: dict[str, Any], key: str) -> float:
    try:
        value = float(crop[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Crop value must be numeric: {key}") from exc
    if value < 0 or value > 1:
        raise ValueError(f"Crop value must be between 0 and 1: {key}")
    return round(value, 4)


def _expected_chunk_count(output_dir: Path) -> int | None:
    summary = _read_json_object(output_dir / "summary.json")
    value = summary.get("chunk_count")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _refresh_excel(output_dir: Path, validation_output: Any, source_rows_path: Path | None = None) -> Any:
    source_rows = source_rows_path or output_dir / "merged" / "rows_merged.jsonl"
    return export_excel(
        validation_output=validation_output,
        output_dir=output_dir,
        filename="result.xlsx",
        source_rows_path=source_rows,
    )


def _update_run_summary(
    output_dir: Path,
    validation_output: Any,
    normalization_output: Any | None = None,
    excel_output: Any | None = None,
) -> None:
    summary_path = output_dir / "summary.json"
    summary = _read_json_object(summary_path)
    if not summary:
        return
    summary["checksum_status"] = validation_output.checksum_status
    summary["validation_issue_row_count"] = validation_output.issue_row_count
    if normalization_output:
        summary["transaction_count"] = normalization_output.transaction_count
        summary["normalization_review_count"] = normalization_output.review_count
        summary["normalized_amount_total"] = normalization_output.amount_total
    if excel_output:
        summary["excel_path"] = str(excel_output.workbook_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_mapping_payload_to_suggestions(suggestions_path: Path, payload: dict[str, Any]) -> None:
    suggestions = _read_json_object(suggestions_path)
    groups = suggestions.get("table_groups", []) if isinstance(suggestions.get("table_groups"), list) else []
    incoming_groups = payload.get("table_groups", []) if isinstance(payload.get("table_groups"), list) else []
    incoming_by_group = {
        str(group.get("group_id", "")): group
        for group in incoming_groups
        if isinstance(group, dict)
    }

    for group in groups:
        if not isinstance(group, dict):
            continue
        incoming_group = incoming_by_group.get(str(group.get("group_id", "")))
        if not isinstance(incoming_group, dict):
            continue
        selected_by_column = {
            str(column.get("column_id", "")): str(column.get("selected_field", "")).strip()
            for column in incoming_group.get("columns", [])
            if isinstance(column, dict)
        }
        for column in group.get("columns", []):
            if not isinstance(column, dict):
                continue
            selected = selected_by_column.get(str(column.get("column_id", "")))
            if not selected:
                continue
            column["selected_field"] = selected
            column["suggested_field"] = selected
            column["confidence"] = "user_confirmed"
            column["requires_review"] = False
            column["review_reason"] = ""
            column["reason"] = "사용자가 리뷰 화면에서 확정한 매핑입니다."
        group["review_column_count"] = sum(
            1 for column in group.get("columns", []) if isinstance(column, dict) and column.get("requires_review")
        )
        group["auto_column_count"] = sum(
            1 for column in group.get("columns", []) if isinstance(column, dict) and not column.get("requires_review")
        )

    suggestions["status"] = "user_confirmed_applied"
    suggestions["saved_at"] = datetime.now().isoformat(timespec="seconds")
    suggestions_path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _strip_known_suffix(name: str, suffix: str) -> str:
    return name[: -len(suffix)] if name.endswith(suffix) else Path(name).stem


def _page_number(chunk_id: str, value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    match = re.search(r"page_(\d+)", chunk_id)
    if match:
        return int(match.group(1))
    return 0


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
