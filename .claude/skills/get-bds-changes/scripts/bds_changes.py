#!/usr/bin/env python3
"""Gather per-card BDS (Balance Dataslate) change history for one Kill Team.

Pulls data from the `madarasz/datacard-manager` GitHub repo via the `gh` CLI:
  - data/constants.json            -> BDS name -> {date, displayName}
  - data/sets/<Team>/metadata.json -> the team's card set, at every commit

For each commit (each roughly one BDS release) it index-matches cards against
the previous commit and reports, per changed card, a word-level text diff plus
any `bdsVersion` transition. It flags two things the model must NOT trust
blindly:

  * COUNT SHIFT: if the number of cards changed between two commits, index
    matching is unreliable (a card gaining text can become two-sided and shift
    the list). The pair is reported with a loud warning so the model can treat
    those diffs as suspect instead of inventing "new card" changes.

  * REVERT: if a card's new text equals its text in an earlier commit (state
    went backwards) AND its bdsVersion did not advance, it's very likely a
    datacard-data correction, not a real rules change. Flagged UNVERIFIED.

The script deliberately does NOT decide NERF vs BUFF vs WORDING — that needs
semantic judgement about the game, which the model does. The script's job is to
hand the model trustworthy, deduplicated raw diffs so it doesn't have to eyeball
git output (which is where the "Bladefins looked new" mistake came from).

Usage:
    python3 bds_changes.py "<Team>"          # e.g. "Murderwing", "Deathwatch"
    python3 bds_changes.py "<Team>" --json   # machine-readable, same content

Team name must be the exact directory name under data/sets/ (capitalised,
spaces allowed, e.g. "Void Dancer Troupe"). Run with --list-teams to print the
available directory names if unsure.
"""
import json
import re
import subprocess
import sys
import difflib

REPO = "madarasz/datacard-manager"
# Oldest snapshot version stamp — cards at this value were never touched by a
# tracked BDS, so a card sitting at it is "unchanged since release".
RELEASE = "2024_Release"


def gh_json(path):
    """GET a repo file via `gh api` and return its decoded JSON content."""
    import base64
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"gh api failed for {path}:\n{out.stderr}")
    content = json.loads(out.stdout)["content"]
    return json.loads(base64.b64decode(content))


def gh_json_at(path, ref):
    import base64
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}?ref={ref}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"gh api failed for {path}@{ref}:\n{out.stderr}")
    content = json.loads(out.stdout)["content"]
    return json.loads(base64.b64decode(content))


def list_teams():
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/data/sets"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(out.stderr)
    return sorted(e["name"] for e in json.loads(out.stdout) if e["type"] == "dir")


def commits_for(path):
    """Return commits touching `path`, OLDEST first: [(sha, date, message)]."""
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/commits?path={path}&per_page=100",
         "--jq", r'.[] | "\(.sha)\t\(.commit.author.date)\t\(.commit.message | gsub("\n";" "))"'],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(out.stderr)
    rows = [ln.split("\t", 2) for ln in out.stdout.splitlines() if ln.strip()]
    return list(reversed(rows))  # gh gives newest-first


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def _clean_name(name):
    """Trim artefacts of greedy ALLCAPS capture.

    The word right after a card's title is often the first (capitalised) word of
    its prose, e.g. "JUMP PACK Armour…" captures a stray "A". Drop trailing 1-2
    letter tokens and a trailing "EXAMPLE" (second-side example cards)."""
    words = name.split()
    while words and (len(words[-1]) <= 2 or words[-1] == "EXAMPLE"):
        # Keep genuine short names (single-word titles) — only strip when there's
        # a longer title in front.
        if len(words) == 1:
            break
        words.pop()
    return " ".join(words)


def card_label(card, team=""):
    """Human-readable card name + type suffix. Best-effort, for display only."""
    t = norm(card["text"])
    typ = card.get("type", "")
    suffix = {
        "Operatives": "operative",
        "Operative Selection": "operative selection",
        "Faction Rules": "faction rule",
        "Strategic Ploys": "strategy ploy",
        "Firefight Ploys": "firefight ploy",
        "Equipment": "equipment",
    }.get(typ, typ.lower())

    if typ == "Operatives":
        # Operative name is the ALLCAPS run just before "N APL" near the end.
        m = list(re.finditer(r"([A-Z][A-Z'’]+(?: [A-Z][A-Z'’]+)*) \d+ APL", t))
        if m:
            name = m[-1].group(1)
            # The run can pick up trailing keyword-list tokens; the operative's
            # own name starts at the last occurrence of the team name.
            tu = team.upper()
            if tu and tu in name:
                name = name[name.rfind(tu):]
            return f"{name} ({suffix})"
    # Ploys / equipment / faction rules: name follows the keyword header.
    m = re.search(
        r"(?:STRATEGY PLOY|STRATEGIC PLOY|FIREFIGHT PLOY|FACTION EQUIPMENT|FACTION RULE)\s+"
        r"([A-Z][A-Z'’!?/&-]*(?: [A-Z][A-Z'’!?/&-]*)*)",
        t,
    )
    if m:
        return f"{_clean_name(m.group(1).strip())} ({suffix})"
    return f"{t[:40]}… ({suffix})"


