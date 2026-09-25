"""
One-off research pull: Yahoo's player rankings with stats, saved raw.

For each time window (season, last month, last week) and each side (hitters,
pitchers), walks Yahoo's player list in rank order inside the league (so it
uses the league's categories), 25 at a time, and saves every response as-is.
Also pulls the top of the same lists outside the league (Yahoo's default
categories) to test whether the rank depends on league settings.

Output: research_out/<window>_<side>_<start>.json (+ game-level files).
Run by .github/workflows/research.yml. Nothing is committed.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update  # noqa: E402  (Yahoo client + league lookup)

OUT = os.path.join(os.path.dirname(HERE), "research_out")
WINDOWS = [("season", "season"), ("lastmonth", "lastmonth"), ("lastweek", "lastweek")]
DEPTH = {"B": 500, "P": 350}
PAGE = 25


def save(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


def count_players(obj, where):
    try:
        pl = obj["fantasy_content"][where][1]["players"]
        return int(pl.get("count", 0)) if isinstance(pl, dict) else 0
    except (KeyError, IndexError, TypeError):
        return 0


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg = json.load(open(update.CFG, encoding="utf-8"))
    y = update.Yahoo()
    mine = [lg for lg in update.my_leagues(y) if lg["name"] == cfg.get("leagueName", "The Frank Cup")]
    cur = max(mine, key=lambda lg: lg["season"])
    lk = cur["key"]
    game = lk.split(".l.")[0]
    print("league", lk, "game", game)
    save("league_settings.json", y.get(f"league/{lk}/settings"))

    for win, stype in WINDOWS:
        for side, depth in DEPTH.items():
            got = 0
            for start in range(0, depth, PAGE):
                path = (f"league/{lk}/players;position={side};sort=AR;sort_type={stype};"
                        f"start={start};count={PAGE}/stats;type={stype}")
                obj = y.get(path)
                n = count_players(obj, "league") if obj else 0
                if obj: save(f"{win}_{side}_{start:03d}.json", obj)
                got += n
                if n < PAGE: break
            print(f"league {win} {side}: {got} players")
        # Yahoo's own default-category ranking, for comparison
        for side in ("B", "P"):
            got = 0
            for start in range(0, 200, PAGE):
                path = (f"game/{game}/players;position={side};sort=AR;sort_type={stype};"
                        f"start={start};count={PAGE}/stats;type={stype}")
                obj = y.get(path)
                n = count_players(obj, "game") if obj else 0
                if obj: save(f"game_{win}_{side}_{start:03d}.json", obj)
                got += n
                if n < PAGE: break
            print(f"game {win} {side}: {got} players")

    # preseason rank order too (OR), season stats, for the draft-value angle
    for side in ("B", "P"):
        for start in range(0, 300, PAGE):
            obj = y.get(f"league/{lk}/players;position={side};sort=OR;start={start};count={PAGE}")
            if obj: save(f"preseason_{side}_{start:03d}.json", obj)
    print(f"done, {y.calls} Yahoo requests, {len(os.listdir(OUT))} files")


if __name__ == "__main__":
    main()
