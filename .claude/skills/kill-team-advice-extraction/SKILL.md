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

It also folds in **balance context** from two sources: the logs span many months, and
a quarterly Balance Dataslate (BDS) can nerf or buff something *after* the advice about
it was posted. So before merging, the orchestrator gathers:

1. **This team's card history** — via the `get-bds-changes` skill (a subagent; covers
   the team's own operatives, ploys, equipment, faction rules).
2. **Shared TacOp changes** — from the bundled `references/tacops-bds-changes.md`
   (Dominate, Sweep & Clear, etc. are *shared* Seek & Destroy tac ops that
   `get-bds-changes` does **not** cover, since they aren't on any single team's cards).
   These overtake advice in the **TacOp Selection** section of every team.

Both feed the merge so the orchestrator can flag advice the balance updates have since
overtaken — see step 3b.

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

### 3b. Pull the balance (BDS) history — in parallel with the fan-out

Spawn **one more general-purpose subagent, in the same turn as the step-3 batch
subagents** (background, parallel — it doesn't touch the chunks, so it costs no extra
wall-clock). Tell it to run the **`get-bds-changes`** skill for this exact team and
return the finished categorised summary (the dated NERF/BUFF/WORDING bullets it
produces). Prompt template:

```
Run the get-bds-changes skill for the Warhammer 40k Kill Team "<TEAM>".
Follow that skill's SKILL.md exactly (resolve the team name, run its scripts,
resolve any REVERT against the official PDF, categorise). Return ONLY the final
categorised summary: the dated NERF / BUFF / WORDING bullets grouped by BDS
release, plus the one-line trajectory takeaway. If the `gh` CLI is not
authenticated or the team can't be resolved, say so plainly and return nothing.
```

**Do NOT pass this BDS summary down to the step-3 chunk subagents.** Their job is
faithful extraction of what people *said*; handing them balance verdicts would bias
them into inventing or re-weighting advice, and it bloats every batch prompt with the
same block. The BDS context is the **orchestrator's** to apply once, at merge, where
it can see all the advice at once and knows each card's current state. (If the BDS
subagent returns nothing — no `gh` auth, team unresolved — just skip the card-level
balance annotations and merge as before.)

**Also read the bundled `references/tacops-bds-changes.md` directly** (orchestrator,
no subagent — it's a short, static, dated list of BDS changes to the **shared** TacOps).
`get-bds-changes` cannot surface these because the shared tac ops live on no single
team's cards, yet they overtake advice in the **TacOp Selection** section of every team.
Respect each bullet's scope: a change may carry a note limiting it to specific teams
(e.g. "only affecting Raveners, omit elsewhere") — apply it only where the note allows,
and omit it for teams it doesn't touch.

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
- **Reconcile against both balance sources (step 3b).** For each card the team's BDS
  history touched, *and* each shared TacOp changed in `references/tacops-bds-changes.md`,
  check the advice about it. If a BDS nerfed/buffed it *after* the advice was posted, the
  advice may be stale — the logs might rave about an ability that got cut or a range that
  shrank, or a TacOp that was reworked. Annotate such advice inline with
  **[changed by <BDS displayName>: <one-clause what moved>]** and, when the change flips
  the verdict, say so ("logs love X, but the <date> BDS cut its self-obscure — treat with
  caution"). The TacOp changes land in the **TacOp Selection** section — apply each only
  within its scope note (skip a team-specific change for teams it doesn't name). Don't
  silently delete the advice; the reader benefits from seeing that it predates a
  nerf/buff. A buff can also *promote* a card the older logs dismissed — flag that too.

## Output format

The document is exactly this, in this order. **H1 is only `<Team> - Advice` with no
paragraph under it** — no preamble, no "distilled from N messages" line. Go straight
into `## TL;DR`.

```markdown
# <Team> - Advice

## TL;DR
<the handful of things nearly everyone agrees on — the fastest way to get better>

## Operative Selection
<per operative: verdict + when/how to use. **Order best→worst**: auto-include /
always-bring operatives first, niche/contested in the middle, useless/skip ones last.>

## TacOp Selection
<per TacOp: verdict + when to pick it. **Order best→worst**: strongest picks for this
team first, trap/never-pick ones last.>

## Equipment Selection
<per equipment piece: take-it-or-not + when. **Order best→worst**: staple/always-take
first, situational in the middle, skip-it ones last.>

## Matchups
<per enemy team (merged nickname): key advice for that matchup. A table works well.
**Order best→worst for the team**: matchups the team is favored in first, even/skill
matchups in the middle, worst/near-unwinnable matchups last.>

## Faction Rule Advice
<how to leverage the faction rules. Omit this section entirely if the logs say nothing.>

## Ploys
<how to use strategy/firefight ploys well. Omit if nothing.>

## Generic Advice
<positioning, tempo, target priority, list-building principles, game-review habits.>

## Recent Balance Changes
<short, dated digest from step 3b — the team's own NERF/BUFF/WORDING card bullets plus
the in-scope shared-TacOp changes from `references/tacops-bds-changes.md`, the ones that
matter for how the team plays now, newest last, plus the trajectory takeaway. Omit this
whole section only if both sources returned nothing for this team.>
```

The advice document has **no experts section** — that goes in `experts.md` instead
(next step).

Notes on the sections:
- Flag repeated points inline with **[strong consensus]**.
- "Faction Rule Advice", "Ploys", and "Recent Balance Changes" are conditional —
  include each only if there's content (logs for the first two; for the last, a
  non-empty BDS summary *or* an in-scope TacOp change from `tacops-bds-changes.md`);
  drop the heading otherwise.
- The extraction rule sentence in step 3 is the *method*, not output — don't print it
  in the document.

## Experts (separate file, not the advice doc)

The recognized authorities go in the repo-root **`experts.md`**, not in the advice
document. From the subagents' USER CONTRIBUTIONS tracking, pick ONLY the few authorities —
the users whose advice others repeatedly adopt, cite, or thank, and who post referenced
guides/videos. Do NOT include the long roster of every contributor or the learners; those
tiers are noise.

Append (or update, if the team already has a block) a section to `experts.md` matching the
existing format there — an H1 with the team name, then one `-` bullet per expert:

```markdown
# <Team>

- **<Name>** — <what they're the authority on + evidence of standing (agreement, thanks,
  cited guides/videos, tournament results)>.
```

Keep one line per expert. If `experts.md` already has a block for this team, replace it;
otherwise append a new one.

## Delivering

Create `advice/<Team> - Advice.md` file. Then send it to the user with SendUserFile so they can read it, and give
the TL;DR contents to the user. Update `experts.md` per the section above.
