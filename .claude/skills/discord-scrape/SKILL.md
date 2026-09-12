---
name: discord-scrape
description: >-
  Extract messages from a Discord channel into structured JSONL
  ({ts, user, content, attachment}) by scraping the live DOM through a browser,
  not by reading screenshots. Use this whenever the user wants to collect,
  archive, export, or scrape Discord messages — a whole channel, a date/timestamp
  range, or a backfill gap — from a Discord tab open in a browser (Claude-in-Chrome
  or the in-app browser). Covers the reliable selectors (snowflake→timestamp,
  author, content, attachments), the on-page accumulator, the scroll pattern that
  actually loads history, and the export paths (blob download, non-destructive
  overlay) that get data out of the page. Trigger on "scrape Discord", "export
  Discord messages", "collect channel history", "backfill Discord", or similar
  even when the user doesn't say "DOM" or "JSONL".
---

# Discord message scraping

This is the first stage of a three-stage pipeline:

1. **`discord-scrape`** (this skill) — scrapes a Discord channel into `scraped-data/<team>/*.jsonl`.
2. **`clean-data`** — merges, transcribes, and chunks that JSONL.
3. **`kill-team-advice-extraction`** — fans subagents over the `chunks/` that
   produces and writes `<Team> - Advice.md`.

Do not run the later stages unless asked.

Discord renders messages in a **virtualized list**: only the on-screen chunk exists
in the DOM at any moment. So you can't fetch the whole history in one shot — you
scroll, harvest what's currently rendered into a persistent accumulator, and repeat
until you've covered the range you want. Everything below serves that loop.

**Scrape from the DOM via JavaScript, never from screenshots.** Screenshot-reading
is slow, lossy, and mangles timestamps and usernames. The DOM has exact data.

## Prefer the API when you can

If the user can get a bot into the server, `GET /channels/{id}/messages?before=<snowflake>&limit=100`
paginates the whole history in ~1 request per 100 messages — no scrolling, no DOM
fragility, no volatile page state. Offer this first and let the user run it locally
so the token never passes through the session. Note once, without lecturing:
automating a *user* account is against Discord's ToS; reading a page the user is
already viewing is a gray area they're choosing to accept.

Use the DOM method below only when the API route isn't available.

## Prerequisites

- A browser with the target Discord channel open and logged in. Either surface works:
  the in-app browser (`mcp__Claude_Browser__javascript_tool` / `get_page_text`) or
  Claude-in-Chrome (`mcp__claude-in-chrome__javascript_tool` / `get_page_text`). Load
  the tools via `ToolSearch` if they aren't already available.
- Confirm with the user *which* channel and *what range* before starting — a full
  channel can be thousands of messages and many slow harvest cycles.
- **Permission mode.** In Auto mode a safety classifier reviews each browser call and
  can latch onto a long run of injected-JS calls, blocking everything for the rest of
  that conversation. Ask the user to select **Manually approve** in the dropdown on the
  chat input before starting. The method needs only ~5–6 calls total, so manual
  approval is cheap.

## Where files go

Write everything under `scraped-data/<team-name>/` at the repo root, where
`<team-name>` is a short lowercase slug for the channel/community being scraped —
e.g. a `#deathwatch` channel goes to `scraped-data/deathwatch/`. Ask the user for the
slug if it isn't obvious. Put the part files and the merged output there:

```
scraped-data/deathwatch/
├── part-0001.jsonl        # only if the overlay fallback is used
├── part-0002.jsonl
└── deathwatch_full.jsonl  # merged, deduped, sorted result
```

`scraped-data/` is gitignored — scraped message content shouldn't be committed. Make
sure the repo's `.gitignore` contains a `scraped-data/` line; add it if missing before
writing any files.

## Output format

One JSON object per line (JSONL):

```json
{"ts":"2026-09-10T14:03:22.000Z","user":"alice","content":"message text","attachment":false,"id":"1357...","edited":false}
```

