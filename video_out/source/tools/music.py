import json,sys,numpy as np,soundfile as sf
from scipy.signal import butter,sosfilt
W=sys.argv[1]; SR=48000
T=json.load(open(W+'/timeline.json')); D=T['duration']; N=int(D*SR)
turn=[s for s in T['scenes'] if s['id']=='turn'][0]['start']
BPM=96; beat=60/BPM; bar=4*beat
rng=np.random.default_rng(7)
def m2f(m): return 440*2**((m-69)/12)
def lp(x,fc,o=2): return sosfilt(butter(o,fc,'low',fs=SR,output='sos'),x)
def hp(x,fc,o=2): return sosfilt(butter(o,fc,'high',fs=SR,output='sos'),x)
def saw(f,n,det=0):
    t=np.arange(n)/SR; out=np.zeros(n)
    for d in ([-det,0,det] if det else [0]):
        ph=(t*f*2**(d/1200)+rng.random())%1; out+=2*ph-1
    return out/(3 if det else 1)
out_pad=np.zeros(N); out_bass=np.zeros(N); out_arp=np.zeros(N)
dark=[[57,60,64],[53,57,60],[50,53,57],[52,56,59]]   # Am F Dm E
light=[[48,52,55],[55,59,62],[57,60,64],[53,57,60]]  # C G Am F
nb=int(np.ceil(D/bar))
for b in range(nb):
    t0=b*bar; chords=dark if t0<turn else light
    ch=chords[b%4]; i0=int(t0*SR); n=min(int(bar*SR),N-i0)
    if n<=0: break
    env=np.minimum(1,np.arange(n)/(0.4*SR))*np.minimum(1,(n-np.arange(n))/(0.3*SR))
    p=sum(saw(m2f(m),n,9) for m in ch)/3
    out_pad[i0:i0+n]+=p*env
    # bass 8ths, root -24
    root=ch[0]-24
    for k in range(8):
        s=int((t0+k*beat/2)*SR); L=int(beat/2*SR*0.9)
        if s+L>N: break
        e=np.exp(-np.arange(L)/(0.12*SR))
        out_bass[s:s+L]+=saw(m2f(root),L)*e
    # arp 16ths after turn-ish (and soft before)
    seq=[ch[0]+12,ch[1]+12,ch[2]+12,ch[1]+12]
    for k in range(16):
        s=int((t0+k*beat/4)*SR); L=int(beat/4*SR)
        if s+L>N: break
        e=np.exp(-np.arange(L)/(0.05*SR))
        out_arp[s:s+L]+=np.sign(np.sin(2*np.pi*m2f(seq[k%4])*np.arange(L)/SR))*e*0.5
pad=lp(out_pad,1400)*0.22; bass=lp(out_bass,380)*0.35; arp=lp(out_arp,2600)*0.08
kick,_=sf.read(W+'/sfx/kick.wav',dtype='float64'); hat,_=sf.read(W+'/sfx/hat.wav',dtype='float64')
if kick.ndim>1: kick=kick.mean(1)
if hat.ndim>1: hat=hat.mean(1)
drums=np.zeros(N)
def put(x,t,g):
    s=int(t*SR); e=min(N,s+len(x));
    if s<N: drums[s:e]+=x[:e-s]*g
t=0
while t<D:
    bi=int(t/beat)
    if bi%2==0: put(kick,t,0.55)
    for k in range(4): put(hat,t+k*beat/4,0.10 if k%2 else 0.16)
    t+=beat
# sidechain duck from kick
sc=np.ones(N)
t=0
while t<D:
    if int(t/beat)%2==0:
        s=int(t*SR); L=min(int(0.3*SR),N-s); sc[s:s+L]=1-0.6*np.exp(-np.arange(L)/(0.08*SR))
    t+=beat
# arrangement: arp only after turn-ish (and from 0 at low level), intro filter
arp_env=np.where(np.arange(N)/SR<turn,0.4,1.0)
mix=(pad+bass)*sc+arp*arp_env+drums
# no drums in the first 0.7 s, fade out end
tt=np.arange(N)/SR
mix*=np.clip((D-tt)/3.0,0,1)
mix=hp(mix,30)
mix/=np.max(np.abs(mix))*1.12
st=np.stack([mix,mix],1)
# fake width: delay pad slightly on right
st[:,1]=np.roll(st[:,1],int(0.012*SR))
sf.write(W+'/music.wav',st.astype(np.float32),SR)
print('ok',D)
