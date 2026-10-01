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

### 2. Gather the data (two commands — ALWAYS run both)
You need two sources every time. They answer different questions, and neither
is complete alone:

| Source | Gives you | Misses |
|---|---|---|
| `bds_changes.py` (datacard mirror history) | old → new text, so the *direction* of a change; per-commit dates | everything before the history starts (`stamp-only` cards); can carry mirror errors |
| `official_update_log.py` (GW rules PDF) | the *official* amended text, GW's own edit-vs-balance colour, deletions (strikes), `PREVIOUS ERRATAS` back to release | old values; exact BDS dates (grouped by month only) |

```
python3 scripts/bds_changes.py "<Team>"
python3 scripts/official_update_log.py "<Team title>"
```

Do **not** re-implement the first by hand with `gh` + `git diff`. The script
exists because naive git-diffing of this JSON is misleading — see the traps below.

Do **not** skip the PDF because the datacard output has no `REVERT` flag. The PDF
is the only source for `stamp-only` cards (the mirror's first commit holds no
prior text, so all early BDS changes show as bare stamps), and it catches
mirror errors that no flag reveals.

### 2b. Read the official Update Log (always)
GW's rules PDF is the source of truth.

**The two scripts take different team names.** `bds_changes.py` wants the
**directory slug** under `data/sets/` (`Chaos_Cult`, underscores — from
`--list-teams`). `official_update_log.py` wants the **GW download title**
(`Chaos Cult`, spaces). If it errors `No download titled '…'`, pick the
space-separated title from the list it prints.

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
`import fitz` fails. If GW's API/PDF is unreachable, say so in the summary,
report any revert as **UNVERIFIED**, and mark `stamp-only` cards as "detail not
recoverable".)

**Sanity-check the extracted log is complete.** If the output ends mid-sentence,
or shows no `PREVIOUS ERRATAS` block (almost every team has old erratas), the
gallery-stop heuristic tripped early and silently truncated the log. As a
stopgap, dump the update-log pages directly: open the PDF with `fitz`, start at
the page whose text contains `UPDATE LOG`, and print `get_text()` for it and the
next page (plain text loses strikes — use it only to confirm what's missing, not
for the strike check). Then fix the heuristic (see the truncation trap).

### 2c. Resolve any REVERT flag
The datacard repo is a fan-made mirror, so a `REVERT` flag (text jumps back to an
earlier state with no `bdsVersion` bump) is ambiguous: it might be the mirror
*fixing* its own earlier mistake, or *introducing* one. Don't guess.

Find the card's entry in the official log and compare it to what the datacard diff
claims. Only read the UPDATE LOG — the datacard pages earlier in the PDF can
carry the same faulty text, so they prove nothing. Then decide:
- Official log matches the datacard's **pre-revert** text → the revert was a bad
  edit; the datacard is now **wrong**. Report the real (pre-revert) change and
  add a note that the datacard data currently misstates it.
- Official log matches the **post-revert** text → the revert was a genuine
  correction; report accordingly.

The point: after checking the official log a "REVERT" is no longer unverified —
you can state the true rule and say which side (if any) the datacard got wrong.

### 2d. Consolidate the two sources into one change list per card
Build one list of changes before you categorise anything. Walk **every** entry in
the official log (current month, `RULES COMMENTARY`, and `PREVIOUS ERRATAS`) and
**every** card in the datacard output, and match them by card name:

- **In both** → one change. Take the *wording and edit/balance colour* from the
  official log; take the *old value* (for direction) and the *date* from the
  datacard diff.
