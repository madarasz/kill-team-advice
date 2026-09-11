---
name: kill-team-advice-extraction
description: >-
  Distill playing advice for a Warhammer 40k Kill Team faction out of a directory
  of chunked Discord/chat-log files, producing a single structured `<Team> - Advice.md`.
  Use this whenever the user points at a folder of chat-log chunks (a `chunks/`
  dir, a `manifest.json` of turn ranges, files like `chunk_000.txt`) and wants the
  advice/tips/strategy pulled out, filtered, grouped, and summarized — even if they
  just say "analyze these logs", "what advice is in here", "summarize the tips for
  <faction>", or "gather the strategy from this channel". Also use it when they ask
  to update or regenerate an existing `<Team> - Advice.md` from fresh chunks. Fans
  out subagents over the chunks, merges their findings, and writes one canonical
  advice document.
---

# Kill Team Advice Extractor

This is the final stage of a three-stage pipeline:

1. **`discord-scrape`** — scrapes a Discord channel into `scraped-data/<team>/*.jsonl`.
2. **`clean-data`** — merges, transcribes, and chunks that JSONL.
3. **`kill-team-advice-extraction`** (this skill) — fans subagents over the
   `chunks/` that produces and writes `<Team> - Advice.md`.

Turn a pile of chunked Discord chat logs about one Kill Team faction into a single,
skimmable advice document. The logs are mostly noise (banter, memes, painting talk);
the value is the minority of messages that say *how to play the team*. The job is to
find that signal across many chunks in parallel, then merge it into one opinionated,
well-grouped guide.

## Why the shape of this task matters

- **The logs are too big for one context.** They come pre-chunked with overlaps. 
  Read them serially and you blow the budget before merging. So
  **fan out**: one subagent per small batch of chunks, each returning a compact
  structured report, then the orchestrator merges. This is the whole reason the task
  is worth a skill.
- **Signal is repeated.** The same advice surfaces in many chunks from many users.
  That repetition is itself the most useful output — it tells the reader what the
  community actually agrees on. Preserve it: flag anything echoed across chunks/users
  as **[strong consensus]**.
- **Names are messy.** Users abbreviate and nickname constantly (Horde-Slayer → "HS",
  Blademaster → "BM", Celestian Insidiants → "Celestians"/"Sisters"). If you don't
  normalize, the same operative or enemy gets split across three headings. Normalize
  against the canonical name list before you extract (see step 2).

## Workflow

### 1. Survey the input

Look at the chunk directory. Read `manifest.json` if present (it gives per-chunk turn
ranges and token estimates), and sample the first chunk to learn the line format —
usually `Username: message`, with consecutive lines being the same user continuing.
Count the chunks and note their size. This tells you how to batch.

### 2. Identify the team and build a name map

Determine which faction the logs are about (the user usually says; otherwise it's
obvious from the operative names in the sample). Then open the bundled canonical
reference to get exact names:

- `references/teams-and-tacops.md` — every team with its **Faction Rules, Operatives,
  Strategy Ploys, Firefight Ploys, Equipment**, plus the shared **TacOps** and
  **CritOps** lists. It is large (~1450 lines); **do not read it whole** — grep/filter
  to the team you care about (e.g. `grep -n -A40 '^- Deathwatch' references/teams-and-tacops.md`),
  and pull the TacOps/CritOps sections at the bottom.

From that section, build a short **alias map** the subagents will use to normalize:
- Operatives → canonical short name + common abbreviations. Multi-word names get
  abbreviated to initials in chat: `Horde-Slayer (HS)`, `Blademaster (BM)`,
  `Headtaker (HT)`. Single-word ops (Aegis, Gunner, Disruptor) rarely need it.
- Enemy teams → merge nicknames to one label. The reference lists the official name;
  chat uses shorthand (`Celestian Insidiants` → "Celestians" / "Sisters"; `Tempestus
  Aquilons` → "Aquilons"; `Xv26 Stealth Battlesuits` → "Stealth Suits"). Pick one
  label per enemy and merge all its aliases under it.

### 3. Fan out over the chunks

Split the chunks into batches (roughly 50–60k tokens of input
per subagent) and spawn one general-purpose subagent per batch, in parallel, in the
same turn. Run them in the background and merge as they report.

