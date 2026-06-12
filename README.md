# vocr

Local Python pipeline for image-based Korean card statement PDFs.

Phase 1 builds inspectable page images, overlapping header+body chunks, and
`output/review.html` without calling any external Vision LLM API.

## Setup

```bash
pip install -r requirements.txt
```

## Phase 1 dry run

```bash
python main.py --input samples/card.pdf --output output --dry-run
```

The command writes:

- `output/pages/page_001.png`
- `output/chunks/page_001_chunk_01.png`
- `output/pages/pages_manifest.json`
- `output/chunks/chunks_manifest.json`
- `output/review.html`
- `output/summary.json`

Use `--force` to rebuild cached page and chunk images.

## Phase 2 and 3 Vision extraction

Set a Gemini API key in the environment or in local `.env`.
Either name is accepted:

```text
GEMINI_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
```

Then run without `--dry-run`:

```bash
python main.py --input 견본/삼성카드_1.pdf --output output
```

For a small API smoke test, process only the first chunk:

```bash
python main.py --input 견본/삼성카드_1.pdf --output output --limit-chunks 1
```

Vision responses are cached under `output/cache/*.vision.json`. Re-running
uses cache unless `--force-vision` is passed. `review.html` shows each chunk
image next to extracted headers, raw cells, totals, review flags, and JSON
cache links.

## Phase 4 duplicate candidate review

When cached Vision JSON exists, the pipeline also writes:

- `output/merged/rows_raw.jsonl`
- `output/merged/rows_merged.jsonl`
- `output/merged/merge_summary.json`

Phase 4 is intentionally conservative. It does not delete rows. Rows repeated
across overlapping chunks are marked as duplicate candidates and shown in
`review.html` for manual review.

## Phase 5 column mapping review

When merged rows exist, the pipeline writes:

- `output/merged/mapping_suggestions.json`

`review.html` shows a mobile-friendly column mapping panel. Confident automatic
matches are collapsed, and only ambiguous or conflicting columns are shown first.
The user can adjust those columns with select menus. Each mapping card includes
the approximate column order, neighboring headers, and source chunk links because
amount-only columns often require visual position context. The browser can
download `mapping-profile.json`.

To reuse a downloaded mapping, put it under `profiles/` or pass it explicitly:

```bash
python main.py --input samples/card.pdf --output output --dry-run --mapping-profile profiles/mapping-profile.json
```

Profiles in `profiles/*.json` are loaded automatically on future runs.

For iPhone review, use the local review server instead of a plain static server
when you want the "PC에 매핑 저장" button to save directly into `profiles/`:

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

Then open `http://<tailscale-ip>:8012/output/review.html` or the matching
output folder URL. If the save server is not running, the review page still lets
you download `mapping-profile.json`.

## Phase 6 to 8 normalized data, validation, and Excel

When cached Vision rows and mapping suggestions exist, the pipeline also writes:

- `output/merged/transactions.jsonl`
- `output/merged/transactions_validated.jsonl`
- `output/merged/normalization_summary.json`
- `output/merged/validation_summary.json`
- `output/merged/validation_issues.json`
- `output/result.xlsx`

`review.html` shows normalization, validation, and Excel export sections. Excel
contains `전체명세`, `검산`, `원본셀`, `추가필드`, and `확인필요` sheets. Rows that
need review are not hidden or discarded.

## Sample smoke test

Sample PDFs live in `견본/`. The trailing number in each filename is the
expected page count, for example `삼성카드_3.pdf` should render 3 pages.

Run all sample PDFs through Phase 1 and check the rendered page counts:

```bash
python tests/smoke_phase1_samples.py
```
