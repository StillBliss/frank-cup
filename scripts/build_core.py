import json, os, glob
RAW = None

def L(path):
    with open(os.path.join(RAW, path), encoding="utf-8") as f:
        return json.load(f)

def flat(block):
    out = {}
    for p in block:
        if isinstance(p, dict):
            out.update(p)
    return out

def seasons_available():
    return sorted(int(os.path.basename(p)) for p in glob.glob(os.path.join(RAW, "[0-9][0-9][0-9][0-9]")))

def settings(season):
    st = L(f"{season}/settings.json")["fantasy_content"]["league"]
    meta, s = st[0], st[1]["settings"][0]
    cats = []
    for c in s["stat_categories"]["stats"]:
        c = c["stat"]
        cats.append({"id": str(c["stat_id"]), "abbr": c["display_name"],
                     "display_only": c.get("is_only_display_stat") == "1",
                     "sort_order": c.get("sort_order"), "group": c.get("group")})
    return meta, s, cats

def teams(season):
    t = L(f"{season}/teams.json")["fantasy_content"]["league"][1]["teams"]
    out = {}
    for k in t:
        if not k.isdigit(): continue
        info = flat(t[k]["team"][0])
        out[info["team_key"]] = info
    return out

def matchups(season):
    """All matchups across scoreboard files, parsed."""
    res = []
    for f in sorted(glob.glob(os.path.join(RAW, str(season), "scoreboard", "week_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        try:
            ms = d["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
        except (KeyError, IndexError, TypeError):
            continue
        for k in ms:
            if not k.isdigit(): continue
            m = ms[k]["matchup"]
            tl = []
            tt = m["0"]["teams"]
            for j in tt:
                if not j.isdigit(): continue
                tm = tt[j]["team"]
                info = flat(tm[0])
                stats = {str(x["stat"]["stat_id"]): x["stat"]["value"] for x in tm[1]["team_stats"]["stats"]}
                pts = tm[1].get("team_points", {}).get("total")
                tl.append({"key": info["team_key"], "name": info["name"], "stats": stats, "points": pts})
            sw = {}
            for x in m.get("stat_winners", []):
                x = x["stat_winner"]
                sw[str(x["stat_id"])] = "tie" if x.get("is_tied") else x.get("winner_team_key")
            res.append({"week": int(m["week"]), "status": m.get("status"),
                        "playoffs": m.get("is_playoffs") == "1",
                        "consolation": m.get("is_consolation") == "1",
                        "is_tied": bool(int(m.get("is_tied") or 0)),
                        "winner": m.get("winner_team_key"),
                        "teams": tl, "stat_winners": sw})
    return res

def transactions(season):
    d = L(f"{season}/transactions.json")["fantasy_content"]["league"][1]["transactions"]
    out = []
    for k in d:
        if not k.isdigit(): continue
        tx = d[k]["transaction"]
        head = tx[0]
        players = []
        pl = tx[1].get("players", {}) if len(tx) > 1 and isinstance(tx[1], dict) else {}
        for j in pl:
            if not j.isdigit(): continue
            p = pl[j]["player"]
            info = flat(p[0])
            td = p[1]["transaction_data"]
            if isinstance(td, list): td = td[0]
            players.append({"name": info["name"]["full"], "pos": info.get("display_position"),
                            "key": info.get("player_key"), **{k2: td.get(k2) for k2 in
                            ("type", "source_type", "source_team_key", "destination_type", "destination_team_key")}})
        out.append({"id": int(head.get("transaction_id") or 0), "type": head["type"], "status": head.get("status"),
                    "ts": int(head["timestamp"]), "trader": head.get("trader_team_key"),
                    "tradee": head.get("tradee_team_key"), "players": players})
    return out

def draft(season):
    d = L(f"{season}/draft_results.json")["fantasy_content"]["league"][1]["draft_results"]
    out = []
    for k in d:
        if not k.isdigit(): continue
        r = d[k]["draft_result"]
        name = pos = None
        try:
            info = flat(r["0"]["players"]["0"]["player"][0])
            name = info["name"]["full"]; pos = info.get("display_position")
        except (KeyError, TypeError):
            pass
        out.append({"pick": int(r["pick"]), "round": int(r["round"]), "team": r.get("team_key"),
                    "player": name, "pos": pos})
    return out
