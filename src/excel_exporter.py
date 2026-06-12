from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.validator import ValidationOutput


@dataclass(frozen=True)
class ExcelExportOutput:
    workbook_path: Path
    sheet_names: list[str]
    transaction_count: int
    review_count: int


def export_excel(
    validation_output: ValidationOutput | None,
    output_dir: Path,
    filename: str = "result.xlsx",
    source_rows_path: Path | None = None,
) -> ExcelExportOutput | None:
    if not validation_output or not validation_output.validated_transactions_path.exists():
        return None

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.table import Table, TableStyleInfo
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for Excel export. Run: pip install -r requirements.txt"
        ) from exc

    rows = _read_jsonl(validation_output.validated_transactions_path)
    raw_rows = _read_jsonl(source_rows_path) if source_rows_path and source_rows_path.exists() else rows
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    summary = validation_output.summary
    ws_transactions = workbook.create_sheet("전체명세")
    ws_checksum = workbook.create_sheet("검산")
    ws_raw = workbook.create_sheet("원본셀")
    ws_extra = workbook.create_sheet("추가필드")
    ws_review = workbook.create_sheet("확인필요")

    _write_transactions(ws_transactions, rows)
    _write_checksum(ws_checksum, summary)
    _write_raw_cells(ws_raw, raw_rows)
    _write_extra_fields(ws_extra, rows)
    review_count = _write_review_rows(ws_review, rows, summary)

    for sheet in workbook.worksheets:
        _style_sheet(sheet, get_column_letter, Table, TableStyleInfo, PatternFill, Font, Alignment)

    workbook_path = output_dir / filename
    output_dir.mkdir(parents=True, exist_ok=True)
    workbook.save(workbook_path)

    return ExcelExportOutput(
        workbook_path=workbook_path,
        sheet_names=[sheet.title for sheet in workbook.worksheets],
        transaction_count=len(rows),
        review_count=review_count,
    )


def load_excel_export(output_dir: Path, filename: str = "result.xlsx") -> ExcelExportOutput | None:
    workbook_path = output_dir / filename
    if not workbook_path.exists():
        return None
    return ExcelExportOutput(
        workbook_path=workbook_path,
        sheet_names=[],
        transaction_count=0,
        review_count=0,
    )


def _write_transactions(sheet: Any, rows: list[dict[str, Any]]) -> None:
    headers = [
        "source_file",
        "page",
        "chunk_id",
        "local_row_index",
        "date",
        "card_label",
        "merchant",
        "transaction_type",
        "amount",
        "billing_amount",
        "needs_review",
        "review_reason",
    ]
    sheet.append(headers)
    for row in rows:
        source = _dict(row.get("source"))
        transaction = _dict(row.get("transaction"))
        quality = _dict(row.get("quality"))
        validation = _dict(row.get("validation"))
        needs_review = bool(quality.get("needs_review") or validation.get("needs_review"))
        sheet.append(
            [
                source.get("file", ""),
                source.get("page", ""),
                source.get("chunk_id", ""),
                source.get("local_row_index", ""),
                transaction.get("date", ""),
                transaction.get("card_label", ""),
                transaction.get("merchant", ""),
                transaction.get("transaction_type", ""),
                _number_or_blank(transaction.get("amount")),
                _number_or_blank(transaction.get("billing_amount")),
                "Y" if needs_review else "",
                quality.get("review_reason", ""),
            ]
        )


def _write_checksum(sheet: Any, summary: dict[str, Any]) -> None:
    checksum = _dict(summary.get("checksum"))
    sheet.append(["item", "value"])
    sheet.append(["status", checksum.get("status", "")])
    sheet.append(["message", checksum.get("message", "")])
    sheet.append(["amount_total", checksum.get("amount_total", "")])
    sheet.append(["billing_amount_total", checksum.get("billing_amount_total", "")])
    selected = checksum.get("selected_total", {}) if isinstance(checksum.get("selected_total"), dict) else {}
    sheet.append(["selected_total_id", checksum.get("selected_total_id", "")])
    sheet.append(["selected_total_label", selected.get("label", "")])
    sheet.append(["selected_total_amount", selected.get("amount", "")])
    sheet.append(["difference", checksum.get("difference", "")])
    sheet.append(["processed_chunk_count", checksum.get("processed_chunk_count", "")])
    sheet.append(["expected_chunk_count", checksum.get("expected_chunk_count", "")])
    sheet.append([])
    sheet.append(["source_total_label", "amount", "page", "chunk_id"])
    for candidate in checksum.get("source_total_candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        sheet.append(
            [
                candidate.get("label", ""),
                candidate.get("amount", ""),
                candidate.get("page", ""),
                candidate.get("chunk_id", ""),
            ]
        )
    if not checksum.get("source_total_candidates"):
        sheet.append(["원본 합계 후보 없음", "", "", ""])
    auto_matches = [item for item in checksum.get("auto_match_candidates", []) or [] if isinstance(item, dict)]
    if auto_matches:
        sheet.append([])
        sheet.append(["auto_match_field", "source_total_label", "amount", "chunk_id"])
        for item in auto_matches:
            candidate = item.get("candidate", {}) if isinstance(item.get("candidate"), dict) else {}
            sheet.append(
                [
                    item.get("field", ""),
                    candidate.get("label", ""),
                    candidate.get("amount", ""),
                    candidate.get("chunk_id", ""),
                ]
            )


