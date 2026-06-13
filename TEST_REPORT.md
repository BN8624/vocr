# TEST_REPORT

This report format follows `newplan.md`.

## Latest Local Verification

Last updated: 2026-06-13

Commands recently used during development:

```bash
python -m compileall main.py serve_review.py profile_manager.py review.py src tests
python tests/test_review_entrypoint.py
python tests/test_review_html_smoke.py
python tests/test_review_state_refresh.py
python tests/test_validation_fixtures.py
python tests/test_checksum_selection.py
python tests/test_duplicate_representative.py
python tests/test_column_quality.py
python tests/test_profile_signature.py
python tests/test_profile_manager.py
python tests/test_total_chunks.py
python tests/regression_samples.py
python tests/test_sample_manifest.py
python tests/regression_samples.py --samples-dir 견본 --issuer 현대카드 --pages 1 --limit 1 --output output/first_hyundai_1_dry_run
```

## Acceptance Set

Current local acceptance source:

```text
견본/
```

Current detected samples:

```text
삼성카드_1.pdf
삼성카드_3.pdf
삼성카드_7.pdf
신한카드_1.pdf
신한카드_3.pdf
신한카드_11.pdf
현대카드_1.pdf
현대카드_3.pdf
현대카드_8.pdf
```

## Current Regression Coverage

`tests/regression_samples.py` currently checks:

```text
page count
chunk count
review.html creation
summary.json creation
dry-run pass/fail
optional --with-vision execution
```

It does not yet fully check:

```text
automation_summary.json
auto_accept_rate
manual_review_rate
hard_review_rate
blocked rows
non-empty 전체명세
all required Excel sheets
stable profile reuse metrics
silent error count
```

## Required Report Fields

The acceptance report should evolve to include:

```text
sample_count
issuer_count
single-page sample results
three-page sample results
multi-page sample results
average auto_accept_rate
average manual_review_rate
average hard_review_rate
blocked sample count
blocked row count
top 10 failure reasons
change from previous run
```

## Current Status

```text
sample_count: 9 local PDFs
issuer_count: 3
automation_summary coverage: PLANNED
auto_accept_rate average: not measured
manual_review_rate average: not measured
hard_review_rate average: not measured
blocked count: not measured
full --with-vision acceptance: NEEDS_VERIFICATION
```

## Stepwise Acceptance Progress

First selected sample:

```text
현대카드_1.pdf
```

Dry-run evidence:

```text
command: python tests/regression_samples.py --samples-dir 견본 --issuer 현대카드 --pages 1 --limit 1 --output output/first_hyundai_1_dry_run
result: PASS
pages: 1/1
chunks: 4
vision: not_run
```

Vision evidence:

```text
command attempted: python main.py --input "견본\현대카드_1.pdf" --output output\acceptance_hyundai_1 --force --force-vision
result: pipeline completed but Vision calls failed under sandbox network restrictions
failure: WinError 10013 socket access denied
rows extracted: 0
transaction_count: 0
```

Running the same command with external Gemini access requires explicit approval because statement chunk images are sent to Google Gemini.

## Next Required Test Milestone

```bash
python tools/build_sample_manifest.py --samples samples --output samples/sample_manifest.json
python -m pytest -q
python tests/regression_samples.py
python tests/regression_samples.py --with-vision
```

The first command and full pytest command are target commands from `newplan.md`; they are not fully implemented yet.
