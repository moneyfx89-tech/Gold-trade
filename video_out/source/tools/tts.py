import json,asyncio,subprocess,sys,os
import edge_tts, ssl, edge_tts.communicate as _c
_c._SSL_CTX=ssl.create_default_context(cafile='/root/.ccr/ca-bundle.crt')
W=sys.argv[1]; V=sys.argv[2] if len(sys.argv)>2 else 'lo-LA-ChanthavongNeural'
S=json.load(open(W+'/script.json')); os.makedirs(W+'/tts',exist_ok=True)
def dur(f): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]))
async def main():
  for si,s in enumerate(S):
    for ci,(t,d) in enumerate(s['chunks']):
      f=f"{W}/tts/{si:02d}_{ci}.mp3"
      if not os.path.exists(f): await edge_tts.Communicate(t,V,rate='+6%',pitch='-2Hz').save(f)
asyncio.run(main())
# trim silence and measure
for si,s in enumerate(S):
  for ci,_ in enumerate(s['chunks']):
    f=f"{W}/tts/{si:02d}_{ci}.mp3"; g=f[:-4]+'.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-i',f,'-af','silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse','-ar','48000','-ac','1',g],check=True)
    print(si,ci,round(dur(g),2))
