---
name: tender-discover
description: Discover new Hong Kong public tender (招標) listings from the Conneciz public API. Use when asked to check for, discover, sync, or baseline new tenders, or to run scripts/discover.py.
---

# Tender Discovery (Pipeline Step 1)

> **Canonical copy lives in Hermes:** `~/.hermes/skills/productivity/tender-discover/SKILL.md`
> (2026-08-31: registered there with added data-quality filters + `cd` fix).
> This Claude Code copy is kept in sync manually — update both when changing.

Run the tender-discovery script and report what's new.

## What it does

`scripts/discover.py` queries the Conneciz public API (no login) for tender
listings, diffs them against a local seen-set in `pipeline_state.json`, and
prints JSON with any new records. Two modes:

- **incremental** (default) — fetch records newer than the stored watermark;
  report `new` + `updated`. This is the daily operation.
- **baseline** — mark the recent window as "already seen" so the first real run
  doesn't flood with existing tenders. Always reports `"new": []`.

## Commands

```bash
# First run / reset baseline (last 7 days marked seen)
python3 scripts/discover.py --baseline

# Baseline over a longer window
python3 scripts/discover.py --baseline --lookback-days 30

# Daily incremental check (normal operation)
python3 scripts/discover.py

# Test against a manual watermark without advancing the stored one
python3 scripts/discover.py --since 2026-08-20T00:00:00.000Z
```

## Flags

| Flag | Effect |
|---|---|
| `--baseline` | Mark the past N days seen; never reports new. Auto-runs on first run (no watermark yet). |
| `--since <ts>` | Explicit ISO-8601-UTC start timestamp. In incremental mode it does NOT advance the stored watermark, but still writes newly-seen records to state. |
| `--lookback-days <N>` | Baseline window in days (default 7). Ignored outside baseline. |

## Interpreting output

stdout is one JSON object:

```json
{
  "run":     {"mode": "incremental", "at": "...", "since": "...", "fetched": 12},
  "new":     [{"_id": "...", "tender_ref": "...", "title_en": "...", "title_zh": "...", "category": "...", "created": "...", "modified": "...", "url": "...", "first_seen": "..."}],
  "updated": 3
}
```

- `new` — tenders first seen this run (feed these to the next pipeline step).
- `updated` — already-seen tenders whose `Modified Date` changed (title/url refreshed in state).

## State file (`pipeline_state.json`)

- `tenders_seen` — id → `{first_seen, url, title_en, title_zh}`.
- `watermark_ts` — high-water mark; incremental runs look only newer than this.
- `baseline_ts` — when the baseline was last (re)established.

## After discovery

Steps 2–4 (verify against official sources, download docs, digest) are not built
yet. For now, report the `new` tenders to the user (count + refs + titles), and
say explicitly when a run was baseline (reports nothing).

## Gotchas

- Baseline always outputs `"new": []` by design — that's expected, not a bug.
- `--since` doesn't advance the watermark but does write newly-seen records into
  `tenders_seen` — not a pure read-only dry run.
- Any real run hits the live API (0.3s/page) and mutates `pipeline_state.json`.