- `ts` — ISO timestamp derived from the message snowflake (see below). Exact, no parsing.
- `user` — author display name.
- `content` — message text. **Keep URLs** — the download path has no output filter, so
  stripping them is pure data loss.
- `attachment` — `true` if the message carries an image/embed/file, `false` otherwise.
- `id` — the raw snowflake. Reliable dedupe key and sort key when you merge or stitch
  batches later.
- `edited` — `true` if Discord shows the message as edited.

`ts`, `user`, `content` and `attachment` are what downstream stages consume; `id` and
`edited` are additive and safe to ignore.

## The method

### 1. Selectors — get these exactly right

The selectors are the crux; the common mistakes below all silently grab the *wrong*
message on reply/quoted messages.

- **Each message** is `li[id^="chat-messages-"]`. The id is `chat-messages-<channel>-<message>`;
  take the **last** segment. It's a Discord **snowflake** (18–19 digits). Derive the
  timestamp arithmetically — reliable, no text parsing:
  ```js
  const ts = new Date(Number((BigInt(id) >> 22n) + 1420070400000n)).toISOString();
  ```
  Snowflakes exceed `Number.MAX_SAFE_INTEGER`, so **compare them as `BigInt`** — a
  lexical/numeric sort is wrong.
- **Author** = `li.querySelector('h3 [class*="username"]')`.
  Do **not** use the first `[class*="username"]` on the whole `li` — on a reply, that
  matches the *person being replied to*, not the author. The author only renders on
  the **first message of a group**; later messages in the same group have a `null`
  author. Forward-fill after sorting by snowflake — but **never across a >10 min gap**,
  or a new speaker after a lull gets misattributed to the previous one.
- **Content** = `document.getElementById('message-content-' + messageId)` — exact id
  match. Do **not** use `[id^="message-content-"]`; on a reply that also matches the
  *quoted* preview text and you'll capture the wrong thing.
- **Attachment** = presence of any of
  `[class*="attachment"], [class*="imageContainer"], [class*="embedWrapper"], [class*="originalLink"]`.
  Image/meme-only posts have empty content and `attachment: true`.
- **Edited** = presence of `[class*="edited"]` on the `li`.

### 2. Set up the accumulator (paste once)

State lives on `window` so it survives across many tool calls. A `Map` keyed by
snowflake dedupes automatically as the same message gets re-harvested on overlapping
scrolls, and merges partial captures (fill a missing author, keep the longest content,
sticky the attachment flag).

```js
window.__store = window.__store || new Map();
window.__collect = function(){
  let n = 0;
  document.querySelectorAll('li[id^="chat-messages-"]').forEach(li=>{
    const mid = li.id.split('-').pop();
    if(!/^\d{17,20}$/.test(mid)) return;
    const ts  = new Date(Number((BigInt(mid) >> 22n) + 1420070400000n)).toISOString();
    const u   = li.querySelector('h3 [class*="username"]');
    const c   = document.getElementById('message-content-'+mid);
    const a   = !!li.querySelector('[class*="attachment"],[class*="imageContainer"],[class*="embedWrapper"],[class*="originalLink"]');
    const ed  = !!li.querySelector('[class*="edited"]');
    const rec = {id:mid, ts, u:u?u.innerText.trim():null, c:c?c.innerText:'', a:a?1:0, ed:ed?1:0};
    if(!window.__store.has(mid)){ window.__store.set(mid, rec); n++; }
    else { const e=window.__store.get(mid); if(!e.u&&rec.u)e.u=rec.u; if(e.c.length<rec.c.length)e.c=rec.c; if(rec.a)e.a=1; if(rec.ed)e.ed=1; }
  });
  return n;
};
// Find the message scroller (the scrollable element that actually holds the <li>s):
window.__scroller = [...document.querySelectorAll('[class*="scroller"]')]
  .filter(s=>s.querySelector('li[id^="chat-messages-"]'))
  .sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
```

If `__scroller` is undefined the channel hasn't rendered — have the user click into it
and retry.

### 3. Checkpoint helpers (IndexedDB)

