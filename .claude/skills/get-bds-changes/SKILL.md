---
name: get-bds-changes
description: >-
  Summarise how Warhammer 40k Kill Team quarterly Balance Dataslate (BDS) updates
  changed ONE specific team's cards (nerfs, buffs, wording), pulled from the
  `madarasz/datacard-manager` GitHub repo. Use this whenever the user asks what
  a BDS / balance update / dataslate / errata did to a named team, how a team was
  nerfed or buffed over time, a team's balance/patch history, or what changed for
  a named team — e.g. "how did the balance updates affect Murderwing", "show me
  Deathwatch's nerfs", "what did the Q3 dataslate do to Kommandos", "BDS history
  for Void Dancer Troupe". Trigger even if they don't say "BDS" by name, as long
  as they mean official Kill Team balance changes for a particular team. Needs the
  `gh` CLI authenticated against GitHub.
---

# Get BDS changes for a Kill Team

Turn the raw card-edit history of one Kill Team into a short, categorised summary
of how the quarterly Balance Dataslates (BDS) changed it. The data lives in the
`madarasz/datacard-manager` repo: each team's cards are in
`data/sets/<Team>/metadata.json`, and every BDS is a commit that edits that file.
`data/constants.json` maps a BDS code (`2026_Q3`) to its `displayName` and `date`.

## Workflow

### 1. Resolve the team name
The user gives a team (e.g. "Murderwing", "murderwing", "the Deathwatch"). The
script needs the **exact directory name** under `data/sets/` (capitalised, spaces
allowed: `Void Dancer Troupe`, `Hand Of The Archon`). If you're unsure of the
exact casing/spelling, run:

```
python3 scripts/bds_changes.py --list-teams
```

and pick the match. `.claude/skills/kill-team-advice-extraction/references/teams-and-tacops.md`
also lists every canonical team name if you need to disambiguate.

### 2. Gather the data (one command)
Run the bundled script — it does all the GitHub fetching, downloads every commit's
version of the file, index-matches cards across commits, and prints the raw
word-level diffs plus `bdsVersion` transitions:

```
python3 scripts/bds_changes.py "<Team>"
```

Do **not** re-implement this by hand with `gh` + `git diff`. The script exists
because naive git-diffing of this JSON is misleading — see the traps below.

### 2b. Resolve any REVERT against the official rules (do this whenever the script flags one)
The datacard repo is a fan-made mirror, so a `REVERT` flag (text jumps back to an
earlier state with no `bdsVersion` bump) is ambiguous: it might be the mirror
*fixing* its own earlier mistake, or *introducing* one. Don't guess — check GW's
own PDF, which is the source of truth. Run:

```
python3 scripts/official_update_log.py "<Team>"
```

This queries GW's download API, fetches the team's rules PDF, and prints **only
the UPDATE LOG section** (the authoritative changelog) with formatting preserved:

- `⟦edit:…⟧` — blue text = a clarification / wording edit.
- `⟦balance:…⟧` — magenta text = a balance change.
- `~~…~~` — **struck through = DELETED**. This is the crucial signal a plain text
  dump destroys. GW writes a removed rule as struck magenta; if you can't see the
  strike you'll read a deletion as still-live and miss a real nerf.
- Entries under **PREVIOUS ERRATAS** are still-in-force changes from earlier
  updates (not re-listed under the current month because they didn't change this
  quarter) — treat them as current truth.

(This step needs PyMuPDF for strike-aware extraction — `pip install pymupdf` if
`import fitz` fails. If GW's API/PDF is unreachable, fall back to reporting the
revert as **UNVERIFIED**.)

Find the card's entry in that output and compare it to what the datacard diff
claims. Only read the UPDATE LOG — the datacard pages earlier in the PDF can
carry the same faulty text, so they prove nothing. Then decide:
- Official log matches the datacard's **pre-revert** text → the revert was a bad
  edit; the datacard is now **wrong**. Report the real (pre-revert) change and
  add a note that the datacard data currently misstates it.
- Official log matches the **post-revert** text → the revert was a genuine
  correction; report accordingly.

The point: after checking the official log a "REVERT" is no longer unverified —
you can state the true rule and say which side (if any) the datacard got wrong.

### 3. Categorise each change (this is your job, not the script's)
The script reports *what text changed*; you decide *what it means*. Read each
diff and label it. The script stays out of this on purpose: nerf-vs-buff needs
game judgement (a range going `3"→2"` is a nerf; a ploy's usage window widening
is a buff), which is exactly what you're good at and a regex isn't.

