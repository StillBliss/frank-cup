"""
The Frank Cup - outside news sources for the Gazette.

Every source is free and needs no key. Each one is optional: if a source is
down or changes shape, it is skipped and the rest still work.

  ESPN injuries       status, reason, expected return
  ESPN news           headlines with summaries
  MLB.com, CBS, Yahoo Sports news feeds (RSS)
  MLB probable pitchers for the next ten days (two-start pitchers)
  MLB standings       who is racing, clinched, or eliminated
  MLB transactions    yesterday's injured-list moves, call-ups, trades
  Yahoo free agents   best available hitters and pitchers by last week, with
                      ownership trend (needs the Yahoo client from update.py)

Saved as raw/<season>/news/<date>.json, one snapshot per run day.
"""
import datetime as dt
import html, json, os, re, time, urllib.request, urllib.error
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (frank-cup-gazette)"}
MLB = "https://statsapi.mlb.com/api/v1"
FEEDS = {
    "mlb.com": "https://www.mlb.com/feeds/news/rss.xml",
    "CBS Sports": "https://www.cbssports.com/rss/headlines/mlb/",
    "Yahoo Sports": "https://sports.yahoo.com/mlb/rss.xml",
}
ADS = re.compile(r"promo code|bonus bets|sportsbook|fanduel|draftkings|betmgm|caesars|bet365|fanatics sportsbook|"
                 r"odds,? picks|best bets|parlay|prediction(s)? for", re.I)


def get(url, as_json=True, tries=2):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
                return json.loads(raw) if as_json else raw
        except (urllib.error.URLError, TimeoutError, ValueError):
            time.sleep(4 * (attempt + 1))
    return None


def clean(s, n=400):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def today_pt():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # noqa: BLE001
        return (dt.datetime.utcnow() - dt.timedelta(hours=7)).date()


# ------------------------------------------------------------ ESPN
def espn_injuries():
    d = get("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries")
    if not d: return None
    out = []
    for team in d.get("injuries", []):
        tname = team.get("displayName") or ""
        for inj in team.get("injuries", []):
            ath = inj.get("athlete") or {}
            det = inj.get("details") or {}
            out.append({"who": ath.get("displayName") or ath.get("fullName"), "team": tname,
                        "status": inj.get("status") or (inj.get("type") or {}).get("description"),
                        "date": (inj.get("date") or "")[:10],
                        "what": det.get("type") or det.get("detail"),
                        "back": (det.get("returnDate") or "")[:10] or None,
                        "note": clean(inj.get("shortComment") or inj.get("longComment"), 300)})
    return [x for x in out if x["who"]]


def espn_news():
    d = get("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=60")
    if not d: return None
    out = []
    for a in d.get("articles", []):
        names = [c.get("description") for c in a.get("categories", []) if c.get("type") == "athlete" and c.get("description")]
        item = {"src": "ESPN", "title": clean(a.get("headline"), 200), "summary": clean(a.get("description")),
                "date": (a.get("published") or "")[:10], "players": names}
        if item["title"] and not ADS.search(item["title"] + " " + item["summary"]):
            out.append(item)
    return out


# ------------------------------------------------------------ RSS
def rss(src, url):
    raw = get(url, as_json=False)
    if not raw: return None
    try:
        root = ET.fromstring(raw.encode("utf-8"))
    except ET.ParseError:
        return None
    out = []
    for it in root.iter("item"):
        t = clean(it.findtext("title"), 200)
        s = clean(it.findtext("description"))
        pd = it.findtext("pubDate") or ""
        try:
            from email.utils import parsedate_to_datetime
            day = parsedate_to_datetime(pd).date().isoformat()
        except (TypeError, ValueError):
            day = ""
        if t and not ADS.search(t + " " + s):
            out.append({"src": src, "title": t, "summary": s, "date": day})
    return out


# ------------------------------------------------------------ MLB
def probables(start, days=10):
    end = start + dt.timedelta(days=days)
    d = get(f"{MLB}/schedule?sportId=1&startDate={start}&endDate={end}&hydrate=probablePitcher")
    if not d: return None
    out = []
    for day in d.get("dates", []):
        for g in day.get("games", []):
            t = g.get("teams", {})
            for side, other in (("away", "home"), ("home", "away")):
                pp = (t.get(side) or {}).get("probablePitcher") or {}
                if pp.get("fullName"):
                    out.append({"date": day.get("date"), "who": pp["fullName"],
                                "team": ((t.get(side) or {}).get("team") or {}).get("name"),
                                "vs": ((t.get(other) or {}).get("team") or {}).get("name"),
                                "home": side == "home"})
    return out


def standings(season):
    d = get(f"{MLB}/standings?leagueId=103,104&season={season}&standingsTypes=regularSeason&hydrate=team")
    if not d: return None
    out = []
    for rec in d.get("records", []):
        for t in rec.get("teamRecords", []):
            out.append({"team": (t.get("team") or {}).get("name"), "w": t.get("wins"), "l": t.get("losses"),
                        "div_rank": t.get("divisionRank"), "gb": t.get("gamesBack"),
                        "wc_gb": t.get("wildCardGamesBack"), "clinch": t.get("clinchIndicator"),
                        "elim": t.get("eliminationNumber"), "streak": (t.get("streak") or {}).get("streakCode")})
    return out


