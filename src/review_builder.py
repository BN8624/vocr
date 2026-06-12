from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage
from src.vision_extractor import VisionResult


def build_review_html(
    output_dir: Path,
    pages: list[PageImage],
    chunks: list[ChunkImage],
    config: dict[str, Any],
    input_pdf: Path,
    vision_results: list[VisionResult] | None = None,
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
        '<html lang="en">',
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
        f"<div><strong>Input</strong><span>{escape(str(input_pdf))}</span></div>",
        f"<div><strong>Pages</strong><span>{len(pages)}</span></div>",
        f"<div><strong>Chunks</strong><span>{len(chunks)}</span></div>",
        f"<div><strong>Vision JSON</strong><span>{vision_ok} ok / {vision_errors} errors</span></div>",
        "</section>",
    ]

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
                " reused" if page.reused else " rendered",
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
                    '<dl class="meta">',
                    "<dt>Body crop</dt>",
                    f"<dd>y {chunk.source_y_start} to {chunk.source_y_end}</dd>",
                    "<dt>Header crop</dt>",
                    f"<dd>y {chunk.header_y_start} to {chunk.header_y_end}</dd>",
                    "<dt>Status</dt>",
                    f"<dd>{'reused from cache' if chunk.reused else 'created'}</dd>",
                    "</dl>",
                    _vision_block(review_path, vision),
                    "</article>",
                ]
            )

        html.extend(["</div>", "</div>", "</section>"])

    html.extend(["</main>", "</body>", "</html>"])
    review_path.write_text("\n".join(html), encoding="utf-8")
    return review_path


def _vision_block(review_path: Path, result: VisionResult | None) -> str:
    if result is None:
        return '<section class="vision empty"><h4>Vision Extraction</h4><p>No cached extraction yet.</p></section>'

    if result.data is None:
        links = []
        if result.error_path:
            links.append(_file_link(review_path, result.error_path, "error json"))
        if result.raw_text_path:
            links.append(_file_link(review_path, result.raw_text_path, "raw text"))
        link_html = " ".join(links) if links else ""
        return (
            '<section class="vision error">'
            "<h4>Vision Extraction</h4>"
            f"<p>Status: {escape(result.status)} {link_html}</p>"
            "</section>"
        )

    data = result.data
    header = [str(value) for value in data.get("header", [])]
    rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
    totals = [total for total in data.get("totals", []) if isinstance(total, dict)]
    needs_review = bool(data.get("needs_review"))

    parts = [
        '<section class="vision">',
        "<h4>Vision Extraction</h4>",
        '<div class="vision-status">',
        f"<span>Status: {escape(result.status)}</span>",
        f"<span>Rows: {len(rows)}</span>",
        f"<span>Totals: {len(totals)}</span>",
        f"<span>{'Needs review' if needs_review else 'No chunk-level warning'}</span>",
        _file_link(review_path, result.cache_path, "json"),
        "</div>",
    ]
    if data.get("review_reason"):
        parts.append(f'<p class="warning">{escape(str(data["review_reason"]))}</p>')
    if data.get("notes"):
        parts.append(f'<p class="note">{escape(str(data["notes"]))}</p>')

    parts.append(_rows_table(header, rows))
    if totals:
        parts.append(_totals_table(totals))
    parts.append("</section>")
    return "\n".join(parts)


def _rows_table(header: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty-note">No transaction rows found in this chunk.</p>'

    max_cells = max([len(header)] + [len(row.get("cells", [])) for row in rows])
    labels = header + [f"col_{index}" for index in range(len(header) + 1, max_cells + 1)]
    head = "".join(f"<th>{escape(label)}</th>" for label in labels)
    body_rows = []
    for row in rows:
        cells = [str(value) for value in row.get("cells", [])]
        padded = cells + [""] * (max_cells - len(cells))
        row_class = ' class="needs-review"' if row.get("needs_review") else ""
        reason = str(row.get("review_reason") or row.get("confidence_note") or "")
        tds = "".join(f"<td>{escape(value)}</td>" for value in padded)
        local_index = escape(str(row.get("local_row_index", "")))
        body_rows.append(
            f"<tr{row_class}><th>{local_index}</th>{tds}"
            f"<td>{escape(reason)}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table class="extract-table">'
        f"<thead><tr><th>#</th>{head}<th>review</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def _totals_table(totals: list[dict[str, Any]]) -> str:
    rows = []
    for total in totals:
        row_class = ' class="needs-review"' if total.get("needs_review") else ""
        rows.append(
            f"<tr{row_class}>"
            f"<td>{escape(str(total.get('label', '')))}</td>"
            f"<td>{escape(str(total.get('value_text', '')))}</td>"
            f"<td>{escape(str(total.get('amount', '')))}</td>"
            f"<td>{escape(str(total.get('review_reason', '')))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="totals-table">'
        "<thead><tr><th>Total label</th><th>Value</th><th>Amount</th><th>Review</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _file_link(review_path: Path, target: Path, label: str) -> str:
    try:
        href = _relative_src(review_path, target)
    except ValueError:
        href = str(target)
    return f'<a class="file-link" href="{escape(href)}">{escape(label)}</a>'


def _relative_src(base_file: Path, target: Path) -> str:
    return target.resolve().relative_to(base_file.parent.resolve()).as_posix()


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
@media (max-width: 900px) {
  main {
    width: min(100% - 20px, 760px);
    padding-top: 16px;
  }
  .page-grid {
    grid-template-columns: 1fr;
  }
}
</style>
""".strip()
