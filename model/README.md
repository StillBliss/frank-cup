# Personal player model (not the site)

Benny's win-value model for The Frank Family Classic. Data comes from the `research` branch
(run the "Research pull (manual)" workflow), read from `/home/claude/research/research_out`.

- `talent.py`: 2027 talent (MLB 2026/25/24 weighted 5/4/3 + translated minors, regressed, aged) and durability (IL history, long-term surgeries).
- `ctx27.py` / `sim2.py`: how 2027 rules (12 teams, 3 SP / 2 RP / 3 P / 3 BN) change a typical team's week.
- `value27.py`: win value vs every real 2014-2026 team-week, rescaled to 2027, recent seasons weighted more.
- `export27.py` + `page.html`: builds the Win Value Board page.
- `model.py`, `weeks.py`: shared scoring and league-week loading. `hindsight.py`: hindsight draft. `champ*.py`: matchup sims.
