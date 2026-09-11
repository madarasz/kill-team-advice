# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A data pipeline (not a conventional app) that turns a Discord channel's history into a
skimmable Warhammer 40k Kill Team advice document. It has no build/test/lint step — the
logic lives in three **skills** under `.claude/skills/`, each a stage of one pipeline.
Working here means running the skills in order, not writing/running code in the usual sense.

## The three-stage pipeline

Data flows: **live Discord tab → JSONL → chunks → advice doc.** Each stage is a skill
and consumes exactly what the previous produced.

1. **`discord-scrape`** — scrapes a Discord channel's DOM (via a browser's `javascript_tool`,
   never screenshots) into `scraped-data/<team>/*.jsonl`, one `{ts,user,content,attachment}`
   object per line. Timestamps are derived arithmetically from the message **snowflake**, not
   parsed from text.
2. **`clean-data`** — merges/dedupes overlapping scrape passes, collapses to a compact
   speaker-turn transcript, and splits into ~55k-token chunks. Pure-stdlib Python 3 scripts
   in `.claude/skills/clean-data/references/`:
   - `merge.py OUT.jsonl IN1.jsonl [IN2...]` — dedupe on `(ts,user,content)`, sort by `ts`.
   - `to_transcript.py MERGED.jsonl OUT.txt` — drop ts/attachment, merge consecutive same-user lines.
   - `chunk.py TRANSCRIPT.txt OUTDIR [--target-tokens 55000] [--overlap 2]` — break only on
     turn boundaries, overlap 2 turns, write `manifest.json`.
3. **`kill-team-advice-extraction`** — fans out one general-purpose subagent per chunk batch
   (in parallel, background), each returns a structured report, then merges into `<Team> - Advice.md`.

**Invoke the skill rather than reinventing its steps** — each SKILL.md holds hard-won detail
(correct Discord selectors, the exfiltration trick around the `javascript_tool` output cap,
the fan-out prompt template). Read the relevant SKILL.md before doing that stage's work.

## Conventions that span stages

- **Team slug.** Everything for one scrape lives under `scraped-data/<team>/` where `<team>`
  is a short lowercase slug (e.g. `deathwatch`). Reuse the same slug across all three stages.
- **`scraped-data/` is gitignored** — scraped message content is never committed. Only skill
  code and the final `<Team> - Advice.md` are tracked.
- **Scripts take explicit paths.** Filenames vary per scrape (a full pass plus gap/backfill
  passes); adapt paths to what actually exists rather than assuming fixed names.

## Non-obvious traps (already handled in the skills, don't re-break)

- **Never reload the Discord page mid-scrape** — it wipes `window.__store`; `localStorage`
  throws in Discord's context, so there's no safe backup. Exfiltrate first, reload after.
- **Selectors matter on replies.** Author is `li h3 [class*="username"]` (not the first
  username match — that's the quoted person); content is `getElementById('message-content-'+id)`
  (not the `[id^=...]` prefix match — that grabs the quoted preview). Authors forward-fill after
  sorting by snowflake.
- **Advice extraction is a fan-out, not a serial read** — the logs exceed one context. One
  subagent per batch, merge the reports; cross-chunk repetition is the signal for `[strong consensus]`.
