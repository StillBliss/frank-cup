"""
The Frank Cup Gazette - weekly AI-written league news.

How it works
  1. The robot does the reporting. For each finished week it builds a "beat
     notebook" from the real data: results, category margins, grades, streaks,
     standings moves, league records, adds left unused, bench production,
     empty lineup slots, injured players left in lineups, big days, duds, hot
     and cold players, waiver hits, drops that came back to bite, the MLB
     transaction wire, next week's matchups and their ugliest history.
  2. It also computes each writer's weekly feature with real numbers:
     trivia (answered next week), playoff odds (Monte Carlo), Dud of the Week,
     Matchups to Watch, and a trade rumor that fits both rosters.
  3. Five writers (scripts/writers.json) each get the notebook, their own
     feature, their last columns and the Gazette's running ledger, and the AI
     only writes. It is told never to state a fact that isn't in the notebook.

AI provider: Google Gemini (free tier), key in the GEMINI_API_KEY secret.
An ANTHROPIC_API_KEY secret works too, if one is ever added instead.

Output: news.js at the repo root (window.NEWS = {...}), read by the News tab.
First run writes the last 4 finished weeks; after that, one issue per week.
NEWS_REDO=latest rewrites the newest issue.
"""
import datetime as dt
import hashlib, json, math, os, random, re, sys, time, unicodedata
import urllib.request, urllib.error
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.environ.get("FRANK_RAW") or os.path.join(ROOT, "raw")
NEWS_JS = os.environ.get("FRANK_NEWS") or os.path.join(ROOT, "news.js")
sys.path.insert(0, HERE)
import build, build_core as bc  # noqa: E402
import sources, players  # noqa: E402

BACKFILL = 4
MAX_ADDS_DEFAULT = 4

# ============================================================== small helpers
def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s.lower())
    return re.sub(r"[^a-z]", "", s)

