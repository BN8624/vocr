# Profiles

Confirmed column mapping profiles live here.

Any `*.json` file in this folder is loaded automatically on future runs. Profile JSON files are user/local data and are ignored by Git.

## Save From Review Page

If you serve the review page with:

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

the `PC에 매핑 저장` button in `review.html` saves the confirmed profile directly into this folder. This is useful when reviewing from iPhone over Tailscale.

If the review server is not running, use `매핑 JSON 내려받기` and place the downloaded `mapping-profile.json` in this folder manually.

## Explicit Use

You can also pass a profile explicitly:

```bash
python main.py --input samples/card.pdf --output output --dry-run --mapping-profile profiles/mapping-profile.json
```

Saved profiles are hints. Raw cells are still preserved, and validation still marks suspicious rows for review.
