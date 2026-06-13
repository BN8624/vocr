from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProfileSummary:
    filename: str
    path: Path
    status: str
    saved_at: str
    group_count: int
    column_count: int
    selected_count: int
    fields: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="List, inspect, rename, or delete local mapping profiles.")
    parser.add_argument("--profiles-dir", default="profiles", help="Folder containing local profile JSON files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List saved mapping profiles.")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    show_parser = subparsers.add_parser("show", help="Show one saved mapping profile.")
    show_parser.add_argument("profile", help="Profile filename or path under profiles-dir.")
    show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    rename_parser = subparsers.add_parser("rename", help="Rename one saved mapping profile.")
    rename_parser.add_argument("profile", help="Profile filename or path under profiles-dir.")
    rename_parser.add_argument("new_name", help="New profile filename. .json is added when omitted.")

    delete_parser = subparsers.add_parser("delete", help="Delete one saved mapping profile.")
    delete_parser.add_argument("profile", help="Profile filename or path under profiles-dir.")
    delete_parser.add_argument("--yes", action="store_true", help="Confirm deletion without an interactive prompt.")

    args = parser.parse_args()
    profiles_dir = Path(args.profiles_dir).expanduser().resolve()
    profiles_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "list":
        return command_list(profiles_dir, as_json=bool(args.json))
    if args.command == "show":
        return command_show(profiles_dir, str(args.profile), as_json=bool(args.json))
    if args.command == "rename":
        return command_rename(profiles_dir, str(args.profile), str(args.new_name))
    if args.command == "delete":
        return command_delete(profiles_dir, str(args.profile), assume_yes=bool(args.yes))
    raise AssertionError(f"Unhandled command: {args.command}")


def command_list(profiles_dir: Path, as_json: bool = False) -> int:
    summaries = [profile_summary(path) for path in profile_paths(profiles_dir)]
    if as_json:
        print(json.dumps([summary_to_json(item) for item in summaries], ensure_ascii=False, indent=2))
        return 0
    if not summaries:
        print(f"No mapping profiles found in {profiles_dir}")
        return 0
    print("filename\tgroups\tcolumns\tselected\tstatus\tsaved_at\tfields")
    for summary in summaries:
        print(
            "\t".join(
                [
                    summary.filename,
                    str(summary.group_count),
                    str(summary.column_count),
                    str(summary.selected_count),
                    summary.status,
                    summary.saved_at,
                    ", ".join(summary.fields),
                ]
            )
        )
    return 0


def command_show(profiles_dir: Path, profile: str, as_json: bool = False) -> int:
    path = resolve_profile_path(profiles_dir, profile)
    payload = read_json_object(path)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    summary = profile_summary(path)
    print(f"Profile: {summary.filename}")
    print(f"Path: {summary.path}")
    print(f"Status: {summary.status}")
    print(f"Saved at: {summary.saved_at}")
    print(f"Groups: {summary.group_count}")
    print(f"Columns: {summary.column_count}")
    print(f"Selected: {summary.selected_count}")
    print(f"Fields: {', '.join(summary.fields) if summary.fields else '-'}")

    groups = payload.get("table_groups", []) if isinstance(payload.get("table_groups"), list) else []
    for group_index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        header = [str(value) for value in group.get("header", [])]
        columns = [column for column in group.get("columns", []) if isinstance(column, dict)]
        print("")
        print(f"[Group {group_index}] {group.get('group_id', '')}")
        if header:
            print(f"Header: {' | '.join(header)}")
        for column in columns:
            selected = str(column.get("selected_field") or column.get("suggested_field") or "")
            print(
                f"- {column.get('column_id', '')}: "
                f"{column.get('header', '')} -> {selected or '-'}"
            )
    return 0


def command_rename(profiles_dir: Path, profile: str, new_name: str) -> int:
    source = resolve_profile_path(profiles_dir, profile)
    target_name = safe_profile_filename(new_name)
    target = (profiles_dir / target_name).resolve()
    ensure_within_profiles(profiles_dir, target)
    if target.exists():
        raise FileExistsError(f"Target profile already exists: {target.name}")
    source.rename(target)
    print(f"Renamed {source.name} -> {target.name}")
    return 0


def command_delete(profiles_dir: Path, profile: str, assume_yes: bool = False) -> int:
    path = resolve_profile_path(profiles_dir, profile)
    if not assume_yes:
        answer = input(f"Delete {path.name}? Type yes to confirm: ").strip().lower()
        if answer != "yes":
            print("Delete cancelled.")
            return 1
    path.unlink()
    print(f"Deleted {path.name}")
    return 0


def profile_paths(profiles_dir: Path) -> list[Path]:
    return sorted(path for path in profiles_dir.glob("*.json") if path.is_file())


def profile_summary(path: Path) -> ProfileSummary:
    payload = read_json_object(path)
    groups = payload.get("table_groups", []) if isinstance(payload.get("table_groups"), list) else []
    group_count = 0
    column_count = 0
    selected_fields: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_count += 1
        columns = [column for column in group.get("columns", []) if isinstance(column, dict)]
        column_count += len(columns)
        for column in columns:
            field = str(column.get("selected_field") or column.get("suggested_field") or "").strip()
            if field:
                selected_fields.append(field)
    fields = sorted(set(selected_fields))
    return ProfileSummary(
        filename=path.name,
        path=path,
        status=str(payload.get("status", "")),
        saved_at=str(payload.get("saved_at", "")),
        group_count=group_count,
        column_count=column_count,
        selected_count=len(selected_fields),
        fields=fields,
    )


def summary_to_json(summary: ProfileSummary) -> dict[str, Any]:
    return {
        "filename": summary.filename,
        "path": str(summary.path),
        "status": summary.status,
        "saved_at": summary.saved_at,
        "group_count": summary.group_count,
        "column_count": summary.column_count,
        "selected_count": summary.selected_count,
        "fields": summary.fields,
    }


def resolve_profile_path(profiles_dir: Path, value: str) -> Path:
    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raw_path = profiles_dir / raw_path
    path = raw_path.resolve()
    ensure_within_profiles(profiles_dir, path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Profile not found: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError(f"Profile must be a JSON file: {path}")
    return path


def safe_profile_filename(value: str) -> str:
    path = Path(value)
    name = path.name.strip()
    if not name:
        raise ValueError("New profile name is empty")
    allowed = []
    for char in name:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
    filename = "".join(allowed)
    if not filename:
        raise ValueError("New profile name has no safe characters")
    if not filename.endswith(".json"):
        filename += ".json"
    return filename


def ensure_within_profiles(profiles_dir: Path, path: Path) -> None:
    try:
        path.relative_to(profiles_dir)
    except ValueError as exc:
        raise ValueError(f"Profile path must stay under {profiles_dir}") from exc


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profile is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Profile JSON must be an object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
