#!/usr/bin/env python3
"""
News Ticker updater for Discourse via Unraid User Scripts.

• Skips post #1 in each topic (usually the image).  
• Extracts the first Markdown H1 (“# Title”) from each new post.  
• Builds a list of up to 7 most‐recent unique headlines, each as:
    <a href="…">Title</a>
• Joins them with '|' so Discourse sees each link as its own marquee_list entry
  (no quotes or commas).  
• Compares against your saved state and, if different, pushes the new list.  
• Persists last_seen and marquee in state.
"""

import os
import sys
import json
import re
import requests

# ─── Paths & Imports ────────────────────────────────────────────────────────────
PERSISTENT = "/boot/config/plugins/user.scripts/scripts/News Ticker"
sys.path.insert(0, PERSISTENT)  # allow vendored requests if you pip‑installed there

CFG_PATH   = os.path.join(PERSISTENT, "news_ticker_config.json")
STATE_PATH = os.path.join(PERSISTENT, "news_ticker_state.json")

# ─── Load & Save ────────────────────────────────────────────────────────────────
def load_config():
    try:
        return json.load(open(CFG_PATH, "r"))
    except FileNotFoundError:
        sys.exit(f"[ERROR] Missing config: {CFG_PATH}")

def load_state():
    if os.path.exists(STATE_PATH):
        st = json.load(open(STATE_PATH, "r"))
    else:
        st = {}
    return {
        "last_seen": st.get("last_seen", {}),
        "marquee":   st.get("marquee", [])
    }

def save_state(state):
    json.dump(state, open(STATE_PATH, "w"), indent=2)

# ─── Discourse API Calls ───────────────────────────────────────────────────────
def get_posts(topic_id, base_url, headers):
    url = f"{base_url}/t/{topic_id}/posts.json?include_raw=true"
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json().get("post_stream", {}).get("posts", [])

def update_ticker(items, cfg):
    """
    PUT to /admin/themes/{component_id}/setting.json with:
      { name: "marquee_list", value: "item1|item2|…" }
    """
    url = f"{cfg['base_url']}/admin/themes/{cfg['component_id']}/setting.json"
    hdr = {
        "Api-Key":      cfg["api_key"],
        "Api-Username": cfg["api_username"],
        "Content-Type": "application/json",
    }
    payload = {
        "name":  "marquee_list",
        "value": "|".join(items)
    }
    resp = requests.put(url, headers=hdr, json=payload, timeout=10)
    resp.raise_for_status()
    print(f"[+] Ticker updated with {len(items)} item(s)")

# ─── Utility: Keep up to N unique, most recent ────────────────────────────────
def uniq_limit(pairs, limit=7):
    seen = set()
    out  = []
    # None timestamps are treated as empty string, so real ISO‐dates sort first
    for _, itm in sorted(pairs, key=lambda x: x[0] or "", reverse=True):
        if itm not in seen:
            seen.add(itm)
            out.append(itm)
            if len(out) >= limit:
                break
    return out

# ─── Main Logic ────────────────────────────────────────────────────────────────
def main():
    cfg   = load_config()
    state = load_state()

    headers = {
        "Api-Key":      cfg["api_key"],
        "Api-Username": cfg["api_username"]
    }
    HEADING = re.compile(r"^#\s+(.+)$")

    all_cands = []
    new_cands = []

    for tid in cfg["topics"]:
        posts = get_posts(tid, cfg["base_url"], headers)
        seen  = state["last_seen"].get(str(tid), 0)

        for p in posts:
            pn = p.get("post_number", 0)
            if pn == 1:
                continue
            raw = p.get("raw", "")
            title = None
            for line in raw.splitlines():
                m = HEADING.match(line.strip())
                if m:
                    title = m.group(1).strip()
                    break
            if not title:
                continue

            url  = f"{cfg['base_url']}/t/{tid}/{pn}"
            item = f'<a href="{url}">{title}</a>'
            ts   = p.get("created_at", "")
            all_cands.append((ts, item))
            if pn > seen:
                new_cands.append((ts, item))

        if posts:
            state["last_seen"][str(tid)] = max(p.get("post_number", 0) for p in posts)

    # Merge new headlines ahead of the old marquee, else fallback to all_cands
    if new_cands:
        combined = new_cands + [(None, i) for i in state["marquee"]]
        desired  = uniq_limit(combined, 7)
    else:
        desired  = uniq_limit(all_cands, 7)

    # Push if changed
    if desired != state["marquee"]:
        update_ticker(desired, cfg)
        state["marquee"] = desired
    else:
        print("[*] Marquee already up-to-date.")

    save_state(state)

if __name__ == "__main__":
    main()
