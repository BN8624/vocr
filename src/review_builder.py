from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.excel_exporter import ExcelExportOutput
from src.normalizer import NormalizationOutput
from src.page_renderer import PageImage
from src.profile_store import MAPPING_OPTIONS, MappingOutput
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

    chunks_by_page: dict[int, list[ChunkImage]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_page[chunk.page_number].append(chunk)

    vision_by_chunk = {result.chunk_id: result for result in vision_results or []}
    vision_ok = sum(1 for result in vision_by_chunk.values() if result.data is not None)
    vision_errors = sum(1 for result in vision_by_chunk.values() if result.status == "error")

    html = [
        "<!doctype html>",
        '<html lang="ko">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        _style_block(),
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{escape(title)}</h1>",
        '<section class="summary">',
        f"<div><strong>입력 PDF</strong><span>{escape(str(input_pdf))}</span></div>",
        f"<div><strong>페이지</strong><span>{len(pages)}</span></div>",
        f"<div><strong>청크</strong><span>{len(chunks)}</span></div>",
        f"<div><strong>AI 추출</strong><span>성공 {vision_ok} / 오류 {vision_errors}</span></div>",
        "</section>",
    ]
    if merge_output:
        html.append(_merge_block(review_path, merge_output))
    if mapping_output:
        html.append(_mapping_block(review_path, mapping_output))
    if normalization_output:
        html.append(_normalization_block(review_path, normalization_output))
    if validation_output:
        html.append(_validation_block(review_path, validation_output))
    if excel_output:
        html.append(_excel_block(review_path, excel_output))

    for page in pages:
        page_src = _relative_src(review_path, page.image_path)
        html.extend(
            [
                '<section class="page-section">',
                f"<h2>{escape(page.page_id)}</h2>",
                '<div class="page-grid">',
                '<figure class="page-image">',
                f'<img src="{escape(page_src)}" alt="{escape(page.page_id)}">',
                "<figcaption>",
                f"{page.width} x {page.height}px, {page.dpi} DPI",
                " 캐시 사용" if page.reused else " 새로 생성",
                "</figcaption>",
                "</figure>",
                '<div class="chunks">',
            ]
        )

        for chunk in chunks_by_page.get(page.page_number, []):
            chunk_src = _relative_src(review_path, chunk.image_path)
            vision = vision_by_chunk.get(chunk.chunk_id)
            html.extend(
                [
                    '<article class="chunk">',
                    f"<h3>{escape(chunk.chunk_id)}</h3>",
                    f'<img src="{escape(chunk_src)}" alt="{escape(chunk.chunk_id)}">',
                    f'<p class="chunk-action"><a class="file-link" href="{escape(chunk_src)}" target="_blank">원본 청크 크게 보기</a></p>',
                    '<dl class="meta">',
                    "<dt>본문 위치</dt>",
                    f"<dd>y {chunk.source_y_start} to {chunk.source_y_end}</dd>",
                    "<dt>헤더 위치</dt>",
                    f"<dd>y {chunk.header_y_start} to {chunk.header_y_end}</dd>",
                    "<dt>상태</dt>",
                    f"<dd>{'캐시 사용' if chunk.reused else '새로 생성'}</dd>",
                    "</dl>",
                    _vision_block(review_path, vision, merge_output),
                    "</article>",
                ]
            )

        html.extend(["</div>", "</div>", "</section>"])

    html.extend([_script_block(), "</main>", "</body>", "</html>"])
    review_path.write_text("\n".join(html), encoding="utf-8")
    return review_path


def _mapping_block(review_path: Path, mapping_output: MappingOutput) -> str:
    parts = [
        '<section class="mapping-panel">',
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
    checksum_class = "mapping-ok" if checksum_status == "user_confirmed_total_matched" else "merge-warning"
    row_ok = validation_output.issue_row_count == 0
    column_issue_count = int(column_quality.get("issue_count", 0) or 0)
    column_ok = column_issue_count == 0
    parts = [
        '<section class="validation-panel">',
        "<h2>검증 결과</h2>",
        f'<p class="{checksum_class}">{escape(_checksum_label(checksum_status))}: {escape(checksum_message)}</p>',
        (
            '<p class="mapping-ok">행 단위 이상 징후는 없습니다.</p>'
            if row_ok
            else '<p class="merge-warning">행 단위 확인필요 항목이 있습니다. 원본셀과 청크 링크로 바로 확인할 수 있습니다.</p>'
        ),
        (
            '<p class="mapping-ok">열 단위 오염 징후는 없습니다.</p>'
            if column_ok
            else '<p class="merge-warning">열 단위 확인필요 항목이 있습니다. 카드명/가맹점/금액 열이 섞였는지 확인하세요.</p>'
        ),
        '<div class="summary validation-stats">',
        f"<div><strong>거래</strong><span>{validation_output.transaction_count}</span></div>",
        f"<div><strong>문제 행</strong><span>{validation_output.issue_row_count}</span></div>",
        f"<div><strong>문제 수</strong><span>{validation_output.row_issue_count}</span></div>",
        f"<div><strong>열 문제</strong><span>{column_issue_count}</span></div>",
        f"<div><strong>검산</strong><span>{escape(_checksum_label(checksum_status))}</span></div>",
        "</div>",
        '<div class="merge-links">',
        _file_link(review_path, validation_output.validated_transactions_path, "transactions_validated.jsonl"),
        _file_link(review_path, validation_output.issues_path, "validation_issues.json"),
        _file_link(review_path, validation_output.summary_path, "validation_summary.json"),
        "</div>",
    ]

    parts.append(_checksum_details(review_path, validation_output.summary_path.parent / "review_state.json", checksum))
    parts.append(_column_quality_details(column_quality))

    if issue_counts:
        parts.extend(
            [
                '<details class="validation-details">',
                f"<summary>행 문제 유형 보기 ({len(issue_counts)}종류)</summary>",
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
        parts.extend(["</div>", "</details>"])

    if review_samples:
        parts.extend(
            [
                '<details class="validation-details">',
                f"<summary>확인필요 행 샘플 보기 ({len(review_samples)}개)</summary>",
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
        parts.extend(["</div>", "</details>"])

    parts.append("</section>")
    return "\n".join(parts)


def _column_quality_details(column_quality: dict[str, Any]) -> str:
    issues = [issue for issue in column_quality.get("issues", []) if isinstance(issue, dict)]
    groups = [group for group in column_quality.get("groups", []) if isinstance(group, dict)]
    if not issues and not groups:
        return ""

    issue_cards = []
    for issue in issues:
        header = " | ".join(str(value) for value in issue.get("header", []))
        issue_cards.append(
            '<article class="column-issue">'
            f"<h3>{escape(str(issue.get('label') or issue.get('code') or '열 문제'))}</h3>"
            f"<p>{escape(str(issue.get('message', '')))}</p>"
            f"<dl><div><dt>필드</dt><dd>{escape(str(issue.get('field', '')))}</dd></div>"
            f"<div><dt>값</dt><dd>{escape(str(issue.get('value', '')))}</dd></div>"
            f"<div><dt>기준</dt><dd>{escape(str(issue.get('threshold', '')))}</dd></div>"
            f"<div><dt>헤더</dt><dd>{escape(header)}</dd></div></dl>"
            "</article>"
        )

    metric_cards = []
    for group in groups[:6]:
        metrics = group.get("metrics", {}) if isinstance(group.get("metrics"), dict) else {}
        distribution = metrics.get("row_cell_count_distribution", {})
        counts = distribution.get("counts", {}) if isinstance(distribution, dict) else {}
        metric_cards.append(
            '<article class="column-metrics">'
            f"<h3>{escape(str(group.get('group_id', 'table')))}</h3>"
            "<dl>"
            f"<div><dt>행</dt><dd>{escape(str(group.get('row_count', '')))}</dd></div>"
            f"<div><dt>날짜 성공률</dt><dd>{escape(_percent(metrics.get('date_parse_success_rate')))}</dd></div>"
            f"<div><dt>금액 성공률</dt><dd>{escape(_percent(metrics.get('amount_parse_success_rate')))}</dd></div>"
            f"<div><dt>가맹점 숫자</dt><dd>{escape(_percent(metrics.get('merchant_numeric_like_rate')))}</dd></div>"
            f"<div><dt>가맹점 빈 값</dt><dd>{escape(_percent(metrics.get('merchant_empty_rate')))}</dd></div>"
            f"<div><dt>카드명 고유값</dt><dd>{escape(str(metrics.get('card_label_unique_count', '')))}</dd></div>"
            f"<div><dt>셀 개수</dt><dd>{escape(str(counts))}</dd></div>"
            "</dl>"
            "</article>"
        )

    return (
        '<details class="validation-details">'
        f"<summary>열 품질 보기 (문제 {len(issues)}개)</summary>"
        '<div class="column-quality-list">'
        f"{''.join(issue_cards) if issue_cards else '<p class=\"mapping-ok\">열 품질 문제는 없습니다.</p>'}"
        f"{''.join(metric_cards)}"
        "</div>"
        "</details>"
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
            '<section class="excel-panel">',
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
    selected_total_id = str(checksum.get("selected_total_id", ""))
    auto_match_ids = {
        str(item.get("candidate", {}).get("id", ""))
        for item in checksum.get("auto_match_candidates", [])
        if isinstance(item, dict) and isinstance(item.get("candidate"), dict)
    }
    candidate_items = []
    for candidate in candidates[:12]:
        candidate_id = str(candidate.get("id", ""))
        checked = " checked" if candidate_id and candidate_id == selected_total_id else ""
        marker = "선택됨" if checked else ("자동일치" if candidate_id in auto_match_ids else "후보")
        candidate_json = escape(json.dumps(candidate, ensure_ascii=False))
        input_html = (
            f'<input type="radio" name="checksum-total" value="{escape(candidate_id)}" '
            f'data-candidate="{candidate_json}"{checked}>'
        )
        candidate_items.append(
            '<div class="checksum-candidate">'
            "<label>"
            f"{input_html}"
            f"<strong>{escape(marker)}</strong>"
            f"<span>{escape(str(candidate.get('label', '원본 합계')))}: {escape(str(candidate.get('amount', '')))}</span>"
            "</label>"
            "</div>"
        )
    return (
        '<details class="validation-details">'
        f"<summary>검산 기준 원본 합계 선택 ({len(candidates)}개 후보)</summary>"
        f'<div class="checksum-candidates" data-state-path="{escape(_relative_src(review_path, state_path))}">'
        f"{''.join(candidate_items)}"
        "</div>"
        '<div class="checksum-actions">'
        '<button type="button" id="save-checksum-total">검산 기준 저장</button>'
        '<span id="checksum-message" class="note"></span>'
        "</div>"
        '<p class="note">저장 후 같은 명령을 다시 실행하면 선택한 원본 합계만 기준으로 검산합니다.</p>'
        "</details>"
    )


def _checksum_label(status: str) -> str:
    labels = {
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
    return """
<script>
(() => {
  const saveButton = document.getElementById('save-mapping');
  const downloadButton = document.getElementById('download-mapping');
  const message = document.getElementById('mapping-message');
  const saveChecksumButton = document.getElementById('save-checksum-total');
  const checksumMessage = document.getElementById('checksum-message');

  const collectPayload = (status) => {
    const groups = [...document.querySelectorAll('.mapping-group')].map(group => {
      const columns = [...group.querySelectorAll('select')].map(select => ({
        column_id: select.dataset.columnId || '',
        header: select.dataset.header || '',
        suggested_field: select.dataset.suggested || '',
        selected_field: select.value
      }));
      return {
        group_id: group.dataset.groupId || '',
        columns
      };
    });
    return {
      schema_version: '1.0',
      status,
      created_at: new Date().toISOString(),
      table_groups: groups
    };
  };

  const downloadPayload = (payload) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'mapping-profile.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  if (saveButton) {
    saveButton.addEventListener('click', async () => {
      const payload = collectPayload('user_confirmed_save_request');
      if (message) message.textContent = 'PC에 매핑을 저장하는 중입니다...';
      try {
        const response = await fetch('/api/mapping-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
        if (message) message.textContent = `PC profiles 폴더에 저장했습니다: ${result.filename}`;
      } catch (error) {
        if (message) message.textContent = '저장 서버가 없거나 실패했습니다. JSON 내려받기를 사용하세요.';
      }
    });
  }

  if (downloadButton) {
    downloadButton.addEventListener('click', () => {
      downloadPayload(collectPayload('user_confirmed_download'));
      if (message) message.textContent = '매핑 JSON을 내려받았습니다.';
    });
  }

  if (saveChecksumButton) {
    saveChecksumButton.addEventListener('click', async () => {
      const container = document.querySelector('.checksum-candidates');
      const selected = document.querySelector('input[name="checksum-total"]:checked');
      if (!container || !selected) {
        if (checksumMessage) checksumMessage.textContent = '먼저 원본 합계를 선택하세요.';
        return;
      }
      let candidate = {};
      try {
        candidate = JSON.parse(selected.dataset.candidate || '{}');
      } catch (error) {
        candidate = {};
      }
      const statePath = new URL(container.dataset.statePath || 'merged/review_state.json', window.location.href).pathname;
      const payload = {
        schema_version: '1.0',
        status: 'user_confirmed_review_state',
        state_path: statePath,
        checksum: {
          selected_total_id: selected.value,
          selected_total: candidate
        }
      };
      if (checksumMessage) checksumMessage.textContent = '검산 기준을 PC에 저장하는 중입니다...';
      try {
        const response = await fetch('/api/review-state', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
        if (checksumMessage) checksumMessage.textContent = '저장했습니다. 같은 명령을 다시 실행하면 검산에 반영됩니다.';
      } catch (error) {
        if (checksumMessage) checksumMessage.textContent = '저장 서버가 없거나 실패했습니다. serve_review.py로 열어 주세요.';
      }
    });
  }
})();
</script>
""".strip()


def _style_block() -> str:
    return """
<style>
:root {
  color-scheme: light;
  --bg: #f7f7f4;
  --panel: #ffffff;
  --ink: #202124;
  --muted: #5f6368;
  --line: #d6d9d2;
  --accent: #176b5d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--ink);
  background: var(--bg);
}
main {
  width: min(1440px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 48px;
}
h1 {
  margin: 0 0 18px;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}
h2 {
  margin: 0 0 14px;
  font-size: 22px;
  letter-spacing: 0;
}
h3 {
  margin: 0 0 10px;
  font-size: 15px;
  letter-spacing: 0;
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
  margin-bottom: 22px;
}
.summary div {
  min-width: 0;
  padding: 12px 14px;
  background: var(--panel);
}
.merge-summary {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 2px solid var(--line);
}
.merge-summary h2 {
  margin-bottom: 12px;
}
.merge-stats {
  margin-bottom: 10px;
}
.merge-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.merge-warning {
  margin: 10px 0;
  border: 1px solid #e2a35d;
  border-radius: 8px;
  background: #fff5e8;
  color: #8a3f00;
  padding: 10px;
  font-size: 14px;
  font-weight: 700;
}
.duplicate-details {
  margin-top: 10px;
}
.duplicate-details summary {
  min-height: 36px;
  border: 1px solid #e2a35d;
  border-radius: 8px;
  background: #fff5e8;
  color: #8a3f00;
  padding: 8px 10px;
  cursor: pointer;
  font-weight: 700;
}
.duplicate-details[open] summary {
  margin-bottom: 10px;
}
.duplicate-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}
.duplicate-group {
  border: 1px solid #e2a35d;
  border-radius: 8px;
  background: #fff5e8;
  padding: 10px;
}
.duplicate-group h3 {
  margin-bottom: 6px;
}
.duplicate-group p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.45;
}
.mapping-panel {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 2px solid var(--line);
}
.normalization-panel {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 2px solid var(--line);
}
.validation-panel {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 2px solid var(--line);
}
.excel-panel {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 2px solid var(--line);
}
.normalization-stats {
  margin-bottom: 10px;
}
.validation-stats {
  margin-bottom: 10px;
}
.excel-stats {
  margin-bottom: 10px;
}
.normalization-details {
  margin-top: 10px;
}
.validation-details {
  margin-top: 10px;
}
.normalization-details summary {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfbf9;
  padding: 8px 10px;
  cursor: pointer;
  color: var(--accent);
  font-weight: 700;
}
.validation-details summary {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfbf9;
  padding: 8px 10px;
  cursor: pointer;
  color: var(--accent);
  font-weight: 700;
}
.normalization-details[open] summary {
  margin-bottom: 10px;
}
.validation-details[open] summary {
  margin-bottom: 10px;
}
.reason-list,
.normalization-samples,
.checksum-candidates,
.column-quality-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}
.reason-item,
.normalization-sample,
.checksum-candidate,
.column-issue,
.column-metrics {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 10px;
}
.column-issue {
  border-color: #e2a35d;
  background: #fff5e8;
}
.column-issue h3,
.column-metrics h3 {
  margin-bottom: 8px;
}
.column-issue dl,
.column-metrics dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
  margin: 8px 0 0;
}
.column-issue dl div,
.column-metrics dl div {
  min-width: 0;
  background: #fff;
  padding: 7px;
}
.column-issue dt,
.column-metrics dt {
  color: var(--muted);
  font-size: 11px;
}
.column-issue dd,
.column-metrics dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.reason-item {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 8px;
  align-items: start;
}
.reason-item strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  border-radius: 6px;
  background: #eef4f1;
  color: var(--accent);
}
.reason-item span {
  min-width: 0;
  overflow-wrap: anywhere;
  line-height: 1.4;
}
.checksum-candidate {
  display: grid;
  align-items: start;
}
.checksum-candidate label {
  display: grid;
  grid-template-columns: 22px 68px 1fr;
  gap: 8px;
  align-items: start;
  cursor: pointer;
}
.checksum-candidate input {
  margin-top: 2px;
}
.checksum-candidate strong {
  color: var(--accent);
}
.checksum-candidate span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.checksum-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}
.checksum-actions button {
  min-height: 36px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  padding: 8px 12px;
  font-weight: 700;
  cursor: pointer;
}
.normalization-sample h3 {
  margin-bottom: 8px;
}
.sample-transaction {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
  margin: 0 0 8px;
}
.sample-transaction div {
  min-width: 0;
  background: #fff;
  padding: 7px;
}
.sample-transaction dt {
  color: var(--muted);
  font-size: 11px;
}
.sample-transaction dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.mapping-panel > .note {
  margin-top: 0;
}
.mapping-group {
  margin-top: 14px;
}
.mapping-columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}
.mapping-column {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 10px;
}
.mapping-column.needs-review {
  border-color: #e2a35d;
  background: #fffaf2;
}
.mapping-column.auto {
  background: #fbfbf9;
}
.mapping-column h4 {
  margin: 0 0 10px;
  font-size: 14px;
  line-height: 1.35;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}
.position-hint {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 8px;
  margin: 8px 0 10px;
}
.position-hint p {
  margin: 0 0 7px;
  font-size: 13px;
}
.position-cells {
  display: grid;
  gap: 2px;
  margin: 8px 0;
}
.position-cell {
  min-width: 0;
  height: 24px;
  border: 1px solid #cfd8d3;
  border-radius: 4px;
  background: #edf3f0;
  color: transparent;
}
.position-cell.active {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-color: #11594d;
  background: #176b5d;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.position-hint dl {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 0;
}
.position-hint dt {
  color: var(--muted);
  font-size: 11px;
}
.position-hint dd {
  margin: 2px 0 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.mapping-source-links {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  margin-bottom: 10px;
}
.mapping-source-links .file-link {
  justify-content: center;
}
.mapping-ok {
  margin: 10px 0;
  border: 1px solid #bdd8cb;
  border-radius: 8px;
  background: #eef8f3;
  color: #235c4d;
  padding: 10px;
  font-size: 14px;
}
.mapping-auto-details {
  margin-top: 12px;
}
.mapping-auto-details summary {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfbf9;
  padding: 8px 10px;
  cursor: pointer;
  color: var(--accent);
  font-weight: 700;
}
.mapping-auto-details[open] summary {
  margin-bottom: 10px;
}
.mapping-column label span {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 12px;
}
.mapping-column select {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  font-size: 15px;
  padding: 6px 8px;
}
.mapping-column ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.45;
}
.mapping-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.mapping-actions button {
  min-height: 40px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-weight: 700;
  padding: 8px 14px;
}
.summary strong,
.summary span {
  display: block;
}
.summary strong {
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--muted);
}
.summary span {
  overflow-wrap: anywhere;
}
.page-section {
  margin-top: 28px;
  padding-top: 22px;
  border-top: 2px solid var(--line);
}
.page-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(320px, 1.1fr);
  gap: 18px;
  align-items: start;
}
figure {
  margin: 0;
}
.page-image,
.chunk {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 12px;
}
.page-image img,
.chunk img {
  display: block;
  width: 100%;
  height: auto;
  border: 1px solid var(--line);
  background: #fff;
}
figcaption {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
}
.chunks {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.meta {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 4px 10px;
  margin: 10px 0 0;
  font-size: 13px;
}
.meta dt {
  color: var(--muted);
}
.meta dd {
  margin: 0;
}
.chunk-action {
  margin: 8px 0 0;
}
.chunk-action .file-link {
  width: 100%;
  justify-content: center;
}
.vision {
  margin-top: 12px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.vision h4 {
  margin: 0 0 8px;
  font-size: 14px;
  letter-spacing: 0;
}
.vision p {
  margin: 8px 0 0;
  font-size: 13px;
}
.vision-status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
}
.vision-status span,
.file-link {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 3px 7px;
  background: #fbfbf9;
}
.file-link {
  color: var(--accent);
  text-decoration: none;
}
.warning {
  color: #9f3a2f;
  font-weight: 700;
}
.note,
.empty-note {
  color: var(--muted);
}
.table-wrap {
  width: 100%;
  overflow-x: auto;
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
table {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
  font-size: 12px;
  background: #fff;
}
th,
td {
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #eef4f1;
  font-weight: 700;
}
tr.needs-review td,
tr.needs-review th {
  background: #fff5e8;
}
.row-card-list,
.total-card-list {
  display: none;
}
.row-card,
.total-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  margin-top: 10px;
}
.row-card.needs-review,
.total-card.needs-review {
  border-color: #e2a35d;
  background: #fff5e8;
}
.row-card h5,
.total-card h5 {
  margin: 0 0 8px;
  font-size: 14px;
  letter-spacing: 0;
}
.row-card dl,
.total-card dl {
  margin: 0;
}
.row-field {
  display: grid;
  grid-template-columns: minmax(82px, 36%) 1fr;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid var(--line);
}
.row-field:first-child {
  border-top: 0;
}
.row-field dt {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}
.row-field dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.35;
}
.review-field dd {
  color: #8a3f00;
  font-weight: 700;
}
.review-badge {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  margin-right: 6px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #cf6f1d;
  color: #fff;
  font-weight: 700;
  white-space: nowrap;
}
.review-badge.duplicate {
  background: #7b5cbd;
}
.auto-badge {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  margin-right: 6px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #dfe9e4;
  color: #31584e;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
@media (max-width: 900px) {
  main {
    width: 100%;
    padding: 12px 10px 32px;
  }
  h1 {
    font-size: 22px;
    margin-bottom: 12px;
  }
  h2 {
    font-size: 18px;
  }
  .page-grid {
    grid-template-columns: 1fr;
  }
  .summary {
    grid-template-columns: 1fr 1fr;
    margin-bottom: 16px;
  }
  .summary div {
    padding: 10px;
  }
  .merge-links {
    display: grid;
    grid-template-columns: 1fr;
  }
  .merge-links .file-link {
    justify-content: center;
  }
  .duplicate-groups {
    grid-template-columns: 1fr;
  }
  .mapping-columns {
    grid-template-columns: 1fr;
  }
  .mapping-actions button {
    width: 100%;
  }
  .chunks {
    grid-template-columns: 1fr;
  }
  .page-image,
  .chunk {
    padding: 10px;
  }
  .chunk img {
    max-height: none;
  }
  .vision-status {
    gap: 6px;
  }
  .vision-status span,
  .file-link {
    min-height: 30px;
    font-size: 13px;
  }
  .rows-table-wrap,
  .totals-table-wrap {
    display: none;
  }
  .row-card-list,
  .total-card-list {
    display: block;
  }
}
@media (max-width: 420px) {
  .summary {
    grid-template-columns: 1fr;
  }
  .row-field {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>
""".strip()
