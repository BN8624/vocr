# PLAN.md

# AI Vision-Based Card Statement Converter Plan

## Current Implementation Status

- Phase 1 dry-run pipeline is implemented.
- It renders PDF pages to `output/pages/`.
- It creates overlapping header+body chunks in `output/chunks/`.
- It builds `output/review.html` for visual inspection.
- It does not call any Vision LLM API.
- Sample PDFs in `견본/` use the filename suffix as expected page count, and
  `tests/smoke_phase1_samples.py` verifies that Phase 1 renders each one.
- Phase 2/3 extraction and review are implemented: non-dry-run calls Gemini
  Vision, saves `output/cache/*.vision.json`, and shows extracted rows/cells in
  `review.html` next to chunk images.
- Phase 4A/4B is implemented conservatively: cached Vision rows are collected
  into `output/merged/rows_raw.jsonl`, duplicate candidates are marked in
  `rows_merged.jsonl`, and `review.html` shows the candidate groups without
  deleting any rows.
- Phase 5 initial mapping review is implemented: `mapping_suggestions.json` is
  generated from merged rows, and `review.html` lets the user confirm fields and
  download a mapping profile JSON.

---

## 0. Background

We converted three image-based Korean card statement PDFs into Excel manually by visually inspecting page images and table regions. The work revealed several important lessons:

- Traditional OCR is unreliable for these complex statement tables.
- Amount checksum can pass even when text columns are wrong.
- In one case, `이용카드` and `가맹점명` were mixed while totals still matched.
- Card statement formats vary across card companies and even within the same company.
- Hard-coded templates will become difficult to maintain.
- The useful direction is Vision LLM extraction plus Python validation and user review.

This project turns that process into a local Python tool.

---

## 1. Product Goal

Build a local tool that takes an image-based card statement PDF and produces:

1. Page images.
2. Overlapping review chunks with headers attached.
3. Vision LLM JSON extraction results.
4. A review HTML file for column mapping and error inspection.
5. Validation results.
6. Final Excel file with all transactions in one sheet and audit sheets.

The system should be usable by a non-developer who can inspect HTML results and click/confirm mappings.

---

## 2. Core Strategy

The pipeline is:

```text
PDF
→ page images
→ overlapping header+body chunks
→ Vision LLM extracts rows/cells JSON
→ Python merges overlapping rows
→ Python normalizes fields
→ Python validates totals and text columns
→ review.html shows extraction and warnings
→ user confirms column mapping
→ profile is saved
→ Excel is exported
```

The project must not try to solve everything with precise coordinates. Instead:

- Use rough page/chunk regions.
- Use overlapping chunks.
- Attach the table header to each chunk.
- Merge rows by content, not coordinates.
- Use validation and review UI to catch failures.

---

## 3. Key Design Decisions

### 3.1 Vision LLM over OCR

The primary table-reading method is a Vision LLM such as Gemini Flash-Lite. Traditional OCR may be used only as optional assistance.

### 3.2 Weak Profiles Instead of Hard Templates

Do not build one parser per card company or statement type.

Use saved profiles containing:

- Header keywords.
- Column count.
- Relative column positions if available.
- User-confirmed column mapping.
- Total mapping.
- Validation rules.

Profiles are hints, not hard-coded parsers.

### 3.3 User Mapping Loop

When a new format appears, the user should not edit code. The user should confirm a few column mappings in HTML:

```text
col_1 = 이용일
col_2 = 이용카드
col_3 = 가맹점명
col_4 = 이용금액
col_5 = 청구금액
```

This mapping becomes a saved profile for future files.

### 3.4 Raw Cells Are Mandatory

Every extracted row must keep `cells[]` exactly as the Vision LLM saw them. Normalized transaction fields are derived data.

### 3.5 Validation Is Multi-Layered

Validation must include:

- Amount totals.
- Date-like column check.
- Numeric amount check.
- Merchant/card column contamination checks.
- Duplicate detection from overlapping chunks.
- Row shape consistency.

---

## 4. Target Output Folder Structure

```text
output/
├── pages/
│   ├── page_001.png
│   └── page_002.png
├── chunks/
│   ├── page_001_chunk_01.png
│   ├── page_001_chunk_02.png
│   └── page_001_chunk_03.png
├── cache/
│   ├── page_001_chunk_01.vision.json
│   └── page_001_chunk_02.vision.json
├── merged/
│   ├── rows_raw.jsonl
│   ├── rows_merged.jsonl
│   └── validation.json
├── review.html
└── result.xlsx
```

---

## 5. Repository Files

