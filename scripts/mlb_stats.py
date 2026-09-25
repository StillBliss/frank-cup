"""
Research pull: MLB season stats (hitting + pitching) from the free MLB Stats API,
for the personal win-value ranking model. Saved raw, one file per window/group.

Windows:
  2026_season  2026 regular season to date (main number)
  last60       last 60 days (trend)
  2025_2h      2025 second half, after the All-Star break (fallback)
  2025_season  2025 full season (extra fallback)

Output: research_out/mlb/<window>_<group>.json plus teams.json.
Run by .github/workflows/research.yml after the Yahoo pull.
"""
import datetime as dt
import json, os, time, urllib.request, urllib.error
from urllib.parse import urlencode

API = "https://statsapi.mlb.com/api/v1"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research_out", "mlb")


def get(path, params, tries=3):
    url = f"{API}/{path}?{urlencode(params)}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "frank-cup-research"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print("   retry", attempt + 1, e)
            time.sleep(5 * (attempt + 1))
    return None


def save(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


def main():
    os.makedirs(OUT, exist_ok=True)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-7))).date()
    end = today - dt.timedelta(days=1)
    windows = {
        "2026_season": {"stats": "season", "season": 2026},
        "last60": {"stats": "byDateRange", "season": end.year,
                   "startDate": str(end - dt.timedelta(days=59)), "endDate": str(end)},
        "2025_2h": {"stats": "byDateRange", "season": 2025,
                    "startDate": "2025-07-18", "endDate": "2025-09-28"},
        "2025_season": {"stats": "season", "season": 2025},
    }
    teams = get("teams", {"sportId": 1, "season": 2026})
    if teams: save("teams.json", teams)
    meta = {"pulled": str(today), "windows": windows}
    for win, p in windows.items():
        for group in ("hitting", "pitching"):
            params = dict(p, group=group, sportId=1, gameType="R", playerPool="ALL", limit=5000)
            d = get("stats", params)
            n = len(d["stats"][0]["splits"]) if d and d.get("stats") else 0
            print(f"mlb {win} {group}: {n} rows")
            if d: save(f"{win}_{group}.json", d)
    save("meta.json", meta)


if __name__ == "__main__":
    main()
