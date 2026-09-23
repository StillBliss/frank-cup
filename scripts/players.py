"""
The Frank Cup - player-level pulls for the news desk.

Yahoo: every team's roster for every day of a finished week, with that day's
stats, so the writers know who was started, who sat on the bench, who was on
the IL, and exactly what each player did.

MLB: the league-wide transaction wire for the same dates (injured list moves,
call-ups, trades), from MLB's free public stats API. No key needed.

Both are stored compactly under raw/<season>/players and raw/<season>/mlb.
A week is only pulled once it is final, and never re-pulled after that.
"""
import datetime as dt
import json, os, time, urllib.request, urllib.error

MLB_API = "https://statsapi.mlb.com/api/v1"


def _flat(block):
    out = {}
    if isinstance(block, list):
        for p in block:
            if isinstance(p, dict):
                out.update(p)
            elif isinstance(p, list):
                out.update(_flat(p))
    elif isinstance(block, dict):
        out.update(block)
    return out


def parse_roster(obj):
    """One team-day response -> {"adds": n, "players": [...]}. Defensive: Yahoo
    nests these as lists of one-key dicts, and some parts can be missing."""
    try:
        team = obj["fantasy_content"]["team"]
    except (KeyError, TypeError):
        return None
    meta = _flat(team[0])
    adds = None
    ra = meta.get("roster_adds")
    if isinstance(ra, dict):
        try: adds = int(ra.get("value"))
        except (TypeError, ValueError): adds = None
    roster = team[1].get("roster", {}) if len(team) > 1 and isinstance(team[1], dict) else {}
    plist = (roster.get("0") or {}).get("players") or {}
    out = []
    for k in plist:
        if not str(k).isdigit():
            continue
        parts = plist[k].get("player") or []
        if not parts:
            continue
        info = _flat(parts[0])
        rec = {"k": info.get("player_key"),
               "n": (info.get("name") or {}).get("full"),
               "tm": info.get("editorial_team_abbr"),
               "pt": info.get("position_type"),
               "pos": info.get("display_position")}
        if info.get("status"):
            rec["st"] = info["status"]
        if info.get("injury_note"):
            rec["inj"] = info["injury_note"]
        for part in parts[1:]:
            if not isinstance(part, dict):
                continue
            if "selected_position" in part:
                rec["sel"] = _flat(part["selected_position"]).get("position")
            if "player_stats" in part:
                stats = {}
                for s in (part["player_stats"] or {}).get("stats", []):
                    s = s.get("stat", {})
                    v = s.get("value")
                    if v not in (None, "", "-"):
                        stats[str(s.get("stat_id"))] = v
                if stats:
                    rec["s"] = stats
        out.append(rec)
    return {"adds": adds, "players": out}


def _days(start, end):
    a = dt.date.fromisoformat(start); b = dt.date.fromisoformat(end)
    while a <= b:
        yield a.isoformat()
        a += dt.timedelta(days=1)


def yesterday_pt():
    try:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # noqa: BLE001
        today = (dt.datetime.utcnow() - dt.timedelta(hours=7)).date()
    return (today - dt.timedelta(days=1)).isoformat()


def pull_week(y, season, week, start, end, team_keys, raw, final=True):
    """Pull every team for every finished day of one week. A week still in
    progress is saved as partial and topped up on each run; once the week is
    final and every day is in, it is never pulled again."""
    rel = os.path.join(raw, str(season), "players", f"week_{week:02d}.json")
    have = {"days": {}}
    if os.path.exists(rel):
        have = json.load(open(rel, encoding="utf-8"))
        if not have.get("partial"):
            return False
    last = min(end, yesterday_pt())
    todo = [d for d in _days(start, last) if len(have["days"].get(d, {})) < len(team_keys)]
    if not todo and not (final and have.get("partial")):
        return False
    days = have["days"]
    fails, no_stats = 0, 0
    for d in todo:
        days.setdefault(d, {})
        for tk in team_keys:
            if tk in days[d]: continue
            obj = y.get(f"team/{tk}/roster;date={d}/players/stats;type=date;date={d}")
            if obj is None:
                # fall back to the roster alone, so lineup facts still work
                obj = y.get(f"team/{tk}/roster;date={d}")
                no_stats += 1
            r = parse_roster(obj) if obj is not None else None
            if r is None:
                fails += 1
                if fails >= 3 and not any(days.values()):
                    print(f"   players week {week}: Yahoo is refusing roster calls, skipping player pulls this run")
                    return None
                continue
            days[d][tk] = r
    complete = final and last == end and all(len(days.get(d, {})) >= len(team_keys) for d in _days(start, end))
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    with open(rel, "w", encoding="utf-8") as f:
        json.dump({"season": season, "week": week, "start": start, "end": end, "partial": not complete,
                   "days": days}, f, separators=(",", ":"), ensure_ascii=False)
    print(f"   players week {week}: {len(todo)} day(s) added{'' if complete else ' (week in progress)'}"
          f"{f', {no_stats} team-days without stats' if no_stats else ''}")
    return True