```text
main.py
config.yaml
requirements.txt
src/page_renderer.py
src/chunk_builder.py
src/vision_extractor.py
src/row_merger.py
src/normalizer.py
src/validator.py
src/review_builder.py
src/profile_store.py
src/excel_exporter.py
prompts/vision_extract_table.md
prompts/vision_repair_rows.md
profiles/README.md
tests/.gitkeep
```

---

## 6. Implementation Phases

## Phase 1 — Image Preparation and Review HTML

### Goal

Create a dry-run pipeline that does not call any AI API yet.

### Input

```text
python main.py --input samples/card.pdf --output output --dry-run
```

### Output

```text
output/pages/page_001.png
output/chunks/page_001_chunk_01.png
output/review.html
```

### Requirements

1. Render PDF pages to high-resolution PNG.
2. Create overlapping vertical chunks from each page.
3. Attach the estimated table header area to each chunk.
4. Generate `review.html` showing:
   - Page image.
   - Chunk images.
   - Chunk id.
   - Basic metadata.

### Suggested Files

- `main.py`
- `src/page_renderer.py`
- `src/chunk_builder.py`
- `src/review_builder.py`
- `config.yaml`

### Acceptance Criteria

- User can open `review.html` and inspect all pages/chunks.
- Chunks overlap enough that rows cut at the boundary are visible in another chunk.
- Each chunk includes a header area at the top.
- No API key is required for this phase.

---

## Phase 2 — Vision LLM Extraction

### Goal

Send chunk images to the Vision LLM and store strict JSON responses.

### Requirements

1. Read API key from environment variable.
2. Send each chunk image with a strict prompt.
3. Require JSON output with:
   - page
   - chunk_id
   - header
   - rows
   - cells
   - totals
   - needs_review
4. Save each response to `output/cache/`.
5. Reuse cached response unless `--force` is set.
6. Handle rate limits with a request queue and delay.

### Suggested Files

- `src/vision_extractor.py`
- `prompts/vision_extract_table.md`

### Initial Prompt Contract

The prompt should tell the model:

```text
You are reading a cropped image of a Korean card statement table.
Return JSON only.
Extract visible rows from top to bottom.
Do not summarize.
Do not merge rows.
Do not invent missing text.
Preserve raw cells.
If uncertain, set needs_review=true and explain briefly.
```

### Acceptance Criteria

- Every chunk has a corresponding JSON cache file.
- Invalid JSON is caught and saved as an error artifact.
- The pipeline can resume without recalling the API.

---

## Phase 3 — Raw Rows Review HTML

### Goal

Show AI-extracted rows next to chunk images.

### Requirements

`review.html` should show:

- Chunk image.
- Extracted header.
- Extracted rows/cells table.
- Totals detected by the model.
- Rows marked `needs_review`.
- JSON source file link or path.

### Acceptance Criteria

- User can visually compare the chunk image and extracted cells.
- It is obvious when `이용카드` and `가맹점명` are mixed.

---

## Phase 4 — Row Merge

### Goal

Merge repeated rows from overlapping chunks without losing real duplicate transactions.

### Strategy

Use content-based duplicate detection:

```text
date + amount + merchant fragment + card fragment + nearby order
```

But do not blindly delete duplicates.

Classify duplicate candidates as:

```text
auto_merge
needs_review
keep_both
```

### Requirements

1. Preserve all raw chunk rows.
2. Create merged rows in `output/merged/rows_merged.jsonl`.
3. Keep merge metadata.
4. Mark ambiguous duplicates for review.

### Acceptance Criteria

- Overlap duplicates are mostly removed.
- Same-date same-amount repeated purchases are not automatically deleted unless highly confident.

---

## Phase 5 — Column Mapping UI

### Goal

Let the user map generic columns to semantic fields with minimal clicks.

### UI Concept

For each detected table group:

```text
col_1: [이용일 ▼]
col_2: [이용카드 ▼]
col_3: [가맹점명 ▼]
col_4: [이용금액 ▼]
col_5: [청구금액 ▼]
```

### Mapping Options

Core:

```text
date
card_label
merchant
amount
billing_amount
transaction_type
ignore
```

Optional:

```text
discount
points
installment_month
installment_round
fee
foreign_amount
currency
exchange_rate
memo
extra
```

### Requirements

1. Auto-suggest mappings from header text and value patterns.
2. Let user correct them.
3. Save mapping profile to `profiles/`.
4. Reuse profile when a similar layout appears.

### Acceptance Criteria

- A new statement format can be handled by mapping columns in the UI without editing Python code.

---

## Phase 6 — Normalization

### Goal

Convert raw cells plus mapping into structured transaction rows.

### Requirements

