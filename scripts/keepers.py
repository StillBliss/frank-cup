"""
Build keepers.js for the site's Keeper Helper.

    python scripts/keepers.py <ranks.json> [season]

Rosters come from the last day of the season's player file, draft costs from
Yahoo's draft results, and 2026 keepers from league_config.json.

"Worth" is the draft round a player would likely go in a 12-team draft. Until real
ADP exists it comes from Benny's private Win Value board (ranks.json, never
committed): only the rounded round lands in keepers.js, never the values or the
board itself. When ADP arrives, pass a ranks file built from ADP instead
({"source": "adp", "players": [{"n", "role", "r"}]}) and the page says so.
"""
import json, math, os, re, sys, unicodedata
import build_core as bc
import build

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEAMS_NEXT = 12
ROUNDS_NEXT = 22

RULES = [
    "You can keep <b>up to 4 players</b>: 1 hitter, 1 pitcher, 1 more of either, and 1 player nobody drafted.",
    "A kept player <b>costs the round he was drafted in</b>. You give up that round's pick.",
    "Every year you keep him again, he <b>costs one round earlier</b>.",
    "Anyone drafted <b>after round 10 costs a 10th</b>.",
    "<b>1st-round picks can't be kept</b>. Once a player's cost would hit round 1, he can't be kept anymore.",
    "A player <b>nobody drafted costs a 5th</b>. If you keep him again, he moves into one of your drafted spots and costs a round earlier each year.",
    "Traded or dropped players <b>keep their original draft cost</b>, no matter who has them now.",
    "If two of your keepers cost the same round, or you traded that pick away, <b>that keeper costs one round earlier</b>.",
    "You can keep a player <b>3 years in a row at most</b>. Everyone's count starts fresh with 2027.",
    "Starting with the 2027 season, a player must be on your roster <b>from the trade deadline to the end of the season</b> to be kept.",
    "Players kept in 2026 after round 10 get <b>one more keep at their normal cost</b> (a round-21 keeper costs a 20th), and that counts as year 1.",
    "<b>New teams:</b> after everyone locks in keepers, the 2 new teams take turns claiming from every player who could have been kept but wasn't, at that player's cost. A coin flip decides who claims first. They fill the same 4 spots as everyone else.",
]


def fold(s):
    s = re.sub(r"\s*\((batter|pitcher)\)", "", s or "", flags=re.I)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def side_of(name, pos):
    if re.search(r"\(pitcher\)", name or "", re.I): return "P"
    if re.search(r"\(batter\)", name or "", re.I): return "H"
    return "P" if (pos or "").replace("SP", "P").replace("RP", "P").split(",")[0] == "P" else "H"


def cost_of(name, side, mgr, draft, kept):
    """(how, cost, ok) for one rostered player"""
    f = fold(name)
    if f in kept and kept[f][0] == mgr:
        r = kept[f][1]; return f"kept this season in round {r}", r - 1, r - 1 >= 2
    dr = draft.get((f, side))
    if dr:
        r, by = dr; return f"drafted in round {r}" + (f" by {by}" if by and by != mgr else ""), min(r, 10), r >= 2
    return "undrafted pickup", 5, True


def cost_tables(season, cfg, S):
    draft = {}
    for d in bc.draft(season):
        draft[(fold(d["player"]), side_of(d["player"], d["pos"]))] = (int(d["round"]), S.mgr.get(d["team"]))
    kept = {fold(n): (m, r) for n, (m, r) in ((cfg.get("keepers") or {}).get(str(season)) or {}).items()}
    return draft, kept


