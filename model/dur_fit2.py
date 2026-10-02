import pickle, numpy as np, re, collections
rows = pickle.load(open('dur_rows.pkl','rb'))
ELB = re.compile(r'elbow|forearm|ucl|ulnar|tommy john|flexor', re.I)
def fit(train):
    par = {}
    Hh = [r for r in train if r['g']=='healthy']
    for role in ('H','SP','RP'):
        rs = [r for r in Hh if r['role']==role]; tgt = 1-np.mean([r['act'] for r in rs]); best=None
        for k0 in (2,4,6,8,12,20,40):
            lo,hi=0,0.9
            for _ in range(40):
                mid=(lo+hi)/2
                if np.mean([min(.6,(r['num']+k0*mid)/(r['den']+k0)) for r in rs])<tgt: lo=mid
                else: hi=mid
            mse=np.mean([(1-min(.6,(r['num']+k0*mid)/(r['den']+k0))-r['act'])**2 for r in rs])
            if best is None or mse<best[0]-1e-5: best=(mse,k0,mid)
        par[role]=(best[1],best[2])
    for g in ('H_short','H_long','P15_short','P15_long','P60elbow_late','P60elbow_early','P60other'):
        rs=[r for r in train if r['g']==g]
        par[g]=np.mean([r['act'] for r in rs])/np.mean([base(r,par) for r in rs])
    return par
def base(r,par):
    k0,lg=par[r['role']]; return 1-min(.6,(r['num']+k0*lg)/(r['den']+k0))
def pred(r,par): return base(r,par)*(par[r['g']] if r['g']!='healthy' else 1)
full=fit(rows); print('fit on all three seasons:', {k:(tuple(round(float(x),3) for x in v) if isinstance(v,tuple) else round(float(v),2)) for k,v in full.items()})
new=[];old=[];con=[]
for t in (2024,2025,2026):
    par=fit([r for r in rows if r['t']!=t]); te=[r for r in rows if r['t']==t]
    cm={role:np.mean([r['act'] for r in rows if r['t']!=t and r['role']==role]) for role in ('H','SP','RP')}
    for r in te: new.append((pred(r,par),r)); old.append((r['pred'],r)); con.append((cm[r['role']],r))
    print(t,{k:(v[0] if isinstance(v,tuple) else round(float(v),2)) for k,v in par.items()})
def rep(lab,xs):
    out=[]
    for role in ('H','SP','RP'):
        e=[(p-r['act']) for p,r in xs if r['role']==role]
        out.append(f"{role}: bias {np.mean(e):+.3f} avg miss {np.mean(np.abs(e)):.3f} rmse {np.sqrt(np.mean(np.square(e))):.3f}")
    print(f'{lab:22s}', '   '.join(out))
rep('current board',old); rep('everyone the same',con); rep('refit (held-out year)',new)
for role in ('H','SP','RP'):
    xs=[(p,r) for p,r in new if r['role']==role]; pr=np.array([p for p,_ in xs]); ac=np.array([r['act'] for _,r in xs])
    qs=np.quantile(pr,[0,.1,.3,.7,1]); print(role,'  '.join(f'pred {pr[(pr>=a)&(pr<=b)].mean():.2f} actual {ac[(pr>=a)&(pr<=b)].mean():.2f} (n={((pr>=a)&(pr<=b)).sum()})' for a,b in zip(qs[:-1],qs[1:])))
