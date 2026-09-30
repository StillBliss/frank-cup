import json, os, glob, datetime as dt
RAW='/home/claude/frank-cup/raw'
IDS={'7':'R','11':'3B','12':'HR','13':'RBI','16':'SB','18':'BB','52':'A','53':'E','3':'AVG','55':'OPS','61':'XBH',
 '50':'IP','28':'W','29':'L','30':'CG','32':'SV','42':'K','48':'HLD','26':'ERA','27':'WHIP','56':'KBB','83':'QS'}
def ip(v):
    a,_,b=v.partition('.'); return int(a)+(int(b or 0))/3
def load(years=None):
    rows=[]
    files = sorted(glob.glob(RAW+'/*/scoreboard/week_*.json'))
    if years is not None:
        files = sorted(glob.glob(RAW+'/*/scoreboard/week_*.json') + glob.glob(RAW+'_redraft/*/scoreboard/week_*.json'))
        files = [f for f in files if int(f.split('/')[-3]) in years]
    for f in files:
        yr=f.split('/')[-3]
        L=json.load(open(f))['fantasy_content']['league']
        sb=L[1]['scoreboard']['0']['matchups']
        for k,v in sb.items():
            if k=='count': continue
            m=v['matchup']
            if m.get('is_playoffs')=='1' or m.get('is_consolation')=='1' or m.get('status')!='postevent': continue
            sw={x['stat_winner']['stat_id']:x['stat_winner'].get('winner_team_key','TIE') for x in m.get('stat_winners',[])}
            s,e=m['week_start'],m['week_end']
            days=(dt.date.fromisoformat(e)-dt.date.fromisoformat(s)).days+1
            teams=[]
            for tk in ('0','1'):
                t=m['0']['teams'][tk]['team']
                st={}
                for x in t[1]['team_stats']['stats']:
                    i,val=x['stat']['stat_id'],x['stat']['value']
                    if i=='60':
                        h,ab=val.split('/'); st['H']=float(h or 0); st['AB']=float(ab or 0)
                    elif i in IDS:
                        n=IDS[i]
                        st[n]=ip(val) if n=='IP' else float(val) if val not in ('','-') else None
                teams.append(dict(sw=sw,year=yr,week=int(m['week']),days=days,key=t[0][0]['team_key'],**st))
            rows.append(teams)
    return rows
if __name__=='__main__':
    r=load(); print(len(r),'matchups')
    import collections
    c=collections.Counter((t[0]['year'],t[0]['days']) for t in r); print(sorted(c.items()))
    print(r[0][0])
