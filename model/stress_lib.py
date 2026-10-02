"""Shared helpers for the stress tests: move the model's clock back, and score a real season."""
import datetime as dt, json, os, collections
import numpy as np
import talent, value27 as V
from model import norm

REPO = '/home/claude/frank-cup'
DEFAULTS = {k: getattr(talent, k) for k in ('SEASONS', 'DUR_W', 'MILB_W', 'AGE_DATE', 'AGE_ON', 'PEDIGREE_ON', 'PRIOR_PA', 'PRIOR_BF',
                                            'OUT_PRIOR_SP', 'OUT_PRIOR_RP', 'PAG_PRIOR', 'FIELD_PRIOR_A', 'FIELD_PRIOR_E', 'SEASON_27',
                                            'IL_END', 'LT_FROM', 'PIPE_EXCLUDE', 'PIPE_REC', 'MILB_DISC', 'MILB_DISC_P', 'DUR_K0', 'DUR_V2', 'CARRY_ON', 'PED_RATE', 'PED_SHARE')}


_QS = V.qs_model


def reset():
    for k, v in DEFAULTS.items(): setattr(talent, k, v)
    V._YQS = None


def as_of(target, **over):
    """Set the clock to the October before `target`: only data a manager had then."""
    reset()
    y = target - 1
    talent.SEASONS = {y: 5, y - 1: 4, y - 2: 3}
    talent.MILB_W = {yy: w for yy, w in ((y, 5), (y - 1, 4)) if os.path.exists(f'{talent.H}/milb/{yy}_AAA_hitting.json')}
    talent.AGE_DATE = dt.date(target, 7, 1)
    talent.DUR_W = {yy: w for yy, w in zip(range(y, y - 5, -1), (5, 4, 3, 2, 1)) if yy >= 2022}
    talent.IL_END = y
    talent.LT_FROM = dt.date(y - 1, 10, 1)
    talent.SEASON_27 = (dt.date(target, 3, 25), dt.date(target, 9, 26))
    talent.PIPE_EXCLUDE = {'current'} | {f'preseason_{yy}' for yy in range(target, 2030)}
    talent.PIPE_REC = {f'preseason_{y}': 1.0, f'preseason_{y - 1}': 0.7}
    for k, v in over.items(): setattr(talent, k, v)


def project(target, teams=10, context=2026, team_ctx=False, post=None, **over):
    as_of(target, **over)
    T, _ = talent.build(); talent.durability(T)
    if team_ctx: talent.team_context(T)
    talent.pedigree(T); talent.fielding(T)
    if post: post(T)
    V.set_context(context)
    pool, meta = V.run(T, teams=teams)
    return pool, meta, T


def actual(year, weeks=26.7, teams=10):
    """What really happened: each player's real season total, valued by the same engine."""
    reset()
    talent.SEASONS = {year: 1}; talent.MILB_W = {}; talent.PRIOR_PA = talent.PRIOR_BF = 1
    talent.AGE_ON = False; talent.PEDIGREE_ON = False; talent.AGE_DATE = dt.date(year, 7, 1)
    talent.OUT_PRIOR_SP = talent.OUT_PRIOR_RP = talent.PAG_PRIOR = 0.001
    talent.FIELD_PRIOR_A = talent.FIELD_PRIOR_E = 0.001
    T, _ = talent.build(); talent.fielding(T)
    V.set_context(2026)
    V._YQS = None; qb = _QS(); keep = V.qs_model
    V.qs_model = lambda: qb
    if year != 2026: V._YQS = {}            # Yahoo quality starts are only on hand for 2026; model them otherwise
    rev, meta = V.run(T, actual_weeks=weeks, teams=teams,
                      pool_filter=lambda p: (p['pa_y0'] >= 30) if p['role'] == 'H' else (p['g_y0'] >= 5))
    V.qs_model = keep
    reset()
    return rev, meta


def key(p): return ('H' if p['role'] == 'H' else 'P', p['id'])
def nkey(p): return ('H' if p['role'] == 'H' else 'P', norm(p['name']))


def flat(b):
    o = {}
    for x in b:
        if isinstance(x, dict): o.update(x)
    return o


def draft(year):
    """league draft: (side, normalized name) -> (pick, round, kept)"""
    d = json.load(open(f'{REPO}/raw/{year}/draft_results.json'))['fantasy_content']['league'][1]['draft_results']
    out = {}
    for i in range(d['count']):
        x = d[str(i)]['draft_result']; info = flat(x['0']['players']['0']['player'][0])
        k = ('H' if info.get('position_type') == 'B' else 'P', norm(info['name']['full']))
        out[k] = (int(x['pick']), int(x['round']), bool((info.get('is_keeper') or {}).get('kept')), info['name']['full'])
    return out
