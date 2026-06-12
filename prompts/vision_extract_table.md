You are reading a cropped image of a Korean credit card statement table.

Return JSON only. Do not wrap the JSON in Markdown.

Task:
- Extract visible table rows from top to bottom.
- Preserve raw cells exactly as seen.
- Do not summarize rows.
- Do not merge rows.
- Do not invent missing text.
- If a row, cell, header, or total is uncertain, keep it and mark it with needs_review=true.
- If the chunk contains repeated header rows, keep the table header in header and do not include header rows as transactions.
- If the image has no readable transaction rows, return an empty rows array and explain in notes.

Output shape:

{
  "schema_version": "1.0",
  "page": 1,
  "chunk_id": "page_001_chunk_01",
  "header": ["column header text"],
  "rows": [
    {
      "local_row_index": 1,
      "cells": ["raw cell text"],
      "line_text": "",
      "needs_review": false,
      "review_reason": "",
      "confidence_note": ""
    }
  ],
  "totals": [
    {
      "label": "합계",
      "value_text": "123,456",
      "amount": 123456,
      "needs_review": false,
      "review_reason": ""
    }
  ],
  "needs_review": false,
  "review_reason": "",
  "notes": ""
}