Categories — start every bullet with one:
- **NERF** — the change makes the team weaker (worse stats, tighter restrictions,
  shorter ranges, narrower usage windows, lost abilities).
- **BUFF** — the change makes the team stronger.
- **WORDING** — clarification/errata with no real power change (rephrasing,
  relocating a rule, punctuation, "activation/counteraction" → "activation").
- **UNVERIFIED** — a `REVERT` you could not resolve against the official PDF
  (e.g. the download API was unreachable). This should be rare: step 2b resolves
  most reverts. Once resolved, a revert becomes a normal NERF / BUFF / WORDING
  based on the *official* rule, ideally with a note on what the datacard got
  wrong — see the Warp Talon example below.

Add an adjective on the extent when it's clear: `NERF (major)`, `BUFF (minor)`.
If a change is genuinely a real rules edit but you can't tell direction, use
`CHANGE` and explain.

### 4. Write the summary
Group by BDS release, newest concern last (chronological), and **skip any BDS
that didn't touch this team** — don't pad the output with "no changes" sections
or summaries of what the BDS did for *other* teams. Focus only on the requested
team.

Bullet format — category first, then the card name and its type in parentheses,
then a plain-English description of the change:

```
### <BDS displayName> (<date>)
- **NERF (major) - Jump Pack (faction rule)** — plain-English what changed and why it's weaker.
- **WORDING - Vox-casters (equipment)** — what was reworded.
```

Keep descriptions short and concrete (name the actual number/keyword that moved).
End with a one- or two-line takeaway on the team's overall trajectory (serially
nerfed? buffed back into viability?) — but only if it adds something.

## Traps (already handled or flagged by the script — respect them)

- **Never call a card "new" from a raw diff alone.** When a card gains enough text
  it can become two-sided and shift the list, so a positional diff makes an
  *edited* card look new or deleted. The script index-matches and prints a loud
  `⚠️ COUNT SHIFT` warning whenever the card count changes between commits — if you
  see that warning, treat that commit's diffs as suspect and verify any "new/removed
  card" claim by name against the previous version (`--json` gives you the indices).
  This is the exact mistake that once turned relocated Bladefins text into a
  phantom "new equipment".

- **Reverts must be checked against the official PDF, not guessed.** The script
  flags `REVERT` when a card's text returns to an earlier state without a
  `bdsVersion` bump. The mirror can revert to *fix* a mistake or to *cause* one —
  so run `official_update_log.py` (step 2b) and let GW's changelog decide. A
  revert once erased a real Warp Talon nerf: the mirror's Q2 edit was correct and
  its Q3 "revert" regressed it, which only the official log reveals.

- **Strikethrough = deletion, and plain text extraction destroys it.** GW marks a
  removed rule as struck-through magenta. `official_update_log.py` surfaces it as
  `~~…~~`; do not use `pdftotext` or a generic PDF reader for this check, because
  they drop the strike line and a deleted rule then reads as still in force. This
  is exactly how the Warp Talon self-obscure removal was first missed.

- **The first commit is stamp-only.** The file's history starts at some commit;
  changes from that first BDS show only as a `bdsVersion` stamp with no prior text
  to diff. The script marks these `stamp-only`. Mention the card was changed in
  that BDS, but say the detail isn't recoverable from history rather than guessing.

- **`bdsVersion` records only the *last* BDS that touched a card.** Trust the
  per-commit diffs for the actual sequence of changes, not the single stamp on the
  current card.

## Example (abridged, for the `Murderwing` team)

```
### 2026 Q2 Emergency Update (2026-04-01)
- **NERF (major) - Jump Pack (faction rule)** — BOOST during a Charge no longer adds the extra 2" of movement.
- **NERF (major) - Malicious Narcissism (firefight ploy)** — usable window slashed: now only while you have fewer ready operatives than your opponent.
- **WORDING - Bladefins (equipment)** — anti-combo restriction relocated onto the Depredator card; equipment unchanged in effect.

### 2026 Q2 Balance Dataslate (2026-04-29)
- **NERF - Warp Talon (operative)** — lost its self-obscure (was obscured to enemies more than 3" away after emerging from the warp); activation cap also reworded to "cannot spend more than 2AP". _Note: the datacard-manager data is currently wrong here — its Q3 commit reverted both edits (a REVERT flag). The official Update Log confirms the removal (struck-through magenta), so the nerf is real._
```

The Warp Talon line shows the payoff of step 2b: the script raised a `REVERT`
flag on the Q3 commit, the official log resolved it (the removed clause is struck
through), and the change lands as a real dated NERF plus a note that the mirror's
data is stale — instead of a vague "unverified".
