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

## Sample smoke test

Sample PDFs live in `견본/`. The trailing number in each filename is the
expected page count, for example `삼성카드_3.pdf` should render 3 pages.

Run all sample PDFs through Phase 1 and check the rendered page counts:

```bash
python tests/smoke_phase1_samples.py
```
