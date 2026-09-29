"""
One-time, read-only check: which past MLB leagues can this Yahoo account see?
Writes raw/history_probe.json. Changes nothing else.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import Yahoo, league_meta, my_leagues, save

y = Yahoo()
out = {"leagues": [], "chain": [], "games": {}, "errors": []}

# every MLB league this account has ever been in
for lg in my_leagues(y):
    out["leagues"].append(lg)

# MLB game keys by season, for reference
d = y.get("games;game_codes=mlb;seasons=" + ",".join(str(s) for s in range(2011, 2027)))
try:
    g = d["fantasy_content"]["games"]
    for k in [k for k in g if k.isdigit()]:
        gi = g[k]["game"][0] if isinstance(g[k]["game"], list) else g[k]["game"]
        out["games"][gi["season"]] = gi["game_key"]
except Exception as e:
    out["errors"].append(f"games: {e}")

# walk back from the oldest Frank league we can see, following 'renew'
frank = [l for l in out["leagues"] if "frank" in (l["name"] or "").lower()]
if frank:
    lg = min(frank, key=lambda l: l["season"])
    seen = set()
    while lg and lg["renew"] and lg["renew"] not in seen:
        seen.add(lg["renew"])
        gk, lid = lg["renew"].split("_", 1)
        key = f"{gk}.l.{lid}"
        m = y.get(f"league/{key}/metadata")
        if not m:
            out["chain"].append({"key": key, "readable": False})
            break
        lg = league_meta(m["fantasy_content"]["league"][0])
        lg["readable"] = True
        out["chain"].append(lg)

# try a known old league directly, then follow its links both ways
start = os.environ.get("PROBE_KEY", "346.l.170599")
out["direct"] = []
def meta(key):
    m = y.get(f"league/{key}/metadata")
    if not m:
        return None
    b = m["fantasy_content"]["league"][0]
    lg = league_meta(b); lg["renewed"] = (b.get("renewed") or "").strip()
    lg["num_teams"] = b.get("num_teams"); lg["url"] = b.get("url")
    return lg
first = meta(start)
out["direct"].append(first or {"key": start, "readable": False})
for field in ("renew", "renewed"):
    lg, seen = first, set()
    while lg and lg.get(field) and lg[field] not in seen and len(seen) < 20:
        seen.add(lg[field])
        gk, lid = lg[field].split("_", 1)
        key = f"{gk}.l.{lid}"
        lg = meta(key)
        out["direct"].append(lg or {"key": key, "readable": False})
out["calls"] = y.calls
save("history_probe.json", out)
print(json.dumps(out, indent=1)[:3000])