Give every subagent the **same extraction prompt**, filled in with the team name and
the alias map from step 2. Use this template:

```
You are analyzing Discord chat logs about the Warhammer 40k Kill Team faction
<TEAM>. Read these files fully: <absolute paths for this batch>.

Line format is "Username: message"; consecutive lines can be the same user.

Extract ONLY actionable advice on how to PLAY <TEAM>. Extraction rule:
"Chatter, jokes, memes, painting/kitbash talk, and pure balance-wishlist threads
filtered out. Points that recur across many chunks are flagged [strong consensus]."
(A balance wishlist = complaints about what should be buffed/nerfed. That is not
play advice — drop it.)

Normalize names using this map (merge every alias to the canonical label):
<alias map: operatives with abbreviations, enemy teams with nicknames>

Categorize each advice item into exactly one of:
1. OPERATIVE SELECTION — which operatives to bring / how to use them.
2. TACOP SELECTION — which TacOp to pick. TacOps: Plant Banner, Martyrs, Envoy,
   Sweep & Clear, Route, Dominate.
3. MATCHUPS — how to play against a specific enemy team (name the enemy).
4. EQUIPMENT — which equipment to take and when.
5. FACTION RULE — how to use the team's faction rules.
6. PLOYS — how to use strategy/firefight ploys.
7. GENERIC — general play/positioning/tempo advice.

For each advice item give: category, the advice (1–2 sentences), the username who
said it, and whether others echoed/agreed (note repetition explicitly).

Also track USER CONTRIBUTIONS: per username, how many advice items they gave and any
positive feedback/agreement they received (thanks, "great tip", others adopting it,
cited guides/videos).

Be faithful to the source; do not invent advice. Quote sparingly. Return the full
structured report as your final message.
```

### 4. Merge into the advice document

Collect every subagent report and merge into one file named **`<Team> - Advice.md`**
(e.g. `Deathwatch - Advice.md`). While merging:

- **De-duplicate across chunks.** The same point from multiple subagents becomes one
  line — and that cross-chunk repetition is your evidence for tagging it
  **[strong consensus]**.
- **Resolve names** to the canonical labels one more time (subagents mostly do this,
  but catch stragglers).
- **Rank within each section** by how strongly the community holds the view (consensus
  first, contested/ niche later), and surface disagreements honestly ("most say X, but
  Y argues Z") rather than flattening them.
- **Keep it opinionated and concrete.** Reproduce the actual tactical content (breakpoints,
  ranges, ploy interactions, which op kills what), not vague summaries.

## Output format

The document is exactly this, in this order. **H1 is only `<Team> - Advice` with no
paragraph under it** — no preamble, no "distilled from N messages" line. Go straight
into `## TL;DR`.

```markdown
# <Team> - Advice

## TL;DR
<the handful of things nearly everyone agrees on — the fastest way to get better>

## Operative Selection
<per operative: verdict + when/how to use. Auto-includes first, niche/contested last.>

## TacOp Selection
<per TacOp: verdict + when to pick it.>

## Matchups
<per enemy team (merged nickname): key advice for that matchup. A table works well.>

## Equipment Selection
<per equipment piece: take-it-or-not + when.>

## Faction Rule Advice
<how to leverage the faction rules. Omit this section entirely if the logs say nothing.>

## Ploys
<how to use strategy/firefight ploys well. Omit if nothing.>

## Generic Advice
<positioning, tempo, target priority, list-building principles, game-review habits.>

## Core experts
<ONLY the few recognized authorities — the users whose advice others repeatedly adopt,
cite, or thank, and who post referenced guides/videos. One line each: name + what
they're the authority on + evidence of standing. Do NOT include a long roster of every
contributor or the learners; those tiers are noise.>
```

Notes on the sections:
- Flag repeated points inline with **[strong consensus]**.
- "Faction Rule Advice" and "Ploys" are conditional — include them only if the logs
  actually contain such advice; drop the heading otherwise.
- The extraction rule sentence in step 3 is the *method*, not output — don't print it
  in the document.

## Delivering

Create `advice/<Team> - Advice.md` file. Then send it to the user with SendUserFile so they can read it, and give
the TL;DR contents to the user.
