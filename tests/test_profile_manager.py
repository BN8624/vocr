from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp_dir:
        profiles_dir = Path(temp_dir) / "profiles"
        profiles_dir.mkdir()
        profile_path = profiles_dir / "mapping-profile.json"
        profile_path.write_text(json.dumps(_profile_payload(), ensure_ascii=False), encoding="utf-8")

        listed = _run(root, profiles_dir, "list", "--json")
        listed_payload = json.loads(listed.stdout)
        assert listed_payload[0]["filename"] == "mapping-profile.json"
        assert listed_payload[0]["group_count"] == 1
        assert listed_payload[0]["selected_count"] == 3
        assert listed_payload[0]["fields"] == ["amount", "date", "merchant"]

        shown = _run(root, profiles_dir, "show", "mapping-profile.json")
        assert "Profile: mapping-profile.json" in shown.stdout
        assert "col_3" in shown.stdout

        _run(root, profiles_dir, "rename", "mapping-profile.json", "renamed")
        renamed_path = profiles_dir / "renamed.json"
        assert renamed_path.exists()
        assert not profile_path.exists()

        _run(root, profiles_dir, "delete", "renamed.json", "--yes")
        assert not renamed_path.exists()

    print("profile manager test passed")
    return 0


def _run(root: Path, profiles_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "profile_manager.py"),
            "--profiles-dir",
            str(profiles_dir),
            *args,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"profile_manager.py failed: {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _profile_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "user_confirmed_saved",
        "saved_at": "2026-06-13T12:00:00",
        "table_groups": [
            {
                "group_id": "table_1",
                "header": ["이용일", "가맹점", "금액"],
                "columns": [
                    {"column_id": "col_1", "header": "이용일", "selected_field": "date"},
                    {"column_id": "col_2", "header": "가맹점", "selected_field": "merchant"},
                    {"column_id": "col_3", "header": "금액", "selected_field": "amount"},
                ],
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
