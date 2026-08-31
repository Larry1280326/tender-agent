---
name: tender-discover
description: "Discover new Hong Kong public tender (招標) listings from the Conneciz public API and verify them against official sources (Serper + Jina Reader). Use when asked to check for, discover, sync, or baseline new tenders, or to run scripts/discover.py, scripts/serper.py, scripts/reader.py, or scripts/utils.py."
---

# Tender Discovery & Verification (Tender Pipeline Steps 1–3)

> **Canonical copy lives in Hermes:** `~/.hermes/skills/productivity/tender-discover/SKILL.md`.
> This Claude Code copy is kept in sync manually — update both when changing.
> (2026-08-31: synced to cover Steps 1–2 — added `serper.py`/`reader.py` docs,
> env keys, and the region-classification-removal note.)

Run the tender-discovery script, report what's new, then verify each new
tender against official sources.

## What it does

Step 1 — `scripts/discover.py` queries the Conneciz public API (no login) for
tender listings, diffs them against a local seen-set in `pipeline_state.json`,
and prints JSON with any new records. By default it only fetches records whose
deadline (`ClosingDateTime`) is between `now+2d` and `now+365d` (tune with
`--min-days-ahead` / `--max-days-ahead`). Two modes:

- **incremental** (default) — fetch records newer than the stored watermark;
  report `new` + `updated`. This is the daily operation.
- **baseline** — mark the recent window as "already seen" so the first real run
  doesn't flood with existing tenders. Always reports `"new": []`.

Step 2 — verify each new tender against official sources with `serper.py`
(search) + `reader.py` (page fetch/extract). See below.

## Commands (Step 1)

Always run from the pipeline workspace first:

```bash
cd ~/Desktop/tender-pipeline

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
| `--min-days-ahead <N>` | Only fetch records whose deadline is at least N days out (default 2). Applied in both modes. |
| `--max-days-ahead <N>` | Only fetch records whose deadline is within N days (default 365). Drops year-2504 placeholder deadlines. Applied in both modes. |

## Interpreting output

stdout is one JSON object:

```json
{
  "run":     {"mode": "incremental", "at": "...", "since": "...", "fetched": 12},
  "new":     [{"_id": "...", "tender_ref": "...", "title_en": "...", "title_zh": "...", "category": "...", "created": "...", "modified": "...", "deadline": "...", "url": "...", "first_seen": "..."}],
  "updated": 3
}
```

- `new` — tenders first seen this run (feed these to Step 2).
- `updated` — already-seen tenders whose `Modified Date` changed (title/url refreshed in state).

## State file (`pipeline_state.json`)

- `tenders_seen` — id → `{first_seen, url, title_en, title_zh, deadline, status, status_at}`.
- `watermark_ts` — high-water mark; incremental runs look only newer than this.
- `baseline_ts` — when the baseline was last (re)established.

Each entry's `status` tracks progress along the happy path:
`discovered → searched → downloaded → digested` (default `discovered`;
`status_at` records when it last changed). Incremental runs preserve
`status`/`status_at` on refresh.

Manage this state with `scripts/utils.py`:

```bash
# Read the seen-set (read-only; count + watermark + tenders_seen array)
python3 scripts/utils.py --list

# Advance one or more tenders (batch)
python3 scripts/utils.py --set-status searched --ids <id1> <id2> <id3>
```

`--set-status` takes one of the four statuses and one or more `--ids`; it prints
per-id results and exits non-zero if any id is missing.

## Step 2 — verify against official sources

Conneciz is discovery-only; item details (deadline, docs) are verified from
official sources. Two stdlib-only tools (sharing `scripts/common.py` for `.env`
loading + SSL fallback) do the fetching — the agent (LLM) does the judgement.

```bash
# Extract issuer/tender_no/deadline/doc_links from a Conneciz detail page
python3 scripts/reader.py --url <conneciz_url> --extract

# Search for the official notice
python3 scripts/serper.py --query "<Tender_No> <issuer> 招標"

# Read a chosen official page (full markdown)
python3 scripts/reader.py --url <official_url>
```

- **`reader.py`** — Jina Reader (`https://r.jina.ai`). `--url` fetches the page as
  markdown; `--extract` returns JSON `{title, issuer, tender_no, deadline,
  doc_links}` (best-effort; Chinese labels target Conneciz pages, English labels
  target official notice pages). `--max-chars N` truncates full output.
- **`serper.py`** — Serper Google search. Returns `{query, results:[{title,
  link, snippet, position}]}`. Flags: `--num` (default 10), `--gl hk`,
  `--hl zh-Hant`.