def fnum(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def ip_float(v):
    """Yahoo innings '6.2' mean 6 and 2/3."""
    try:
        whole, _, frac = str(v).partition(".")
        return int(whole or 0) + (int(frac or 0) / 3.0)
    except ValueError:
        return 0.0

def ip_str(x):
    w = int(x + 1e-9); f = round((x - w) * 3)
    if f == 3: w, f = w + 1, 0
    return f"{w}.{f}"

def rec_str(r):
    return f"{r[0]}-{r[1]}-{r[2]}"

def monday_after(day):
    d = dt.date.fromisoformat(day)
    return (d + dt.timedelta(days=1)).isoformat()


# ============================================================== the league
class League:
    def __init__(self, D=None, cfg=None):
        if cfg is None:
            with open(os.path.join(ROOT, "league_config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        self.cfg = cfg
        self.D = D if D is not None else build.build(RAW, self.cfg)
        D = self.D
        self.managers = D["managers"]
        self.cats = D["cats"]
        self.hitN = D["hitN"]
        self.lower = set(D["lowerBetter"])
        skip = set(D.get("nonScoring") or ["H/AB"])
        self.score_idx = [i for i, c in enumerate(self.cats) if c not in skip]
        self.HIT = [i for i in self.score_idx if i < self.hitN]
        self.PIT = [i for i in self.score_idx if i >= self.hitN]
        self._S = {}
        self._grade = {}
        self._txs = {}

    def S(self, y):
        if y not in self._S:
            self._S[y] = build.Season(int(y), self.cfg)
        return self._S[y]

    def seasons(self):
        return sorted(int(s) for s in self.D["seasons"])

    def rows(self, y):
        return self.D["seasons"][str(y)]["matchups"]

    def line(self, y, m, w):
        e = self.D["weeklyDetail"].get(str(y), {}).get(m, {}).get(str(w))
        return e["you"] if e else None

    def teamname(self, y, m):
        return self.D["seasons"][str(y)]["teamNames"].get(m, m)

    def completed_weeks(self, y):
        wk = defaultdict(list)
        for r in self.rows(y):
            wk[r["week"]].append(r)
        return sorted(w for w, rs in wk.items() if rs and not any(r.get("live") for r in rs))

    def po_start(self, y):
        return self.S(y).po_start

    def end_week(self, y):
        return int(self.S(y).meta.get("end_week") or 26)

    def week_range(self, y, w):
        wr = build.week_ranges(self.S(y))
        return wr.get(w)

    def champ_keys(self, y):
        return set(((self.D.get("bracket") or {}).get(str(y)) or {}).get("live") or [])

    def in_champ(self, y, r):
        k = self.champ_keys(y)
        return f"{r['week']}|{r['a']}|{r['b']}" in k or f"{r['week']}|{r['b']}|{r['a']}" in k

    def winner(self, r):
        if r.get("win"): return r["win"]
        if r["aw"] > r["al"]: return r["a"]
        if r["al"] > r["aw"]: return r["b"]
        return None

    # ----- grades: same arithmetic as the site's plusWeek()
    def grades(self, y, w):
        key = (y, w)
        if key in self._grade: return self._grade[key]
        lines = {}
        for m in self.managers:
            l = self.line(y, m, w)
            if l: lines[m] = l
        if len(lines) < 4:
            self._grade[key] = None; return None
        acc = {m: {"H": [], "P": []} for m in lines}
        for i in self.score_idx:
            b = "H" if i < self.hitN else "P"
            lb = self.cats[i] in self.lower
            for m in lines:
                a = fnum(lines[m][i])
                if a is None: continue
                pts = n = 0
                for o in lines:
                    if o == m: continue
                    c = fnum(lines[o][i])
                    if c is None: continue
                    n += 1
                    if a == c: pts += .5
                    elif (a < c) if lb else (a > c): pts += 1
                if n: acc[m][b].append(pts / n)
        out = {}
        for m in lines:
            av = lambda a: 200 * sum(a) / len(a) if a else None
            H, P = av(acc[m]["H"]), av(acc[m]["P"])
            G = P if H is None else H if P is None else (H + P) / 2
            out[m] = {"H": H, "P": P, "G": G}
        self._grade[key] = out
        return out

    def allplay(self, y, w):
        lines = {m: self.line(y, m, w) for m in self.managers if self.line(y, m, w)}
        out = {}
        for me in lines:
            W = L = T = 0
            for o in lines:
                if o == me: continue
                cw = cl = 0
                for i in self.score_idx:
                    a, c = fnum(lines[me][i]), fnum(lines[o][i])
                    if a is None or c is None or a == c: continue
                    if (a < c) if self.cats[i] in self.lower else (a > c): cw += 1
                    else: cl += 1
                if cw > cl: W += 1
                elif cl > cw: L += 1
                else: T += 1
            out[me] = (W, L, T)
        return out

    def txs(self, y):
        if y not in self._txs:
            bc.RAW = RAW
            self._txs[y] = bc.transactions(y)
        return self._txs[y]


# ============================================================== player weeks
STAT_KEYS = {"H/AB": "HAB", "R": "R", "3B": "3B", "HR": "HR", "RBI": "RBI", "SB": "SB",
             "BB": "BB", "A": "A", "E": "E", "AVG": "AVG", "OPS": "OPS", "XBH": "XBH",
             "IP": "IP", "W": "W", "L": "L", "CG": "CG", "SV": "SV", "K": "K", "HLD": "HLD",
             "ERA": "ERA", "WHIP": "WHIP", "K/BB": "KBB", "QS": "QS"}
INACTIVE = {"BN", "IL", "IL+", "IL10", "IL15", "IL60", "NA", "DL", None}
HURT = ("IL", "O", "DL", "SUSP")
# personal, paternity, bereavement and family leave are short absences, not injuries
LEAVE = re.compile(r"personal|paternity|bereavement|family|restricted", re.I)


def on_leave(st, inj):
    return bool(LEAVE.search(f"{st or ''} {inj or ''}"))


def day_stats(raw, idmap):
    """Yahoo's {stat_id: value} for one day -> counting components."""
    s = {}
    for sid, v in raw.items():
        k = idmap.get(str(sid))
        if not k: continue
        if k == "HAB":
            h, _, ab = str(v).partition("/")
            s["H"] = fnum(h) or 0; s["AB"] = fnum(ab) or 0
        elif k == "IP":
            s["IP"] = ip_float(v)
        else:
            s[k] = fnum(v)
    ip = s.get("IP") or 0
    if ip:
        if s.get("ERA") is not None: s["ER"] = round(s["ERA"] * ip / 9.0)
        if s.get("WHIP") is not None: s["BR"] = round(s["WHIP"] * ip)
    return s


COUNT_H = ["H", "AB", "R", "HR", "RBI", "SB", "BB", "XBH", "3B", "A", "E"]
COUNT_P = ["IP", "W", "L", "CG", "SV", "K", "HLD", "QS", "ER", "BR"]


def add_into(acc, s):
    for k in COUNT_H + COUNT_P:
        v = s.get(k)
        if v: acc[k] = acc.get(k, 0) + v


def hit_prod(a):
    return (a.get("R", 0) + 2 * a.get("HR", 0) + a.get("RBI", 0) + 1.5 * a.get("SB", 0)
            + a.get("H", 0) + .5 * a.get("BB", 0) + .5 * a.get("XBH", 0)
            - .3 * (a.get("AB", 0) - a.get("H", 0)))

def pit_prod(a):
    return (.5 * a.get("K", 0) + 4 * a.get("W", 0) + 4 * a.get("SV", 0) + 2 * a.get("HLD", 0)
            + 3 * a.get("QS", 0) + a.get("IP", 0) - 1.5 * a.get("ER", 0) - .5 * a.get("BR", 0)
            - 2 * a.get("L", 0))

def hit_line(a):
    h, ab = int(a.get("H", 0)), int(a.get("AB", 0))
    bits = [f"{h}-for-{ab}"]
    for k, lbl in (("HR", "HR"), ("RBI", "RBI"), ("R", "R"), ("SB", "SB"), ("BB", "BB")):
        v = int(a.get(k, 0))
        if v: bits.append(f"{v} {lbl}")
    return ", ".join(bits)

def pit_line(a):
    ip = a.get("IP", 0)
    bits = [f"{ip_str(ip)} IP"]
    for k, lbl in (("W", "W"), ("L", "L"), ("SV", "SV"), ("HLD", "HLD"), ("QS", "QS"), ("K", "K")):
        v = int(a.get(k, 0))
        if v: bits.append(f"{v} {lbl}")
    if ip:
        bits.append(f"{a.get('ER', 0) * 9 / ip:.2f} ERA")
        bits.append(f"{a.get('BR', 0) / ip:.2f} WHIP")
    return ", ".join(bits)


class PlayerWeek:
    """Everything the notebook needs from one week of daily rosters."""

    def __init__(self, L, y, w):
        self.ok = False
        p = os.path.join(RAW, str(y), "players", f"week_{w:02d}.json")
        if not os.path.exists(p): return
        with open(p, encoding="utf-8") as f:
            self.raw = json.load(f)
        S = L.S(y)
        self.mgr = S.mgr
        idmap = {c["id"]: STAT_KEYS.get(c["abbr"]) for c in S.cats}
        self.idmap = idmap
        self.daylog = defaultdict(list)   # date -> every player line that day (for the daily report)
        # starting slots per position type
        need = {"B": 0, "P": 0}
        for rp in S.settings.get("roster_positions", []):
            rp = rp.get("roster_position", rp)
            if int(rp.get("is_starting_position") or 0) and rp.get("position_type") in need:
                need[rp["position_type"]] += int(rp.get("count") or 0)
        self.need = need
        self.players = {}   # (pkey, owner) -> dict
        self.days = []      # per-day notable lines
        self.empty = defaultdict(lambda: {"B": 0, "P": 0})
        self.hurt_active = defaultdict(lambda: defaultdict(int))  # owner -> player -> days
        self.adds = {}
        have_stats = False
        for d, teams in sorted(self.raw.get("days", {}).items()):
            for tk, tr in teams.items():
                owner = self.mgr.get(tk)
                if not owner: continue
                if tr.get("adds") is not None:
                    self.adds[owner] = max(self.adds.get(owner, 0), tr["adds"])
                filled = {"B": 0, "P": 0}
                for pl in tr.get("players", []):
                    sel = pl.get("sel")
                    active = sel not in INACTIVE
                    pt = pl.get("pt") or ("P" if (pl.get("pos") or "").endswith("P") else "B")
                    if active and pt in filled: filled[pt] += 1
                    key = (pl.get("k"), owner)
                    rec = self.players.setdefault(key, {
                        "name": pl.get("n"), "owner": owner, "pt": pt, "pos": pl.get("pos"),
                        "tm": pl.get("tm"), "act": {}, "bench": {}, "act_days": 0, "games": 0})
                    rec["st"] = pl.get("st"); rec["inj"] = pl.get("inj")
                    st = (pl.get("st") or "").upper()
                    if active and st.startswith(HURT) and not on_leave(st, pl.get("inj")) and not pl.get("s"):
                        self.hurt_active[owner][pl.get("n")] += 1
                    if active: rec["act_days"] += 1
                    if not pl.get("s"): continue
                    have_stats = True
                    s = day_stats(pl["s"], idmap)
                    played = (s.get("AB", 0) or 0) > 0 or (s.get("IP", 0) or 0) > 0 or s.get("BB")
                    if played: rec["games"] += 1
                    add_into(rec["act" if active else "bench"], s)
                    if played:
                        self.daylog[d].append({"owner": owner, "name": pl.get("n"), "tm": pl.get("tm"),
                                               "pt": pt, "bench": not active, "s": s})
                    note = self._big_day(s, pt)
                    if note:
                        self.days.append({"date": d, "owner": owner, "name": pl.get("n"),
                                          "bench": not active, "note": note[0], "score": note[1],
                                          "bad": note[2]})
                for t in ("B", "P"):
                    self.empty[owner][t] += max(0, need[t] - filled[t])
        self.ok = True
        self.have_stats = have_stats

    @staticmethod
    def _big_day(s, pt):
        if pt == "B":
            h, ab = int(s.get("H", 0)), int(s.get("AB", 0))
            hr, rbi, sb = int(s.get("HR", 0)), int(s.get("RBI", 0)), int(s.get("SB", 0))
            if hr >= 2 or h >= 4 or rbi >= 5 or sb >= 3 or (h >= 3 and hr >= 1 and rbi >= 4):
                a = {"H": h, "AB": ab, "HR": hr, "RBI": rbi, "SB": sb, "R": s.get("R", 0), "BB": s.get("BB", 0)}
                return hit_line(a), hr * 3 + h + rbi + sb * 2, False
            return None
        ip, k, er = s.get("IP", 0) or 0, int(s.get("K", 0) or 0), s.get("ER", 0) or 0
        if k >= 10 or s.get("CG") or (ip >= 7 and er == 0):
            return pit_line(s), k + ip * 1.5 - er * 2, False
        if er >= 7 or (ip < 3 and er >= 6):
            return pit_line(s), er, True
        return None

    def team_bench(self, owner):
        acc = {}
        for (_, o), r in self.players.items():
            if o == owner: add_into(acc, r["bench"])
        return acc

    def rows(self, owner=None):
        for (_, o), r in self.players.items():
            if owner is None or o == owner:
                yield r


# ============================================================== close calls
CLOSE = {"AVG": .004, "OPS": .010, "ERA": .15, "WHIP": .03, "K/BB": .15, "IP": 1.0}

def fmt_val(c, v):
    if v is None: return "-"
    if c in ("AVG", "OPS"): return f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}"
    if c in ("ERA", "WHIP", "K/BB"): return f"{v:.2f}"
    if c == "IP": return ip_str(v) if isinstance(v, float) and v != int(v) else f"{v:g}"
    return f"{v:g}"


def cat_detail(L, y, w, a, b):
    la, lb = L.line(y, a, w), L.line(y, b, w)
    out = []
    if not la or not lb: return out
    for i in L.score_idx:
        c = L.cats[i]
        va, vb = fnum(la[i]), fnum(lb[i])
        if va is None or vb is None: continue
        if va == vb: res = "T"
        elif (va < vb) if c in L.lower else (va > vb): res = "W"
        else: res = "L"
        margin = abs(va - vb)
        close = res != "T" and margin <= CLOSE.get(c, 1)
        out.append({"cat": c, "a": va, "b": vb, "res": res, "close": close, "margin": margin})
    return out


# ============================================================== standings
def standings_at(L, y, w):
    po = L.po_start(y)
    last = min(w, po - 1)
    if w >= po - 1:
        st = L.D["seasons"][str(y)]["standings"]
        return [{"m": r["manager"], "cat": [r["w"], r["l"], r["t"]], "wk": [r["mw"], r["ml"], r["mt"]],
                 "gb": r["gb"]} for r in st]
    cat = {m: [0, 0, 0] for m in L.managers}; wk = {m: [0, 0, 0] for m in L.managers}
    for r in L.rows(y):
        if r["stage"] != "Regular" or r["week"] > last or r.get("live"): continue
        for me, w_, l_, sw in ((r["a"], r["aw"], r["al"], 1), (r["b"], r["al"], r["aw"], 1)):
            cat[me][0] += w_; cat[me][1] += l_; cat[me][2] += r["at"]
            wk[me][0 if w_ > l_ else 1 if l_ > w_ else 2] += 1
    pct = lambda c: (c[0] + c[2] / 2) / max(1, sum(c))
    order = sorted(L.managers, key=lambda m: (-pct(cat[m]), -cat[m][0]))
    lead = cat[order[0]]
    return [{"m": m, "cat": cat[m], "wk": wk[m],
             "gb": ((lead[0] - cat[m][0]) + (cat[m][1] - lead[1])) / 2} for m in order]


def streaks(L, y, w):
    """current matchup streak for each manager, carried across seasons"""
    seq = defaultdict(list)
    for yy in L.seasons():
        if yy > y: break
        for r in sorted(L.rows(yy), key=lambda r: r["week"]):
            if r.get("live") or (yy == y and r["week"] > w): continue
            if r["stage"] != "Regular" and not L.in_champ(yy, r): continue
            win = L.winner(r)
            for m in (r["a"], r["b"]):
                seq[m].append("T" if win is None else "W" if win == m else "L")
    out = {}
    for m, s in seq.items():
        if not s: continue
        k = s[-1]; n = 0
        for x in reversed(s):
            if x != k: break
            n += 1
        out[m] = (k, n)
    return out


# ============================================================== records
def weekly_records(L, y, w):
    """Did anything this week crack the league's all-time single-week top 3?"""
    hist = defaultdict(list)
    for yy in L.seasons():
        for m, weeks in L.D["weeklyDetail"].get(str(yy), {}).items():
            for ws, e in weeks.items():
                ww = int(ws)
                if yy > y or (yy == y and ww > w): continue
                for i in L.score_idx:
                    v = fnum(e["you"][i])
                    if v is None: continue
                    hist[i].append((v, m, yy, ww))
    notes = []
    for i, arr in hist.items():
        c = L.cats[i]
        if c in ("AVG", "OPS", "ERA", "WHIP", "K/BB", "IP", "L", "E"):
            continue  # rate stats swing on playing time; skip
        arr.sort(key=lambda t: -t[0])
        for rank, (v, m, yy, ww) in enumerate(arr[:3]):
            if yy == y and ww == w:
                prev = next(((pv, pm, py, pw) for pv, pm, py, pw in arr if not (py == y and pw == w)), None)
                tag = "an all-time league record" if rank == 0 else f"the #{rank + 1} single week in league history"
                s = f"{m} put up {fmt_val(c, v)} {c} this week, {tag}"
                if rank == 0 and prev: s += f" (old mark: {prev[1]}, {fmt_val(c, prev[0])} in {prev[2]} week {prev[3]})"
                notes.append(s)
    # grade records
    allg = []
    for yy in L.seasons():
        if yy > y: break
        for ww in L.completed_weeks(yy):
            if yy == y and ww > w: continue
            g = L.grades(yy, ww)
            if not g: continue
            for m, v in g.items():
                if v["G"] is not None: allg.append((v["G"], m, yy, ww))
    allg.sort(key=lambda t: -t[0])
    for rank, (v, m, yy, ww) in enumerate(allg[:5]):
        if yy == y and ww == w:
            notes.append(f"{m}'s week grade of {v:.0f} is #{rank + 1} all time in league history")
    for rank, (v, m, yy, ww) in enumerate(sorted(allg, key=lambda t: t[0])[:5]):
        if yy == y and ww == w:
            notes.append(f"{m}'s week grade of {v:.0f} is the #{rank + 1} worst in league history")
    return notes


# ============================================================== odds (Norm)
def cat_model(L, y, w, shrink=0):
    share = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    ties = defaultdict(lambda: [0, 0])
    for ww in L.completed_weeks(y):
        if ww > w: continue
        lines = {m: L.line(y, m, ww) for m in L.managers if L.line(y, m, ww)}
        for i in L.score_idx:
            lb = L.cats[i] in L.lower
            for m in lines:
                a = fnum(lines[m][i])
                if a is None: continue
                for o in lines:
                    if o == m: continue
                    c = fnum(lines[o][i])
                    if c is None: continue
                    x = share[m][i]; x[1] += 1
                    if a == c: x[0] += .5; ties[i][0] += 1
                    elif (a < c) if lb else (a > c): x[0] += 1
                    ties[i][1] += 1
    P = {m: {i: min(.95, max(.05, share[m][i][0] / share[m][i][1])) if share[m][i][1] else .5
             for i in L.score_idx} for m in L.managers}
    if shrink:
        # few weeks played: pull each team's rates toward even, fading as weeks pile up
        nw = len([ww for ww in L.completed_weeks(y) if ww <= w])
        f = nw / (nw + shrink)
        P = {m: {i: .5 + (p - .5) * f for i, p in P[m].items()} for m in P}
    T = {i: (ties[i][0] / ties[i][1]) if ties[i][1] else .05 for i in L.score_idx}
    return P, T


def sim_odds(L, y, w, n=2000, shrink=0, wk_sd=0.0, team_sd=0.0):
    """wk_sd: a team's hot/cold swing across all categories in one week.
    team_sd: doubt about a team's true level, fading with weeks played. Both 0 = original model."""
    po, end = L.po_start(y), L.end_week(y)
    if w >= end: return None
    P, T = cat_model(L, y, w, shrink)
    pair = {}
    def probs(a, b):
        if (a, b) not in pair:
            v = []
            for i in L.score_idx:
                pa, pb = P[a][i], P[b][i]
                v.append((T[i], pa * (1 - pb) / (pa * (1 - pb) + pb * (1 - pa))))
            pair[(a, b)] = v
        return pair[(a, b)]
    nw = max(1, len([ww for ww in L.completed_weeks(y) if ww <= w]))
    lvl = {}
    def play(a, b, rnd):
        sh = 0.0
        if wk_sd or team_sd:
            sh = (lvl.get(a, 0) + rnd.gauss(0, wk_sd)) - (lvl.get(b, 0) + rnd.gauss(0, wk_sd))
        wa = wb = 0
        for t, p in probs(a, b):
            r = rnd.random()
            if r < t: continue
            if rnd.random() < min(.98, max(.02, p + sh)): wa += 1
            else: wb += 1
        return wa, wb
    st = standings_at(L, y, w)
    base = {r["m"]: list(r["cat"]) for r in st}
    sched = defaultdict(list)
    for r in L.rows(y):
        if r["stage"] == "Regular" and r["week"] > w and r["week"] < po:
            sched[r["week"]].append((r["a"], r["b"]))
    actual_seeds = (L.D.get("bracket", {}).get(str(y)) or {}).get("seeds") if w >= po - 1 else None
    # actual playoff winners for rounds already played
    done_round = {}
    for r in L.rows(y):
        if r["stage"] == "Playoff" and r["week"] <= w and not r.get("live") and L.in_champ(y, r):
            done_round.setdefault(r["week"], []).append(r)
    rnd = random.Random(f"{y}-{w}")
    tally = {m: {"po": 0, "bye": 0, "final": 0, "title": 0} for m in L.managers}
    nteams = 6
    ncat = len(L.score_idx)
    for _ in range(n):
        if team_sd:
            lvl = {m: rnd.gauss(0, team_sd / math.sqrt(nw)) for m in L.managers}
        if actual_seeds:
            seeds = dict(actual_seeds)
        else:
            rec = {m: list(v) for m, v in base.items()}
            for wk in sorted(sched):
                for a, b in sched[wk]:
                    wa, wb = play(a, b, rnd)
                    t = ncat - wa - wb
                    rec[a][0] += wa; rec[a][1] += wb; rec[a][2] += t
                    rec[b][0] += wb; rec[b][1] += wa; rec[b][2] += t
            pct = lambda c: (c[0] + c[2] / 2) / max(1, sum(c))
            order = sorted(rec, key=lambda m: (-pct(rec[m]), -rec[m][0], rnd.random()))
            seeds = {m: i + 1 for i, m in enumerate(order)}
        field = sorted([m for m in seeds if seeds[m] <= nteams], key=lambda m: seeds[m])
        for m in field: tally[m]["po"] += 1
        for m in field[:2]: tally[m]["bye"] += 1
        def game(a, b, wk):
            for r in done_round.get(wk, []):
                if {r["a"], r["b"]} == {a, b}: return L.winner(r) or (a if seeds[a] < seeds[b] else b)
            wa, wb = play(a, b, rnd)
            if wa == wb: return a if seeds[a] < seeds[b] else b
            return a if wa > wb else b
        qf = [game(field[2], field[5], po), game(field[3], field[4], po)]
        semi_pool = sorted(field[:2] + qf, key=lambda m: seeds[m])
        s1 = game(semi_pool[0], semi_pool[3], po + 1)
        s2 = game(semi_pool[1], semi_pool[2], po + 1)
        tally[s1]["final"] += 1; tally[s2]["final"] += 1
        tally[game(s1, s2, po + 2)]["title"] += 1
    return {m: {k: round(100 * v / n, 1) for k, v in t.items()} for m, t in tally.items()}


# ============================================================== trivia (Rosie)
def trivia_pool(L, y, w):
    qs = []
    cut = lambda yy, ww: yy < y or (yy == y and ww <= w)
    # single-week category records
    for c in ("HR", "SB", "K", "SV", "R", "RBI", "QS", "W", "HLD", "XBH", "BB"):
        if c not in L.cats: continue
        i = L.cats.index(c)
        best = None
        for yy in L.seasons():
            for m, weeks in L.D["weeklyDetail"].get(str(yy), {}).items():
                for ws, e in weeks.items():
                    if not cut(yy, int(ws)): continue
                    v = fnum(e["you"][i])
                    if v is not None and (best is None or v > best[0]): best = (v, m, yy, int(ws))
        if best:
            qs.append({"id": f"rec-{c}", "q": f"Which manager holds the league record for most {c} in a single week, and how many?",
                       "a": f"{best[1]}, with {best[0]:g} {c} in {best[2]} week {best[3]}."})
    # most lopsided result
    big = None
    for yy in L.seasons():
        for r in L.rows(yy):
            if r.get("live") or not cut(yy, r["week"]): continue
            mg = abs(r["aw"] - r["al"])
            if big is None or mg > big[0]:
                win, lose = (r["a"], r["b"]) if r["aw"] > r["al"] else (r["b"], r["a"])
                big = (mg, win, lose, max(r["aw"], r["al"]), min(r["aw"], r["al"]), r["at"], yy, r["week"])
    if big:
        qs.append({"id": "blowout", "q": "What is the most lopsided single-week result in league history?",
                   "a": f"{big[1]} over {big[2]}, {big[3]}-{big[4]}-{big[5]}, {big[6]} week {big[7]}."})
    # champions and first overall picks
    for yy in L.seasons():
        if yy >= y: continue
        fp = (L.D.get("finalPlace") or {}).get(str(yy))
        if fp:
            qs.append({"id": f"champ-{yy}", "q": f"Who won the {yy} Frank Cup championship?", "a": f"{fp[0]}."})
        st = L.D["seasons"][str(yy)]["standings"]
        qs.append({"id": f"reg-{yy}", "q": f"Who finished first in the {yy} regular season?", "a": f"{st[0]['manager']}."})
    for yy in L.seasons():
        if yy > y: continue
        pbs = (L.D.get("playersBySeason") or {}).get(str(yy), {})
        for m, v in pbs.items():
            for d in v.get("draft", []):
                if d.get("pick") == 1:
                    qs.append({"id": f"pick1-{yy}", "q": f"Who went first overall in the {yy} draft, and which manager took him?",
                               "a": f"{d['player']}, taken by {m}."})
    # most adds in a finished season
    best = None
    for yy in L.seasons():
        if yy >= y: continue
        for m, v in ((L.D.get("playersBySeason") or {}).get(str(yy), {})).items():
            t = v.get("addTotal", 0)
            if best is None or t > best[0]: best = (t, m, yy)
    if best:
        qs.append({"id": "adds-season", "q": "Which manager made the most adds in a single season, and how many?",
                   "a": f"{best[1]}, with {best[0]} adds in {best[2]}."})
    # longest matchup win streak
    seq = defaultdict(list)
    for yy in L.seasons():
        for r in sorted(L.rows(yy), key=lambda r: r["week"]):
            if r.get("live") or r["stage"] != "Regular" or not cut(yy, r["week"]): continue
            win = L.winner(r)
            for m in (r["a"], r["b"]): seq[m].append((win == m, yy, r["week"]))
    best = None
    for m, s in seq.items():
        cur = 0; start = None
        for ok, yy, ww in s:
            if ok:
                if cur == 0: start = (yy, ww)
                cur += 1
                if best is None or cur > best[0]: best = (cur, m, start, (yy, ww))
            else: cur = 0
    if best:
        qs.append({"id": "streak", "q": "What is the longest regular-season winning streak in league history?",
                   "a": f"{best[1]}, {best[0]} straight from {best[2][0]} week {best[2][1]} to {best[3][0]} week {best[3][1]}."})
    # best all-time grade
    allg = []
    for yy in L.seasons():
        for ww in L.completed_weeks(yy):
            if not cut(yy, ww): continue
            g = L.grades(yy, ww) or {}
            allg += [(v["G"], m, yy, ww) for m, v in g.items() if v["G"] is not None]
    if allg:
        v, m, yy, ww = max(allg)
        qs.append({"id": "grade", "q": "Who owns the highest single-week grade the league has ever seen?",
                   "a": f"{m}, a {v:.0f} in {yy} week {ww}."})
    # most regular season head-to-head wins over one manager
    h = defaultdict(lambda: defaultdict(int))
    for yy in L.seasons():
        for r in L.rows(yy):
            if r.get("live") or r["stage"] != "Regular" or not cut(yy, r["week"]): continue
            win = L.winner(r)
            if win: h[win][r["b"] if win == r["a"] else r["a"]] += 1
    for victim in L.managers:
        best = max(((h[m][victim], m) for m in L.managers if m != victim), default=None)
        if best and best[0] >= 3:
            ties = [m for m in L.managers if m != victim and h[m][victim] == best[0]]
            qs.append({"id": f"h2h-{victim}", "q": f"Which manager has beaten {victim} the most times in the regular season?",
                       "a": f"{' and '.join(ties)}, {best[0]} times."})
    return qs


def pick_trivia(pool, used, seed):
    left = [q for q in pool if q["id"] not in used] or pool
    rnd = random.Random(seed)
    return rnd.choice(left) if left else None


# ============================================================== trade rumor (Sauce)
def team_needs(L, y, w, span=4):
    weeks = [ww for ww in L.completed_weeks(y) if w - span < ww <= w]
    sh = defaultdict(lambda: defaultdict(list))
    for ww in weeks:
        lines = {m: L.line(y, m, ww) for m in L.managers if L.line(y, m, ww)}
        for i in L.score_idx:
            lb = L.cats[i] in L.lower
            for m in lines:
                a = fnum(lines[m][i]); pts = n = 0
                if a is None: continue
                for o in lines:
                    if o == m: continue
                    c = fnum(lines[o][i])
                    if c is None: continue
                    n += 1
                    if a == c: pts += .5
                    elif (a < c) if lb else (a > c): pts += 1
                if n: sh[m][i].append(pts / n)
    return {m: {L.cats[i]: sum(v) / len(v) for i, v in d.items()} for m, d in sh.items()}


CAT_PLAYER_KEY = {"R": "R", "HR": "HR", "RBI": "RBI", "SB": "SB", "BB": "BB", "XBH": "XBH", "3B": "3B",
                  "A": "A", "AVG": "H", "OPS": "HR", "W": "W", "SV": "SV", "K": "K", "HLD": "HLD",
                  "QS": "QS", "CG": "CG", "IP": "IP", "ERA": "-ER", "WHIP": "-BR", "K/BB": "K"}
HIT_CATS = {"R", "HR", "RBI", "SB", "BB", "XBH", "3B", "A", "AVG", "OPS", "E"}


def trade_rumor(L, y, w, pweeks, avoid=None):
    needs = team_needs(L, y, w)
    if len(needs) < 4: return None
    cats = [c for c in L.cats if c in CAT_PLAYER_KEY]
    combos = []
    for a in needs:
        for b in needs:
            if a >= b: continue
            for x in cats:          # a needs x, b has x
                for z in cats:      # b needs z, a has z
                    if x == z: continue
                    sc = (needs[b].get(x, .5) - needs[a].get(x, .5)) + (needs[a].get(z, .5) - needs[b].get(z, .5))
                    combos.append((sc, a, b, x, z))
    combos.sort(reverse=True)
    rnd = random.Random(f"rumor-{y}-{w}")
    top = [c for c in combos[:40] if not avoid or {c[1], c[2]} != set(avoid)][:8]
    if not top: return None
    sc, a, b, x, z = rnd.choice(top)
    # best contributors over the recent player weeks, on the roster at week's end
    def best_for(owner, cat):
        key = CAT_PLAYER_KEY[cat]; neg = key.startswith("-"); key = key.lstrip("-")
        tot = defaultdict(float); nm = {}
        pt_need = "B" if cat in HIT_CATS else "P"
        latest = pweeks[-1] if pweeks else None
        roster = {r["name"] for r in latest.rows(owner)} if latest and latest.ok else set()
        for pw in pweeks:
            if not pw.ok: continue
            for r in pw.rows(owner):
                if r["pt"] != pt_need or r["name"] not in roster: continue
                v = r["act"].get(key, 0) + r["bench"].get(key, 0)
                if neg:
                    ip = r["act"].get("IP", 0) + r["bench"].get("IP", 0)
                    if ip < 8: continue
                    v = -(v / ip)
                tot[r["name"]] += v
        if not tot: return None
        return max(tot, key=tot.get)
    pa, pb = best_for(a, z), best_for(b, x)
    return {"a": a, "b": b, "a_needs": x, "b_needs": z,
            "a_gives": pa, "b_gives": pb,
            "why": f"{a} ranks {needs[a][x]:.0%} in {x} over the last four weeks while {b} sits at {needs[b][x]:.0%}; "
                   f"{b} is at {needs[b][z]:.0%} in {z} where {a} is at {needs[a][z]:.0%} (share of all-play category wins)."}


# ============================================================== the notebook
def history_pair(L, y, w, a, b):
    games = []
    for yy in L.seasons():
        for r in L.rows(yy):
            if r.get("live") or (yy == y and r["week"] > w) or yy > y: continue
            if {r["a"], r["b"]} != {a, b}: continue
            if r["stage"] != "Regular" and not L.in_champ(yy, r): continue
            me = (r["aw"], r["al"]) if r["a"] == a else (r["al"], r["aw"])
            games.append({"y": yy, "w": r["week"], "stage": r["stage"], "a": me[0], "b": me[1], "t": r["at"],
                          "win": L.winner(r)})
    if not games: return None
    wa = sum(1 for g in games if g["win"] == a); wb = sum(1 for g in games if g["win"] == b)
    worst = max(games, key=lambda g: abs(g["a"] - g["b"]))
    last = max(games, key=lambda g: (g["y"], g["w"]))
    def gstr(g):
        who = a if g["a"] > g["b"] else b if g["b"] > g["a"] else "nobody"
        hi, lo = max(g["a"], g["b"]), min(g["a"], g["b"])
        return f"{who} won {hi}-{lo}-{g['t']} ({g['y']} week {g['w']}{', playoffs' if g['stage'] != 'Regular' else ''})"
    return {"n": len(games), "rec": f"{a} {wa}, {b} {wb}" + (f", {len(games) - wa - wb} tied" if len(games) - wa - wb else ""),
            "worst": gstr(worst), "last": gstr(last)}


def form(L, y, w, m, k=3):
    out = []
    for ww in range(w, 0, -1):
        for r in L.rows(y):
            if r["week"] == ww and m in (r["a"], r["b"]) and not r.get("live"):
                me = (r["aw"], r["al"]) if r["a"] == m else (r["al"], r["aw"])
                win = L.winner(r)
                out.append(("W" if win == m else "L" if win else "T") + f" {me[0]}-{me[1]}")
        if len(out) >= k: break
    return ", ".join(out[:k])


class Notebook:
    def __init__(self, L, y, w):
        self.L, self.y, self.w = L, y, w
        self.po, self.end = L.po_start(y), L.end_week(y)
        rng = L.week_range(y, w) or ("", "")
        self.start, self.stop = rng
        self.date = monday_after(self.stop) if self.stop else dt.date.today().isoformat()
        if w < self.po - 1: self.phase = "regular season"
        elif w == self.po - 1: self.phase = "regular season finale; the playoff field is now set"
        elif w < self.end: self.phase = "playoffs"
        else: self.phase = "the championship is decided; season over"
        self.pw = PlayerWeek(L, y, w)
        self.pprev = [PlayerWeek(L, y, ww) for ww in (w - 2, w - 1)]
        # in the playoffs only the championship bracket is covered; consolation teams are left alone
        if w >= self.po:
            self.focus = {m for r in L.rows(y) if r["week"] == w and L.in_champ(y, r) for m in (r["a"], r["b"])}
        else:
            self.focus = set(L.managers)
        self.src = sources.load_recent(y, RAW, upto=self.date, days=3)
        self.sections = {}
        self.build()

    def ok(self, m):
        return m in self.focus

    # ---------------------------------------------------------------- sections
    def build(self):
        L, y, w = self.L, self.y, self.w
        G = L.grades(y, w) or {}
        AP = L.allplay(y, w)
        self.G = G
        season_g = defaultdict(list)
        for ww in L.completed_weeks(y):
            if ww > w: continue
            for m, v in (L.grades(y, ww) or {}).items():
                if v["G"] is not None: season_g[m].append(v["G"])
        self.avg_g = {m: sum(v) / len(v) for m, v in season_g.items() if v}

        teams = [f"{m}: team '{L.teamname(y, m)}'" for m in L.managers]
        self.sections["Managers (first name) and team names"] = teams

        # results
        res = []
        self.results = []
        for r in sorted([r for r in L.rows(y) if r["week"] == w and (r["stage"] == "Regular" or L.in_champ(y, r))], key=lambda r: r["a"]):
            a, b = r["a"], r["b"]
            win = L.winner(r)
            det = cat_detail(L, y, w, a, b)
            kind = ("CHAMPIONSHIP BRACKET" if L.in_champ(y, r) else "consolation") if r["stage"] == "Playoff" else "regular season"
            ga, gb = G.get(a, {}), G.get(b, {})
            s = (f"[{kind}] {a} {r['aw']}-{r['al']}-{r['at']} {b}. "
                 + (f"Winner: {win}." if win else "Tie.")
                 + (" (tied on categories, decided on seed)" if r["stage"] == "Playoff" and r["aw"] == r["al"] else "")
                 + f" Hitting {r['ah'][0]}-{r['ah'][1]}-{r['ah'][2]}, pitching {r['ap'][0]}-{r['ap'][1]}-{r['ap'][2]} (from {a}'s side).")
            for m, g in ((a, ga), (b, gb)):
                if g and g.get("G") is not None:
                    s += f" {m} grade {g['G']:.0f} (hitting {g['H']:.0f}, pitching {g['P']:.0f}), all-play {AP.get(m, (0, 0, 0))[0]}-{AP.get(m, (0, 0, 0))[1]}-{AP.get(m, (0, 0, 0))[2]}."
            won = [d["cat"] for d in det if d["res"] == "W"]
            lost = [d["cat"] for d in det if d["res"] == "L"]
            if won: s += f" {a} won {', '.join(won)}."
            if lost: s += f" {b} won {', '.join(lost)}."
            close = [f"{d['cat']} {fmt_val(d['cat'], d['a'])} to {fmt_val(d['cat'], d['b'])} ({a if d['res'] == 'W' else b})"
                     for d in det if d["close"]]
            if close: s += f" Decided by a hair: {'; '.join(close)}."
            if win and ga.get("G") is not None and gb.get("G") is not None:
                lg = gb if win == a else ga; wg = ga if win == a else gb
                if lg["G"] - wg["G"] >= 8:
                    s += f" Luck alert: the loser had the better week overall (grade {lg['G']:.0f} vs {wg['G']:.0f})."
            res.append(s)
            self.results.append({"r": r, "det": det, "win": win})
        self.sections[f"Results, week {w}"] = res

        # standings / bracket
        st = standings_at(L, y, w)
        prev = {r["m"]: i for i, r in enumerate(standings_at(L, y, w - 1))} if w > 1 else {}
        lines = []
        for i, r in enumerate(st):
            mv = ""
            if prev and self.w < self.po:
                d = prev.get(r["m"], i) - i
                mv = f" (up {d})" if d > 0 else f" (down {-d})" if d < 0 else ""
            lines.append(f"{i + 1}. {r['m']} categories {rec_str(r['cat'])}, weeks {rec_str(r['wk'])}, "
                         + ("leader" if r["gb"] == 0 else "%.1f GB" % r["gb"])
                         + f"{mv}; season avg grade {self.avg_g.get(r['m'], 0):.0f}")
        if w < self.po:
            lines.append(f"Top 6 make the playoffs; seeds 1 and 2 get first-round byes. Regular season ends week {self.po - 1}.")
        else:
            lines.append("Regular season final standings above (seeds 1-6 made the playoffs).")
        self.sections["Standings (category record decides it)"] = lines
        if w >= self.po:
            br = L.D["bracket"].get(str(y), {})
            b_lines = [f"Seeds: " + ", ".join(f"{m} {s}" for m, s in sorted(br.get("seeds", {}).items(), key=lambda kv: kv[1])[:6])]
            for r in L.rows(y):
                if r["stage"] == "Playoff" and L.in_champ(y, r) and r["week"] <= w and not r.get("live"):
                    rd = {self.po: "Quarterfinal", self.po + 1: "Semifinal", self.po + 2: "Final"}.get(r["week"], "Playoff")
                    b_lines.append(f"{rd} (week {r['week']}): {L.winner(r)} beat {r['b'] if L.winner(r) == r['a'] else r['a']}, {max(r['aw'], r['al'])}-{min(r['aw'], r['al'])}-{r['at']}")
            if w >= self.end:
                champ = next((L.winner(r) for r in L.rows(y) if r["week"] == self.end and L.in_champ(y, r)), None)
                if champ: b_lines.append(f"CHAMPION: {champ}.")
            self.sections["Championship bracket"] = b_lines

        # season context: who has owned first place, and schedule luck once the regular season is done
        prog = [p for p in L.D["seasons"][str(y)].get("progression", []) if p["week"] <= min(w, self.po - 1)]
        ctx = []
        if prog:
            firsts = defaultdict(int)
            for p in prog:
                for m, rk in p["rank"].items():
                    if rk == 1: firsts[m] += 1
            ctx.append("Weeks spent in first place this season: " + ", ".join(f"{m} {n}" for m, n in sorted(firsts.items(), key=lambda kv: -kv[1])))
        if w >= self.po - 1:
            dc = (L.D.get("drawCats") or {}).get(str(y), {})
            if dc:
                srt = sorted(dc.items(), key=lambda kv: -(kv[1].get("draw") or 0))
                ctx.append("Schedule luck ('Draw', category wins gained (+) or lost (-) from who you happened to face): "
                           + ", ".join(f"{m} {v['draw']:+g}" for m, v in srt if v.get("draw") is not None))
        if ctx: self.sections["Season context"] = ctx

        # streaks
        sk = streaks(L, y, w)
        s_lines = [f"{m}: {'won' if k == 'W' else 'lost' if k == 'L' else 'tied'} {n} straight" for m, (k, n) in sorted(sk.items(), key=lambda kv: -kv[1][1]) if n >= 3 and self.ok(m)]
        if s_lines: self.sections["Streaks (matchups, carried across seasons)"] = s_lines

        rec = weekly_records(L, y, w)
        if rec: self.sections["League records this week"] = rec

        # transactions this week
        self.tx_notes()
        # players
        if self.pw.ok:
            self.player_notes()
        # MLB wire and outside news
        self.mlb_notes()
        self.outside_notes()
        # league history
        hist = []
        for yy in L.seasons():
            fp = (L.D.get("finalPlace") or {}).get(str(yy))
            if fp and yy < y: hist.append(f"{yy} champion: {fp[0]}; regular season winner: {L.D['seasons'][str(yy)]['standings'][0]['manager']}")
        pay = L.D.get("payouts") or {}
        top = sorted(pay.items(), key=lambda kv: -kv[1]["total"])[:3]
        if top: hist.append("Lifetime payouts leaders: " + ", ".join(f"{m} ${v['total']}" for m, v in top))
        self.sections["League history"] = hist

    def tx_notes(self):
        L, y, w = self.L, self.y, self.w
        wr = build.week_ranges(L.S(y))
        def pt_week(ts):
            d = pt_date(ts)
            return next((ww for ww, (a, b) in wr.items() if a <= d <= b), None)
        adds = defaultdict(list); drops = defaultdict(list); trades = []
        self.added_by = {}   # player name -> (manager, week)
        self.dropped_by = {}
        for t in L.txs(y):
            if t["status"] != "successful": continue
            ww = pt_week(t["ts"])     # Yahoo weeks run Monday to Sunday, Pacific time
            if ww is None or ww > w: continue
            if t["type"] == "trade":
                if ww == w: trades.append(t)
                continue
            for p in t["players"]:
                if p["type"] == "add":
                    m = L.S(y).mgr.get(p["destination_team_key"])
                    if m:
                        self.added_by[p["name"]] = (m, ww)
                        if ww == w: adds[m].append(p["name"])
                elif p["type"] == "drop":
                    m = L.S(y).mgr.get(p["source_team_key"])
                    if m:
                        self.dropped_by[p["name"]] = (m, ww)
                        if ww == w: drops[m].append(p["name"])
        mx = int(L.S(y).settings.get("max_weekly_adds") or MAX_ADDS_DEFAULT)
        lines = []
        for m in L.managers:
            if not self.ok(m): continue
            used = len(adds.get(m, []))
            s = f"{m}: {used} of {mx} adds used"
            if adds.get(m): s += f"; added {', '.join(adds[m])}"
            if drops.get(m): s += f"; dropped {', '.join(drops[m])}"
            lines.append(s)
        for t in trades:
            lines.append("TRADE: " + "; ".join(f"{L.S(y).mgr.get(p.get('destination_team_key'), '?')} got {p['name']}" for p in t["players"]))
        # unused adds that mattered
        unused = []
        for res in self.results:
            r, det, win = res["r"], res["det"], res["win"]
            for side, other in ((r["a"], r["b"]), (r["b"], r["a"])):
                used = len(adds.get(side, []))
                if used >= mx or win == side: continue
                closes = [d for d in det if d["close"] and ((d["res"] == "L") == (side == r["a"]))]
                if closes or win is not None:
                    s = f"{side} left {mx - used} adds unused and lost to {other}"
                    if closes: s += " while losing " + ", ".join(f"{d['cat']} by a hair" for d in closes)
                    unused.append(s)
        self.sections[f"Transactions, week {w} (max {mx} adds per week)"] = lines
        if unused: self.sections["Adds left on the table"] = unused

    def player_notes(self):
        L, y, w, pw = self.L, self.y, self.w, self.pw
        if pw.have_stats:
            # top and bottom performers
            hit = [r for r in pw.rows() if r["pt"] == "B" and r["act"].get("AB", 0) >= 10 and self.ok(r["owner"])]
            pit = [r for r in pw.rows() if r["pt"] == "P" and r["act"].get("IP", 0) >= 3 and self.ok(r["owner"])]
            hot = sorted(hit, key=lambda r: -hit_prod(r["act"]))[:6] + sorted(pit, key=lambda r: -pit_prod(r["act"]))[:5]
            self.sections["Hottest players this week (in active lineups)"] = [
                f"{r['name']} ({r['tm']}, {r['owner']}): {hit_line(r['act']) if r['pt'] == 'B' else pit_line(r['act'])}{self._trend(r)}" for r in hot]
            cold_h = sorted([r for r in hit if r["act"].get("AB", 0) >= 14], key=lambda r: hit_prod(r["act"]))[:4]
            cold_p = sorted([r for r in pit], key=lambda r: pit_prod(r["act"]))[:4]
            self.sections["Coldest players this week (in active lineups)"] = [
                f"{r['name']} ({r['tm']}, {r['owner']}): {hit_line(r['act']) if r['pt'] == 'B' else pit_line(r['act'])}{self._trend(r)}" for r in cold_h + cold_p]
            big = sorted([d for d in pw.days if self.ok(d["owner"])], key=lambda d: -d["score"])
            good = [d for d in big if not d["bad"]][:10]
            bad = [d for d in big if d["bad"]][:4]
            if good:
                self.sections["Big single days"] = [
                    f"{d['date']}: {d['name']} ({d['owner']}) {d['note']}{' -- ON THE BENCH, did not count' if d['bench'] else ''}" for d in good]
            if bad:
                self.sections["Disaster starts"] = [
                    f"{d['date']}: {d['name']} ({d['owner']}) {d['note']}{' (benched, did not count)' if d['bench'] else ''}" for d in bad]
            # bench production and flips
            flips, bench = [], []
            for res in self.results:
                r, det = res["r"], res["det"]
                for side in (r["a"], r["b"]):
                    bt = pw.team_bench(side)
                    parts = [f"{int(bt[k])} {k}" for k in ("HR", "RBI", "R", "SB", "K", "W", "SV", "QS") if bt.get(k, 0) >= (1 if k in ("HR", "SB", "W", "SV", "QS") else 3)]
                    if parts: bench.append(f"{side} left on the bench: {', '.join(parts)}")
                    for d in det:
                        lost = (d["res"] == "L") == (side == r["a"])
                        if not lost or d["res"] == "T": continue
                        key = {"HR": "HR", "RBI": "RBI", "R": "R", "SB": "SB", "BB": "BB", "XBH": "XBH", "3B": "3B",
                               "K": "K", "W": "W", "SV": "SV", "QS": "QS", "HLD": "HLD"}.get(d["cat"])
                        if key and bt.get(key, 0) > 0 and bt.get(key, 0) >= d["margin"]:
                            flips.append(f"{side} lost {d['cat']} by {d['margin']:g} with {int(bt[key])} {d['cat']} sitting on the bench")
            if bench: self.sections["Bench production (did not count)"] = bench
            if flips: self.sections["Bench blunders that flipped a category"] = flips
            # waiver hits and drops that bit back
            wh, haunt = [], []
            for r in pw.rows():
                if not self.ok(r["owner"]): continue
                ab = self.added_by.get(r["name"])
                prod = hit_prod(r["act"]) if r["pt"] == "B" else pit_prod(r["act"])
                line = hit_line(r["act"]) if r["pt"] == "B" else pit_line(r["act"])
                if ab and ab[0] == r["owner"] and ab[1] >= w - 1 and prod >= (12 if r["pt"] == "B" else 12):
                    wh.append(f"{r['owner']} added {r['name']} in week {ab[1]}; this week: {line}")
                dr = self.dropped_by.get(r["name"])
                if dr and dr[0] != r["owner"] and dr[1] >= w - 3 and prod >= 10:
                    haunt.append(f"{dr[0]} dropped {r['name']} in week {dr[1]}; now on {r['owner']}'s roster: {line}")
            if wh: self.sections["Waiver pickups that paid off"] = wh
            if haunt: self.sections["Drops that came back to bite"] = haunt
        # lineup neglect
        neg = []
        for m in self.L.managers:
            if not self.ok(m): continue
            e = pw.empty.get(m)
            if e and (e["B"] + e["P"]) > 0:
                neg.append(f"{m} left {e['B']} hitter slot-days and {e['P']} pitcher slot-days empty")
        for m, pl in pw.hurt_active.items():
            if not self.ok(m): continue
            for n, d in pl.items():
                neg.append(f"{m} started {n} while on the injured list / out for {d} day(s)")
        if neg: self.sections["Lineup neglect"] = neg
        # injured list snapshot
        inj = []
        for r in pw.rows():
            if not self.ok(r["owner"]) or r["games"] > 0: continue   # he played, so the tag is stale
            st = (r.get("st") or "").upper()
            if on_leave(st, r.get("inj")):
                inj.append(f"{r['name']} ({r['owner']}): away on {r.get('inj') or 'personal'} leave. A short absence, "
                           f"not an injury, and no fault of the manager.")
            elif st.startswith(("IL", "O", "DTD")):
                inj.append(f"{r['name']} ({r['owner']}): {r['st']}{' - ' + r['inj'] if r.get('inj') else ''}")
        if inj: self.sections["Injury report (league rosters, end of week)"] = inj[:20]

    def _trend(self, r):
        prev = []
        for pw in self.pprev:
            if not pw.ok: continue
            for q in pw.rows(r["owner"]):
                if q["name"] == r["name"]: prev.append(q)
        if not prev: return ""
        acc = {}
        for q in prev: add_into(acc, q["act"]); add_into(acc, q["bench"])
        if r["pt"] == "B" and acc.get("AB", 0) >= 10:
            return f"; prior two weeks {hit_line(acc)}"
        if r["pt"] == "P" and acc.get("IP", 0) >= 3:
            return f"; prior two weeks {pit_line(acc)}"
        return ""

    def mlb_notes(self):
        p = os.path.join(RAW, str(self.y), "mlb", f"week_{self.w:02d}.json")
        if not os.path.exists(p) or not self.pw.ok: return
        owners = {}
        for r in self.pw.rows():
            owners[norm_name(r["name"])] = r["owner"]
        tx = json.load(open(p, encoding="utf-8")).get("tx", [])
        out = []
        for t in tx:
            o = owners.get(norm_name(t.get("who")))
            if o and self.ok(o):
                tag = " [short leave, not an injury; usually 1 to 7 days]" if on_leave("", t.get("desc")) else ""
                out.append(f"{t['date']} ({o}'s player): {t['desc']}{tag}")
        if out: self.sections["MLB transaction wire (players on league rosters)"] = out[:25]

    def outside_notes(self):
        """ESPN injury details, news headlines from ESPN, MLB.com, CBS and Yahoo Sports that
        mention league players, and the real MLB playoff race."""
        src = self.src or {}
        if not src: return
        own = {}
        if self.pw.ok:
            for r in self.pw.rows():
                if self.ok(r["owner"]):
                    own[fold(re.sub(r"\s*\(.*\)", "", r["name"] or ""))] = (r["owner"], r["name"])
        inj = []
        for x in src.get("espn_injuries") or []:
            o = own.get(fold(x.get("who")))
            if not o: continue
            s = f"{x['who']} ({o[0]}): {x.get('status') or 'injured'}"
            if x.get("what"): s += f", {x['what']}"
            if x.get("back"): s += f", expected back {x['back']}"
            if x.get("note"): s += f". {x['note']}"
            if on_leave("", f"{x.get('status')} {x.get('what')} {x.get('note')}"): s += " [short leave, not an injury]"
            inj.append(s)
        if inj: self.sections["Injury details (ESPN) for league players"] = inj[:15]
        news = []
        for it in src.get("feeds") or []:
            txt = fold(it["title"] + " " + it.get("summary", "") + " " + " ".join(it.get("players") or []))
            hits = [v for k, v in own.items() if len(k) > 6 and k in txt]
            if hits:
                news.append(f"[{it['src']}, {it.get('date')}] {it['title']}. {it.get('summary', '')[:220]} "
                            f"(league: {', '.join(f'{h[1]} of {h[0]}' for h in hits[:3])})")
        if news: self.sections["MLB news mentioning league players (ESPN, MLB.com, CBS, Yahoo Sports)"] = news[:15]
        st = src.get("standings") or []
        if st:
            clinched = [t["team"] for t in st if t.get("clinch")]
            hunt = [f"{t['team']} ({t['w']}-{t['l']}, {t.get('wc_gb')} GB of a wild card)" for t in st
                    if not t.get("clinch") and t.get("elim") not in ("E",) and str(t.get("wc_gb")) not in ("-",) and
                    (fnum(t.get("wc_gb")) or 99) <= 4]
            lines = []
            if clinched: lines.append("Clinched a playoff spot: " + ", ".join(clinched))
            if hunt: lines.append("Still in the wild card hunt: " + "; ".join(hunt))
            if lines: self.sections["Real MLB playoff race (teams resting or pushing players)"] = lines

    # ---------------------------------------------------------------- features
    def next_matchups(self):
        L, y, w = self.L, self.y, self.w
        nxt = [r for r in L.rows(y) if r["week"] == w + 1 and (r["stage"] == "Regular" or L.in_champ(y, r))]
        out = []
        for r in nxt:
            a, b = r["a"], r["b"]
            kind = ("CHAMPIONSHIP BRACKET" if L.in_champ(y, r) else "consolation") if r["stage"] == "Playoff" else "regular season"
            h = history_pair(L, y, w, a, b)
            s = {"a": a, "b": b, "kind": kind, "form_a": form(L, y, w, a), "form_b": form(L, y, w, b),
                 "grade_a": round(self.avg_g.get(a, 0)), "grade_b": round(self.avg_g.get(b, 0))}
            if h: s.update(h)
            out.append(s)
        return out

    def dud(self):
        pw = self.pw
        if not pw.ok or not pw.have_stats: return None
        c = []
        for r in pw.rows():
            if not self.ok(r["owner"]): continue
            if r["pt"] == "B" and r["act"].get("AB", 0) >= 12:
                c.append((hit_prod(r["act"]), r, hit_line(r["act"])))
            elif r["pt"] == "P" and r["act"].get("IP", 0) >= 3:
                c.append((pit_prod(r["act"]) - 2, r, pit_line(r["act"])))
        if not c: return None
        sc, r, line = min(c, key=lambda t: t[0])
        return {"name": r["name"], "mlb": r["tm"], "owner": r["owner"], "line": line}

    def text(self):
        out = [f"THE FRANK CUP GAZETTE, issue dated {self.date}. Covers week {self.w} of the {self.y} season "
               f"({self.start} to {self.stop}). Phase: {self.phase}. League: 10 teams, Yahoo head-to-head, "
               f"{len(self.L.score_idx)} scoring categories: {', '.join(self.L.cats[i] for i in self.L.score_idx)} "
               f"(E, L, ERA, WHIP lower is better). Weekly winner is whoever wins more categories. "
               f"'Grade' is 100 = league average for that week; all-play is the record against all nine others that week."]
        for k, v in self.sections.items():
            if not v: continue
            out.append(f"\n## {k}")
            out += [f"- {x}" for x in v]
        return "\n".join(out)


# ============================================================== AI
class NoAI(Exception): pass
class TimeUp(Exception): pass

# stop starting new articles after this many minutes; the rest wait for the next run
DEADLINE = time.time() + 60 * float(os.environ.get("NEWS_BUDGET_MIN", "30"))


def http_json(url, body, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class OutOfAI(Exception):
    """every model is used up or unavailable for this run"""


_pool = None          # models to try, best first
_dead = set()         # out of daily quota (or missing) for the rest of this run
_busy = {}            # model -> consecutive 'server busy' answers


def gemini_models(key):
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                 headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    full, lite = [], []
    for m in d.get("models", []):
        n = m.get("name", "").split("/")[-1]
        if "generateContent" not in (m.get("supportedGenerationMethods") or []) or "flash" not in n:
            continue
        if any(x in n for x in ("image", "tts", "live", "exp", "preview", "audio", "thinking", "latest")):
            continue
        (lite if "lite" in n else full).append(n)
    def ver(n):
        v = re.findall(r"(\d+(?:\.\d+)?)", n)
        return float(v[0]) if v else 0
    # newest full Flash models first; the lighter ones are a last resort
    return sorted(full, key=ver, reverse=True) + sorted(lite, key=ver, reverse=True)


def gemini_pool(key):
    global _pool
    if _pool is None:
        want = os.environ.get("GEMINI_MODEL")
        try:
            _pool = gemini_models(key)
        except Exception as e:  # noqa: BLE001
            print("   could not list Gemini models:", e)
            _pool = []
        if want: _pool = [want] + [m for m in _pool if m != want]
        if not _pool: _pool = ["gemini-flash-latest"]
        print("   Gemini models, in order:", ", ".join(_pool))
    return _pool


def call_gemini(system, user, key):
    """Try models in order. A model out of its daily allowance is dropped for the
    rest of the run; a busy model gets one quick retry, then we move on."""
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json", "maxOutputTokens": 8192}}
    for rnd in range(2):       # two passes over the pool, in case everything was momentarily busy
        live = [m for m in gemini_pool(key) if m not in _dead]
        if not live: break
        live.sort(key=lambda m: _busy.get(m, 0))      # models that have been busy go to the back
        for model in live:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in range(2):
                try:
                    d = http_json(url, body, {"x-goog-api-key": key})
                    parts = d["candidates"][0]["content"]["parts"]
                    _busy[model] = 0
                    return "".join(p.get("text", "") for p in parts if not p.get("thought")), model
                except urllib.error.HTTPError as e:
                    msg = e.read().decode(errors="replace")
                    if e.code == 429 and re.search(r"PerDay|per day|daily", msg, re.I):
                        print(f"   {model}: out of free requests for today, dropping it")
                        _dead.add(model); break
                    if e.code == 429:       # per-minute limit: a short pause fixes it
                        print(f"   {model}: per-minute limit, pausing 20s")
                        time.sleep(20); continue
                    if e.code in (500, 502, 503, 504):
                        _busy[model] = _busy.get(model, 0) + 1
                        if attempt == 0:
                            print(f"   {model}: Google busy ({e.code}), one retry in 10s")
                            time.sleep(10); continue
                        print(f"   {model}: still busy, trying the next model")
                        break
                    print(f"   {model}: HTTP {e.code} {msg[:200]}, dropping it")
                    _dead.add(model); break
                except (KeyError, IndexError):
                    print(f"   {model}: empty answer, trying the next model")
                    break
                except (urllib.error.URLError, TimeoutError):
                    print(f"   {model}: no response, trying the next model")
                    break
        if rnd == 0:
            print("   every model busy or used up; one more pass in 60s")
            time.sleep(60)
    raise OutOfAI("no Gemini model available")


def call_anthropic(system, user, key):
    model = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5"
    for attempt in range(4):
        try:
            d = http_json("https://api.anthropic.com/v1/messages",
                          {"model": model, "max_tokens": 3000, "system": system,
                           "messages": [{"role": "user", "content": user}]},
                          {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return "".join(b.get("text", "") for b in d.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) or e.code >= 500:
                time.sleep(30 * (attempt + 1)); continue
            raise RuntimeError(f"Anthropic HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    raise RuntimeError("Anthropic did not answer")


def ai(system, user):
    if os.environ.get("NEWS_FAKE_AI"):
        return fake_ai(system, user)
    g = os.environ.get("GEMINI_API_KEY"); a = os.environ.get("ANTHROPIC_API_KEY")
    if g: return call_gemini(system, user, g)[0]
    if a: return call_anthropic(system, user, a)
    raise NoAI()


def fake_ai(system, user):
    """offline stand-in used for testing the pipeline"""
    name = re.search(r"You are (.+?),", system).group(1)
    first = [l for l in user.splitlines() if l.startswith("- ")][:6]
    return json.dumps({"headline": f"{name} files week report", "dek": "A test dispatch from the offline desk.",
                       "body": "\n\n".join(l[2:] for l in first) + "\n\nMore to come next week.",
                       "bit": "Feature text goes here.", "ledger": f"{name} tested the presses."})


def parse_json(txt):
    t = txt.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b < 0: raise ValueError("no json")
    d = json.loads(t[a:b + 1])
    for k in ("headline", "body"):
        if not d.get(k): raise ValueError(f"missing {k}")
    for k in ("headline", "dek", "body", "bit", "ledger"):
        if isinstance(d.get(k), str):
            d[k] = re.sub("\\s*\u2014\\s*", ", ", d[k]).replace(" \u2013 ", ", ")
    return d


# ============================================================== the desk
RULES = """HARD RULES
- Use only facts from the reporter's notebook below. Never invent stats, scores, injuries, trades, transactions, lineup moves, or player performances. If it isn't in the notebook, don't state it as fact.
- Managers are referred to by first name exactly as given. 'Benny' and 'Ben' are two different managers; never mix them up.
- A player away on personal, paternity, bereavement or family leave is not injured and his manager did nothing wrong by keeping him. Never call that wasted roster space.
- Opinions, jokes, hot takes, predictions and running bits are encouraged. Invented anonymous 'sources' are allowed only for Tony Russo, and must stay obviously playful.
- Keep it PG-13 and strictly about fantasy baseball: never comment on anyone's real life, looks, job, family, or relationships.
- Do not use em dashes.
- Headlines in normal title case. Never write a headline or sentence in all capital letters.
- Never open with a stock line such as "Welcome to", "What a week", "Buckle up", "Well, well, well", "Another week" or "Let's dive in". Open on a specific fact, image, or line only you would write.
- Report like a beat writer who watches every detail: specific numbers, specific players, specific category margins. Pick the best 3 to 5 storylines on YOUR beat rather than listing everything.
- Stay on your beat. Your colleagues own theirs (listed below); touch their stories only in passing, and never lead with one.
- Continuity matters. When it fits naturally, call back to earlier Gazette columns in the ledger (yours or a colleague's): follow up on predictions, keep grudges and running jokes alive, admit when you were wrong. Don't force it.
- Body: 350 to 550 words, short paragraphs separated by blank lines. You may use **bold** sparingly.
Return only JSON: {"headline": "...", "dek": "one-sentence subhead", "body": "...", "bit": "text for your weekly feature box, 2 to 5 sentences", "ledger": "one or two sentences recording the specific claims, predictions, jokes or grudges in this column, for future callbacks"EXTRA}"""


def staff_text(cfg, me):
    rows = [f"- {w['name']} ({w['desk']}): {w['beat']}" for w in cfg["monday"] if w["id"] != me]
    return "THE REST OF THE GAZETTE STAFF THIS ISSUE (their beats, not yours):\n" + "\n".join(rows)


def notes_text(cfg, allow_cody):
    out = ["LEAGUE NOTES:"] + [f"- {n}" for n in cfg.get("league_notes", [])]
    for c in cfg.get("characters", []):
        if allow_cody:
            out.append(f"- {c['name']}: {c['about']} This issue you may quote or briefly interview him if it fits; "
                       f"skip him if it doesn't.")
        else:
            out.append(f"- {c['name']} exists, but another writer has him this issue; don't use him.")
    return "\n".join(out)


def writer_prompt(cfg, wr, nb, feature, own_prev, ledger, allow_cody):
    extra = ', "rankings": {"Manager": "one-line blurb", ...} (one entry for every ranked team)' if wr["bit"] == "rankings" else ""
    system = (f"You are {wr['name']}, columnist for The Frank Cup Gazette ({wr['desk']}), the weekly paper of a "
              f"10-manager fantasy baseball league among friends.\nVOICE: {wr['voice']}\nYOUR BEAT: {wr['beat']}\n\n"
              f"{RULES.replace('EXTRA', extra)}\n\n{notes_text(cfg, allow_cody)}\n\n{staff_text(cfg, wr['id'])}")
    parts = [nb.text(), f"\n\n# YOUR WEEKLY FEATURE: {wr['bit_name']}", feature]
    if own_prev:
        parts.append("\n# YOUR RECENT COLUMNS (most recent last)")
        for p in own_prev:
            parts.append(f"- {p['season']} week {p['week']}: \"{p['headline']}\". {p['excerpt']}")
    if ledger:
        parts.append("\n# GAZETTE LEDGER (notes on past columns, oldest first; call back to these when it fits)")
        parts += [f"- {x['season']} wk {x['week']}, {x['name']}: {x['line']}" for x in ledger]
    parts.append("\nWrite this week's column now.")
    return system, "\n".join(parts)


# ============================================================== new features
def power_rankings(L, y, w, nb):
    """Blend of season-long quality, recent form and the standings."""
    st = {r["m"]: r for r in standings_at(L, y, w)}
    po, end = L.po_start(y), L.end_week(y)
    alive = set(L.managers)
    if po <= w < end:
        alive = {L.winner(r) for r in L.rows(y) if r["week"] == w and L.in_champ(y, r)}
        if w == po:
            seeds = ((L.D.get("bracket") or {}).get(str(y)) or {}).get("seeds") or {}
            alive |= {m for m, sd in seeds.items() if sd <= 2}
    recent = defaultdict(list)
    for ww in L.completed_weeks(y):
        if w - 3 < ww <= w:
            for m, v in (L.grades(y, ww) or {}).items():
                if v["G"] is not None: recent[m].append(v["G"])
    rows = []
    for m in L.managers:
        if m not in alive: continue
        c = st.get(m, {}).get("cat", [0, 0, 0])
        pct = (c[0] + c[2] / 2) / max(1, sum(c))
        sg, rg = nb.avg_g.get(m, 100), (sum(recent[m]) / len(recent[m]) if recent[m] else nb.avg_g.get(m, 100))
        rows.append({"m": m, "score": round(.45 * sg + .35 * rg + .20 * pct * 200, 1), "season": round(sg),
                     "last3": round(rg), "cat": rec_str(c), "wk": rec_str(st.get(m, {}).get("wk", [0, 0, 0]))})
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows): r["rank"] = i + 1
    return rows


def history_items(L, y, w, nb):
    items = list(weekly_records(L, y, w))
    for yy in L.seasons():
        if yy >= y: continue
        rs = [r for r in L.rows(yy) if r["week"] == w and not r.get("live") and (r["stage"] == "Regular" or L.in_champ(yy, r))]
        if not rs: continue
        r = max(rs, key=lambda r: abs(r["aw"] - r["al"]))
        win = L.winner(r) or r["a"]; lose = r["b"] if win == r["a"] else r["a"]
        who = " (the previous Jacob)" if "Jacob" in (win, lose) and yy < 2026 else ""
        items.append(f"Week {w}, {yy}: {win} beat {lose} {max(r['aw'], r['al'])}-{min(r['aw'], r['al'])}-{r['at']}, the most lopsided result that week{who}")
    for res in nb.results:
        r = res["r"]
        h = history_pair(L, y, w, r["a"], r["b"])
        if h: items.append(f"{r['a']} vs {r['b']} all time: {h['n']} meetings, {h['rec']}; ugliest: {h['worst']}")
    for yy in L.seasons():
        if yy >= y: continue
        fp = (L.D.get("finalPlace") or {}).get(str(yy))
        if fp: items.append(f"{yy} champion: {fp[0]}")
    return items


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def fa_line(p, idmap):
    s = day_stats(p.get("s") or {}, idmap)
    return pit_line(s) if (s.get("IP") or 0) > 0 or p.get("pos", "").endswith("P") else hit_line(s)


def waiver_data(L, y, w, nb):
    src = nb.src or {}
    S = L.S(y)
    idmap = {c["id"]: STAT_KEYS.get(c["abbr"]) for c in S.cats}
    out = {"hitters": [], "pitchers": [], "two_start": []}
    fa = src.get("free_agents") or {}
    for key, pos in (("hitters", "B"), ("pitchers", "P")):
        for p in (fa.get(pos) or [])[:6]:
            out[key].append({"name": p.get("n"), "tm": p.get("tm"), "pos": p.get("pos"), "line": fa_line(p, idmap),
                             "own": p.get("own"), "delta": p.get("delta"), "st": p.get("st")})
    nxt = L.week_range(y, w + 1)
    pro = src.get("probables") or []
    if nxt and pro:
        starts = defaultdict(list)
        for g in pro:
            if nxt[0] <= g["date"] <= nxt[1]: starts[g["who"]].append(g)
        owners = {}
        if nb.pw.ok:
            for r in nb.pw.rows(): owners[fold(r["name"])] = r["owner"]
        fa_names = {fold(p.get("n")) for p in (fa.get("P") or [])}
        for who, gs in starts.items():
            if len(gs) >= 2:
                o = owners.get(fold(who))
                out["two_start"].append({"who": who, "team": gs[0]["team"],
                                         "owner": o or ("free agent" if fold(who) in fa_names else "unknown"),
                                         "vs": [g["vs"] for g in gs]})
    return out


def feature_for(cfg, wr, nb, state, L):
    y, w = nb.y, nb.w
    bit = {"type": wr["bit"], "name": wr["bit_name"]}
    if wr["bit"] == "trivia":
        prev = state.get("trivia_open")
        pool = trivia_pool(L, y, w)
        q = pick_trivia(pool, set(state.get("trivia_used", [])), f"{y}-{w}")
        bit["data"] = {"question": q["q"] if q else None, "last_q": prev["q"] if prev else None,
                       "last_a": prev["a"] if prev else None}
        txt = (f"Last week's question: {prev['q']} Answer: {prev['a']}\n" if prev else "This is your first trivia question, no answer to reveal yet.\n")
        txt += (f"This week's question (print it, do NOT reveal the answer; it runs next week): {q['q']}" if q else "")
        txt += "\nIn the bit field, reveal last week's answer if there is one, then pose this week's question."
        return bit, txt, q
    if wr["bit"] == "odds":
        odds = sim_odds(L, y, w)
        prev = (state.get("odds_prev") or {})
        bit["data"] = {"odds": odds, "prev": prev, "phase": nb.phase}
        if not odds:
            return bit, "The season is over, so no odds board. In the bit field, give a by-the-numbers season verdict using the standings and grades.", None
        rows = []
        in_po = w >= L.po_start(y)
        odds = {m: o for m, o in odds.items() if (o["final"] > 0 or o["title"] > 0) if in_po} if in_po else odds
        bit["data"]["odds"] = odds
        for m, o in sorted(odds.items(), key=lambda kv: (-kv[1]["title"], -kv[1]["po"])):
            p = prev.get(m, {})
            ch = f" (was {p.get('title')}% title)" if p else ""
            rows.append(f"- {m}: playoffs {o['po']}%, bye {o['bye']}%, reach final {o['final']}%, title {o['title']}%{ch}")
        return bit, ("Monte Carlo odds from 2,000 simulated finishes, each category simulated from every team's "
                     "season-long category win rates:\n" + "\n".join(rows) +
                     "\nIn the bit field, explain the biggest movers and one number that surprised you."), None
    if wr["bit"] == "dud":
        d = nb.dud()
        bit["data"] = d
        if d:
            return bit, (f"Dud of the Week (the worst full-week line by an active player): {d['name']} ({d['mlb']}), owned by "
                         f"{d['owner']}: {d['line']}. Present the award with ceremony in the bit field."), None
        return bit, ("No player-level data this week, so hand the Dud to the worst team category performance in the results "
                     "instead, and say so. Put it in the bit field."), None
    if wr["bit"] == "matchups":
        nm = nb.next_matchups()
        bit["data"] = nm
        if not nm:
            return bit, ("No games left this season. Write the season's obituary instead: revisit the worst beatdowns of "
                         "the year from the results and history in the notebook. In the bit field, name the one wound "
                         "that will never heal."), None
        rows = []
        for m in nm:
            s = f"- [{m['kind']}] {m['a']} vs {m['b']}. Form: {m['a']} {m['form_a']}; {m['b']} {m['form_b']}. Season avg grade {m['grade_a']} vs {m['grade_b']}."
            if m.get("n"):
                s += f" All-time: {m['n']} meetings, {m['rec']}. Last meeting: {m['last']}. Ugliest beatdown: {m['worst']}."
            else:
                s += " They have never met."
            rows.append(s)
        return bit, ("Next week's matchups (your column previews these; lead with the most important ones, and always "
                     "dredge up the ugliest past beatdown between the two):\n" + "\n".join(rows) +
                     "\nIn the bit field, give your single Upset Alert pick with one line of dread."), None
    if wr["bit"] == "rumor":
        pweeks = [PlayerWeek(L, y, ww) for ww in range(w - 3, w + 1)]
        rm = trade_rumor(L, y, w, pweeks, avoid=state.get("rumor_prev"))
        bit["data"] = rm
        closed = L.S(y).settings.get("trade_end_date")
        note = f" The trade deadline was {closed}, so frame it accordingly (a whisper for the offseason or keeper season)." if closed and nb.stop and nb.stop > closed else ""
        if rm:
            who = ""
            if rm["a_gives"] and rm["b_gives"]:
                who = f" The fit: {rm['a']} sends {rm['a_gives']} to {rm['b']} for {rm['b_gives']}."
            return bit, (f"Trade rumor that actually fits both rosters: {rm['a']} needs {rm['a_needs']}, {rm['b']} needs "
                         f"{rm['b_needs']}. {rm['why']}{who}{note} Pitch it in the bit field as a rumor from your "
                         f"sources. It is speculation, not a real deal."), None
        return bit, "No rumor data this week; in the bit field, tease that your sources have gone quiet.", None
    if wr["bit"] == "rankings":
        rows = power_rankings(L, y, w, nb)
        prev = state.get("rank_prev") or {}
        for r in rows:
            r["prev"] = prev.get(r["m"])
        bit["data"] = {"rows": rows}
        scope = ("every team" if len(rows) == 10 else "the teams still alive in the championship bracket")
        lines = [f"- #{r['rank']} {r['m']}" + (f" (last week #{r['prev']})" if r["prev"] else "") +
                 f": season grade {r['season']}, last 3 weeks {r['last3']}, categories {r['cat']}, weeks {r['wk']}"
                 for r in rows]
        return bit, (f"This week's power rankings, computed from season grade (45%), the last three weeks (35%) and the "
                     f"standings (20%). They cover {scope}:\n" + "\n".join(lines) +
                     "\nWrite one sharp blurb per ranked team in the rankings field. In the bit field, name your "
                     "riser and faller of the week."), None
    if wr["bit"] == "history":
        items = history_items(L, y, w, nb)
        bit["data"] = {"items": items[:8]}
        return bit, ("Material for This Week in Frank Cup History:\n" + "\n".join(f"- {x}" for x in items) +
                     "\nIn the bit field, tell one short historical tale from this material."), None
    if wr["bit"] == "waiver":
        wd = waiver_data(L, y, w, nb)
        bit["data"] = wd
        if not (wd["hitters"] or wd["pitchers"] or wd["two_start"]):
            return bit, ("No free agent data this week. Work from the transactions, waiver hits and drops in the notebook. "
                         "In the bit field, name the best pickup of the week from those."), None
        rows = []
        for k, lbl in (("hitters", "Best available hitters (last week)"), ("pitchers", "Best available pitchers (last week)")):
            if wd[k]:
                rows.append(lbl + ":")
                rows += [f"  - {p['name']} ({p['tm']}, {p['pos']}): {p['line']}; {p.get('own') or '?'}% owned across Yahoo"
                         f"{', trending ' + str(p['delta']) if p.get('delta') not in (None, '', '0', '-') else ''}"
                         f"{', status ' + p['st'] if p.get('st') else ''}" for p in wd[k]]
        if wd["two_start"]:
            rows.append("Two-start pitchers next week:")
            rows += [f"  - {t['who']} ({t['team']}), {t['owner']}, vs {' and '.join(t['vs'])}" for t in wd["two_start"]]
        return bit, ("\n".join(rows) + "\nIn the bit field, name your Pickup of the Week and why, using only these numbers."), None
    return bit, "", None


# ============================================================== daily report (Buck)
def pt_date(ts):
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ts, ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001
        return (dt.datetime.utcfromtimestamp(ts) - dt.timedelta(hours=7)).date().isoformat()


class DailyNotebook:
    def __init__(self, L, y, w, day):
        self.L, self.y, self.w, self.day = L, y, w, day
        rng = L.week_range(y, w)
        self.start, self.stop = rng
        po = L.po_start(y)
        rows = [r for r in L.rows(y) if r["week"] == w]
        if w >= po:
            rows = [r for r in rows if L.in_champ(y, r)]
        self.rows = rows
        self.focus = {m for r in rows for m in (r["a"], r["b"])}
        self.pw = PlayerWeek(L, y, w)
        self.src = sources.load_recent(y, RAW, upto=(dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat(), days=1)
        self.sections = {}
        self.build()

    def build(self):
        L, y, w, day = self.L, self.y, self.w, self.day
        left = (dt.date.fromisoformat(self.stop) - dt.date.fromisoformat(day)).days
        phase = "championship bracket" if w >= L.po_start(y) else "regular season"
        live = []
        for r in self.rows:
            det = cat_detail(L, y, w, r["a"], r["b"])
            close = [f"{d['cat']} {fmt_val(d['cat'], d['a'])}-{fmt_val(d['cat'], d['b'])}" for d in det if d["close"]]
            live.append(f"{r['a']} {r['aw']}-{r['al']}-{r['at']} {r['b']} ({phase}, {left} day(s) left)"
                        + (f"; tight categories: {', '.join(close)}" if close else ""))
        self.sections["Live matchups, current score"] = live
        if self.pw.ok:
            big, bad = [], []
            for x in self.pw.daylog.get(day, []):
                if x["owner"] not in self.focus: continue
                note = PlayerWeek._big_day(x["s"], x["pt"])
                if note:
                    t = f"{x['name']} ({x['tm']}, {x['owner']}){' ON THE BENCH' if x['bench'] else ''}: {note[0]}"
                    (bad if note[2] else big).append((note[1], t))
            if big: self.sections[f"Big days on {day}"] = [t for _, t in sorted(big, reverse=True)[:8]]
            if bad: self.sections[f"Blowups on {day}"] = [t for _, t in sorted(bad, reverse=True)[:5]]
        moves = []
        for t in L.txs(y):
            if t["status"] != "successful" or pt_date(t["ts"]) != day: continue
            for p in t["players"]:
                if t["type"] == "trade":
                    m = L.S(y).mgr.get(p.get("destination_team_key")); verb = "acquired in a trade"
                elif p["type"] == "add":
                    m = L.S(y).mgr.get(p.get("destination_team_key")); verb = "added"
                else:
                    m = L.S(y).mgr.get(p.get("source_team_key")); verb = "dropped"
                if m and m in self.focus: moves.append(f"{m} {verb} {p['name']} ({p.get('pos') or ''})")
        if moves: self.sections[f"League moves on {day}"] = moves
        owners = {}
        if self.pw.ok:
            for r in self.pw.rows():
                if r["owner"] in self.focus: owners[fold(r["name"])] = (r["owner"], r["name"])
        wire = []
        for t in self.src.get("mlb_tx", []) or []:
            o = owners.get(fold(t.get("who")))
            if o:
                tag = " [short leave, not an injury]" if on_leave("", t.get("desc")) else ""
                wire.append(f"{o[0]}'s player: {t['desc']}{tag}")
        for x in self.src.get("espn_injuries", []) or []:
            o = owners.get(fold(x.get("who")))
            if o and x.get("date", "") >= (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat():
                wire.append(f"{x['who']} ({o[0]}): {x.get('status')}{', ' + x['what'] if x.get('what') else ''}"
                            f"{', expected back ' + x['back'] if x.get('back') else ''}")
        for it in self.src.get("feeds", []) or []:
            if it.get("date", "") < day: continue
            txt = fold(it["title"] + " " + it.get("summary", ""))
            hits = [v for k, v in owners.items() if len(k) > 6 and k in txt]
            if hits:
                wire.append(f"[{it['src']}] {it['title']}. {it.get('summary', '')[:200]} (league: {', '.join(f'{h[1]} of {h[0]}' for h in hits[:3])})")
        if wire: self.sections["MLB news involving league players"] = wire[:12]

    def text(self):
        out = [f"THE FRANK CUP MORNING WIRE for {dt.date.fromisoformat(self.day) + dt.timedelta(days=1)}. Covers "
               f"{self.day}, during week {self.w} of the {self.y} season ({self.start} to {self.stop}). "
               f"Scores are categories won-lost-tied so far this week."]
        for k, v in self.sections.items():
            if v:
                out.append(f"\n## {k}")
                out += [f"- {x}" for x in v]
        return "\n".join(out)


DAILY_RULES = """HARD RULES
- Use only facts in the notebook. Never invent stats, scores, injuries or moves.
- 'Benny' and 'Ben' are two different managers. Personal, paternity and family leave are not injuries.
- Keep it PG-13 and about fantasy baseball only. No em dashes. No all-caps sentences or headlines.
- Structure: a punchy open, then short segments in this order when there's material: the big days, the blowups, the moves, the MLB wire, and a quick run through every live matchup's score. Use a short bold tag to start each segment, like **Big Bats**.
- 200 to 350 words. It's a quick morning update, not a column. The Monday Gazette does the deep analysis.
Return only JSON: {"headline": "...", "body": "...", "ledger": "one sentence noting anything worth calling back to"}"""


def write_daily(L, cfg, state, y, w, day):
    if any(x["date"] == day for x in state.get("daily", [])):
        return False
    dn = DailyNotebook(L, y, w, day)
    if not dn.rows:
        print(f"daily {day}: no championship games to cover"); return False
    wr = cfg["daily"]
    prev = [x for x in state.get("daily", []) if x["date"] < day][-3:]
    system = (f"You are {wr['name']}, host of {wr['desk']} for The Frank Cup Gazette, a fantasy baseball league among "
              f"friends.\nVOICE: {wr['voice']}\n\n{DAILY_RULES}\n\n{notes_text(cfg, False)}")
    user = dn.text()
    if prev:
        user += "\n\n# YOUR LAST FEW REPORTS\n" + "\n".join(f"- {x['date']}: \"{x['headline']}\". {x.get('ledger', '')}" for x in prev)
    user += "\n\nDo this morning's report now."
    d = parse_json(ai(system, user))
    state.setdefault("daily", []).append({"date": day, "season": y, "week": w, "writer": wr["id"], "name": wr["name"],
                                          "desk": wr["desk"], "color": wr["color"], "headline": d["headline"],
                                          "body": d["body"], "ledger": d.get("ledger", "")})
    state["daily"] = sorted(state["daily"], key=lambda x: x["date"])[-90:]
    print(f"daily {day}: \"{d['headline']}\"")
    return True


# ============================================================== state
RENAMES = [("Rosie Outlook", "Rosie Callahan"), ("Norm Distribution", "Norm Becker"), ("Seymour Burns", "Sam Kessler"),
           ("Doug Graves", "Doug Mercer"), ("Anonymous Sauce", "Tony Russo"), ("Seymour", "Sam")]


def load_state(cfg=None):
    if not os.path.exists(NEWS_JS):
        return {"issues": [], "ledger": [], "trivia_used": [], "daily": []}
    s = open(NEWS_JS, encoding="utf-8").read()
    st = json.loads(s[s.index("{"):s.rindex("}") + 1])
    if cfg and "names2" not in st.get("migrations", []):
        # the writers got ordinary names; carry old columns and callbacks over
        byid = {w["id"]: w for w in cfg["monday"]}
        def fix(t):
            for a, b in RENAMES:
                t = t.replace(a, b)
            return t
        for i in st.get("issues", []):
            i.setdefault("roster", [a["writer"] for a in i["articles"]])
            for a in i["articles"]:
                w = byid.get(a["writer"])
                if w: a.update(name=w["name"], desk=w["desk"], color=w["color"])
                for k in ("headline", "dek", "body"):
                    a[k] = fix(a.get(k) or "")
                if a.get("bit"):
                    a["bit"]["text"] = fix(a["bit"].get("text") or "")
                    if a["bit"].get("type") == "matchups": a["bit"]["name"] = "Upset Alert"
        for x in st.get("ledger", []):
            x["line"] = fix(x["line"])
            if x["writer"] in byid: x["name"] = byid[x["writer"]]["name"]
        st.setdefault("migrations", []).append("names2")
    return st


def save_state(state):
    state["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(NEWS_JS, "w", encoding="utf-8") as f:
        f.write("window.NEWS = " + json.dumps(state, ensure_ascii=False, separators=(",", ":")) + ";\n")


def excerpt(body, n=60):
    words = re.sub(r"\s+", " ", body).split(" ")
    return " ".join(words[:n]) + ("..." if len(words) > n else "")


def write_issue(L, cfg, state, y, w):
    writers = cfg["monday"]
    iid = f"{y}-{w:02d}"
    nb = Notebook(L, y, w)
    issue = next((i for i in state["issues"] if i["id"] == iid), None)
    if issue is None:
        issue = {"id": iid, "season": y, "week": w, "date": nb.date, "phase": nb.phase, "articles": [],
                 "roster": [x["id"] for x in writers]}
        state["issues"].append(issue)
        state["issues"].sort(key=lambda i: i["id"])
    roster = issue.get("roster") or [x["id"] for x in writers]
    have = {a["writer"] for a in issue["articles"]}
    cody = random.Random(f"cody-{iid}").choice(roster)    # one writer per issue may bring in Cody
    print(f"issue {iid} ({nb.phase}); player data: {'yes' if nb.pw.ok else 'no'}; "
          f"outside news: {'yes' if nb.src else 'no'}; notebook ~{len(nb.text()) // 4} tokens")
    for wr in writers:
        if wr["id"] in have or wr["id"] not in roster: continue
        if time.time() > DEADLINE:
            raise TimeUp()
        bit, feat, trivia_q = feature_for(cfg, wr, nb, state, L)
        own = [dict(season=i["season"], week=i["week"], headline=a["headline"], excerpt=excerpt(a["body"]))
               for i in state["issues"] if i["id"] < iid for a in i["articles"] if a["writer"] == wr["id"]][-2:]
        led = [x for x in state["ledger"] if (x["season"], x["week"]) < (y, w)]
        mine = [x for x in led if x["writer"] == wr["id"]]
        recent = [x for x in led if (x["season"], x["week"]) >= (y, w - 2)]
        pick = {id(x): x for x in mine[-12:] + recent}
        led = sorted(pick.values(), key=lambda x: (x["season"], x["week"]))
        system, user = writer_prompt(cfg, wr, nb, feat, own, led, wr["id"] == cody)
        try:
            d = parse_json(ai(system, user))
        except (NoAI, OutOfAI, TimeUp):
            raise
        except Exception as e:  # noqa: BLE001
            print(f"   {wr['name']}: failed ({e}); will retry next run")
            continue
        bit["text"] = d.get("bit", "")
        if wr["bit"] == "rankings" and isinstance(d.get("rankings"), dict):
            for r in bit["data"]["rows"]:
                r["line"] = d["rankings"].get(r["m"], "")
        issue["articles"].append({"writer": wr["id"], "name": wr["name"], "desk": wr["desk"], "color": wr["color"],
                                  "headline": d["headline"], "dek": d.get("dek", ""), "body": d["body"], "bit": bit})
        order = [x["id"] for x in writers]
        issue["articles"].sort(key=lambda a: order.index(a["writer"]) if a["writer"] in order else 99)
        state["ledger"].append({"season": y, "week": w, "writer": wr["id"], "name": wr["name"],
                                "line": d.get("ledger") or d["headline"]})
        if wr["bit"] == "trivia" and trivia_q:
            state.setdefault("trivia_log", {})[iid] = trivia_q
            state["trivia_open"] = trivia_q
            state.setdefault("trivia_used", []).append(trivia_q["id"])
        if wr["bit"] == "odds" and bit.get("data", {}).get("odds"):
            state["odds_prev"] = bit["data"]["odds"]
        if wr["bit"] == "rumor" and bit.get("data"):
            state["rumor_prev"] = [bit["data"]["a"], bit["data"]["b"]]
        if wr["bit"] == "rankings":
            state["rank_prev"] = {r["m"]: r["rank"] for r in bit["data"]["rows"]}
        print(f"   {wr['name']}: \"{d['headline']}\"")
        save_state(state)
        if not os.environ.get("NEWS_FAKE_AI"):
            time.sleep(int(os.environ.get("NEWS_PAUSE", "13")))   # free tier allows 5 a minute
    state["ledger"] = state["ledger"][-400:]
    return issue


def redo_latest(state):
    last = state["issues"].pop()
    state["ledger"] = [x for x in state["ledger"] if (x["season"], x["week"]) != (last["season"], last["week"])]
    # roll the weekly features back to where they stood before that issue
    log = state.get("trivia_log", {})
    gone = log.pop(last["id"], None)
    if gone and gone["id"] in state.get("trivia_used", []): state["trivia_used"].remove(gone["id"])
    prev = state["issues"][-1] if state["issues"] else None
    state["trivia_open"] = log.get(prev["id"]) if prev else None
    state["odds_prev"] = state["rumor_prev"] = state["rank_prev"] = None
    for a in (prev or {}).get("articles", []):
        dd = (a.get("bit") or {}).get("data") or {}
        t = (a.get("bit") or {}).get("type")
        if t == "odds": state["odds_prev"] = dd.get("odds")
        if t == "rumor": state["rumor_prev"] = [dd["a"], dd["b"]] if dd else None
        if t == "rankings": state["rank_prev"] = {r["m"]: r["rank"] for r in dd.get("rows", [])}
    print("rewriting", last["id"])


def main():
    sys.stdout.reconfigure(line_buffering=True)   # show progress live in the Actions log
    cfg = json.load(open(os.path.join(HERE, "writers.json"), encoding="utf-8"))
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("NEWS_FAKE_AI")):
        print("No GEMINI_API_KEY secret yet, so no news this run.")
        return
    L = League()
    state = load_state(cfg)
    y = L.seasons()[-1]
    done = L.completed_weeks(y)
    redo = os.environ.get("NEWS_REDO", "")
    if "latest" in redo and state["issues"]:
        redo_latest(state)
    if "daily" in redo and state.get("daily"):
        gone = state["daily"].pop()
        print("rewriting daily", gone["date"])
    try:
        # 1) the Monday issue for any finished week that doesn't have one yet
        def complete(i):
            return set(i.get("roster") or [a["writer"] for a in i["articles"]]) <= {a["writer"] for a in i["articles"]}
        if done:
            if not state["issues"]:
                todo = done[-BACKFILL:]
            else:
                mine = [i for i in state["issues"] if i["season"] == y]
                latest = max((i["week"] for i in mine), default=0)
                todo = sorted({w for w in done if w > latest} | {i["week"] for i in mine if not complete(i)})
            for w in todo:
                write_issue(L, cfg, state, y, w)
        # 2) the morning wire for yesterday, Tuesday through Sunday
        day = players.yesterday_pt()
        today = dt.date.fromisoformat(day) + dt.timedelta(days=1)
        if today.weekday() != 0 or os.environ.get("NEWS_DAILY_ANYDAY"):
            wr = build.week_ranges(L.S(y))
            wk = next((ww for ww, (a, b) in wr.items() if a <= day <= b), None)
            if wk is None:
                print(f"daily {day}: not a fantasy game day")
            else:
                if time.time() > DEADLINE: raise TimeUp()
                write_daily(L, cfg, state, y, wk, day)
    except OutOfAI:
        print("Gemini is used up or unavailable for now; the rest will be written next run.")
    except TimeUp:
        print("Time budget reached; the rest will be written next run.")
    except NoAI:
        print("No AI key.")
    save_state(state)
    n = sum(len(i["articles"]) for i in state["issues"])
    print(f"{n} articles and {len(state.get('daily', []))} daily reports on file.")


if __name__ == "__main__":
    main()
