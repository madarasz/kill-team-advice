#!/usr/bin/env python3
"""Fetch a Kill Team's OFFICIAL "UPDATE LOG" from Games Workshop and print it
with colour + strikethrough preserved.

Why this exists: the `madarasz/datacard-manager` history occasionally contains a
"revert" — a card's text jumps back to an earlier state without a bdsVersion
bump. That is usually a datacard-data error, but "usually" isn't good enough, so
this script checks the change against GW's own rules PDF, which is the source of
truth.

Two extraction subtleties this handles that naive tools get wrong:

  * COLOUR encodes intent. In GW's update logs, blue text (#0099d9) marks a
    clarification/wording edit and magenta (#ec0086) marks a balance change.
  * STRIKETHROUGH means DELETION. `pdftotext` silently drops the strike line, so
    struck (removed) text reads as if it's still live — which once made a real
    nerf (Warp Talon losing its self-obscure) look like it was retained. We
    detect the strike as a thin horizontal vector line drawn across a span and
    mark that text ~~struck~~.

Only the UPDATE LOG section is read. Earlier pages of the PDF (the actual
datacards) can themselves carry the faulty text — the update log is the
authoritative changelog, so we stop reading once the operative/gallery pages
begin.

Usage:
    python3 official_update_log.py "<Team>"     # e.g. "Murderwing"

Requires: `curl` for the API/asset fetch, and PyMuPDF (`import fitz`) for
strike/colour-aware extraction. If PyMuPDF is missing, install with
`pip install pymupdf`.
"""
import json
import subprocess
import sys
import tempfile
import os

API = "https://www.warhammer-community.com/api/search/downloads/"
ASSET_BASE = "https://assets.warhammer-community.com/"

BLUE = 0x0099d9      # clarification / wording edit
BLUE2 = 0x00aeef     # a second blue GW uses for keywords in edited text
MAGENTA = 0xec0086   # balance change
ORANGE = 0xf15c22    # section headings

# Orange headings that mark the END of the update log (gallery / rules pages).
END_HEADINGS = ("OPERATIVES", "KILL TEAM", "DESIGNER", "EQUIPMENT LIST")


def find_file(team):
    payload = json.dumps({
        "index": "downloads_v2", "searchTerm": "",
        "gameSystem": "kill-team", "language": "english",
    })
    out = subprocess.run(
        ["curl", "-s", "-X", "POST", API,
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"API request failed:\n{out.stderr}")
    data = json.loads(out.stdout)
    hits = data.get("hits", data) if isinstance(data, dict) else data
    tl = team.strip().lower()
    for h in hits:
        if h.get("title", "").strip().lower() == tl:
            f = h.get("id", {}).get("file") or h.get("file")
            if f:
                return f, h.get("id", {}).get("last_updated")
    titles = ", ".join(sorted(h.get("title", "?") for h in hits))
    sys.exit(f"No download titled '{team}'. Available: {titles}")


def download(fname):
    path = os.path.join(tempfile.gettempdir(), fname)
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        url = ASSET_BASE + fname
        out = subprocess.run(["curl", "-s", "-o", path, url],
                             capture_output=True, text=True)
        if out.returncode != 0 or not os.path.exists(path):
            sys.exit(f"Download failed for {url}\n{out.stderr}")
    return path


def horizontal_segments(page):
    """All thin horizontal line/rect drawings on the page: (x0, x1, y)."""
    segs = []
    for dr in page.get_drawings():
        for it in dr.get("items", []):
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.y - p2.y) < 0.8 and abs(p2.x - p1.x) > 8:
                    segs.append((min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2))
            elif it[0] == "re":
                r = it[1]
                if r.height < 1.5 and r.width > 8:
                    segs.append((r.x0, r.x1, r.y0 + r.height / 2))
    return segs


def is_struck(span, segs):
    """A span is struck if a horizontal segment crosses its vertical middle and
    overlaps most of its width (a strike runs through the text, not under it)."""
    x0, y0, x1, y1 = span["bbox"]
    mid_lo, mid_hi = y0 + 0.30 * (y1 - y0), y0 + 0.72 * (y1 - y0)
    w = max(x1 - x0, 1)
    for sx0, sx1, sy in segs:
        if mid_lo <= sy <= mid_hi:
            overlap = min(x1, sx1) - max(x0, sx0)
            if overlap > 0.4 * w:
                return True
    return False


def tag(span, segs):
    """Return the text wrapped with markers for colour + strikethrough."""
    t = span["text"]
    if not t.strip():
        return t
    c = span["color"]
    # White Q:/A: labels sit on a decorative bullet the strike detector mistakes
    # for a line-through; they're never struck rules text, so skip them.
    struck = c != 0xffffff and is_struck(span, segs)
    if struck:
        # Deletion. Colour is usually magenta (balance) but the point is it's GONE.
        return f"~~{t}~~"
    if c in (BLUE, BLUE2):
        return f"⟦edit:{t}⟧"
    if c == MAGENTA:
        return f"⟦balance:{t}⟧"
    return t


def extract(path):
    import fitz
    doc = fitz.open(path)
    started = False
    lines_out = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not started and "UPDATE LOG" not in page.get_text():
            continue
        started = True
        segs = horizontal_segments(page)
        d = page.get_text("dict")
        for block in d["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                # Stop at the first orange heading that starts the gallery pages.
                joined_upper = "".join(s["text"] for s in spans).upper()
                if any(s["color"] == ORANGE for s in spans) and \
                   any(h in joined_upper for h in END_HEADINGS):
                    doc.close()
                    return "\n".join(lines_out)
                # Mark orange headings so entry boundaries are visible.
                if spans and spans[0]["color"] == ORANGE and joined_upper.strip():
                    lines_out.append("")
                    lines_out.append("## " + "".join(s["text"] for s in spans).strip())
                    continue
                text = "".join(tag(s, segs) for s in spans)
                if text.strip():
                    lines_out.append(text.rstrip())
    doc.close()
    return "\n".join(lines_out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    team = args[0]
    fname, updated = find_file(team)
    path = download(fname)
    print(f"# {team} — OFFICIAL update log (source of truth)")
    print(f"# file: {fname}  last_updated: {updated}")
    print("# legend: ⟦edit:…⟧ = blue clarification/wording, "
          "⟦balance:…⟧ = magenta balance change, ~~…~~ = STRUCK THROUGH = DELETED")
    print("# 'PREVIOUS ERRATAS' = still-in-force changes from earlier updates.\n")
    print(extract(path))


if __name__ == "__main__":
    main()
