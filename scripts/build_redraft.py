"""
Build redraft.js: the 2011-2022 redraft era, kept apart from the keeper era.
Uses the same builder as data.js, fed from raw_redraft/ and the "redraft"
block of league_config.json. Never touches data.js.
"""
import copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build  # noqa: E402

DROP = ("payouts", "payoutRules", "awards", "relationships", "trades", "playersBySeason",
        "players", "moves", "weeklyDetail", "weeklyDetailNote", "oddsByWeek")


def main():
    with open(os.path.join(ROOT, "league_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    R = cfg["redraft"]
    rcfg = copy.deepcopy(cfg)
    rcfg.update({"managers": R["managers"], "colors": R["colors"], "teamIds": copy.deepcopy(R["teamIds"]),
                 "ownerChanges": {}, "awards": {}, "relationships": None})
    D = build.build(os.path.join(ROOT, "raw_redraft"), rcfg)
    for k in DROP:
        D.pop(k, None)
    D["era"] = "redraft"
    D["unknownOwners"] = R.get("unknownOwners", [])
    D["leagueNames"] = R.get("leagueNames", {})
    D["who"] = R.get("relationships", {})
    D["teamsBySeason"] = {s: len(v) for s, v in R["teamIds"].items()}
    # categories changed in 2014 (XBH and K/BB added); keep each season's own list
    D["catsBySeason"] = {}
    for s in D["seasons"]:
        S = build.Season(int(s), rcfg)
        D["catsBySeason"][s] = [c["abbr"] for c in S.cats]
    body = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(ROOT, "redraft.js"), "w", encoding="utf-8") as f:
        f.write("const REDRAFT_DATA = " + body + ";\n")
    print("wrote redraft.js:", ", ".join(D["seasons"]), f"({len(body)//1024} KB)")


if __name__ == "__main__":
    main()
