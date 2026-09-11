#!/usr/bin/env python3
"""Convert a merged Discord JSONL log into a compact plain-text transcript.

Downstream this transcript is read by an LLM to extract advice, so the goal is
to spend as few tokens as possible on structure and as many as possible on the
actual words people said. Three moves get there:

- Plain text, not JSON: no repeated {"ts":...,"user":...} keys, quotes, or
  braces on every line. That framing is pure overhead for a reader that only
  needs who-said-what in order.
- Merge consecutive messages by the same user into one turn: Discord chat is
  bursty (one person fires off five short lines in a row), so the speaker name
  is printed once per turn instead of once per line.
- Drop the timestamp and attachment flag entirely: order alone carries the
  conversation, and image-only posts (empty content) add nothing to read.

Output shape:

    Speaker: first line
    second line
    third line

    NextSpeaker: their message

Usage:
    to_transcript.py INPUT.jsonl OUTPUT.txt
"""
import json
import sys


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: to_transcript.py INPUT.jsonl OUTPUT.txt")
    src, out_path = argv[1], argv[2]

    rows = []
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    # Input is expected time-sorted (see merge.py); preserve that order.
    turns = []  # list of [user, [lines...]]
    skipped_empty = 0
    for o in rows:
        user = (o.get("user") or "unknown").strip()
        content = (o.get("content") or "").strip()
        if not content:
            skipped_empty += 1
            continue
        # A message can itself contain blank lines; drop them so a blank line
        # only ever separates turns. The chunker relies on that to split on
        # turn boundaries without orphaning lines from their speaker.
        msg_lines = [ln for ln in (l.rstrip() for l in content.splitlines()) if ln]
        if not msg_lines:
            skipped_empty += 1
            continue
        if turns and turns[-1][0] == user:
            turns[-1][1].extend(msg_lines)
        else:
            turns.append([user, msg_lines])

    with open(out_path, "w", encoding="utf-8") as out:
        for user, lines in turns:
            out.write(f"{user}: {lines[0]}\n")
            for extra in lines[1:]:
                out.write(f"{extra}\n")
            out.write("\n")

    print(f"messages={len(rows)} skipped_empty={skipped_empty} turns={len(turns)}")


if __name__ == "__main__":
    main(sys.argv)
