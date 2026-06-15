# TEST_REPORT

This report follows the current original-table product goal.

## Latest Local Verification

Last updated: 2026-06-15

Commands verified:

```bash
python -X utf8 tests\test_app_gui.py
python -X utf8 tests\test_convert_entrypoint.py
python -X utf8 tests\test_original_table_metrics.py
python -X utf8 convert.py "견본\현대카드_8.pdf" --output output\acceptance_hyundai_8_gemma --dry-run
```

Full test sweep also passed:

```bash
$tests = Get-ChildItem tests -Filter 'test_*.py' | Sort-Object Name
foreach ($test in $tests) { python -X utf8 $test.FullName }
```

## Representative Acceptance Set

Current acceptance scope is the largest-page representative sample for each card company.

```text
KB: kb_bzcard_13.pdf
삼성카드: 삼성카드_7.pdf
신한카드: 신한카드_11.pdf
현대카드: 현대카드_8.pdf
```

Split-down PDFs in `견본/` remain useful for staged debugging, but they are not the final acceptance set by themselves.

## Acceptance Results

Latest preservation audit:

```text
output/original_table_acceptance_4.json
output/original_table_visual_audit.md
```

| Card company | Sample | Original rows | Original cells | Transactions | Validation issues | Checksum |
|---|---|---:|---:|---:|---:|---|
| KB | kb_bzcard_13 | 211/211 | 1157/1157 | 173 | 0 | auto_selected_total_matched |
| 삼성카드 | 삼성카드_7 | 260/260 | 1752/1752 | 248 | 0 | auto_selected_total_matched |
| 신한카드 | 신한카드_11 | 594/594 | 2877/2877 | 510 | 0 | auto_selected_total_matched |
| 현대카드 | 현대카드_8 | 325/325 | 2099/2099 | 289 | 0 | no_user_total_selected |

Hyundai remains `no_user_total_selected` because of the documented `7-8페이지 16,500원 차이` edge case. This is not an original-table preservation failure.

## Excel Contract

Every representative workbook must use this sheet order:

```text
원본표
원본표_개발자
전체명세_정규화
검산
원본셀
추가필드
확인필요
```

The first sheet, `원본표`, is the main user output. It contains the dominant transaction-table header only, with date columns formatted as `yyyy-mm-dd` and amount-like columns stored as numeric cells.

`원본표_개발자` preserves rows from `rows_merged.jsonl`, including `row_type=total` rows generated from Vision `totals`.

## Current Pass Criteria

```text
result.xlsx exists
원본표 is the first sheet
원본표 is non-empty
원본표_개발자 row coverage against rows_merged.jsonl is 100%
원본표_개발자 non-empty cell coverage against rows_merged.jsonl is 100%
전체명세_정규화 exists
검산 exists
validation issue rows == 0, or there is a documented exception
checksum is auto matched, or there is a documented exception
```

## Known Limits

```text
Long 안내문 and free-form section titles are not fully structured yet.
The current preserved original table covers Vision rows and Vision totals.
PDF visual ground-truth accuracy still depends on representative visual sampling.
```
