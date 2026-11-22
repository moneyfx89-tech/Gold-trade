import json,sys,numpy as np,soundfile as sf
W=sys.argv[1];SR=48000
T=json.load(open(W+'/timeline.json'));D=T['duration'];N=int(D*SR)+SR
def load(n):
    a,sr=sf.read(f'{W}/sfx/{n}.wav',dtype='float64'); a=a.mean(1) if a.ndim>1 else a; assert sr==SR; return a
fx={k:load(k) for k in ['whoosh','impact','subdrop','riser','tick','popin','sting','glitch']}
sfx=np.zeros(N)
def put(n,t,db):
    x=fx[n]*10**(db/20); s=int(max(0,t)*SR); e=min(N,s+len(x)); sfx[s:e]+=x[:e-s]
sc={s['id']:s for s in T['scenes']}
def C(i,k): return sc[i]['chunks'][k]['start']
def st(i): return sc[i]['start']
for s in T['scenes'][1:]:
    put('whoosh',s['start']-0.3,-8)
put('glitch',0.02,-10); put('impact',st('hook')+1.05,-4); put('subdrop',st('hook')+1.1,-6)
put('popin',st('peak')+.05,-10)
for t in np.arange(st('peak')+.3,C('peak',1)+.9,0.075): put('tick',t,-16)
put('subdrop',C('now',1)-.05,-6)
for t in np.arange(C('now',1),C('now',1)+1.1,0.075): put('tick',t,-16)
put('impact',st('q')+.15,-7)
put('popin',st('fed')+.05,-10); put('popin',C('fed',2)-.1,-10)
put('popin',st('usd')+.05,-10); put('popin',C('usd',1)-.1,-10)
put('glitch',st('ai')+.3,-11); put('popin',C('ai',1)-.05,-10)
put('riser',st('turn')-2.0,-12); put('impact',st('turn')+.1,-5)
for t in np.arange(st('cb')+.3,C('cb',0)+3.2,0.09): put('tick',t,-18)
put('popin',C('cb',1)-.05,-8); put('popin',C('cb',2)-.1,-10)
for t in np.arange(st('etf')+.2,C('etf',1)+1,0.09): put('tick',t,-18)
put('impact',C('etf',2)-.1,-9)
put('popin',st('lao')+.1,-10)
for k in range(1,4): put('popin',C('watch',k)-.1,-9)
put('impact',st('end')+.05,-6); put('popin',C('end',1)-.1,-9); put('popin',C('end',2)-.1,-9); put('popin',C('end',3)-.1,-9)
put('sting',C('end',3)+2.2-.45,-5)
v,_=sf.read(W+'/voice.wav',dtype='float64'); voice=np.zeros(N); voice[:len(v)]=v
m,_=sf.read(W+'/music.wav',dtype='float64'); music=np.zeros((N,2)); music[:len(m)]=m
# duck music under voice
env=np.abs(voice); k=int(0.05*SR); from scipy.ndimage import uniform_filter1d as uf
env=uf(env,k)
act=(env>0.01).astype(float); k2=int(0.25*SR); act=uf(act,k2)
duck=10**((-9*np.clip(act,0,1))/20)
mus_gain=10**(-15/20)
out=np.zeros((N,2))
out+=music*(mus_gain*duck)[:,None]
out+=(voice*1.0)[:,None]
out+=(sfx*0.55)[:,None]
out=out[:int((D+0.05)*SR)]
sf.write(W+'/mix_raw.wav',out.astype(np.float32),SR)
print('ok')