- **Official only** (usually a `stamp-only` card, or a change older than the
  mirror's history) → still report it. Date it from the card's `bdsVersion` stamp
  (step 3.5). The old value is unknown, so use the struck text, the colour, and
  the rule's structure to call direction; if still unclear, use `CHANGE`.
- **Datacard only** (a text diff with no official entry) → GW leaves out "minor
  changes to standardise wording" (see the log's own header), so this is
  normally **WORDING**. If the diff looks like a real rules change, say the
  official log doesn't list it.
- **Disagree** → the official log wins. Report the official rule and add a note
  that the datacard misstates it.
- **Datacard shows two steps, official shows one** (e.g. a card changed in Q1
  and again in an emergency update) → the official log shows only the *current*
  text. Keep both datacard steps on the timeline; check the final step matches
  the official text.

Do not report a card as "changed, detail not recoverable" when the official log
has an entry for it. That phrase is only for a card with a stamp and no
official entry (or when the PDF is unreachable).

`RULES COMMENTARY` Q&As are not rules changes. Mention one only when it changes
how a change in the summary plays (e.g. which targets a weapon bonus applies to).

### 3. Categorise each change (this is your job, not the script's)
The scripts report *what text changed*; you decide *what it means*. Label each
item in the consolidated list from step 2d. The scripts stay out of this on purpose: nerf-vs-buff needs
game judgement (a range going `3"→2"` is a nerf; a ploy's usage window widening
is a buff), which is exactly what you're good at and a regex isn't.

Categories — start every bullet with one:
- **NERF** — the change makes the team weaker (worse stats, tighter restrictions,
  shorter ranges, narrower usage windows, lost abilities).
- **BUFF** — the change makes the team stronger.
- **WORDING** — clarification/errata with no real power change (rephrasing,
  relocating a rule, punctuation, "activation/counteraction" → "activation").
- **UNVERIFIED** — a `REVERT` you could not resolve against the official PDF
  (e.g. the download API was unreachable). This should be rare: step 2c resolves
  most reverts. Once resolved, a revert becomes a normal NERF / BUFF / WORDING
  based on the *official* rule, ideally with a note on what the datacard got
  wrong — see the Warp Talon example below.

Add an adjective on the extent when it's clear: `NERF (major)`, `BUFF (minor)`.
If a change is genuinely a real rules edit but you can't tell direction, use
`CHANGE` and explain.

**A magenta number needs its old value before you can call direction.** The
official log prints the *amended* (new) text only; struck `~~…~~` marks deletions
but a changed stat gives no direction on its own. `max twice per turning point`
reads as a change, but is a NERF or BUFF only relative to the previous number.
Recover the old value from the datacard diff (`bds_changes.py`) when the change
is inside the diffable window; otherwise label it `CHANGE`. Real case: Mutation
went `once → twice`, which is a **BUFF** — invisible from the PDF alone, and easy
to misread as a nerf ("a cap") if you don't dig out the prior value.

### 3.5 Line each official-log entry up to a dated BDS
The official PDF groups erratas by **month** (`JULY '25`), not by BDS code, so its
entries aren't dated on their own. To place each change on the timeline:

1. `bds_changes.py` prints each card's `bdsVersion` stamp (the BDS code).
2. `data/constants.json` (`bds[]`) maps each code → `displayName` + `date`. Fetch
   with `gh api repos/madarasz/datacard-manager/contents/data/constants.json`.
3. A month heading ≈ that quarter's Balance Dataslate — `JULY '25` → `2025_Q3`
   (`2025 Q3 Balance Dataslate`, 2025-07-23). Confirm against the card's stamp.

**Trap:** `bdsVersion` records only the *last* BDS to touch a card, so a card
errata'd in two releases carries one stamp — an earlier change is invisible.
`PREVIOUS ERRATAS` entries carry older stamps than the current month's entries;
that's expected and is how you separate "this quarter" from "still in force".

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
  so let GW's changelog (step 2c) decide. A
  revert once erased a real Warp Talon nerf: the mirror's Q2 edit was correct and
  its Q3 "revert" regressed it, which only the official log reveals.

- **Strikethrough = deletion, and plain text extraction destroys it.** GW marks a
  removed rule as struck-through magenta. `official_update_log.py` surfaces it as
  `~~…~~`; do not use `pdftotext` or a generic PDF reader for this check, because
  they drop the strike line and a deleted rule then reads as still in force. This
  is exactly how the Warp Talon self-obscure removal was first missed.

- **The official-log extractor can truncate silently.** `official_update_log.py`
  stops in two ways: (1) at the orange heading that opens the datacard gallery
  (`PLAGUE MARINE OPERATIVES`, `KILL TEAM`, …), and (2) at a page after the first
  that carries no log markers (no orange `ERRATA` / `COMMENTARY` heading and no
  orange `TYPE, NAME` heading) — that catches lore pages between log and gallery.
  The gallery match (`is_gallery_heading`) checks **orange text only**, needs the
  heading to **end** with an END word, and rejects any heading with a **comma**.
  Both guards came from real truncations: a whole-line match tripped on black
  "operatives" next to an orange `CHAOS CULT` keyword (lost Chaos Cult's
  `PREVIOUS ERRATAS`), and a substring match tripped on the errata heading
  `CHAMPION, BOMBARDIER & WARRIOR OPERATIVES, *TOXIC` (lost every Plague Marines
  entry after the first). If you change the heuristic, re-test on Plague Marines,
  Chaos Cult, Murderwing, Deathwatch and Kommandos and confirm each log runs to
  its last entry and no lore text leaks in.

- **The first commit is stamp-only.** The file's history starts at some commit;
  changes from that first BDS show only as a `bdsVersion` stamp with no prior text
  to diff. The script marks these `stamp-only`. Get the detail from the official
  log's entry for that card (step 2d). Only if the log has no entry, say the
  detail isn't recoverable rather than guessing.

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

The Warp Talon line shows the payoff of step 2c: the script raised a `REVERT`
flag on the Q3 commit, the official log resolved it (the removed clause is struck
through), and the change lands as a real dated NERF plus a note that the mirror's
data is stale — instead of a vague "unverified".
