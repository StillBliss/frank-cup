"""
The Frank Cup - automated refresh (runs on GitHub Actions)

1. Gets a Yahoo access token from the refresh token in the repo Secrets.
2. Pulls any season folder that is missing (first run pulls all history).
3. Re-pulls the current season: standings, teams, transactions, season
   stats, and every scoreboard week that isn't final yet.
4. Rebuilds data.js from the raw files.

Secrets expected as environment variables:
  YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_REFRESH_TOKEN

Fantasy data provided by Yahoo Fantasy.
"""
import base64, json, os, sys, time
import urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "raw")
CFG = os.path.join(ROOT, "league_config.json")
API = "https://fantasysports.yahooapis.com/fantasy/v2"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
PAUSE = 0.7


def die(msg):
    print("ERROR:", msg)
    sys.exit(1)


def access_token():
    cid = os.environ.get("YAHOO_CLIENT_ID")
    sec = os.environ.get("YAHOO_CLIENT_SECRET")
    ref = os.environ.get("YAHOO_REFRESH_TOKEN")
    if not (cid and sec and ref):
        die("Yahoo secrets are missing. Add YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET "
            "and YAHOO_REFRESH_TOKEN under Settings > Secrets and variables > Actions.")
    body = urllib.parse.urlencode({"grant_type": "refresh_token",
                                   "redirect_uri": "https://localhost:8080",
                                   "refresh_token": ref}).encode()
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Authorization": "Basic " + auth,
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as r:
            tok = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(f"Yahoo refused the refresh token ({e.code}): {e.read().decode()[:300]}\n"
            "If this keeps happening, run frank.py locally to log in again and "
            "paste the new refresh_token into the YAHOO_REFRESH_TOKEN secret.")
    if tok.get("refresh_token") and tok["refresh_token"] != ref:
        print("NOTE: Yahoo issued a different refresh token. The old one still "
              "worked this time; update the secret if future runs fail.")
    return tok["access_token"]


class Yahoo:
    def __init__(self):
        self.token = access_token()
        self.calls = 0

    def get(self, path, tries=4):
        url = f"{API}/{path}{'&' if '?' in path else '?'}format=json"
        for attempt in range(tries):
            time.sleep(PAUSE)
            req = urllib.request.Request(url, headers={
                "Authorization": "Bearer " + self.token, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.calls += 1
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.token = access_token(); continue
                if e.code in (429, 999):
                    time.sleep(20 * (attempt + 1)); continue
                print(f"   HTTP {e.code} on {path}: {e.read().decode(errors='replace')[:200]}")
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                time.sleep(10 * (attempt + 1))
        return None


def save(rel, obj):
    p = os.path.join(RAW, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def load(rel):
    p = os.path.join(RAW, rel)
    if not os.path.exists(p) or os.path.getsize(p) < 40:
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def league_meta(block):
    return {"season": int(block["season"]), "key": block["league_key"], "name": block.get("name"),
            "start": int(block.get("start_week") or 1), "end": int(block.get("end_week") or 25),
            "current": int(block.get("current_week") or 0), "renew": (block.get("renew") or "").strip()}


def my_leagues(y):
    d = y.get("users;use_login=1/games;game_codes=mlb/leagues")
    out = []
    try:
        games = d["fantasy_content"]["users"]["0"]["user"][1]["games"]
    except (KeyError, IndexError, TypeError):
        return out
    for gi in [k for k in games if k.isdigit()]:
        for part in games[gi].get("game", []):
            if isinstance(part, dict) and "leagues" in part:
                lg = part["leagues"]
                for li in [k for k in lg if k.isdigit()]:
                    out.append(league_meta(lg[li]["league"][0]))
    return out


def scoreboard_final(obj):
    try:
        ms = obj["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
        st = [ms[k]["matchup"]["status"] for k in ms if k.isdigit()]
        return bool(st) and all(s == "postevent" for s in st)
    except (KeyError, IndexError, TypeError):
        return False


def pull_season(y, lg, full):
    key, s = lg["key"], str(lg["season"])
    print(f"{s}  {lg['name']}  ({key})  {'full pull' if full else 'refresh'}")
    for name, path in (("settings", "settings"), ("standings", "standings"), ("teams", "teams"),
                       ("draft_results", "draftresults/players"), ("transactions", "transactions"),
                       ("team_stats_season", "teams/stats;type=season")):
        if not full and name in ("settings", "draft_results") and load(f"{s}/{name}.json"):
            continue
        obj = y.get(f"league/{key}/{path}")
        if obj is None:
            die(f"could not pull {name} for {s}")
        save(f"{s}/{name}.json", obj)
    last = lg["end"] if full else min(lg["end"], max(lg["current"], lg["start"]))
    for wk in range(lg["start"], last + 1):
        rel = f"{s}/scoreboard/week_{wk:02d}.json"
        old = load(rel)
        if old and scoreboard_final(old):
            continue
        obj = y.get(f"league/{key}/scoreboard;week={wk}")
        if obj is not None:
            save(rel, obj)
            print(f"   week {wk}{'' if scoreboard_final(obj) else ' (in progress)'}")


def main():
    with open(CFG, encoding="utf-8") as f:
        cfg = json.load(f)
    first = min(int(k) for k in cfg["teamIds"])
    y = Yahoo()
    name = cfg.get("leagueName", "The Frank Cup")
    mine = [lg for lg in my_leagues(y) if lg["name"] == name]
    if not mine:
        die(f"No league named '{name}' on this Yahoo account.")
    cur = max(mine, key=lambda lg: lg["season"])
    print(f"current season {cur['season']}, week {cur['current']}")

    # walk back through previous seasons; pull any we don't have yet
    lg = cur
    chain = [cur]
    while lg["renew"] and lg["season"] > first:
        g, lid = lg["renew"].split("_", 1)
        prev_key = f"{g}.l.{lid}"
        meta = load(f"metadata_{prev_key}.json")
        if meta is None:
            meta = y.get(f"league/{prev_key}/metadata")
            if meta is None: break
            save(f"metadata_{prev_key}.json", meta)
        lg = league_meta(meta["fantasy_content"]["league"][0])
        chain.append(lg)
    for lg in reversed(chain):
        s = str(lg["season"])
        if lg is cur:
            pull_season(y, lg, full=not os.path.isdir(os.path.join(RAW, s)))
        elif not os.path.exists(os.path.join(RAW, s, "standings.json")):
            pull_season(y, lg, full=True)
    sys.path.insert(0, HERE)
    # player-level detail for the news desk; never allowed to break the refresh
    try:
        import players
        players.pull_recent(y, cur["season"], RAW)
    except Exception as e:  # noqa: BLE001
        print("player pull skipped:", repr(e))
    print(f"{y.calls} Yahoo requests")

    import build
    D = build.build(RAW, cfg)
    build.write_js(D, os.path.join(ROOT, "data.js"))
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("data.js rebuilt:", ", ".join(D["seasons"]))


if __name__ == "__main__":
    main()
