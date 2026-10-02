# The FFC Grade, in plain English

**100 = the average starter. 80 = a free agent. Every 20 points = one more average starter of value.**

1. **What he produces.** Each player gets a per-game line in our categories: his last three MLB seasons weighted 5/4/3, plus minor league stats translated to MLB level, pulled toward the MLB average (more for small samples), then aged to next season (young players improve, older ones decline, speed fades fastest, pitchers fade faster past 33). Wins, saves and holds scale with his team's record; runs and RBI with his team's offense. Top-100 prospects and recent 1st-round picks get a small bump.
2. **Put him on an average team.** Scale that to a normal week (6 games, 1.25 starts, or 2.5 relief outings) and swap him onto our league's average team in place of a waiver-level hitter, starter or reliever (one hitting baseline for all hitters).
3. **Replay real weeks.** That team plays every real 7-day week our league has had since 2014 (same 22 categories), rescaled to next season's rules and weighted toward recent seasons. Count how often it wins each category and the matchup.
4. **Value = added wins.** His value is the points of matchup win % he adds over that waiver player. Scarce categories in our league (holds, steals, triples) are worth more because one more flips more weeks.
5. **Grade.** Average starter = 100, waiver player = 80, linear from there.

**Draft grade** = per-game value x Healthy % x MLB role, re-graded.
- Healthy %: start from what a typical established player misses the next year (hitters 17%, starters 24%, relievers 20%). Blend in his own injured-list days since 2022 (recent years most, capped by games actually played); this counts a lot for hitters and only a little for pitchers, because that is what the data supports. Then cut it if he finished last season on the injured list: hitter out under 75 days keeps 90%, hitter out longer keeps 60%; pitcher on the 15-day list out 30+ days keeps 63%; pitcher on the 60-day list keeps 50%, or 29% when it is an elbow or forearm that went down in the last four months. A 60-day pitcher who returned for the playoffs is not cut. No age penalty: older established players did not miss more time. Years before his debut never count.
- MLB role: for prospects, the chance he is in the majors, from the highest level reached and Pipeline rank. An established player with no MLB games last season and no injured-list time is marked down to 30%.
- Pitcher role: starter or reliever by his weighted history, except that last season decides it when two thirds or more of his games were one role. Innings and decisions per start come from his starts only.

**Keeper grade** = the same value over three seasons (100% / 80% / 60%), re-aged each year.

**What is held neutral:** complete games. **Fielding:** assists and errors are a small adjustment, judged only against leftover players at the same position, so they separate similar hitters without rewarding a position.

**Stress test (October 2026).** Build the board as of the October before, then score it against the real season, for 2025 and 2026.
- Rank agreement with real value on a fixed pre-season group of about 370 players: this board 0.42, our own March draft 0.41, last year's ranks 0.34. It ties the room five months early; it does not beat it.
- Big disagreements with our draft (25+ spots): the board was closer on about half.
- Win engine vs real standings (40 team-seasons): predicted categories won per week within about half a category; correlation 0.91.
- League assumptions (16 variations: recency, era, weekly volumes, replacement level, margins): board order agreement 0.96 to 0.99.
- Luck of which weeks were played (bootstrap): top 12 wobble 1 spot, ranks 13-50 about 6, ranks 51-150 about 8-10. Anything within 3 grade points is a tie.
- Healthy % was too rosy by 4 points (hitters) and 9 (pitchers), worst for pitchers finishing on the 60-day list (65% predicted, 34% real). Refit above; on held-out seasons the bias is gone and pitcher error is about 12% lower.
- Prospect pedigree: the bump moved prospects the wrong way in 34 of 47 back-test cases, overall accuracy unchanged. Kept at full strength by choice (keeper league; years two and three cannot be back-tested yet).
- The one piece that clearly improves prediction is the age curve on performance. Year weights and the strength of the pull to average make no measurable difference.
- Scripts: stress_lib.py, stress1.py (vs the draft), stress2.py and dur_fit*.py (durability), stress3.py (one piece at a time), stress4.py (stability), stress5.py (engine and data checks).
