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

Set a Gemini API key in the environment or in local `.env`:

```text
GEMINI_API_KEY=your_key_here
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

## Sample smoke test

Sample PDFs live in `견본/`. The trailing number in each filename is the
expected page count, for example `삼성카드_3.pdf` should render 3 pages.

Run all sample PDFs through Phase 1 and check the rendered page counts:

```bash
python tests/smoke_phase1_samples.py
```