Discord deletes `window.localStorage` to prevent token theft — it's `undefined`, so
it's no backup. Use **IndexedDB**. Checkpoint after every harvest batch so a crash or
accidental reload doesn't cost the whole scroll.

```js
window.__save = () => new Promise((res, rej) => {
  const rq = indexedDB.open('ds_scrape', 1);
  rq.onupgradeneeded = e => e.target.result.createObjectStore('b');
  rq.onsuccess = e => {
    const tx = e.target.result.transaction('b', 'readwrite');
    tx.objectStore('b').put(JSON.stringify([...window.__store.values()]), 'store');
    tx.oncomplete = () => res(window.__store.size);
  };
  rq.onerror = () => rej(rq.error);
});
window.__load = () => new Promise(res => {
  const rq = indexedDB.open('ds_scrape', 1);
  rq.onupgradeneeded = e => e.target.result.createObjectStore('b');
  rq.onsuccess = e => {
    const g = e.target.result.transaction('b').objectStore('b').get('store');
    g.onsuccess = () => {
      for (const r of JSON.parse(g.result || '[]')) window.__store.set(r.id, r);
      res(window.__store.size);
    };
  };
});
```

After an unexpected reload: re-run steps 2 (and re-find `__scroller`), then
`await window.__load()` to resume without rescrolling.

### 4. Harvest by scrolling UP

Scrolling **up from the present** is the reliable direction. Downward scrolling drops
messages and stalls at chunk boundaries and on still-loading "skeleton" frames.

```js
window.__minId = () => [...window.__store.keys()]
  .reduce((m,k)=> (m===null || BigInt(k)<BigInt(m)) ? k : m, null);

window.__harvest = async (rounds = 25, targetIso = null) => {
  let added = 0, idle = 0, hitTarget = false;
  for(let i=0;i<rounds;i++){
    const before = window.__store.size;
    window.__scroller.scrollTop = 0;
    await new Promise(r=>setTimeout(r, 550 + Math.random()*250));
    added += window.__collect();
    if(window.__store.size === before){ if(++idle>=5) break; } else idle = 0;
    if(targetIso){
      const min = window.__minId();
      const earliest = new Date(Number((BigInt(min) >> 22n) + 1420070400000n)).toISOString();
      if(earliest < targetIso){ hitTarget = true; break; }
    }
  }
  await window.__save();
  const ids = [...window.__store.keys()].sort((x,y)=> BigInt(x)<BigInt(y)?-1:1);
  const iso = id => new Date(Number((BigInt(id) >> 22n) + 1420070400000n)).toISOString();
  return JSON.stringify({ size: window.__store.size, added,
    earliest: iso(ids[0]), latest: iso(ids[ids.length-1]), hitTarget, atTop: idle>=5 });
};
```

Setting `scrollTop = 0` after each older chunk loads (scrollTop jumps positive once it
does) re-fires the scroll event that triggers the next load. Guidance:

- Call `await window.__harvest(25, '2026-04-02T00:00:00Z')` repeatedly; each call returns
  a small status object — watch `earliest` march backwards. Stop when `hitTarget` or
  `atTop` is true. Omit the target to harvest a fixed number of rounds.
- Longer loops (~40+ rounds) can make the tool *report* a failure, but the work still
  persisted on `window.__store` (and IndexedDB) — just re-query and continue.
- **Positioning to a range:** to reach a gap that ends at the present, click
  **Jump To Present** first, then harvest up until `earliest` reaches your target start.
  Force the jump in JS (the button, then re-find the scroller — it's recreated after the
  jump):
  ```js
  document.querySelector('[class*="jumpToPresentBar"] [class*="button"]')?.click();
  ```
  For an older range with no anchor, use Discord's search / date jump in the UI to land
  near the target, then harvest up and down around it.

### 5. Build records

Forward-fill authors after sorting by snowflake, but never across a >10 min gap.