def word_diff(old, new):
    """Return list of ('DEL'|'INS'|'OLD'|'NEW', text) fragments, old vs new."""
    frags = []
    sm = difflib.SequenceMatcher(None, old.split(), new.split())
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "delete":
            frags.append(("DEL", " ".join(old.split()[a1:a2])))
        elif op == "insert":
            frags.append(("INS", " ".join(new.split()[b1:b2])))
        elif op == "replace":
            frags.append(("OLD", " ".join(old.split()[a1:a2])))
            frags.append(("NEW", " ".join(new.split()[b1:b2])))
    return frags


def build(team):
    path = f"data/sets/{team}/metadata.json"
    bds = gh_json("data/constants.json").get("bds", [])
    bds_map = {b["name"]: b for b in bds}

    commits = commits_for(path)
    if not commits:
        sys.exit(f"No commit history for {path}. Check the team name "
                 f"(run with --list-teams).")

    # Download every version's card list once.
    versions = []  # [(sha, date, msg, [cards])]
    for sha, date, msg in commits:
        cards = gh_json_at(path, sha)["cards"]
        versions.append((sha, date, msg, cards))

    result = {"team": team, "commits": []}

    for idx, (sha, date, msg, cards) in enumerate(versions):
        entry = {
            "sha": sha[:10], "date": date, "message": msg,
            "count_shift": None, "changes": [], "bds": None,
        }

        if idx == 0:
            # File created here: earliest changes visible only as stamps, no
            # prior text to diff. Report cards already advanced past RELEASE.
            entry["created_here"] = True
            for i, c in enumerate(cards):
                if c.get("bdsVersion") and c["bdsVersion"] != RELEASE:
                    entry["changes"].append({
                        "index": i, "label": card_label(c, team),
                        "type": c.get("type"),
                        "bds_from": None, "bds_to": c["bdsVersion"],
                        "stamp_only": True, "revert": False, "diff": [],
                    })
        else:
            prev = versions[idx - 1][3]
            if len(prev) != len(cards):
                entry["count_shift"] = {"prev": len(prev), "now": len(cards)}
            n = min(len(prev), len(cards))
            for i in range(n):
                pc, cc = prev[i], cards[i]
                pt, ct = norm(pc["text"]), norm(cc["text"])
                bf, bt = pc.get("bdsVersion"), cc.get("bdsVersion")
                if pt == ct and bf == bt:
                    continue
                # Revert: current text equals this card's text in any strictly
                # earlier version (state moved backwards).
                reverted = False
                for j in range(idx - 1, -1, -1):
                    older = versions[j][3]
                    if i < len(older) and norm(older[i]["text"]) == ct and ct != pt:
                        reverted = True
                        break
                entry["changes"].append({
                    "index": i, "label": card_label(cc, team),
                    "type": cc.get("type"),
                    "bds_from": bf, "bds_to": bt,
                    "stamp_only": False,
                    "revert": reverted and bf == bt,
                    "diff": word_diff(pt, ct),
                })

        # Which BDS is this commit? Use the dominant NEW bdsVersion among
        # changed cards; fall back to none (model reads commit message).
        bumped = [ch["bds_to"] for ch in entry["changes"]
                  if ch["bds_to"] and ch["bds_to"] != ch["bds_from"]
                  and ch["bds_to"] != RELEASE]
        if bumped:
            top = max(set(bumped), key=bumped.count)
            entry["bds"] = {"name": top, **bds_map.get(top, {})}
        result["commits"].append(entry)

    return result


def render(result):
    lines = [f"# {result['team']} — BDS change data", ""]
    for c in result["commits"]:
        changes = c["changes"]
        header = c["message"]
        if c.get("bds"):
            b = c["bds"]
            header = f"{b.get('displayName', b['name'])} ({b.get('date','?')})"
        lines.append(f"## commit {c['sha']} — {header}")
        if c.get("created_here"):
            lines.append("_History begins here (file created at this commit); "
                         "changes below are stamp-only, no prior text to diff._")
        if c.get("count_shift"):
            cs = c["count_shift"]
            lines.append(f"⚠️ COUNT SHIFT {cs['prev']}→{cs['now']} cards — "
                         f"index matching UNRELIABLE for this commit; verify any "
                         f"'new card' claim against the previous version by name.")
        if not changes:
            lines.append("_No card changes for this team._")
            lines.append("")
            continue
        for ch in changes:
            tag = []
            if ch["bds_from"] != ch["bds_to"]:
                tag.append(f"bdsVersion {ch['bds_from']} → {ch['bds_to']}")
            if ch["revert"]:
                tag.append("REVERT (bdsVersion NOT bumped → likely data fix, "
                           "flag UNVERIFIED)")
            if ch["stamp_only"]:
                tag.append("stamp-only, no diff available")
            suffix = ("  [" + "; ".join(tag) + "]") if tag else ""
            lines.append(f"\n### [{ch['index']}] {ch['label']}{suffix}")
            for kind, frag in ch["diff"]:
                sym = {"DEL": "− DEL", "INS": "+ INS",
                       "OLD": "− OLD", "NEW": "+ NEW"}[kind]
                lines.append(f"  {sym}: {frag[:400]}")
        lines.append("")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if "--list-teams" in args:
        print("\n".join(list_teams()))
        return
    as_json = "--json" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    team = args[0]
    result = build(team)
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render(result))


if __name__ == "__main__":
    main()
