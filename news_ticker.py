#!/usr/bin/env python3
"""
News Ticker updater for Discourse via Unraid User Scripts.

• Fetches all H1 (“# …”) headlines (ignoring post #1) from configured topics.
• Builds a list of the 7 most recent unique headlines (linking back to each post).
• Emits each entry as an HTML <a> tag in marquee_list.
• Joins them with '|' so Discourse splits them without quotes or commas.
• Always pushes the updated list (no compare logic).
• Always updates its “last_seen” checkpoints in state.
"""

import os
import sys
import json
import re
import requests

# ─── Paths & Imports ────────────────────────────────────────────────────────────
PERSISTENT = "/boot/config/plugins/user.scripts/scripts/News Ticker"
sys.path.insert(0, PERSISTENT)  # for vendored requests
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
    # join items so Discourse sees each <a>…</a> as its own entry
    payload = {
        "name":  "marquee_list",
        "value": "|".join(items)
    }
    r = requests.put(url, headers=hdr, json=payload, timeout=10)
    r.raise_for_status()
    print(f"[+] Ticker updated with {len(items)} item(s)")

# ─── Main Logic ────────────────────────────────────────────────────────────────
def main():
    cfg   = load_config()
    state = load_state()

    auth = {"Api-Key": cfg["api_key"], "Api-Username": cfg["api_username"]}
    HEADING = re.compile(r"^#\s+(.+)$")

    all_candidates = []
    new_candidates = []

    for tid in cfg["topics"]:
        posts = get_posts(tid, cfg["base_url"], auth)
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
            when = p.get("created_at", "")
            all_candidates.append((when, item))
            if pn > seen:
                new_candidates.append((when, item))

        if posts:
            state["last_seen"][str(tid)] = max(p.get("post_number", 0) for p in posts)

    def uniq_limit(pairs, limit=7):
        seen_items = set()
        result     = []
        for _, itm in sorted(pairs, key=lambda x: x[0], reverse=True):
            if itm not in seen_items:
                seen_items.add(itm)
                result.append(itm)
                if len(result) == limit:
                    break
        return result

    if new_candidates:
        combined = new_candidates + [(None, i) for i in state["marquee"]]
        desired  = uniq_limit(combined, 7)
    else:
        desired  = uniq_limit(all_candidates, 7)

    # Always push the updated list
    update_ticker(desired, cfg)
    state["marquee"] = desired
    save_state(state)

if __name__ == "__main__":
    main()
