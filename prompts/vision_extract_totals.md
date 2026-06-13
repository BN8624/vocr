You are reading a cropped summary/total area from a Korean credit card statement.

Return JSON only. Do not wrap the JSON in Markdown.

Task:
- Extract only visible total, subtotal, billing, payment due, installment total, lump-sum total, fee, discount, point, balance, or amount summary lines.
- Put these values in the totals array.
- Do not include ordinary transaction rows in rows.
- The label must be specific enough for a user to choose the checksum basis.
- If a value is inside a summary table, combine the nearest row label and column header.
  Example: use "본인 이달에 입금하실 금액" instead of only "본인".
  Example: use "일시불 이용금액 합계" instead of only "합계".
- If there are multiple numbers near the same row label, do not reuse the same short label for all of them.
- If the image has no readable totals, return an empty totals array and explain in notes.
- Do not guess missing values.
- If a total label or amount is uncertain, keep it and mark it with needs_review=true.

Output shape:

{
  "schema_version": "1.0",
  "page": 1,
  "chunk_id": "page_001_totals_01",
  "header": [],
  "rows": [],
  "totals": [
    {
      "label": "이번달 결제금액",
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
