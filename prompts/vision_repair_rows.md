Repair the previous response into valid JSON only.

Requirements:
- Keep the same schema_version, page, chunk_id, header, rows, totals, needs_review, review_reason, and notes fields.
- Preserve Korean text and raw cell values.
- Do not add rows or cells that were not present in the previous response.
- Return JSON only. Do not wrap it in Markdown.
