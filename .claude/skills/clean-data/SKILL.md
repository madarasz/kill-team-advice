---
name: clean-data
description: >-
  Turn raw scraped Discord JSONL ({ts, user, content, attachment}) into
  LLM-ready chunk files: merge/dedupe overlapping scrape passes, collapse to a
  compact plain-text transcript (speaker turns, no timestamps/attachments), and
  split into ~50-60k-token chunks with a manifest. Use this whenever the user
  has scraped Discord logs under `scraped-data/<team>/` and wants them cleaned,
  merged, chunked, or otherwise "prepped for analysis" before advice extraction
  — even if they just say "clean this up", "chunk these logs", "merge the
  scrapes", "get this ready for the LLM", or "prep the deathwatch data". This is
  the middle stage of the pipeline: it consumes what `discord-scrape` produces
  and produces exactly the `chunks/` directory that `kill-team-advice-extraction`
  consumes. Trigger it after a scrape and before any advice extraction.
---

# Clean Discord data into LLM-ready chunks

This is the middle stage of a three-stage pipeline:

1. **`discord-scrape`** — scrapes a Discord channel into `scraped-data/<team>/*.jsonl`.
2. **`clean-data`** (this skill) — merges, transcribes, and chunks that JSONL.
3. **`kill-team-advice-extraction`** — fans subagents over the `chunks/` this
   produces and writes `<Team> - Advice.md`.

The raw scrape is JSONL, one object per line: `{ts, user, content, attachment}`.
That format is right for archiving but wrong for feeding an LLM — the repeated
JSON keys, the timestamps, and the empty image-only posts are all tokens a reader
that only needs who-said-what-in-order would waste. The job here is to strip the
log down to that essence and cut it into pieces a single subagent can hold.

## Where files live

Everything stays under `scraped-data/<team>/` (gitignored — scraped content isn't
committed). The pipeline adds three artifacts next to the scrape parts:

```
scraped-data/deathwatch/
├── deathwatch_scrape.jsonl                       # scrape pass(es) from discord-scrape
├── deathwatch_gap_2026-06-06_to_2026-09-10.jsonl # a backfill pass, overlaps the above
├── deathwatch_merged.jsonl                       # (1) merged + deduped + time-sorted
├── deathwatch_transcript.txt                     # (2) compact plain-text transcript
└── chunks/                                        # (3) what stage 3 consumes
    ├── chunk_000.txt
    ├── chunk_001.txt
    └── manifest.json
```

Use the same `<team>` slug the scrape used. The scripts take explicit paths, so
adapt the filenames to whatever the scrape actually produced.

## The three steps

The scripts are in `references/`. They are plain-stdlib Python 3, no dependencies.
Run them in order, reading each one's printed summary before moving on.

### 1. Merge + dedupe (optional)

Only needed when there is **more than one** JSONL file — typically a full scrape
plus one or more gap/backfill passes, which overlap in time and so share
messages. If there's a single scrape file that's already clean, skip straight to
step 2 (or run this anyway on the one file — it still dedupes and time-sorts,
harmlessly).

```bash
python3 references/merge.py \
  scraped-data/<team>/<team>_merged.jsonl \
  scraped-data/<team>/<scrape>.jsonl scraped-data/<team>/<gap>.jsonl
```

Dedupe key is `(ts, user, content)` — the snowflake-derived timestamp plus author
plus text pin a message down uniquely, so exact repeats across passes collapse to
one. Output is sorted by `ts`. The printed `dupes=` and `first=/last=` lines are
your sanity check that the overlap was real and the range is what you expect.

### 2. To transcript

```bash
python3 references/to_transcript.py \
  scraped-data/<team>/<team>_merged.jsonl \
  scraped-data/<team>/<team>_transcript.txt
```

This drops `ts` and `attachment`, drops empty (image-only) messages, and merges
each speaker's consecutive burst into one turn so the name is printed once, not
per line. The result looks like:

```
Lunarcultist: I mean kinda?
But only when plasmas good
I dont think they compete for slots most of the time

TheArmorOfContempt: Interesting, ill give it a whirl
```

Expect a big shrink (roughly halving the byte size, and more in tokens because
the JSON scaffolding is gone). The `turns=` count is what step 3 chunks on.

### 3. Chunk

```bash
python3 references/chunk.py \
  scraped-data/<team>/<team>_transcript.txt \
  scraped-data/<team>/chunks
```

Chunks target **55k tokens** by default (the 50-60k a subagent handles well) and
break **only on turn boundaries**, so every chunk starts and ends on a speaker
switch and no message is split. Consecutive chunks **overlap by 2 turns** so a
piece of advice never gets severed from the question it answers. It also writes
`manifest.json` (per-chunk turn range + char/token estimate) that stage 3 reads
to see the layout without opening every file.

Tunables (rarely needed): `--target-tokens N` and `--overlap N`. If the extractor
is running short on context, drop the target; if advice keeps getting cut mid-
thread at boundaries, raise the overlap.

## Verify before handing off

After chunking, glance at the printed `per-chunk approx_tokens:` list — every
entry but the last should sit near the target, and the last is a smaller tail.
Then the data is ready for `kill-team-advice-extraction`, which points at
`scraped-data/<team>/chunks/`.