def mlb_transactions(day):
    d = get(f"{MLB}/transactions?startDate={day}&endDate={day}&sportId=1")
    if not d: return None
    return [{"date": t.get("date"), "type": t.get("typeDesc"), "who": (t.get("person") or {}).get("fullName"),
             "desc": t.get("description")} for t in d.get("transactions", [])
            if t.get("typeCode") != "NUM" and t.get("person")]


# ------------------------------------------------------------ Yahoo free agents
def _flat(block):
    out = {}
    if isinstance(block, list):
        for p in block:
            if isinstance(p, dict): out.update(p)
            elif isinstance(p, list): out.update(_flat(p))
    elif isinstance(block, dict):
        out.update(block)
    return out


def _players(obj):
    try:
        pl = obj["fantasy_content"]["league"][1]["players"]
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for k in pl:
        if not str(k).isdigit(): continue
        parts = pl[k].get("player") or []
        if not parts: continue
        info = _flat(parts[0])
        rec = {"k": info.get("player_key"), "n": (info.get("name") or {}).get("full"),
               "tm": info.get("editorial_team_abbr"), "pos": info.get("display_position"),
               "st": info.get("status")}
        for part in parts[1:]:
            if not isinstance(part, dict): continue
            if "player_stats" in part:
                rec["s"] = {str(s["stat"]["stat_id"]): s["stat"]["value"]
                            for s in (part["player_stats"] or {}).get("stats", []) if s.get("stat")}
            if "percent_owned" in part:
                po = _flat(part["percent_owned"])
                rec["own"] = po.get("value"); rec["delta"] = po.get("delta")
        out.append(rec)
    return out


def free_agents(y, league_key):
    out = {}
    for pos in ("B", "P"):
        base = f"league/{league_key}/players;status=A;position={pos};sort=AR;sort_type=lastweek;count=15"
        stats = y.get(base + "/stats;type=lastweek")
        own = y.get(base + "/percent_owned")
        rows = _players(stats) if stats else []
        by = {r["k"]: r for r in (_players(own) if own else [])}
        for r in rows:
            if r["k"] in by:
                r["own"] = by[r["k"]].get("own"); r["delta"] = by[r["k"]].get("delta")
        out[pos] = rows
    return out if (out.get("B") or out.get("P")) else None


# ------------------------------------------------------------ all together
def pull_all(season, raw, y=None, league_key=None):
    day = today_pt()
    rel = os.path.join(raw, str(season), "news", f"{day.isoformat()}.json")
    snap = {"date": day.isoformat(), "season": season}
    jobs = [("espn_injuries", espn_injuries), ("espn_news", espn_news),
            ("probables", lambda: probables(day)), ("standings", lambda: standings(season)),
            ("mlb_tx", lambda: mlb_transactions((day - dt.timedelta(days=1)).isoformat()))]
    for name, url in FEEDS.items():
        jobs.append((f"rss:{name}", (lambda n=name, u=url: rss(n, u))))
    for key, fn in jobs:
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001
            v = None; print(f"   source {key}: error {e!r}")
        print(f"   source {key}: {'skipped' if v is None else len(v)}")
        if v is not None: snap[key] = v
    if y is not None and league_key:
        try:
            fa = free_agents(y, league_key)
            print(f"   source yahoo free agents: {'skipped' if fa is None else sum(len(v) for v in fa.values())}")
            if fa: snap["free_agents"] = fa
        except Exception as e:  # noqa: BLE001
            print("   source yahoo free agents: error", repr(e))
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    with open(rel, "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"), ensure_ascii=False)
    # keep three weeks of snapshots
    ndir = os.path.dirname(rel)
    for f in sorted(os.listdir(ndir))[:-21]:
        os.remove(os.path.join(ndir, f))
    return snap


def load_recent(season, raw, upto=None, days=3):
    """Merge the last few daily snapshots (newest wins) for the notebook."""
    ndir = os.path.join(raw, str(season), "news")
    if not os.path.isdir(ndir): return {}
    files = sorted(f for f in os.listdir(ndir) if f.endswith(".json") and (upto is None or f[:10] <= upto))
    merged = {"feeds": []}
    seen = set()
    for f in files[-days:]:
        d = json.load(open(os.path.join(ndir, f), encoding="utf-8"))
        for k, v in d.items():
            if k.startswith("rss:") or k == "espn_news":
                for it in v:
                    key = it["title"].lower()
                    if key not in seen:
                        seen.add(key); merged["feeds"].append(it)
            elif k in ("mlb_tx",):
                merged.setdefault("mlb_tx", []).extend(v)
            else:
                merged[k] = v   # newest snapshot wins
    return merged