```js
window.__build = () => {
  const recs = [...window.__store.values()].sort((x,y)=> BigInt(x.id)<BigInt(y.id)?-1:1);
  let last = null, lastT = 0;
  window.__lines = recs.map(r=>{
    const t = Date.parse(r.ts);
    let u = r.u;
    if(!u && last && (t-lastT) < 600000) u = last;   // fill grouped msgs, never across a gap
    if(r.u) last = r.u;
    lastT = t;
    return JSON.stringify({ ts:r.ts, user:u||null, content:r.c.replace(/\s+/g,' ').trim(),
      attachment:!!r.a, id:r.id, edited:!!r.ed });
  });
  return JSON.stringify({ lines: window.__lines.length });
};
```

### 6. Export the data

**Never assign to `document.body.innerHTML`.** It destroys Discord's React tree,
invalidates the scroller reference, and forces a reload. Use the download path; fall back
to a non-destructive overlay only if downloads are blocked.

**Primary — blob download.** One call, whole dataset, nothing through tool output. Ask the
user before triggering it — state the filename and approximate size.

```js
window.__download = (name = 'channel_full.jsonl') => {
  const blob = new Blob([window.__lines.join('\n') + '\n'], { type: 'application/x-ndjson' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 5000);
  return JSON.stringify({ lines: window.__lines.length, bytes: blob.size, name });
};
```

The file lands in the user's Downloads. They attach it to the chat, or — if the session is
linked to their computer — it's picked up directly via the device bridge. Then write the
final file locally under `scraped-data/<team-name>/`. If Discord's CSP blocks the blob
download, retry with a `data:` URL href. Only if that also fails, use the fallback.

**Fallback — non-destructive overlay windows.** Unlike the old `innerHTML` method this
appends a fixed overlay and removes it after, so **no reload is needed**.

```js
window.__show = (a, b) => {
  let el = document.getElementById('__dsout');
  if(!el){
    el = document.createElement('pre');
    el.id = '__dsout';
    el.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#fff;color:#000;overflow:auto;white-space:pre-wrap;font:11px monospace;margin:0;padding:8px';
    document.body.appendChild(el);
  }
  el.textContent = window.__lines.slice(a, b).join('\n');
  return JSON.stringify({ from: a, to: b, total: window.__lines.length });
};
window.__hide = () => { document.getElementById('__dsout')?.remove(); return 'ok'; };
```

Read each window with `get_page_text` and write it to
`scraped-data/<team-name>/part-NNNN.jsonl`. **~240 lines per window** — more overflows the
~50k-char cap. Call `__hide()` when done. This costs roughly one round trip plus a full
retype per 240 messages, so exhaust the download options first.

### 7. Finalize and verify

Write `scraped-data/<team-name>/<team>_full.jsonl`, then check all of:

- Line count matches the reported `lines`.
- All `ts` ≥ the requested start date (drop stragglers from the day before the boundary).
- `id` values are unique and strictly ascending (BigInt compare).
- No implausible multi-day gap in the middle of an active channel — a gap means a missed
  scroll region; re-harvest it.
- Newest message is near today (unless a range was requested).
- Report count, exact date span, distinct authors, attachment count.

If part files from a fallback run exist, diff them against the corresponding slice of the
download — a match validates the download end to end for free.

### Pitfalls

- **Don't reload, navigate, or close the tab mid-scrape** — it wipes `window.__store`.
  IndexedDB (`window.__save`/`__load`) is the only backup; `localStorage` is `undefined`
  on Discord by design. Don't navigate until the data is on disk and verified.
- **Never assign `document.body.innerHTML`** — destroys the React tree and the scroller.
  Append/remove nodes (the overlay above) instead.
- Rapid programmatic scrolling can jam the virtual list into a stuck skeleton state.
  Wait a few seconds, or a single real user scroll resets it.
- Skeleton (still-loading) frames render `<li>`s with no content yet — the dedupe/merge
  in the accumulator handles this (a later pass fills the real content), so just keep
  harvesting.
- Snowflakes are 18–19 digits and exceed `Number.MAX_SAFE_INTEGER` — compare as `BigInt`,
  never lexically or as `Number`.
