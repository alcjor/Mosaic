# Fixture sources

Sources for Mosaic's conformance fixtures that cannot be downloaded from their origin by
an agent environment (no login, GitHub only). Each is pinned by this branch's commit and
its SHA-256 in `conformance/fixtures/manifest.json` on `main`, and downloaded by
`scripts/fetch_fixtures.py`. Files here are never changed: a new version is a new file.

This branch never merges into `main`.

| File | Source | Licence | SHA-256 |
|---|---|---|---|
| `netflix-titles/netflix_titles.csv` | "Netflix Movies and TV Shows", Shivam Bansal, Kaggle; 8,807 titles | CC0 1.0 Universal | `df1f4ad2027a5a14c3a33932ef0d4054565ff88adf92b7f263601b70fdc6f3f3` |
