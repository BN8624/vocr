from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.excel_exporter import ExcelExportOutput
from src.normalizer import NormalizationOutput
from src.page_renderer import PageImage
from src.profile_store import MAPPING_OPTIONS, MappingOutput
from src.reconciliation import load_section_reconciliation
from src.row_merger import RowMergeOutput
from src.validator import ValidationOutput
from src.vision_extractor import VisionResult


def build_review_html(
    output_dir: Path,
    pages: list[PageImage],
    chunks: list[ChunkImage],
    config: dict[str, Any],
    input_pdf: Path,
    vision_results: list[VisionResult] | None = None,
    merge_output: RowMergeOutput | None = None,
    mapping_output: MappingOutput | None = None,
    normalization_output: NormalizationOutput | None = None,
    validation_output: ValidationOutput | None = None,
    excel_output: ExcelExportOutput | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_path = output_dir / "review.html"
    title = str(config.get("html_title", "Card Statement Review"))

    vision_ok = sum(1 for result in vision_results or [] if result.data is not None)
    vision_errors = sum(1 for result in vision_results or [] if result.status == "error")
    mapping_review_count = _mapping_review_count(mapping_output)
    normalization_review_count = normalization_output.review_count if normalization_output else 0
    validation_issue_count = validation_output.issue_row_count if validation_output else 0
    checksum_status = validation_output.checksum_status if validation_output else "not_run"

    needs_validation = bool(validation_output and _validation_needs_judgment(validation_output))
    needs_attention = bool(mapping_review_count or normalization_review_count or validation_issue_count or needs_validation)

    html = [
        '<header class="page-title">',
        '<p class="eyebrow">AI SOP OCR</p>',
        f"<h1>{escape(title)}</h1>",
        f"<p class=\"source\">{escape(str(input_pdf))}</p>",
        "</header>",
        _summary_grid(
            [
                ("페이지", len(pages)),
                ("청크", len(chunks)),
                ("Vision", f"성공 {vision_ok} / 오류 {vision_errors}"),
                ("거래 행", _transaction_count(normalization_output, validation_output)),
                ("정규화 확인", normalization_review_count),
                ("검증 이슈", validation_issue_count),
                ("검산", _checksum_label(checksum_status)),
            ]
        ),
    ]

    if not needs_attention:
        html.append(
            '<section class="panel empty-state" id="done">'
            "<h2>확인 필요 없음</h2>"
            "<p>자동 처리 결과와 산출 파일만 확인하면 됩니다.</p>"
            "</section>"
        )
    else:
        html.append('<section class="panel" id="attention"><h2>확인 필요</h2>')
        if mapping_output and mapping_review_count:
            html.append(_simple_mapping_block(review_path, mapping_output))
        if normalization_review_count:
            html.append(
                '<article class="issue-card">'
                f"<h3>정규화 확인 {normalization_review_count}건</h3>"
                "<p>정규화 단계에서 보수적으로 확인이 필요한 행이 남아 있습니다.</p>"
                "</article>"
            )
        if validation_output and needs_validation:
            html.append(_simple_validation_block(review_path, validation_output))
        html.append("</section>")

    if excel_output:
        html.append(_simple_excel_block(review_path, excel_output))
    html.append(_simple_file_links(review_path, merge_output, mapping_output, normalization_output, validation_output))

    review_path.write_text(
        _render_template(
            title=title,
            body="\n".join(html),
            style_block=_style_block(),
            script_block=_script_block(),
        ),
        encoding="utf-8",
    )
    return review_path

def _summary_grid(items: list[tuple[str, object]]) -> str:
    cards = []
    for label, value in items:
        cards.append(
            '<div class="stat-card">'
            f"<strong>{escape(str(label))}</strong>"
            f"<span>{escape(str(value))}</span>"
            "</div>"
        )
    return '<section class="summary">' + "".join(cards) + "</section>"


def _transaction_count(
    normalization_output: NormalizationOutput | None,
    validation_output: ValidationOutput | None,
) -> int:
    if normalization_output:
        return int(normalization_output.transaction_count)
    if validation_output:
        return int(validation_output.summary.get("transaction_count", 0) or 0)
    return 0


def _simple_mapping_block(review_path: Path, mapping_output: MappingOutput) -> str:
    review_count = 0
    for group in mapping_output.table_groups:
        for column in group.get("columns", []):
            if not isinstance(column, dict) or not column.get("requires_review"):
                continue
            review_count += 1
    if not review_count:
        return ""
    return (
        '<div id="mapping" class="mapping-panel" '
        f'data-mapping-path="{escape(str(mapping_output.suggestions_path))}" '
        f'data-profile-dir="{escape(str(mapping_output.profile_dir))}">'
        '<div class="mapping-header">'
        "<h3>열 역할 확인</h3>"
        "</div>"
        f'<p class="note">자동 판정이 애매한 열 {review_count}개가 있습니다. 이 화면에서는 직접 고치지 않고 원인 확인용으로만 보여줍니다.</p>'
        '<p class="note">후보 목록은 숨겼습니다. 필요한 경우 기술 파일의 열 역할 후보 JSON만 확인합니다.</p>'
        "</div>"
    )


def _simple_validation_block(review_path: Path, validation_output: ValidationOutput) -> str:
    summary = validation_output.summary
    checksum = summary.get("checksum", {}) if isinstance(summary.get("checksum"), dict) else {}
    column_quality = summary.get("column_quality", {}) if isinstance(summary.get("column_quality"), dict) else {}
    column_issue_count = int(column_quality.get("issue_count", 0) or 0)
    parts = [
        '<article class="issue-card" id="validation">',
        "<h3>검증 확인</h3>",
        _summary_grid(
            [
                ("행 이슈", validation_output.issue_row_count),
                ("열 품질 이슈", column_issue_count),
                ("검산 상태", _checksum_label(str(checksum.get("status", validation_output.checksum_status)))),
            ]
        ),
    ]
    checksum_html = _checksum_details(review_path, review_path.parent / "merged" / "validation_summary.json", checksum)
    if checksum_html:
        parts.append(checksum_html)
    if validation_output.issues_path.exists():
        parts.append(_file_link(review_path, validation_output.issues_path, "검증 이슈 JSON"))
    parts.append("</article>")
    return "".join(parts)


def _simple_excel_block(review_path: Path, excel_output: ExcelExportOutput) -> str:
    links = [_file_link(review_path, excel_output.workbook_path, "result.xlsx")]
    return (
        '<section class="panel" id="excel">'
        "<h2>산출 파일</h2>"
        '<div class="file-links">'
        f"{''.join(links)}"
        "</div>"
        "</section>"
    )


def _simple_file_links(
    review_path: Path,
    merge_output: RowMergeOutput | None,
    mapping_output: MappingOutput | None,
    normalization_output: NormalizationOutput | None,
    validation_output: ValidationOutput | None,
) -> str:
    links = []
    if merge_output:
        links.extend(
            [
                _file_link(review_path, merge_output.rows_merged_path, "병합 행"),
                _file_link(review_path, merge_output.summary_path, "병합 요약"),
            ]
        )
    if mapping_output:
        links.append(_file_link(review_path, mapping_output.suggestions_path, "열 역할 후보"))
    if normalization_output:
        links.extend(
            [
                _file_link(review_path, normalization_output.transactions_path, "거래 JSONL"),
                _file_link(review_path, normalization_output.summary_path, "정규화 요약"),
            ]
        )
    if validation_output:
        links.extend(
            [
                _file_link(review_path, validation_output.validated_transactions_path, "검증 거래 JSONL"),
                _file_link(review_path, validation_output.summary_path, "검증 요약"),
            ]
        )
        reconciliation_path = validation_output.summary_path.parent / "section_reconciliation.json"
        if reconciliation_path.exists():
            links.append(_file_link(review_path, reconciliation_path, "섹션 검산 요약"))
    links = [link for link in links if link]
    if not links:
        return ""
    return (
        '<details class="panel technical-details">'
        "<summary>기술 파일</summary>"
        '<div class="file-links">'
        f"{''.join(links)}"
        "</div>"
        "</details>"
    )

def _review_tasks_block(
    mapping_output: MappingOutput | None,
    validation_output: ValidationOutput | None,
    excel_output: ExcelExportOutput | None,
) -> str:
    mapping_review_count = _mapping_review_count(mapping_output)
    checksum_status = validation_output.checksum_status if validation_output else "not_run"
    checksum_label = _checksum_label(checksum_status)
    issue_count = validation_output.issue_row_count if validation_output else 0
    column_issue_count = 0
    if validation_output:
        column_quality = validation_output.summary.get("column_quality", {})
        if isinstance(column_quality, dict):
            column_issue_count = int(column_quality.get("issue_count", 0) or 0)

    tasks = []
    step_number = 1
    mapping_needs = bool(mapping_output and mapping_review_count > 0)
    validation_needs = bool(validation_output and _validation_needs_judgment(validation_output))

    if mapping_needs:
        tasks.append(
            _task_item(
                number=step_number,
                title="열 매핑",
                status=f"확인 필요 {mapping_review_count}개",
                href="#mapping",
                tone="warn",
            )
        )
        step_number += 1
    if validation_needs:
        validation_status = (
            f"{checksum_label} · 행 {issue_count}개 · 열 {column_issue_count}개"
            if issue_count or column_issue_count
            else checksum_label
        )
        tasks.append(
            _task_item(
                number=step_number,
                title="검산/확인필요",
                status=validation_status,
                href="#validation",
                tone=(
                    "ok"
                    if checksum_status in {"user_confirmed_total_matched", "auto_selected_total_matched"}
                    and issue_count == 0
                    and column_issue_count == 0
                    else "warn"
                ),
            )
        )
        step_number += 1
    if excel_output:
        tasks.append(
            _task_item(
                number=step_number,
                title="Excel",
                status="생성됨",
                href="#excel",
                tone="ok",
            )
        )
        step_number += 1
    if not tasks:
        tasks.append(
            _task_item(
                number=1,
                title="판단할 항목 없음",
                status="출력 파일만 확인하면 됩니다",
                href="#done",
                tone="ok",
            )
        )
    return (
        '<section class="review-tasks">'
        "<h2>변환 확인</h2>"
        '<p class="task-lead">순서대로 확인하면 됩니다. 저장이 끝나면 다음 단계로 자동 이동합니다.</p>'
        '<div class="task-list">'
        f"{''.join(tasks)}"
        "</div>"
        "</section>"
    )


def _mapping_review_count(mapping_output: MappingOutput | None) -> int:
    if not mapping_output:
        return 0
    count = 0
    for group in mapping_output.table_groups:
        for column in group.get("columns", []):
            if isinstance(column, dict) and column.get("requires_review"):
                count += 1
    return count


def _mapping_needs_judgment(mapping_output: MappingOutput | None) -> bool:
    return _mapping_review_count(mapping_output) > 0


def _validation_needs_judgment(validation_output: ValidationOutput | None) -> bool:
    if not validation_output:
        return False
    summary = validation_output.summary
    checksum = summary.get("checksum", {}) if isinstance(summary.get("checksum"), dict) else {}
    checksum_status = str(checksum.get("status", validation_output.checksum_status))
    column_quality = summary.get("column_quality", {}) if isinstance(summary.get("column_quality"), dict) else {}
    column_issue_count = int(column_quality.get("issue_count", 0) or 0)
    needs_checksum_choice = checksum_status in {
        "no_user_total_selected",
        "user_confirmed_total_mismatch",
    } and bool(checksum.get("source_total_candidates"))
    return needs_checksum_choice or validation_output.issue_row_count > 0 or column_issue_count > 0


def _task_item(number: int, title: str, status: str, href: str, tone: str) -> str:
    target = href.lstrip("#")
    return (
        f'<a class="task-item {escape(tone)}" href="{escape(href)}" data-workflow-target="{escape(target)}">'
        f'<span class="task-number">{number}</span>'
        "<span>"
        f"<strong>{escape(title)}</strong>"
        f"<small>{escape(status)}</small>"
        "</span>"
        "</a>"
    )


def _page_crop_overlay(ratios: dict[str, float]) -> str:
    labels = {
        "header_ratio": "헤더",
        "body_start_ratio": "거래 시작",
        "body_end_ratio": "거래 끝",
        "summary_start_ratio": "합계 시작",
        "summary_end_ratio": "합계 끝",
    }
    lines = []
    for field, label in labels.items():
        percent = max(0, min(100, round(float(ratios.get(field, 0)) * 100)))
        lines.append(
            f'<span class="crop-overlay-line {escape(field)}" '
            f'data-overlay-field="{escape(field)}" style="top: {percent}%">'
            f'<em>{escape(label)}</em>'
            "</span>"
        )
    return '<div class="crop-overlay" aria-hidden="true">' + "".join(lines) + "</div>"


def _page_crop_controls(review_path: Path, page: PageImage, ratios: dict[str, float]) -> str:
    state_path = review_path.parent / "merged" / "page_crop_profile.json"
    controls = [
        ("header_ratio", "헤더 끝", ratios["header_ratio"]),
        ("body_start_ratio", "거래 시작", ratios["body_start_ratio"]),
        ("body_end_ratio", "거래 끝", ratios["body_end_ratio"]),
        ("summary_start_ratio", "합계 시작", ratios["summary_start_ratio"]),
        ("summary_end_ratio", "합계 끝", ratios["summary_end_ratio"]),
    ]
    control_html = []
    for field, label, ratio in controls:
        percent = max(0, min(100, round(ratio * 100)))
        control_html.append(
            '<label class="crop-control">'
            f"<span>{escape(label)}</span>"
            f'<input type="range" min="0" max="100" step="1" value="{percent}" data-ratio-field="{escape(field)}">'
            f"<output>{percent}%</output>"
            "</label>"
        )
    return (
        f'<details class="crop-controls" data-page-number="{page.page_number}" '
        f'data-crop-state-path="{escape(_relative_src(review_path, state_path))}">'
        "<summary>이 페이지 자르기 조정</summary>"
        '<p class="note">표 시작/끝이나 합계 위치가 잘렸을 때만 조정하세요. 저장 후 같은 명령을 --force --force-vision으로 다시 실행하면 적용됩니다.</p>'
        '<div class="crop-control-grid">'
        f"{''.join(control_html)}"
        "</div>"
        '<div class="crop-actions">'
        '<button type="button" class="save-page-crop">자르기 설정 저장</button>'
        '<span class="page-crop-message note"></span>'
        "</div>"
        "</details>"
    )


def _page_crop_ratios(page: PageImage, page_chunks: list[ChunkImage]) -> dict[str, float]:
    body_chunks = [chunk for chunk in page_chunks if "_totals_" not in chunk.chunk_id]
    total_chunks = [chunk for chunk in page_chunks if "_totals_" in chunk.chunk_id]
    header_end = _first_positive([chunk.header_y_end for chunk in body_chunks + total_chunks], int(page.height * 0.12))
    body_start = min((chunk.source_y_start for chunk in body_chunks), default=int(page.height * 0.12))
    body_end = max((chunk.source_y_end for chunk in body_chunks), default=int(page.height * 0.95))
    summary_start = min((chunk.source_y_start for chunk in total_chunks), default=int(page.height * 0.62))
    summary_end = max((chunk.source_y_end for chunk in total_chunks), default=int(page.height * 0.98))
    return {
        "header_ratio": _pixel_ratio(header_end, page.height),
        "body_start_ratio": _pixel_ratio(body_start, page.height),
        "body_end_ratio": _pixel_ratio(body_end, page.height),
        "summary_start_ratio": _pixel_ratio(summary_start, page.height),
        "summary_end_ratio": _pixel_ratio(summary_end, page.height),
    }


def _first_positive(values: list[int], fallback: int) -> int:
    for value in values:
        if value > 0:
            return value
    return fallback


def _pixel_ratio(value: int, height: int) -> float:
    if height <= 0:
        return 0
    return max(0.0, min(1.0, value / height))


def _mapping_block(review_path: Path, mapping_output: MappingOutput) -> str:
    parts = [
        f'<section id="mapping" class="mapping-panel workflow-panel" data-mapping-path="{escape(_relative_src(review_path, mapping_output.suggestions_path))}">',
        "<h2>열 매핑 확인</h2>",
        '<p class="note">AI가 읽은 열을 실제 의미에 맞게 확인하세요. 저장 버튼은 이 화면에서 JSON 파일을 내려받습니다.</p>',
        '<div class="merge-links">',
        _file_link(review_path, mapping_output.suggestions_path, "mapping_suggestions.json"),
        "</div>",
    ]
    if mapping_output.applied_profiles:
        profile_names = ", ".join(Path(path).name for path in mapping_output.applied_profiles)
        parts.append(
            f'<p class="mapping-ok">저장된 매핑 프로필 적용됨: {escape(profile_names)}</p>'
        )

    for group in mapping_output.table_groups:
        group_id = str(group.get("group_id", "unknown"))
        columns = [column for column in group.get("columns", []) if isinstance(column, dict)]
        review_columns = [column for column in columns if column.get("requires_review")]
        auto_columns = [column for column in columns if not column.get("requires_review")]
        parts.extend(
            [
                f'<article class="mapping-group" data-group-id="{escape(group_id)}">',
                f"<h3>테이블 그룹 {escape(group_id)}</h3>",
                (
                    f'<p class="note">행 {int(group.get("row_count", 0))}개 기준입니다. '
                    f'확인 필요 {len(review_columns)}개, 자동 추천 {len(auto_columns)}개.</p>'
                ),
            ]
        )
        profile_match = group.get("profile_match", {}) if isinstance(group.get("profile_match"), dict) else {}
        if profile_match.get("status") == "candidate":
            parts.append(
                '<p class="merge-warning">'
                "저장된 프로필과 비슷하지만 자동 적용하기에는 애매합니다. "
                f"점수 {float(profile_match.get('score', 0)):.2f}, "
                f"파일 {escape(Path(str(profile_match.get('profile_source', ''))).name)}"
                "</p>"
            )
        elif profile_match.get("status") == "auto":
            parts.append(
                '<p class="mapping-ok">'
                f"프로필 자동 적용 점수 {float(profile_match.get('score', 0)):.2f}"
                "</p>"
            )

        if review_columns:
            parts.append('<div class="mapping-columns mapping-review-columns">')
            for column in review_columns:
                parts.append(_mapping_column_card(review_path, column, mapping_output.option_labels, is_review=True))
            parts.append("</div>")
        else:
            parts.append('<p class="mapping-ok">확인할 애매한 열이 없습니다. 자동 추천값을 그대로 사용할 수 있습니다.</p>')

        parts.extend(
            [
                '<details class="mapping-auto-details">',
                f"<summary>자동 추천된 열 보기 ({len(auto_columns)}개)</summary>",
                '<div class="mapping-columns">',
            ]
        )
        for column in auto_columns:
            parts.append(_mapping_column_card(review_path, column, mapping_output.option_labels, is_review=False))
        parts.extend(["</div>", "</details>", "</article>"])

    parts.extend(
        [
            '<div class="mapping-actions">',
            '<button type="button" id="save-mapping">PC에 매핑 저장</button>',
            '<button type="button" id="download-mapping">매핑 JSON 내려받기</button>',
            '<span id="mapping-message" class="note"></span>',
            "</div>",
            "</section>",
        ]
    )
    return "\n".join(parts)


def _normalization_block(review_path: Path, normalization_output: NormalizationOutput) -> str:
    summary = normalization_output.summary
    review_count = normalization_output.review_count
    review_samples = [
        sample for sample in summary.get("review_samples", []) if isinstance(sample, dict)
    ]
    reason_counts = [
        item for item in summary.get("review_reason_counts", []) if isinstance(item, dict)
    ]
    parts = [
        '<section class="normalization-panel">',
        "<h2>정규화 결과</h2>",
        (
            '<p class="mapping-ok">거래 데이터로 변환했습니다. 확인필요 항목이 없으면 다음 단계에서 검증과 엑셀 출력을 진행할 수 있습니다.</p>'
            if review_count == 0
            else '<p class="merge-warning">정규화는 완료했지만 확인필요 거래가 있습니다. 원본셀은 보존했고, 애매한 값은 추측하지 않았습니다.</p>'
        ),
        '<div class="summary normalization-stats">',
        f"<div><strong>거래</strong><span>{normalization_output.transaction_count}</span></div>",
        f"<div><strong>확인필요</strong><span>{review_count}</span></div>",
        f"<div><strong>이용금액 합계</strong><span>{normalization_output.amount_total:,}</span></div>",
        f"<div><strong>결제/청구 합계</strong><span>{normalization_output.billing_amount_total:,}</span></div>",
        "</div>",
        '<div class="merge-links">',
        _file_link(review_path, normalization_output.transactions_path, "transactions.jsonl"),
        _file_link(review_path, normalization_output.summary_path, "normalization_summary.json"),
        "</div>",
    ]

    if reason_counts:
        parts.extend(
            [
                '<details class="normalization-details">',
                f"<summary>확인필요 이유 보기 ({len(reason_counts)}종류)</summary>",
                '<div class="reason-list">',
            ]
        )
        for item in reason_counts:
            parts.append(
                '<div class="reason-item">'
                f"<strong>{escape(str(item.get('count', 0)))}</strong>"
                f"<span>{escape(str(item.get('reason', '')))}</span>"
                "</div>"
            )
        parts.extend(["</div>", "</details>"])

    if review_samples:
        parts.extend(
            [
                '<details class="normalization-details">',
                f"<summary>확인필요 거래 샘플 보기 ({len(review_samples)}개)</summary>",
                '<div class="normalization-samples">',
            ]
        )
        for sample in review_samples:
            source = sample.get("source", {}) if isinstance(sample.get("source"), dict) else {}
            transaction = (
                sample.get("transaction", {}) if isinstance(sample.get("transaction"), dict) else {}
            )
            cells = [str(value) for value in sample.get("cells", [])]
            image_ref = str(sample.get("image_ref", "")).strip()
            image_link = ""
            if image_ref:
                image_link = _file_link(review_path, review_path.parent / image_ref, "원본 청크 보기")
            parts.extend(
                [
                    '<article class="normalization-sample">',
                    (
                        f"<h3>p{escape(str(source.get('page', '')))} "
                        f"{escape(str(source.get('chunk_id', '')))} "
                        f"#{escape(str(source.get('local_row_index', '')))}</h3>"
                    ),
                    '<dl class="sample-transaction">',
                    f"<div><dt>날짜</dt><dd>{escape(str(transaction.get('date', '')))}</dd></div>",
                    f"<div><dt>카드</dt><dd>{escape(str(transaction.get('card_label', '')))}</dd></div>",
                    f"<div><dt>가맹점</dt><dd>{escape(str(transaction.get('merchant', '')))}</dd></div>",
                    f"<div><dt>금액</dt><dd>{escape(str(transaction.get('amount', '')))}</dd></div>",
                    "</dl>",
                    f'<p class="warning">{escape(str(sample.get("review_reason", "")))}</p>',
                    f'<p class="note">원본셀: {escape(" | ".join(cells))}</p>',
                    image_link,
                    "</article>",
                ]
            )
        parts.extend(["</div>", "</details>"])

    parts.append("</section>")
    return "\n".join(parts)


def _validation_block(review_path: Path, validation_output: ValidationOutput) -> str:
    summary = validation_output.summary
    checksum = summary.get("checksum", {}) if isinstance(summary.get("checksum"), dict) else {}
    column_quality = summary.get("column_quality", {}) if isinstance(summary.get("column_quality"), dict) else {}
    issue_counts = [
        item for item in summary.get("issue_counts", []) if isinstance(item, dict)
    ]
    review_samples = [
        sample for sample in summary.get("review_samples", []) if isinstance(sample, dict)
    ]
    checksum_status = str(checksum.get("status", validation_output.checksum_status))
    checksum_message = str(checksum.get("message", ""))
    column_issue_count = int(column_quality.get("issue_count", 0) or 0)
    parts = [
        '<section id="validation" class="validation-panel workflow-panel">',
        "<h2>내 판단 필요</h2>",
        '<p class="note">정상으로 처리된 항목은 숨겼습니다. 아래 카드만 확인하면 됩니다.</p>',
        '<div class="summary validation-stats compact-stats">',
        f"<div><strong>거래</strong><span>{validation_output.transaction_count}</span></div>",
        f"<div><strong>문제 행</strong><span>{validation_output.issue_row_count}</span></div>",
        f"<div><strong>열 문제</strong><span>{column_issue_count}</span></div>",
        f'<div><strong>검산</strong><span id="checksum-status-badge">{escape(_checksum_label(checksum_status))}</span></div>',
        "</div>",
        '<div class="judgment-list">',
    ]

    parts.append(_checksum_details(review_path, validation_output.summary_path.parent / "review_state.json", checksum))
    parts.append(_column_quality_details(column_quality))

    if issue_counts:
        parts.extend(
            [
                '<section class="judgment-card">',
                "<h3>행 경고 유형</h3>",
                '<p class="note">같은 문제는 묶어서 보여줍니다. 실제 행은 아래 카드에서 확인하세요.</p>',
                '<div class="reason-list">',
            ]
        )
        for item in issue_counts:
            parts.append(
                '<div class="reason-item">'
                f"<strong>{escape(str(item.get('count', 0)))}</strong>"
                f"<span>{escape(str(item.get('label') or item.get('code') or ''))}</span>"
                "</div>"
            )
        parts.extend(["</div>", "</section>"])

    if review_samples:
        parts.extend(
            [
                '<section class="judgment-card">',
                f"<h3>확인필요 행 {len(review_samples)}개</h3>",
                '<p class="note">여기 있는 행만 원본셀과 비교하면 됩니다.</p>',
                '<div class="normalization-samples">',
            ]
        )
        for sample in review_samples:
            source = sample.get("source", {}) if isinstance(sample.get("source"), dict) else {}
            transaction = (
                sample.get("transaction", {}) if isinstance(sample.get("transaction"), dict) else {}
            )
            issues = [issue for issue in sample.get("issues", []) if isinstance(issue, dict)]
            issue_text = "; ".join(str(issue.get("message", "")) for issue in issues)
            cells = [str(value) for value in sample.get("cells", [])]
            image_ref = str(sample.get("image_ref", "")).strip()
            image_link = ""
            if image_ref:
                image_link = _file_link(review_path, review_path.parent / image_ref, "원본 청크 보기")
            parts.extend(
                [
                    '<article class="normalization-sample">',
                    (
                        f"<h3>p{escape(str(source.get('page', '')))} "
                        f"{escape(str(source.get('chunk_id', '')))} "
                        f"#{escape(str(source.get('local_row_index', '')))}</h3>"
                    ),
                    '<dl class="sample-transaction">',
                    f"<div><dt>날짜</dt><dd>{escape(str(transaction.get('date', '')))}</dd></div>",
                    f"<div><dt>카드</dt><dd>{escape(str(transaction.get('card_label', '')))}</dd></div>",
                    f"<div><dt>가맹점</dt><dd>{escape(str(transaction.get('merchant', '')))}</dd></div>",
                    f"<div><dt>금액</dt><dd>{escape(str(transaction.get('amount', '')))}</dd></div>",
                    "</dl>",
                    f'<p class="warning">{escape(issue_text)}</p>',
                    f'<p class="note">원본셀: {escape(" | ".join(cells))}</p>',
                    image_link,
                    "</article>",
                ]
            )
        parts.extend(["</div>", "</section>"])

    parts.extend(
        [
            "</div>",
            '<details class="validation-details technical-details">',
            "<summary>기술 파일 보기</summary>",
            '<div class="merge-links">',
            _file_link(review_path, validation_output.validated_transactions_path, "transactions_validated.jsonl"),
            _file_link(review_path, validation_output.issues_path, "validation_issues.json"),
            _file_link(review_path, validation_output.summary_path, "validation_summary.json"),
            "</div>",
            "</details>",
            "</section>",
        ]
    )
    return "\n".join(parts)


def _column_quality_details(column_quality: dict[str, Any]) -> str:
    issues = [issue for issue in column_quality.get("issues", []) if isinstance(issue, dict)]
    if not issues:
        return ""

    issue_cards = []
    for issue in issues:
        header = " | ".join(str(value) for value in issue.get("header", []))
        issue_cards.append(
            '<article class="column-issue">'
            f"<h3>{escape(str(issue.get('label') or issue.get('code') or '열 문제'))}</h3>"
            f"<p>{escape(str(issue.get('message', '')))}</p>"
            f'<p class="note">{escape(header)}</p>'
            "</article>"
        )

    return (
        '<section class="judgment-card">'
        f"<h3>열 섞임 의심 {len(issues)}개</h3>"
        '<p class="note">사람이 이 화면에서 고칠 항목은 아닙니다. 자동 규칙 개선 대상입니다.</p>'
        '<div class="column-quality-list">'
        f"{''.join(issue_cards) if issue_cards else '<p class=\"mapping-ok\">열 품질 문제는 없습니다.</p>'}"
        "</div>"
        "</section>"
    )


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return ""


def _excel_block(review_path: Path, excel_output: ExcelExportOutput) -> str:
    sheet_text = ", ".join(excel_output.sheet_names) if excel_output.sheet_names else "전체명세, 검산, 원본셀, 추가필드, 확인필요"
    return "\n".join(
        [
            '<section id="excel" class="excel-panel workflow-panel">',
            "<h2>엑셀 출력</h2>",
            '<p class="mapping-ok">검증 결과를 포함한 엑셀 파일을 만들었습니다. 확인필요 행도 숨기지 않고 별도 시트에 담았습니다.</p>',
            '<div class="summary excel-stats">',
            f"<div><strong>거래</strong><span>{excel_output.transaction_count}</span></div>",
            f"<div><strong>확인필요</strong><span>{excel_output.review_count}</span></div>",
            f"<div><strong>시트</strong><span>{escape(sheet_text)}</span></div>",
            "</div>",
            '<div class="merge-links">',
            _file_link(review_path, excel_output.workbook_path, excel_output.workbook_path.name),
            "</div>",
            "</section>",
        ]
    )


def _checksum_details(review_path: Path, state_path: Path, checksum: dict[str, Any]) -> str:
    candidates = [
        item for item in checksum.get("source_total_candidates", []) if isinstance(item, dict)
    ]
    if not candidates:
        return ""
    status = str(checksum.get("status", ""))
    if status not in {"no_user_total_selected", "user_confirmed_total_mismatch"}:
        return ""
    amount_total = checksum.get("amount_total", "")
    billing_amount_total = checksum.get("billing_amount_total", "")
    auto_matches = [
        item for item in checksum.get("auto_match_candidates", []) if isinstance(item, dict)
    ]
    reason = "자동으로 확정할 수 있는 합계 후보가 없습니다."
    if auto_matches:
        reason = "자동 일치 후보가 있으나 우선순위가 충분히 안전하지 않습니다."
    reconciliation = load_section_reconciliation(review_path.parent / "merged")
    reconciliation_html = _section_reconciliation_summary(reconciliation)
    return (
        '<section class="judgment-card checksum-review">'
        "<h3>검산 보류</h3>"
        f'<p id="checksum-status-line" class="merge-warning" data-checksum-status="{escape(status)}">'
        f'{escape(_checksum_label(status))}: {escape(str(checksum.get("message", "")))}</p>'
        f"<p class=\"note\">{escape(reason)} 사람이 이 화면에서 고르는 대신 원인 분석 대상입니다.</p>"
        '<div class="summary validation-stats compact-stats">'
        f"<div><strong>거래 합계</strong><span>{escape(_format_amount(amount_total))}</span></div>"
        f"<div><strong>청구 합계</strong><span>{escape(_format_amount(billing_amount_total))}</span></div>"
        f"<div><strong>원본 후보</strong><span>{len(candidates)}</span></div>"
        "</div>"
        f"{reconciliation_html}"
        '<p class="note">원본 합계 후보 목록은 숨겼습니다. 필요한 경우 기술 파일의 검증 요약 JSON만 확인합니다.</p>'
        "</section>"
    )


def _section_reconciliation_summary(reconciliation: dict[str, Any] | None) -> str:
    if not reconciliation:
        return ""
    pairs = [pair for pair in reconciliation.get("pairs", []) if isinstance(pair, dict)]
    if not pairs:
        return ""
    rows = []
    for pair in pairs:
        pages = pair.get("pages", [])
        page_text = "-".join(str(page) for page in pages) if isinstance(pages, list) else str(pages)
        source_total = pair.get("source_total", {}) if isinstance(pair.get("source_total"), dict) else {}
        source_amount = source_total.get("amount", "")
        difference = pair.get("difference", "")
        explanation = pair.get("explanation", {}) if isinstance(pair.get("explanation"), dict) else {}
        raw_summary = _raw_adjustment_summary(pair.get("raw_adjustment_totals", {}))
        rows.append(
            '<div class="reason-item">'
            f"<strong>{escape(page_text)}</strong>"
            f"<span>원본 {escape(_format_amount(source_amount))} · 거래 {escape(_format_amount(pair.get('amount_total', '')))} · 차이 {escape(_format_amount(difference))} · {escape(str(explanation.get('status', '')))}{raw_summary}</span>"
            "</div>"
        )
    return (
        '<details class="technical-details">'
        f"<summary>페이지 묶음별 섹션 검산 보기 ({len(rows)}개)</summary>"
        '<div class="reason-list">'
        f"{''.join(rows)}"
        "</div>"
        "</details>"
    )


def _raw_adjustment_summary(raw_adjustments: Any) -> str:
    if not isinstance(raw_adjustments, dict):
        return ""
    parts = []
    for section, totals in raw_adjustments.items():
        if not isinstance(totals, dict):
            continue
        amount = totals.get("unique_amount_total")
        count = totals.get("unique_row_count")
        if not amount:
            continue
        parts.append(f"{section} {count}건 {_format_amount(amount)}")
    if not parts:
        return ""
    return " · 제외행 " + ", ".join(parts)


def _format_amount(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _checksum_label(status: str) -> str:
    labels = {
        "auto_selected_total_matched": "검산 자동 일치",
        "user_confirmed_total_matched": "검산 일치",
        "user_confirmed_total_mismatch": "검산 불일치",
        "no_user_total_selected": "검산 기준 미선택",
        "no_source_total": "원본 합계 없음",
        "incomplete_source_scan": "합계 확인 미완료",
    }
    return labels.get(status, status)


def _mapping_column_card(
    review_path: Path,
    column: dict[str, Any],
    option_labels: dict[str, str],
    is_review: bool,
) -> str:
    suggested = str(column.get("suggested_field", "extra"))
    option_html = _mapping_options_html(option_labels, suggested)
    samples = [str(value) for value in column.get("sample_values", [])]
    sample_html = "".join(f"<li>{escape(value)}</li>" for value in samples) or "<li>샘플 없음</li>"
    review_reason = str(column.get("review_reason", ""))
    position = column.get("position", {}) if isinstance(column.get("position"), dict) else {}
    card_class = "mapping-column needs-review" if is_review else "mapping-column auto"
    badge = '<span class="review-badge">확인필요</span>' if is_review else '<span class="auto-badge">자동추천</span>'
    review_text = f'<p class="warning">{escape(review_reason)}</p>' if review_reason else ""
    position_block = _mapping_position_block(position)
    source_links = _mapping_source_links(review_path, column)
    return "\n".join(
        [
            f'<article class="{card_class}">',
            f'<h4>{badge} {escape(str(column.get("column_id", "")))} · {escape(str(column.get("header", "")))}</h4>',
            position_block,
            source_links,
            '<label>',
            "<span>필드 선택</span>",
            (
                f'<select data-column-id="{escape(str(column.get("column_id", "")))}" '
                f'data-header="{escape(str(column.get("header", "")))}" '
                f'data-suggested="{escape(suggested)}">'
                f"{option_html}"
                "</select>"
            ),
            "</label>",
            f'<p class="note">추천: {escape(option_labels.get(suggested, suggested))} · {escape(str(column.get("confidence", "")))}</p>',
            f'<p class="note">{escape(str(column.get("reason", "")))}</p>',
            review_text,
            f"<ul>{sample_html}</ul>",
            "</article>",
        ]
    )


def _mapping_position_block(position: dict[str, Any]) -> str:
    if not position:
        return ""
    index = int(position.get("index", 0) or 0)
    total = int(position.get("total", 0) or 0)
    left_header = str(position.get("left_header", "") or "없음")
    right_header = str(position.get("right_header", "") or "없음")
    cells = []
    for cell_index in range(1, total + 1):
        active_class = " active" if cell_index == index else ""
        label = str(cell_index) if cell_index == index else ""
        title = f"{cell_index}번째 열"
        cells.append(f'<span class="position-cell{active_class}" title="{escape(title)}">{escape(label)}</span>')
    return (
        '<div class="position-hint">'
        f'<p><strong>위치</strong> 전체 {total}열 중 {index}번째</p>'
        f'<div class="position-cells" style="grid-template-columns: repeat({total}, minmax(12px, 1fr));">'
        f"{''.join(cells)}"
        "</div>"
        f'<dl><div><dt>왼쪽</dt><dd>{escape(left_header)}</dd></div>'
        f'<div><dt>오른쪽</dt><dd>{escape(right_header)}</dd></div></dl>'
        "</div>"
    )


def _mapping_source_links(review_path: Path, column: dict[str, Any]) -> str:
    refs = [str(ref) for ref in column.get("source_image_refs", []) if str(ref).strip()]
    if not refs:
        return ""
    links = []
    for index, ref in enumerate(refs[:2], start=1):
        target = review_path.parent / ref
        links.append(_file_link(review_path, target, f"원본 청크 {index} 보기"))
    return f'<div class="mapping-source-links">{"".join(links)}</div>'


def _mapping_options_html(option_labels: dict[str, str], selected: str) -> str:
    options = []
    for option in MAPPING_OPTIONS:
        label = option_labels.get(option, option)
        selected_attr = " selected" if option == selected else ""
        options.append(f'<option value="{escape(option)}"{selected_attr}>{escape(label)}</option>')
    return "".join(options)


def _merge_block(review_path: Path, merge_output: RowMergeOutput) -> str:
    has_duplicates = merge_output.duplicate_group_count > 0
    representative_count = int(merge_output.summary.get("representative_count", 0))
    duplicate_excluded_count = int(merge_output.summary.get("duplicate_excluded_count", 0))
    duplicate_review_count = int(merge_output.summary.get("duplicate_review_count", 0))
    parts = [
        '<section class="merge-summary">',
        "<h2>행 병합 검토</h2>",
        (
            '<p class="mapping-ok">중복 후보가 없습니다. 원본 행을 그대로 거래 후보로 사용합니다.</p>'
            if not has_duplicates
            else '<p class="mapping-ok">겹침 청크의 같은 raw cells는 대표행 1개만 거래로 사용하고, 제외행은 원본셀 보존용으로 남깁니다.</p>'
        ),
        '<div class="summary merge-stats">',
        f"<div><strong>원본 행</strong><span>{merge_output.raw_row_count}</span></div>",
        f"<div><strong>거래 후보</strong><span>{merge_output.summary.get('transaction_candidate_count', merge_output.merged_row_count)}</span></div>",
        f"<div><strong>중복 그룹</strong><span>{merge_output.duplicate_group_count}</span></div>",
        f"<div><strong>대표행</strong><span>{representative_count}</span></div>",
        f"<div><strong>원본셀 보존 제외행</strong><span>{duplicate_excluded_count}</span></div>",
        f"<div><strong>확인필요 중복</strong><span>{duplicate_review_count}</span></div>",
        "</div>",
        '<div class="merge-links">',
        _file_link(review_path, merge_output.rows_raw_path, "rows_raw.jsonl"),
        _file_link(review_path, merge_output.rows_merged_path, "rows_merged.jsonl"),
        _file_link(review_path, merge_output.summary_path, "merge_summary.json"),
        "</div>",
    ]

    duplicate_groups = merge_output.summary.get("duplicate_groups", [])
    if duplicate_groups:
        parts.extend(
            [
                '<details class="duplicate-details">',
                f"<summary>중복 처리 자세히 보기 ({len(duplicate_groups)}개 그룹)</summary>",
                '<div class="duplicate-groups">',
            ]
        )
        for group in duplicate_groups:
            rows = group.get("rows", [])
            row_labels = ", ".join(
                f"{row.get('chunk_id')} 행 {row.get('local_row_index')}={row.get('decision', '')}" for row in rows
            )
            representative = group.get("representative", {})
            representative_label = ""
            if isinstance(representative, dict) and representative:
                representative_label = (
                    f"{representative.get('chunk_id')} 행 {representative.get('local_row_index')}"
                )
            parts.extend(
                [
                    '<article class="duplicate-group">',
                    f"<h3>{escape(str(group.get('group_id', '중복 후보')))}</h3>",
                    f"<p>{escape(str(group.get('reason', '')))}</p>",
                    f"<p><strong>대표행:</strong> {escape(representative_label)}</p>",
                    f"<p><strong>대상:</strong> {escape(row_labels)}</p>",
                    "</article>",
                ]
            )
        parts.extend(["</div>", "</details>"])

    parts.append("</section>")
    return "\n".join(parts)


def _vision_block(
    review_path: Path,
    result: VisionResult | None,
    merge_output: RowMergeOutput | None,
) -> str:
    if result is None:
        return '<section class="vision empty"><h4>AI 추출 결과</h4><p>아직 추출 결과가 없습니다.</p></section>'

    if result.data is None:
        links = []
        if result.error_path:
            links.append(_file_link(review_path, result.error_path, "오류 JSON"))
        if result.raw_text_path:
            links.append(_file_link(review_path, result.raw_text_path, "원문 응답"))
        link_html = " ".join(links) if links else ""
        return (
            '<section class="vision error">'
            "<h4>AI 추출 결과</h4>"
            f"<p>상태: {escape(_status_label(result.status))} {link_html}</p>"
            "</section>"
        )

    data = result.data
    header = [str(value) for value in data.get("header", [])]
    rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
    totals = [total for total in data.get("totals", []) if isinstance(total, dict)]
    needs_review = bool(data.get("needs_review"))

    parts = [
        '<section class="vision">',
        "<h4>AI 추출 결과</h4>",
        '<div class="vision-status">',
        f"<span>상태: {escape(_status_label(result.status))}</span>",
        f"<span>행: {len(rows)}</span>",
        f"<span>합계: {len(totals)}</span>",
        f"<span>{'청크 확인필요' if needs_review else '청크 경고 없음'}</span>",
        _file_link(review_path, result.cache_path, "JSON 열기"),
        "</div>",
    ]
    if data.get("review_reason"):
        parts.append(f'<p class="warning">{escape(str(data["review_reason"]))}</p>')
    if data.get("notes"):
        parts.append(f'<p class="note">{escape(str(data["notes"]))}</p>')

    duplicate_index = merge_output.duplicate_index if merge_output else {}
    duplicate_decision_index = merge_output.duplicate_decision_index if merge_output else {}
    parts.append(_rows_table(header, rows, result.chunk_id, duplicate_index, duplicate_decision_index))
    if totals:
        parts.append(_totals_table(totals))
    parts.append("</section>")
    return "\n".join(parts)


def _rows_table(
    header: list[str],
    rows: list[dict[str, Any]],
    chunk_id: str,
    duplicate_index: dict[tuple[str, int], str],
    duplicate_decision_index: dict[tuple[str, int], dict[str, Any]],
) -> str:
    if not rows:
        return '<p class="empty-note">이 청크에서 거래 행을 찾지 못했습니다.</p>'

    max_cells = max([len(header)] + [len(row.get("cells", [])) for row in rows])
    labels = header + [f"col_{index}" for index in range(len(header) + 1, max_cells + 1)]
    head = "".join(f"<th>{escape(label)}</th>" for label in labels)
    body_rows = []
    cards = []
    for row in rows:
        cells = [str(value) for value in row.get("cells", [])]
        padded = cells + [""] * (max_cells - len(cells))
        local_index = escape(str(row.get("local_row_index", "")))
        duplicate_key = (chunk_id, _safe_int(row.get("local_row_index"), 0))
        duplicate_group = duplicate_index.get(duplicate_key, "")
        duplicate_decision = str(duplicate_decision_index.get(duplicate_key, {}).get("decision", ""))
        row_needs_review = bool(row.get("needs_review") or duplicate_decision == "needs_review")
        row_class = ' class="needs-review"' if row_needs_review else ""
        reason = str(row.get("review_reason") or row.get("confidence_note") or "")
        tds = "".join(f"<td>{escape(value)}</td>" for value in padded)
        review_parts = []
        if row.get("needs_review"):
            review_parts.append(f'<span class="review-badge">확인필요</span> {escape(reason)}')
        elif reason:
            review_parts.append(escape(reason))
        if duplicate_group:
            review_parts.append(
                f'<span class="review-badge duplicate">{escape(_merge_decision_label(duplicate_decision))} {escape(duplicate_group)}</span>'
            )
        review_value = " ".join(review_parts)
        body_rows.append(
            f"<tr{row_class}><th>{local_index}</th>{tds}"
            f"<td>{review_value}</td></tr>"
        )

        field_rows = []
        for label, value in zip(labels, padded):
            if value:
                field_rows.append(
                    '<div class="row-field">'
                    f"<dt>{escape(label)}</dt>"
                    f"<dd>{escape(value)}</dd>"
                    "</div>"
                )
        if review_value:
            field_rows.append(
                '<div class="row-field review-field">'
                "<dt>확인</dt>"
                f"<dd>{review_value}</dd>"
                "</div>"
            )
        card_class = "row-card needs-review" if row_needs_review else "row-card"
        cards.append(
            f'<article class="{card_class}">'
            f'<h5>행 {local_index}</h5>'
            f"<dl>{''.join(field_rows)}</dl>"
            "</article>"
        )

    return (
        '<div class="table-wrap rows-table-wrap"><table class="extract-table">'
        f"<thead><tr><th>#</th>{head}<th>확인</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
        f'<div class="row-card-list">{"".join(cards)}</div>'
    )


def _totals_table(totals: list[dict[str, Any]]) -> str:
    rows = []
    cards = []
    for total in totals:
        row_class = ' class="needs-review"' if total.get("needs_review") else ""
        label = escape(str(total.get("label", "")))
        value_text = escape(str(total.get("value_text", "")))
        amount = escape(str(total.get("amount", "")))
        reason = escape(str(total.get("review_reason", "")))
        rows.append(
            f"<tr{row_class}>"
            f"<td>{label}</td>"
            f"<td>{value_text}</td>"
            f"<td>{amount}</td>"
            f"<td>{reason}</td>"
            "</tr>"
        )
        card_class = "total-card needs-review" if total.get("needs_review") else "total-card"
        cards.append(
            f'<article class="{card_class}">'
            f"<h5>{label or '합계'}</h5>"
            "<dl>"
            f'<div class="row-field"><dt>표시값</dt><dd>{value_text}</dd></div>'
            f'<div class="row-field"><dt>숫자값</dt><dd>{amount}</dd></div>'
            f'<div class="row-field review-field"><dt>확인</dt><dd>{reason}</dd></div>'
            "</dl>"
            "</article>"
        )
    return (
        '<div class="table-wrap totals-table-wrap"><table class="totals-table">'
        "<thead><tr><th>합계 항목</th><th>표시값</th><th>숫자값</th><th>확인</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
        f'<div class="total-card-list">{"".join(cards)}</div>'
    )


def _status_label(status: str) -> str:
    labels = {
        "ok": "완료",
        "cached": "캐시됨",
        "error": "오류",
    }
    return labels.get(status, status)


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _merge_decision_label(decision: str) -> str:
    labels = {
        "representative": "대표행",
        "duplicate_excluded": "원본셀 보존",
        "needs_review": "중복 확인필요",
    }
    return labels.get(decision, "중복")


def _file_link(review_path: Path, target: Path, label: str) -> str:
    try:
        href = _relative_src(review_path, target)
    except ValueError:
        href = str(target)
    return f'<a class="file-link" href="{escape(href)}">{escape(label)}</a>'


def _relative_src(base_file: Path, target: Path) -> str:
    return target.resolve().relative_to(base_file.parent.resolve()).as_posix()


def _script_block() -> str:
    return f"<script>\n{_read_asset('review.js')}\n</script>"


def _style_block() -> str:
    return f"<style>\n{_read_asset('review.css')}\n</style>"


def _render_template(title: str, body: str, style_block: str, script_block: str) -> str:
    template_path = Path(__file__).resolve().parents[1] / "templates" / "review.html"
    template = template_path.read_text(encoding="utf-8")
    return (
        template.replace("{{ title }}", escape(title))
        .replace("{{ style_block }}", style_block)
        .replace("{{ body }}", body)
        .replace("{{ script_block }}", script_block)
    )


def _read_asset(filename: str) -> str:
    asset_path = Path(__file__).resolve().parents[1] / "static" / filename
    return asset_path.read_text(encoding="utf-8").strip()