1. Normalize dates.
2. Normalize Korean won amounts.
3. Preserve original string values.
4. Put unknown statement-specific columns into `extra_fields`.
5. Mark ambiguous normalization as `needs_review`.

### Output

```text
output/merged/transactions.jsonl
```

---

## Phase 7 — Validation

### Goal

Detect extraction errors before Excel export.

### Required Checks

1. Amount checksum.
2. Page or statement total comparison.
3. Date-like column check.
4. Amount-like column check.
5. Merchant column numeric contamination check.
6. Card label column merchant contamination check.
7. Empty merchant/card/date rate.
8. Duplicate candidate review.
9. Row cell count consistency.

### Validation Example

```json
{
  "status": "warning",
  "checks": [
    {
      "name": "amount_total",
      "status": "ok",
      "source_total": 34523411,
      "extracted_total": 34523411,
      "diff": 0
    },
    {
      "name": "merchant_numeric_contamination",
      "status": "warning",
      "count": 3,
      "message": "Merchant column contains amount-like strings. Possible column shift."
    }
  ]
}
```

### Acceptance Criteria

- Amount OK does not automatically mean the entire conversion is OK.
- Text-column warnings are visible in `review.html`.

---

## Phase 8 — Excel Export

### Goal

Export final reviewable Excel.

### Required Sheets

1. `전체명세`
2. `검산`
3. `원본셀`
4. `추가필드`
5. `확인필요`

### Requirements

1. Use numeric amount cells.
2. Include source file/page/chunk/row identifiers.
3. Include review flags and reasons.
4. Include validation summary.
5. Do not hide uncertain rows.

---

## 7. Config Draft

```yaml
render:
  dpi: 300
  image_format: png

chunking:
  header_ratio: 0.12
  body_start_ratio: 0.12
  body_end_ratio: 0.95
  chunk_height_ratio: 0.35
  overlap_ratio: 0.25
  attach_header: true

vision:
  provider: gemini
  model: gemini-3.1-flash-lite
  rpm_limit: 15
  request_delay_seconds: 5
  cache_enabled: true
  max_retries: 3

review:
  html_title: Card Statement Review
  show_chunk_images: true
  show_raw_json_paths: true

export:
  excel_filename: result.xlsx
```

---

## 8. Development Instructions for Codex

When implementing this project:

1. Start with Phase 1 only.
2. Do not implement Gemini API in the first commit.
3. Make visual output first.
4. Keep every stage resumable.
5. Keep code modular.
6. Do not delete intermediate artifacts.
7. Prefer readable, simple Python.
8. Update `PLAN.md` after each completed phase.

---

## 9. First Codex Task Prompt

Use this as the first task:

```text
Implement Phase 1 of PLAN.md.

Build a dry-run Python pipeline for image-based card statement PDFs.

Requirements:
1. Create main.py, config.yaml, requirements.txt.
2. Create src/page_renderer.py to render PDF pages to output/pages/page_001.png etc.
3. Create src/chunk_builder.py to create overlapping vertical chunks from each page.
4. Each chunk should include the top header area attached above the body crop.
5. Create src/review_builder.py to generate output/review.html showing page images and chunk images.
6. Do not implement any Vision LLM API calls yet.
7. The command should be:
   python main.py --input samples/card.pdf --output output --dry-run
8. Use pathlib and clear logging.
9. Make the output folder structure if it does not exist.
10. Keep settings in config.yaml.
```

---

## 10. Risks and Mitigations

### Risk: Chunk boundaries cut rows

Mitigation:

- Use overlap.
- Attach header to every chunk.
- Later merge by content.

### Risk: Vision LLM returns invalid JSON

Mitigation:

- Strict prompt.
- JSON parsing guard.
- Save invalid response artifact.
- Retry with repair prompt.

### Risk: Totals match but text columns are wrong

Mitigation:

- Merchant/card contamination checks.
- Raw cells sheet.
- Review UI.

### Risk: New card statement format appears

Mitigation:

- User mapping UI.
- Saved weak profile.
- No hard-coded parser dependency.

### Risk: API limits

Mitigation:

- Request queue.
- Cache.
- Dry-run mode.
- Repair only failed chunks.

---

## 11. V1 Definition of Done

V1 is complete when:

1. A PDF can be rendered into page images.
2. Pages can be split into overlapping header+body chunks.
3. `review.html` can show pages and chunks.
4. Vision LLM can extract raw rows/cells JSON from chunks.
5. Extracted rows can be reviewed in HTML.
6. User can confirm column mappings.
7. Validation can flag amount and text-column issues.
8. Excel can be exported with `전체명세`, `검산`, `원본셀`, `추가필드`, `확인필요` sheets.
