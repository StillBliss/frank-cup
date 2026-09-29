"""
One-time pull of the redraft era (2011-2022) into raw_redraft/.
Does not touch raw/, data.js or the site.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update

update.RAW = os.path.join(update.ROOT, "raw_redraft")
KEYS = ["253.l.205007", "268.l.95322", "308.l.99199",                 # YANKEES'11
        "328.l.87406", "346.l.170599", "357.l.74165", "370.l.123413",  # Big Monies
        "378.l.102212", "388.l.93775", "398.l.75486", "404.l.110221", "412.l.59223"]

y = update.Yahoo()
update.die = lambda msg: print("   SKIPPED:", msg)
for key in KEYS:
    m = y.get(f"league/{key}/metadata")
    if not m:
        print("cannot read", key); continue
    b = m["fantasy_content"]["league"][0]
    lg = update.league_meta(b)
    s = str(lg["season"])
    if os.path.exists(os.path.join(update.RAW, s, "standings.json")):
        print(s, "already pulled"); continue
    update.save(f"metadata_{key}.json", m)
    update.pull_season(y, lg, full=True)
print("calls:", y.calls)