def main():
    ranks_path = sys.argv[1]
    season = int(sys.argv[2]) if len(sys.argv) > 2 else None
    cfg = json.load(open(os.path.join(ROOT, "league_config.json"), encoding="utf-8"))
    bc.RAW = os.path.join(ROOT, "raw")
    season = season or max(bc.seasons_available())
    S = build.Season(season, cfg)
    R = json.load(open(ranks_path, encoding="utf-8"))
    source = R.get("source", "winvalue")
    rank = {}
    for p in R["players"]:
        side = "P" if p.get("role") in ("SP", "RP", "P") else "H"
        k = (fold(p["n"]), side)
        if k not in rank or p["r"] < rank[k]: rank[k] = p["r"]

    # draft costs, any team (a traded or dropped player keeps his draft round)
    draft = {}
    for d in bc.draft(season):
        side = side_of(d["player"], d["pos"])
        draft[(fold(d["player"]), side)] = (int(d["round"]), S.mgr.get(d["team"]))
    kept = {fold(n): (m, r) for n, (m, r) in ((cfg.get("keepers") or {}).get(str(season)) or {}).items()}

    # final rosters
    pf = json.load(open(os.path.join(bc.RAW, str(season), "players", f"week_{max(int(f[5:7]) for f in os.listdir(os.path.join(bc.RAW, str(season), 'players')) if f.startswith('week_')):02d}.json"), encoding="utf-8"))
    last = sorted(pf["days"])[-1]
    teams = {}
    for tk, tr in pf["days"][last].items():
        m = S.mgr.get(tk)
        if not m: continue
        out = []
        for pl in tr.get("players", []):
            name = pl.get("n") or ""
            side = "P" if pl.get("pt") == "P" else "H"
            nm = re.sub(r"\s*\((Batter|Pitcher)\)", "", name)
            st = (pl.get("st") or "").upper()
            p = {"n": name if "Ohtani" in name else nm, "side": side, "pos": pl.get("pos") or "", "tm": pl.get("tm") or "",
                 "il": st.startswith(("IL", "NA")) or pl.get("sel") in ("IL", "IL+", "NA")}
            f = fold(name)
            dr = draft.get((f, side))
            if f in kept and kept[f][0] == m:
                r = kept[f][1]
                p.update(how=f"Kept in {season} (round {r})", slot="drafted", cost=r - 1)
                if r > 10 and season == 2026: p["note"] = "Grandfathered: one more keep at his normal cost, then the round-10 rule applies"
            elif dr:
                r, by = dr
                p.update(how=f"Drafted round {r}" + (f" by {by}" if by and by != m else ""), slot="drafted", cost=min(r, 10))
                if r > 10: p["note"] = "After round 10, so he costs a 10th"
            else:
                p.update(how="Undrafted pickup", slot="undrafted", cost=5)
            p["ok"] = p["cost"] >= 2
            if not p["ok"]:
                p["why"] = "1st-round picks can't be kept" if p["how"].startswith("Drafted round 1") else "His cost would reach round 1"
                p["cost"] = max(p["cost"], 1)
            rk = rank.get((f, side))
            worth = math.ceil(rk / TEAMS_NEXT) if rk else None
            if worth and worth > ROUNDS_NEXT: worth = None
            p["worth"] = worth
            p["save"] = (p["cost"] - worth) if (worth and p["ok"]) else None
            out.append(p)
        teams[m] = out

    # suggestions: best undrafted, then best hitter, best pitcher, best of the rest; must save a round
    for m, ps in teams.items():
        good = sorted([p for p in ps if p["ok"] and p["save"] and p["save"] >= 1], key=lambda p: (-p["save"], p["worth"]))
        used = set()
        def take(pred, slot):
            for p in good:
                if p["n"] in used or not pred(p): continue
                p["sug"] = slot; used.add(p["n"]); return
        take(lambda p: p["slot"] == "undrafted", "Undrafted")
        take(lambda p: p["slot"] == "drafted" and p["side"] == "H", "Hitter")
        take(lambda p: p["slot"] == "drafted" and p["side"] == "P", "Pitcher")
        take(lambda p: p["slot"] == "drafted", "Wildcard")
        for p in ps: p.setdefault("sug", None)

    basis = ("real 2027 average draft position" if source == "adp" else
             "our own 2027 draft board (how much a player helps win matchups in this league, times how much "
             "he's expected to play), converted to a draft round; it switches to real 2027 average draft "
             "position once that's out" if source == "winvalue27" else
             "our own player values (per-game win value in this league, with 2025's second half blended in), "
             "converted to a draft round; it switches to real 2027 average draft position once that's out")
    K = {"season": season + 1, "asof": last, "managers": [m for m in cfg["managers"] if m in teams],
         "expansion": cfg.get("expansion2027") or [], "teams": teams, "rules": RULES, "source": source,
         "foot": f"Rosters as of {last}. \"Worth\" is the round a player would likely go in a 12-team {season + 1} draft, "
                 f"based on {basis}. Suggestions only count players who save you at least one round."}
    with open(os.path.join(ROOT, "keepers.js"), "w", encoding="utf-8") as f:
        f.write("window.KEEPERS = " + json.dumps(K, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("wrote keepers.js:", {m: sum(1 for p in ps if p["sug"]) for m, ps in teams.items()})


if __name__ == "__main__":
    main()
