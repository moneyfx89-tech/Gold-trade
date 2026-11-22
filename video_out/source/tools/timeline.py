import json,sys,numpy as np,soundfile as sf
W=sys.argv[1]; SR=48000
S=json.load(open(W+'/script.json'))
t=0.0; voice=[]; scenes=[]
def silence(d): return np.zeros(int(round(d*SR)),dtype=np.float32)
for si,s in enumerate(S):
    lead=0.7 if si==0 else 0.4
    st=t; voice.append(silence(lead)); t+=lead; chunks=[]
    for ci,(tt,disp) in enumerate(s['chunks']):
        a,_=sf.read(f"{W}/tts/{si:02d}_{ci}.wav",dtype='float32')
        chunks.append({'start':round(t,3),'end':round(t+len(a)/SR,3),'text':disp})
        voice.append(a); t+=len(a)/SR
        g=0.22 if ci<len(s['chunks'])-1 else (2.8 if si==len(S)-1 else 0.3)
        voice.append(silence(g)); t+=g
    scenes.append({'id':s['id'],'start':round(st,3),'end':round(t,3),'chunks':chunks})
v=np.concatenate(voice)
sf.write(W+'/voice.wav',v,SR)
json.dump({'duration':round(t,3),'scenes':scenes},open(W+'/timeline.json','w'),ensure_ascii=False,indent=1)
print('total',round(t,2)); [print(s['id'],s['start'],s['end']) for s in scenes]
