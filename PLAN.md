# PLAN.md

## Mission

Build a local Python tool that converts image-based Korean credit card statement PDFs into structured, reviewable data and finally Excel.

The tool must not be OCR-first. The primary extraction path is:

```text
PDF page image
-> overlapping table chunks with header
-> Vision LLM JSON rows/cells
-> conservative merge
-> user-visible mapping review
-> normalization
-> validation
-> Excel export
```

The first-class review artifact is `review.html`, not Excel. Excel is exported only after raw cells, mappings, normalization, and validation artifacts exist.

## Current Implementation Status

Implemented:

- Phase 1: PDF page rendering and chunk building
- Phase 2/3: Gemini Vision extraction, cache, and raw row review
- Phase 3B: targeted page summary/total chunks for checksum candidates
- Phase 4: conservative row collection, exact duplicate representative selection, and raw-cell preservation for excluded duplicates
- Phase 5: column mapping suggestions and mobile-friendly mapping UI
- Phase 5B: saved mapping profile reuse from `profiles/*.json` or `--mapping-profile`
- Phase 5C: `serve_review.py` review server for saving confirmed mappings directly from iPhone/Browser
- Phase 6: transaction normalization into `transactions.jsonl`
- Phase 7: validation into `transactions_validated.jsonl`, `validation_summary.json`, and `validation_issues.json`
- Phase 7B: user-selected checksum total saved in `merged/review_state.json`
- Phase 7C: column-level validation for date, amount, merchant, card label, and row cell-count distribution
- Phase 7D: table-signature profile matching with auto/candidate thresholds
- Phase 7E: review-state save refreshes validation summary from cached Vision results in the review server
- Phase 7F: page-level crop profile saved from review UI and applied to chunk/total extraction on rerun
- Phase 7G: visual crop overlays on page images for header/body/summary slider positions
- Phase 8: Excel export to `result.xlsx`

Generated Excel sheets:

- `전체명세`
- `검산`
- `원본셀`
- `추가필드`
- `확인필요`

## Non-Negotiable Rules

1. Do not build an OCR-first pipeline.
2. Do not hard-code card-company-specific parsers as the main strategy.
3. Do not trust amount checksum alone.
4. Always preserve raw cells.
5. Avoid precision-coordinate dependency.
6. Cache expensive or external steps.
7. Expose results visually.
8. Mark uncertainty instead of guessing.

## Repository Shape

```text
.
├── AGENTS.md
├── PLAN.md
├── README.md
├── config.yaml
├── requirements.txt
├── main.py
├── serve_review.py
├── src/
│   ├── page_renderer.py
│   ├── chunk_builder.py
│   ├── vision_extractor.py
│   ├── row_merger.py
│   ├── normalizer.py
│   ├── validator.py
│   ├── review_builder.py
│   ├── profile_store.py
│   └── excel_exporter.py
├── prompts/
│   ├── vision_extract_table.md
│   └── vision_repair_rows.md
├── profiles/
│   └── README.md
├── samples/
│   └── .gitkeep
├── output/
│   └── .gitkeep
└── tests/
    └── smoke_phase1_samples.py
```

## Output Contract

Main output folder:

```text
output/
├── pages/
├── chunks/
├── total_chunks/
├── cache/
├── merged/
│   ├── rows_raw.jsonl
│   ├── rows_merged.jsonl
│   ├── merge_summary.json
│   ├── mapping_suggestions.json
│   ├── transactions.jsonl
│   ├── transactions_validated.jsonl
│   ├── normalization_summary.json
│   ├── validation_summary.json
│   └── validation_issues.json
├── review.html
├── result.xlsx
└── summary.json
```

Canonical row shape keeps:

- `source.file`
- `source.page`
- `source.chunk_id`
- `source.local_row_index`
- `raw.header`
- `raw.cells`
- `raw.image_ref`
- normalized `transaction`
- `extra_fields`
- `quality`
- `validation`

## Review UI Requirements

`review.html` should show:

- input summary
- page images
- chunk images
- Vision extracted rows/cells
- totals detected by Vision
- duplicate candidates
- mapping suggestions
- mapping profile save/download controls
- normalization summary
- validation summary
- Excel output link

Mobile/iPhone constraints:

- avoid wide mandatory tables for core review
- use cards or collapsed details for noisy sections
- show only ambiguous mapping columns first
- collapse confident automatic mappings
- show source chunk links for position-dependent columns

## Mapping Profiles

Confirmed mappings can be saved in two ways:

1. `PC에 매핑 저장` from `review.html` when served by `serve_review.py`
2. `매핑 JSON 내려받기` and manual placement under `profiles/`

Profiles under `profiles/*.json` are loaded automatically. A specific profile can also be passed with:

```bash
python main.py --input samples/card.pdf --output output --dry-run --mapping-profile profiles/mapping-profile.json
```

Profiles are hints. Validation still runs and raw cells are preserved.

## Validation Requirements

Implemented checks include:

- amount checksum against Vision total candidates
- incomplete source scan state when not all chunks have Vision results
- date-like transaction date
- numeric amount and billing amount
- merchant numeric contamination
- card label merchant-like contamination
- row cell count consistency
- duplicate candidate propagation from merge step
- exact duplicate representative rows are used for transactions; excluded duplicates remain in raw cells only
- checksum uses the user-selected source total when `merged/review_state.json` is present
- column-level validation catches table-wide contamination even when row totals look plausible
- total-only chunks can capture summary totals without reprocessing every transaction body chunk
- mapping profiles can match by table signature, not only exact header/group id
- `serve_review.py` refreshes `validation_summary.json` immediately after saving a checksum choice when cached Vision and normalized transactions already exist
- page-level crop profiles can adjust header/body/summary ratios for difficult pages without changing global config
- crop sliders update colored overlay lines on the page image before rerunning extraction

Checksum status meanings:

- `user_confirmed_total_matched`: selected source total matches extracted amount or billing total
- `user_confirmed_total_mismatch`: selected source total differs from extracted totals
- `no_user_total_selected`: source totals exist, but the user has not selected the checksum basis yet
- `no_source_total`: all available chunks were processed and no source total was found
- `incomplete_source_scan`: only some chunks have Vision results, so a later page/chunk may still contain totals

## Excel Requirements

`result.xlsx` must:

- use numeric cells for amounts
- include source file/page/chunk/row identifiers
- include raw cells
- include extra fields
- include validation summary
- include review flags and reasons
- keep uncertain rows visible

## Local Review Server

Use the review server when reviewing from iPhone over Tailscale and saving mappings back to the PC:

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

Then open:

```text
http://<tailscale-ip>:8012/output/review.html
```

or an output-specific path such as:

```text
http://<tailscale-ip>:8012/output/gemini_smoke/review.html
```

## Git and Secret Policy

Do not commit:

- `.env`
- API keys
- `output/`
- sample/견본 PDFs
- user mapping profile JSON files

Keep `.gitignore` enforcing those boundaries.

## Suggested Next Work

Good next improvements:

1. Add more validation tests with tiny fixture JSONL files.
2. Split `review_builder.py` into template/static assets once behavior stabilizes.
3. Add a small profile management CLI for listing/removing saved profiles.