def _write_raw_cells(sheet: Any, rows: list[dict[str, Any]]) -> None:
    sheet.append(
        [
            "source_file",
            "page",
            "chunk_id",
            "local_row_index",
            "cell_index",
            "header",
            "cell_value",
            "image_ref",
        ]
    )
    for row in rows:
        source = _dict(row.get("source"))
        raw = _dict(row.get("raw"))
        headers = [str(value) for value in raw.get("header", [])]
        cells = [str(value) for value in raw.get("cells", [])]
        for index, cell in enumerate(cells, start=1):
            header = headers[index - 1] if index <= len(headers) else f"col_{index}"
            sheet.append(
                [
                    source.get("file", ""),
                    source.get("page", ""),
                    source.get("chunk_id", ""),
                    source.get("local_row_index", ""),
                    index,
                    header,
                    cell,
                    raw.get("image_ref", ""),
                ]
            )


def _write_extra_fields(sheet: Any, rows: list[dict[str, Any]]) -> None:
    sheet.append(["source_file", "page", "chunk_id", "local_row_index", "field", "value"])
    for row in rows:
        source = _dict(row.get("source"))
        extra_fields = _dict(row.get("extra_fields"))
        for key, value in extra_fields.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                sheet.append(
                    [
                        source.get("file", ""),
                        source.get("page", ""),
                        source.get("chunk_id", ""),
                        source.get("local_row_index", ""),
                        key,
                        item,
                    ]
                )


def _write_review_rows(sheet: Any, rows: list[dict[str, Any]], summary: dict[str, Any]) -> int:
    column_quality = _dict(summary.get("column_quality"))
    column_issues = [
        issue for issue in column_quality.get("issues", []) if isinstance(issue, dict)
    ]
    if column_issues:
        sheet.append(["type", "code", "field", "message", "value", "threshold", "header"])
        for issue in column_issues:
            sheet.append(
                [
                    "column_quality",
                    issue.get("code", ""),
                    issue.get("field", ""),
                    issue.get("message", ""),
                    issue.get("value", ""),
                    issue.get("threshold", ""),
                    " | ".join(str(value) for value in issue.get("header", [])),
                ]
            )
        sheet.append([])

    sheet.append(
        [
            "source_file",
            "page",
            "chunk_id",
            "local_row_index",
            "date",
            "merchant",
            "amount",
            "quality_reason",
            "validation_issues",
            "raw_cells",
            "image_ref",
        ]
    )
    review_count = len(column_issues)
    for row in rows:
        quality = _dict(row.get("quality"))
        validation = _dict(row.get("validation"))
        issues = [issue for issue in validation.get("issues", []) if isinstance(issue, dict)]
        if not quality.get("needs_review") and not validation.get("needs_review") and not issues:
            continue
        review_count += 1
        source = _dict(row.get("source"))
        raw = _dict(row.get("raw"))
        transaction = _dict(row.get("transaction"))
        sheet.append(
            [
                source.get("file", ""),
                source.get("page", ""),
                source.get("chunk_id", ""),
                source.get("local_row_index", ""),
                transaction.get("date", ""),
                transaction.get("merchant", ""),
                _number_or_blank(transaction.get("amount")),
                quality.get("review_reason", ""),
                "; ".join(str(issue.get("message", "")) for issue in issues),
                " | ".join(str(value) for value in raw.get("cells", [])),
                raw.get("image_ref", ""),
            ]
        )
    return review_count


def _style_sheet(
    sheet: Any,
    get_column_letter: Any,
    Table: Any,
    TableStyleInfo: Any,
    PatternFill: Any,
    Font: Any,
    Alignment: Any,
) -> None:
    sheet.freeze_panes = "A2"
    max_row = sheet.max_row
    max_col = sheet.max_column
    header_fill = PatternFill("solid", fgColor="176B5D")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        if cell.value is None:
            cell.value = f"column_{cell.column}"
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for column_index in range(1, max_col + 1):
        letter = get_column_letter(column_index)
        values = [sheet.cell(row=row_index, column=column_index).value for row_index in range(1, min(max_row, 80) + 1)]
        width = min(42, max(10, max(len(str(value)) if value is not None else 0 for value in values) + 2))
        sheet.column_dimensions[letter].width = width

    for row_index in range(2, max_row + 1):
        if row_index % 2 == 0:
            for cell in sheet[row_index]:
                cell.fill = PatternFill("solid", fgColor="F7FAF8")

    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, int):
                cell.number_format = '#,##0'

    if max_row >= 1 and max_col >= 1:
        table_ref = f"A1:{get_column_letter(max_col)}{max_row}"
        table_name = _safe_table_name(sheet.title)
        table = Table(displayName=table_name, ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)


def _safe_table_name(sheet_name: str) -> str:
    letters = "".join(ch for ch in sheet_name if ch.isalnum())
    if not letters:
        letters = "Sheet"
    return f"{letters}Table"


def _number_or_blank(value: Any) -> int | str:
    return value if isinstance(value, int) else ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
