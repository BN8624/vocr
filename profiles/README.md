# Profiles

This folder stores local mapping/profile JSON files.

Profile JSON files are user/local data and are ignored by Git. Keep this README only.

## Purpose

Profiles should reduce manual intervention across recurring issuer layouts.

They are not the main extraction strategy and should not become full hard-coded card-company parsers. A good profile records stable layout facts:

```text
issuer
layout_signature
header_signature
column_roles
value_patterns
verified_samples
last_verified_metrics
```

## Stable Profile Promotion

A profile should be considered stable only after the issuer's single-page, three-page, and multi-page acceptance samples pass with:

```text
blocked rows == 0
hard_review_rate <= 3%
manual_review_rate <= 10%
silent_error_count == 0
```

Until then, treat profiles as candidates.

## Current Use

Profiles can still be saved from `review.html` when served through:

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

They can also be passed explicitly:

```bash
python main.py --input "견본\삼성카드_1.pdf" --output output/samsung_1 --mapping-profile profiles/mapping-profile.json
```

## Manage Local Profiles

```bash
python profile_manager.py list
python profile_manager.py show mapping-profile.json
python profile_manager.py rename mapping-profile.json samsung-card-v1
python profile_manager.py delete samsung-card-v1.json --yes
```
