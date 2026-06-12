# Profiles

Saved column mapping profiles will live here.

`review.html` lets the user confirm mappings and download a
`mapping-profile.json` file from the browser.

To reuse a downloaded profile on the next run, put the JSON file in this folder.
Any `*.json` file here is loaded automatically.

You can also pass a profile explicitly:

```bash
python main.py --input samples/card.pdf --output output --dry-run --mapping-profile profiles/mapping-profile.json
```

Saved profiles are hints. Raw cells are still preserved, and validation still
marks suspicious rows for review.
