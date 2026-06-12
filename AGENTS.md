# AGENTS.md

## Project Mission

Build a local Python tool that converts image-based Korean credit card statement PDFs into structured, reviewable data and finally into Excel.

This project must not rely on traditional OCR as the primary extraction method. Previous attempts with OCR failed on complex statement tables. The core strategy is:

```text
Python = image preparation, chunking, caching, validation, review UI, Excel export
Vision LLM = visually read table chunks and return rows/cells JSON
Text LLM = optional post-processing and anomaly detection
User = confirm column mapping and review only uncertain cases
```

The first reliable deliverable is not Excel. The first reliable deliverable is `review.html`, where a non-developer user can visually inspect page images, chunk images, extracted rows, column mappings, validation warnings, and only then export Excel.

---

## Non-Negotiable Design Rules

1. **Do not build an OCR-first pipeline.**
   - OCR may be used only as an auxiliary heuristic.
   - The primary extraction path is image chunk → Vision LLM → JSON rows/cells.

2. **Do not hard-code card-company-specific parsers as the main strategy.**
   - Korean card statements vary by card company, personal/corporate/business type, and occasional layout changes.
   - Use a generic table-reading engine plus saved user mapping profiles.

3. **Do not trust amount checksum alone.**
   - A prior conversion had correct totals while `card_name` and `merchant` columns were mixed.
   - Validation must include both amount checks and text/column contamination checks.

4. **Always preserve raw cells.**
   - Never keep only normalized fields.
   - Every extracted row must retain `cells[]`, source file, page, chunk id, and local row index.

5. **Avoid precision-coordinate dependency.**
   - Exact table coordinates are brittle with scanned PDFs and changing layouts.
   - Use approximate chunks with overlap, header+body composite images, content-based merging, and human review.

6. **Cache every expensive or external step.**
   - Rendered page images, chunk images, Vision LLM responses, merged rows, validation results, and user mappings must be saved.
   - Re-running should resume from cache unless explicitly forced.

7. **Expose results visually.**
   - The user is a vibe-coder, not a Python developer.
   - Every major stage should produce a file or HTML view that can be inspected without reading code.

8. **Mark uncertainty instead of guessing.**
   - If a field, row, total, or mapping is ambiguous, use `needs_review=true` and explain why.
   - Do not silently fabricate merchant names or amounts.

---

## Expected Repository Shape

```text
.
├── AGENTS.md
├── PLAN.md
├── README.md
├── config.yaml
├── requirements.txt
├── main.py
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
    └── .gitkeep
```

Do not create a large monolithic script. Implement small modules with testable functions.

---

## Initial Implementation Priority

Implement in this order:

1. `page_renderer.py`
   - PDF → high-resolution PNG pages.

2. `chunk_builder.py`
   - Page image → overlapping body chunks.
   - Each body chunk should include the table header area at the top.

3. `review_builder.py`
   - Generate `output/review.html` showing original pages and chunks.
   - No LLM API call yet.

4. `vision_extractor.py`
   - Send each chunk image to Gemini Vision and save strict JSON.

5. `row_merger.py`
   - Merge overlapping chunk results by content similarity.
   - Do not blindly delete duplicates.

6. `validator.py`
   - Amount checksum, row consistency, column contamination, date/amount sanity checks.

7. `profile_store.py`
   - Save and reuse user-confirmed column mappings.

8. `excel_exporter.py`
   - Export only after review and validation data exist.

---

## Data Contract

Use JSONL or JSON files for intermediate data. The canonical row shape is:

```json
{
  "schema_version": "1.0",
  "source": {
    "file": "card.pdf",
    "page": 1,
    "chunk_id": "page_001_chunk_02",
    "local_row_index": 7,
    "statement_type": "unknown_or_profile_id",
    "period": ""
  },
  "raw": {
    "header": ["이용일", "이용카드", "이용가맹점", "이용금액", "결제원금"],
    "cells": ["03.14", "the Purple", "쿠팡", "38,200", "38,200"],
    "line_text": "",
    "image_ref": "output/chunks/page_001_chunk_02.png"
  },
  "transaction": {
    "date": "03.14",
    "card_label": "the Purple",
    "merchant": "쿠팡",
    "amount": 38200,
    "billing_amount": 38200,
    "transaction_type": "일시불"
  },
  "extra_fields": {},
  "quality": {
    "needs_review": false,
    "review_reason": "",
    "confidence_note": ""
  }
}
```

Core fields should stay stable. New statement-specific fields go to `extra_fields` and/or the raw cells sheet, not into an ever-growing core schema.

---

## Excel Output Contract

Final Excel should contain at least these sheets:

1. `전체명세`
   - Human-friendly transaction table.

2. `검산`
   - Source totals vs extracted totals vs difference.

3. `원본셀`
   - Raw `cells[]` by source file/page/chunk/row.

4. `추가필드`
   - Key-value style extra fields.

5. `확인필요`
   - Rows, chunks, or mappings that need manual review.

---

## Validation Requirements

At minimum, implement these checks:

- Amount total matches selected source total.
- Date column is date-like.
- Amount columns are numeric-like.
- Merchant column is not mostly numeric.
- Card label column does not contain too many merchant-like long strings.
- Row cell count is stable within a table group.
- Duplicate detection from overlapping chunks is explainable.
- Unknown or ambiguous rows are kept with `needs_review=true`, not discarded.

---

## API and Secret Handling

- Never hard-code API keys.
- Read API keys from environment variables or `.env`, but do not commit `.env`.
- Cache Vision API responses under `output/cache/`.
- Include a dry-run mode that builds pages/chunks/review HTML without calling any external API.

---

## Coding Style

- Prefer simple, explicit Python over clever abstractions.
- Use type hints where helpful.
- Use pathlib for file paths.
- Write logs that a non-developer can understand.
- Fail safely with clear messages.
- Keep prompts in `prompts/`, not embedded deep inside code.

---

## Definition of Done for Each Step

A step is done only when:

1. It can be run from the command line.
2. It writes inspectable output under `output/`.
3. It can resume without redoing completed expensive work.
4. It has clear error messages.
5. The user can verify progress visually or from a summary file.

