# AGENTS.md

## Project Mission

Build a local Python tool that automatically converts image-based Korean credit card statement PDFs into structured Excel files.

The current acceptance target is:

```text
3 issuers x single-page / three-page / multi-page local statement samples
-> automatic Vision-first extraction
-> validation and automation scoring
-> result.xlsx
```

`review.html` is not the main product and not a screen for reviewing every row. It is an exception/debug screen for finding why automatic conversion failed.

## Core Strategy

```text
Python = image preparation, chunking, caching, validation, automation metrics, Excel export
Vision LLM = visually read table chunks and return strict rows/cells JSON
Profiles = stabilize recurring issuer layouts
User = intervene only for rare hard failures
```

The first reliable deliverable is automatic Excel conversion across the acceptance samples, measured by regression reports and automation metrics.

## Non-Negotiable Design Rules

1. **Do not build an OCR-first pipeline.**
   - OCR may be used only as an auxiliary heuristic.
   - The primary extraction path is image chunk -> Vision LLM -> JSON rows/cells.

2. **Do not hard-code full card-company parsers as the main strategy.**
   - Use generic visual table extraction plus reusable issuer/layout profiles.
   - Profiles may encode layout signatures, column roles, and value patterns.

3. **Do not trust amount checksum alone.**
   - Correct totals can still hide swapped `card_label` and `merchant` columns.
   - Validation must include text/column contamination checks and row-level risk scoring.

4. **Always preserve raw cells.**
   - Every extracted row must retain `cells[]`, source file, page, chunk id, and local row index.
   - Normalized rows must remain auditable from original cells.

5. **Avoid precision-coordinate dependency.**
   - Exact coordinates are brittle with scanned PDFs and layout changes.
   - Use approximate chunks with overlap, content-based merging, profiles, and measured recovery.

6. **Cache every expensive or external step.**
   - Rendered images, chunk images, Vision responses, merged rows, validation outputs, automation summaries, and profiles must be saved.
   - Re-running should resume from cache unless explicitly forced.

7. **Measure automation quality.**
   - `result.xlsx` existing is not enough.
   - Track auto acceptance rate, manual review rate, hard review rate, blocked rows, and failure reasons.

8. **Mark uncertainty instead of guessing.**
   - Do not silently fabricate merchant names, amounts, dates, or totals.
   - Distinguish warning-level uncertainty from hard-review or blocked failures.

## Acceptance Set

The local acceptance PDFs are ignored by Git and currently live in `견본/`.

The intended P0 acceptance set is:

```text
3 issuers
1-page sample per issuer
3-page sample per issuer
multi-page sample per issuer
```

The current local filenames are:

```text
삼성카드_1.pdf, 삼성카드_3.pdf, 삼성카드_7.pdf
신한카드_1.pdf, 신한카드_3.pdf, 신한카드_11.pdf
현대카드_1.pdf, 현대카드_3.pdf, 현대카드_8.pdf
```

P0 should standardize sample discovery through `samples/sample_manifest.json`, but implementation must respect the current local `견본/` acceptance set until the manifest workflow is complete.

## Completion Metrics

P0 target:

```text
all acceptance samples produce result.xlsx
all acceptance samples produce review.html
all acceptance samples produce merged/automation_summary.json
blocked samples == 0
blocked rows == 0
average hard_review_rate <= 5%
average manual_review_rate <= 15%
```

P1 target:

```text
average hard_review_rate <= 3%
average manual_review_rate <= 10%
```

Final target:

```text
average hard_review_rate <= 1%
average manual_review_rate <= 5%
silent_error_count == 0
```

## Row Automation Contract

Validated transaction rows should move beyond a single `needs_review` flag.

Use:

```text
auto_confirmed
auto_confirmed_with_warning
needs_light_review
needs_hard_review
blocked
```

Each row should eventually include:

```json
{
  "automation": {
    "row_status": "auto_confirmed",
    "confidence_score": 0.97,
    "risk_level": "low",
    "signals": {},
    "reasons": []
  }
}
```

## Review UI Rules

`review.html` must be an exception/debug screen.

Show first:

```text
blocked rows
needs_hard_review rows
checksum mismatch
duplicate conflicts
profile conflicts
amount candidate conflicts
automation metrics
```

Hide by default:

```text
auto_confirmed rows
auto_confirmed_with_warning rows
normal chunks/pages
raw JSON file links unless under technical details
```

If a user must scroll through all rows or all pages, the UI is drifting away from the goal.

## Output Contract

Main output folder:

```text
output/<sample_name>/
  pages/
  chunks/
  total_chunks/
  cache/
  merged/
    rows_raw.jsonl
    rows_merged.jsonl
    merge_summary.json
    mapping_suggestions.json
    transactions.jsonl
    transactions_validated.jsonl
    validation_summary.json
    validation_issues.json
    automation_summary.json
  review.html
  result.xlsx
  summary.json
```

Excel must contain at least:

```text
전체명세
검산
원본셀
추가필드
확인필요
```

## Priority Order

Follow `newplan.md`. Current order:

```text
1. sample manifest generation
2. acceptance runner strengthening
3. automation_summary.json
4. row_status / confidence_score / risk_level
5. stable issuer profile criteria
6. automatic checksum candidate selection
7. duplicate state refinement
8. strict parsers and automatic recovery
9. selective 2-pass Vision
10. review.html exception/debug screen
11. STATUS.md and TEST_REPORT.md
```

## Do Not Do

```text
do not improve manual row review as the main solution
do not treat many needs_review rows as acceptable
do not call result.xlsx creation alone a success
do not leave checksum selection manual if it can be scored safely
do not change prompts without measuring regression metrics
do not commit .env, output artifacts, local profiles, or sample PDFs
```
