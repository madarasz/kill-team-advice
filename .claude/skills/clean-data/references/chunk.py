#!/usr/bin/env python3
"""Split a turn-based transcript into LLM-sized chunk files.

Downstream, one subagent reads one chunk, so a chunk should be as large as a
subagent can comfortably hold while leaving room for its prompt and output —
50-60k tokens of transcript is the sweet spot (default target 55k).

Two properties matter:

- Break only on turn boundaries. A turn (one speaker's merged burst) is
  separated from the next by a blank line, so a chunk always starts and ends on
  a speaker switch — no message is cut in half and no line is orphaned from its
  author. Token counts are approximate (~4 chars/token), so a chunk lands near
  the target, not exactly on it.
- Overlap a couple of turns between neighbours. A piece of advice often answers
  a question asked in the previous turn; the overlap keeps that context intact
  across a cut so the extractor doesn't lose the thread at boundaries.

Also writes manifest.json (per-chunk turn range, char and token estimate) so the
downstream extractor can see the layout without opening every file.

Usage:
    chunk.py INPUT.txt OUTDIR [--target-tokens 55000] [--overlap 2]
"""
import argparse
import json
import os

CHARS_PER_TOKEN = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("--target-tokens", type=int, default=55000,
                    help="approx tokens per chunk (default 55000; aim 50-60k)")
    ap.add_argument("--overlap", type=int, default=2,
                    help="turns of overlap between consecutive chunks")
    args = ap.parse_args()

    target_chars = args.target_tokens * CHARS_PER_TOKEN

    raw = open(args.input, encoding="utf-8").read().strip("\n")
    turns = [t for t in raw.split("\n\n") if t.strip()]
    n = len(turns)

    chunks = []  # (start, end_exclusive)
    i = 0
    while i < n:
        size = 0
        j = i
        while j < n:
            tlen = len(turns[j]) + 2  # +2 for the blank-line separator
            if size and size + tlen > target_chars:
                break
            size += tlen
            j += 1
        chunks.append((i, j))
        if j >= n:
            break
        i = max(j - args.overlap, i + 1)

    os.makedirs(args.outdir, exist_ok=True)
    dir_label = os.path.basename(args.outdir.rstrip("/")) or "chunks"
    manifest = []
    for idx, (a, b) in enumerate(chunks):
        body = "\n\n".join(turns[a:b])
        name = f"chunk_{idx:03d}.txt"
        with open(os.path.join(args.outdir, name), "w", encoding="utf-8") as f:
            f.write(body)
        manifest.append({
            "file": f"{dir_label}/{name}",
            "turns": [a, b],
            "n_turns": b - a,
            "chars": len(body),
            "approx_tokens": len(body) // CHARS_PER_TOKEN,
        })

    with open(os.path.join(args.outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    tot = sum(m["approx_tokens"] for m in manifest)
    print(f"turns={n} chunks={len(chunks)} overlap={args.overlap} "
          f"approx_total_tokens={tot}")
    print("per-chunk approx_tokens:", [m["approx_tokens"] for m in manifest])


if __name__ == "__main__":
    main()
