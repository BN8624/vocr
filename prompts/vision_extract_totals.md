You are reading a cropped summary/total area from a Korean credit card statement.

Return JSON only. Do not wrap the JSON in Markdown.

Task:
- Extract only visible total, subtotal, billing, payment due, installment total, lump-sum total, fee, discount, point, balance, or amount summary lines.
- Put these values in the totals array.
- Do not include ordinary transaction rows in rows.
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