Workflow: extract issuer/tender_no from the Conneciz detail page → serper search
with ref + issuer → create the dossier dir (see below) → pick official-domain
results (`*.gov.hk`, `*.edu.hk`, the issuer's own domain) → read each with
`reader.py` → report findings with sources.

### Dossier directory

Once the Serper search confirms a tender is worth pursuing, create its working
directory under `dossiers/`, named by the tender id — the `_id` value from the
`new` record (also the `tenders_seen` key):

```bash
mkdir -p dossiers/<tender_id>
```

e.g. `dossiers/1787921986116x962531916457976400/`. This dir holds everything
downstream for that tender (official docs, digest, compliance). `dossiers/` is
gitignored. Pair it with advancing the tender to `searched`:

```bash
python3 scripts/utils.py --set-status searched --ids <tender_id>
```

### Step 3 (C1) — download documents

Direct-download tender documents into the dossier with `scripts/utils.py --download`:

```bash
python3 scripts/utils.py --download <tender_id> --urls <url1> [url2 ...] [--max-mb 100]
```

- Streams each URL to `dossiers/<tender_id>/docs/` (atomic `.part` → `os.replace`),
  deriving the filename from `Content-Disposition` → URL path → `Content-Type`.
- Prints JSON `{tender_id, dir, results:[{url, ok, file, size, sha1}], downloaded,
  requested}`; exits non-zero if any URL fails. Per-file failures don't abort the batch.
- Reuses `common.urlopen` (SSL fallback) + `common.UA`; no login.
- Feed it `doc_links` from `reader.py --extract`. It does **not** advance status — follow
  up with `--set-status downloaded --ids <tender_id>`.

### Setup

```bash
cp .env.example .env   # then fill keys (`.env` is gitignored)
```

```
SERPER_API_KEY=...
JINA_API_KEY=...
```

Both tools exit with a missing-key error if the env var isn't set.

## Data quality — filter BEFORE reporting/feeding Step 2

The Conneciz feed is raw and noisy. Apply these filters to `new` records:

0. **Deadline range (already applied at query level)** — `discover.py` filters
   `now+2d < ClosingDateTime < now+365d` by default, so far-future placeholder
   deadlines (year 2504, e.g. `2504-07-10T08:00:00.000Z`) and soon-closing
   tenders never reach `new`. No manual action needed.

1. **Placeholder / junk titles** — skip records whose title matches any of:
   `Unknown Subject`, `招標公告`, `Tender Announcement`, `Tender`, `招標`,
   `Procurement`, `採購`, `Lunch Supplier`, `午膳供應商`, `Accounting system`,
   `會計系統`, `2026-2027 Academic Year`, `暫時沒有相關資料`, or an EMPTY
   `title_en` / missing `url`.
2. **Region** — the feed mixes Singapore/Malaysia records (Tuas, HDB, Sengkang,
   MacRitchie, Hwa Chong, ...) and school quotations (遊學團/午膳/校服) in with
   HK government tenders. Region is **not** auto-classified — `discover.py` no
   longer has a `--hk-only` flag or `region_guess` field (that logic was moved
   out of Step 1). Judge region yourself from title/category/url before feeding
   records to Step 2, and confirm the target scope with the user (HK-only vs all).

## Gotchas

- Baseline always outputs `"new": []` by design — that's expected, not a bug.
- `--since` doesn't advance the watermark but does write newly-seen records into
  `tenders_seen` — not a pure read-only dry run. Don't backfill-test with an old
  `--since`, it pollutes the seen-set.
- Any real run hits the live API (0.3s/page) and mutates `pipeline_state.json`.
- SSL: script retries with macOS system roots (`/etc/ssl/cert.pem`) on
  `CERTIFICATE_VERIFY_FAILED` — already handled internally.
- Watermark pagination uses `min(Modified Date)` + strictly-greater constraint:
  if >100 records share one exact millisecond timestamp, cross-page records at
  that boundary are skipped (rare; only matters on bulk-import days).
- `_id` fallback hashes `Tender_No|Subject_EN` — two records with all three
  empty would collide; dedupe on `tender_ref` too if filtering raw API output.

## Related skills

- `web-scraping-recon` → `references/hk-tender-pipeline.md` — full pipeline
  architecture, runbook, and pitfalls learned during recon.
- `tender-writing` — Step 5+ bid writing (dossier naming will be reconciled
  there: `01_digest.md`/`02_compliance.md` vs `01_spec_digest.md`/`02_compliance_checklist.md`).
