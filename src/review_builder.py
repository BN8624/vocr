from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage


def build_review_html(
    output_dir: Path,
    pages: list[PageImage],
    chunks: list[ChunkImage],
    config: dict[str, Any],
    input_pdf: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_path = output_dir / "review.html"
    title = str(config.get("html_title", "Card Statement Review"))

    chunks_by_page: dict[int, list[ChunkImage]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_page[chunk.page_number].append(chunk)

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
        "<div><strong>LLM calls</strong><span>0</span></div>",
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
                    "</article>",
                ]
            )

        html.extend(["</div>", "</div>", "</section>"])

    html.extend(["</main>", "</body>", "</html>"])
    review_path.write_text("\n".join(html), encoding="utf-8")
    return review_path


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
