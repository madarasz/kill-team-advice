#!/usr/bin/env python3
"""Merge several Discord JSONL scrape files into one, deduped and time-sorted.

The scraper emits one JSON object per line: {ts, user, content, attachment}.
Separate scrapes (a full pass plus gap/backfill passes) overlap in time, so the
same message appears in more than one file. Dedupe on (ts, user, content) — the
snowflake-derived ts plus author plus text uniquely identify a message — then
sort by ts so the merged log reads front to back in time.

Usage:
    merge.py OUTPUT.jsonl INPUT1.jsonl INPUT2.jsonl [INPUT3.jsonl ...]

Optional even with a single input file: it will still dedupe and sort.
"""
import json
import sys


def main(argv):
    if len(argv) < 3:
        sys.exit("usage: merge.py OUTPUT.jsonl INPUT1.jsonl [INPUT2.jsonl ...]")
    out_path, in_paths = argv[1], argv[2:]

    seen = set()
    rows = []
    dupes = bad = 0
    for f in in_paths:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                key = (obj.get("ts"), obj.get("user"), obj.get("content"))
                if key in seen:
                    dupes += 1
                    continue
                seen.add(key)
                rows.append(obj)

    rows.sort(key=lambda o: o.get("ts") or "")

    with open(out_path, "w", encoding="utf-8") as out:
        for o in rows:
            out.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(f"kept={len(rows)} dupes={dupes} bad_json={bad}")
    if rows:
        print(f"first={rows[0].get('ts')} last={rows[-1].get('ts')}")


if __name__ == "__main__":
    main(sys.argv)
