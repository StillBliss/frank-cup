"""
Research pull for the personal 2027 player model (not the site). Everything
from the free MLB Stats API plus MLB Pipeline's public Top 100 page:

  seasons/<year>_<group>.json   MLB season stats 2022-2026 (multi-year talent)
  people.json                   birth date, MLB debut, bats/throws, draft info
  il/<year>.json                injured-list moves 2022-2026 (durability)
  milb/<year>_<level>_<group>.json  AAA / AA / High-A stats 2025-2026 (rookies)
  draft/<year>.json             MLB draft picks 2019-2025 (pedigree)
  pipeline_top100.html          MLB Pipeline Top 100 page, saved raw (pedigree)

Run by .github/workflows/research.yml. Output goes to the research branch.
"""
import datetime as dt
import json, os, time, urllib.request, urllib.error
from urllib.parse import urlencode

API = "https://statsapi.mlb.com/api/v1"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research_out", "history")
UA = {"User-Agent": "frank-cup-research"}
YEARS = range(2022, 2027)
MILB = {"AAA": 11, "AA": 12, "A+": 13}


def get(path, params=None, tries=3, raw=False, url=None):
    url = url or f"{API}/{path}" + (f"?{urlencode(params)}" if params else "")
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read().decode("utf-8", "replace")
                return body if raw else json.loads(body)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print("   retry", attempt + 1, url[:90], e)
            time.sleep(5 * (attempt + 1))
    return None


def save(rel, obj, raw=False):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        if raw: f.write(obj)
        else: json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


def splits(d):
    return d["stats"][0]["splits"] if d and d.get("stats") else []


def main():
    os.makedirs(OUT, exist_ok=True)
    ids = set()

    # 1) MLB seasons, full regular season each year
    for y in YEARS:
        for g in ("hitting", "pitching"):
            d = get("stats", dict(stats="season", season=y, group=g, sportId=1, gameType="R", playerPool="ALL", limit=5000))
            s = splits(d); print(f"mlb {y} {g}: {len(s)}")
            if d: save(f"seasons/{y}_{g}.json", d)
            ids.update(x["player"]["id"] for x in s)

    # 2) minor leagues, recent two seasons (rookie baselines)
    for y in (2025, 2026):
        for lvl, sid in MILB.items():
            for g in ("hitting", "pitching"):
                d = get("stats", dict(stats="season", season=y, group=g, sportId=sid, gameType="R", playerPool="ALL", limit=8000))
                s = splits(d); print(f"milb {y} {lvl} {g}: {len(s)}")
                if d: save(f"milb/{y}_{lvl}_{g}.json", d)
                ids.update(x["player"]["id"] for x in s if (x["stat"].get("plateAppearances", 0) >= 100 or x["stat"].get("battersFaced", 0) >= 100))

    # 3) MLB drafts
    for y in range(2019, 2026):
        d = get(f"draft/{y}")
        n = sum(len(r.get("picks", [])) for r in (d or {}).get("drafts", {}).get("rounds", []))
        print(f"draft {y}: {n} picks")
        if d: save(f"draft/{y}.json", d)

    # 4) injured-list moves, month by month
    for y in YEARS:
        keep = []
        for m in range(2, 12):
            a = dt.date(y, m, 1); b = (dt.date(y, m + 1, 1) if m < 12 else dt.date(y + 1, 1, 1)) - dt.timedelta(days=1)
            d = get("transactions", dict(startDate=str(a), endDate=str(b), sportId=1))
            for t in (d or {}).get("transactions", []):
                desc = (t.get("description") or "").lower()
                if "injured list" in desc and t.get("person"):
                    keep.append({"id": t["person"]["id"], "name": t["person"].get("fullName"), "date": t.get("date"),
                                 "code": t.get("typeCode"), "desc": t.get("description")})
        print(f"il {y}: {len(keep)} moves")
        save(f"il/{y}.json", keep)

    # 5) biographical details for everyone seen above
    people = {}
    idl = sorted(ids)
    for i in range(0, len(idl), 100):
        d = get("people", dict(personIds=",".join(map(str, idl[i:i + 100])), hydrate="draft"))
        for p in (d or {}).get("people", []):
            dr = (p.get("drafts") or [{}])[-1] if p.get("drafts") else {}
            people[p["id"]] = {"name": p.get("fullName"), "birth": p.get("birthDate"), "debut": p.get("mlbDebutDate"),
                               "pos": (p.get("primaryPosition") or {}).get("abbreviation"),
                               "bats": (p.get("batSide") or {}).get("code"), "throws": (p.get("pitchHand") or {}).get("code"),
                               "draft_year": dr.get("year"), "draft_round": dr.get("pickRound"), "draft_pick": dr.get("pickNumber")}
    print(f"people: {len(people)}")
    save("people.json", people)

    # 6) MLB Pipeline Top 100 (public page; parsed later, so keep it raw)
    html = get(None, raw=True, url="https://www.mlb.com/prospects/top100/")
    print("pipeline page:", len(html) if html else "failed")
    if html: save("pipeline_top100.html", html, raw=True)
    save("meta.json", {"pulled": str(dt.date.today()), "years": list(YEARS), "people": len(people)})


if __name__ == "__main__":
    main()
