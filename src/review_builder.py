from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage
from src.profile_store import MAPPING_OPTIONS, MappingOutput
from src.row_merger import RowMergeOutput
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

        if review_columns:
            parts.append('<div class="mapping-columns mapping-review-columns">')
            for column in review_columns:
                parts.append(_mapping_column_card(column, mapping_output.option_labels, is_review=True))
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
            parts.append(_mapping_column_card(column, mapping_output.option_labels, is_review=False))
        parts.extend(["</div>", "</details>", "</article>"])

    parts.extend(
        [
            '<div class="mapping-actions">',
            '<button type="button" id="download-mapping">매핑 JSON 내려받기</button>',
            '<span id="mapping-message" class="note"></span>',
            "</div>",
            "</section>",
        ]
    )
    return "\n".join(parts)


def _mapping_column_card(
    column: dict[str, Any],
    option_labels: dict[str, str],
    is_review: bool,
) -> str:
    suggested = str(column.get("suggested_field", "extra"))
    option_html = _mapping_options_html(option_labels, suggested)
    samples = [str(value) for value in column.get("sample_values", [])]
    sample_html = "".join(f"<li>{escape(value)}</li>" for value in samples) or "<li>샘플 없음</li>"
    review_reason = str(column.get("review_reason", ""))
    card_class = "mapping-column needs-review" if is_review else "mapping-column auto"
    badge = '<span class="review-badge">확인필요</span>' if is_review else '<span class="auto-badge">자동추천</span>'
    review_text = f'<p class="warning">{escape(review_reason)}</p>' if review_reason else ""
    return "\n".join(
        [
            f'<article class="{card_class}">',
            f'<h4>{badge} {escape(str(column.get("column_id", "")))} · {escape(str(column.get("header", "")))}</h4>',
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


def _mapping_options_html(option_labels: dict[str, str], selected: str) -> str:
    options = []
    for option in MAPPING_OPTIONS:
        label = option_labels.get(option, option)
        selected_attr = " selected" if option == selected else ""
        options.append(f'<option value="{escape(option)}"{selected_attr}>{escape(label)}</option>')
    return "".join(options)


def _merge_block(review_path: Path, merge_output: RowMergeOutput) -> str:
    parts = [
        '<section class="merge-summary">',
        "<h2>행 병합 검토</h2>",
        '<div class="summary merge-stats">',
        f"<div><strong>원본 행</strong><span>{merge_output.raw_row_count}</span></div>",
        f"<div><strong>병합 출력 행</strong><span>{merge_output.merged_row_count}</span></div>",
        f"<div><strong>중복 후보 그룹</strong><span>{merge_output.duplicate_group_count}</span></div>",
        f"<div><strong>중복 후보 행</strong><span>{merge_output.duplicate_row_count}</span></div>",
        "</div>",
        '<div class="merge-links">',
        _file_link(review_path, merge_output.rows_raw_path, "rows_raw.jsonl"),
        _file_link(review_path, merge_output.rows_merged_path, "rows_merged.jsonl"),
        _file_link(review_path, merge_output.summary_path, "merge_summary.json"),
        "</div>",
    ]

    duplicate_groups = merge_output.summary.get("duplicate_groups", [])
    if duplicate_groups:
        parts.append('<div class="duplicate-groups">')
        for group in duplicate_groups:
            rows = group.get("rows", [])
            row_labels = ", ".join(
                f"{row.get('chunk_id')} 행 {row.get('local_row_index')}" for row in rows
            )
            parts.extend(
                [
                    '<article class="duplicate-group">',
                    f"<h3>{escape(str(group.get('group_id', '중복 후보')))}</h3>",
                    f"<p>{escape(str(group.get('reason', '')))}</p>",
                    f"<p><strong>대상:</strong> {escape(row_labels)}</p>",
                    "</article>",
                ]
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty-note">현재 확인된 중복 후보가 없습니다.</p>')

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
    parts.append(_rows_table(header, rows, result.chunk_id, duplicate_index))
    if totals:
        parts.append(_totals_table(totals))
    parts.append("</section>")
    return "\n".join(parts)


def _rows_table(
    header: list[str],
    rows: list[dict[str, Any]],
    chunk_id: str,
    duplicate_index: dict[tuple[str, int], str],
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
        duplicate_group = duplicate_index.get((chunk_id, _safe_int(row.get("local_row_index"), 0)), "")
        row_needs_review = bool(row.get("needs_review") or duplicate_group)
        row_class = ' class="needs-review"' if row_needs_review else ""
        reason = str(row.get("review_reason") or row.get("confidence_note") or "")
        tds = "".join(f"<td>{escape(value)}</td>" for value in padded)
        review_parts = []
        if row.get("needs_review"):
            review_parts.append(f'<span class="review-badge">확인필요</span> {escape(reason)}')
        elif reason:
            review_parts.append(escape(reason))
        if duplicate_group:
            review_parts.append(f'<span class="review-badge duplicate">중복후보 {escape(duplicate_group)}</span>')
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
  const button = document.getElementById('download-mapping');
  const message = document.getElementById('mapping-message');
  if (!button) return;
  button.addEventListener('click', () => {
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
    const payload = {
      schema_version: '1.0',
      status: 'user_confirmed_download',
      created_at: new Date().toISOString(),
      table_groups: groups
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'mapping-profile.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    if (message) message.textContent = '매핑 JSON을 내려받았습니다.';
  });
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