def mlb_get(path, tries=3):
    url = f"{MLB_API}/{path}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "frank-cup-news"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError):
            time.sleep(5 * (attempt + 1))
    return None


SKIP_TYPES = {"NUM"}  # jersey number changes


def pull_mlb_week(season, week, start, end, raw):
    rel = os.path.join(raw, str(season), "mlb", f"week_{week:02d}.json")
    if os.path.exists(rel):
        return False
    d = mlb_get(f"transactions?startDate={start}&endDate={end}&sportId=1")
    if d is None:
        print(f"   mlb week {week}: MLB API did not answer, will retry next run")
        return False
    out = []
    for t in d.get("transactions", []):
        if t.get("typeCode") in SKIP_TYPES or not t.get("person"):
            continue
        out.append({"date": t.get("date"), "type": t.get("typeDesc"),
                    "who": t["person"].get("fullName"), "desc": t.get("description")})
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    with open(rel, "w", encoding="utf-8") as f:
        json.dump({"season": season, "week": week, "tx": out}, f, separators=(",", ":"), ensure_ascii=False)
    print(f"   mlb week {week}: {len(out)} transactions")
    return True


def pull_recent(y, season, raw, weeks_back=6):
    """Pull player days and the MLB wire for the last few finished weeks that we
    don't have yet. The first run fills the window; later runs add one week."""
    sb_dir = os.path.join(raw, str(season), "scoreboard")
    teams = json.load(open(os.path.join(raw, str(season), "teams.json"), encoding="utf-8"))
    tl = teams["fantasy_content"]["league"][1]["teams"]
    team_keys = [_flat(tl[k]["team"][0])["team_key"] for k in tl if str(k).isdigit()]
    done, live = [], []
    for f in sorted(os.listdir(sb_dir)):
        obj = json.load(open(os.path.join(sb_dir, f), encoding="utf-8"))
        try:
            ms = obj["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
            first = ms["0"]["matchup"]
            st = [ms[k]["matchup"]["status"] for k in ms if str(k).isdigit()]
        except (KeyError, IndexError, TypeError):
            continue
        if st and all(s == "postevent" for s in st):
            done.append((int(first["week"]), first["week_start"], first["week_end"]))
        elif st and any(s == "midevent" for s in st):
            live.append((int(first["week"]), first["week_start"], first["week_end"]))
    done.sort()
    for wk, a, b in done[-weeks_back:]:
        if pull_week(y, season, wk, a, b, team_keys, raw) is None:
            return
        pull_mlb_week(season, wk, a, b, raw)
    # the week in progress, day by day, for the daily report
    for wk, a, b in live:
        if a <= yesterday_pt():
            if pull_week(y, season, wk, a, b, team_keys, raw, final=False) is None:
                return
    done += live
    # keep the repo lean: the news desk only ever looks a few weeks back
    keep = {f"week_{wk:02d}.json" for wk, _, _ in done[-(weeks_back + 2):]}
    pdir = os.path.join(raw, str(season), "players")
    for f in os.listdir(pdir) if os.path.isdir(pdir) else []:
        if f not in keep:
            os.remove(os.path.join(pdir, f))
