import asyncio, json, os, ssl, sys
import edge_tts, edge_tts.communicate as c
c._SSL_CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
V=sys.argv[1]; lines=json.load(open(f"{V}/lines.json"))
SAY={"CPI":"ຊີພີໄອ","PPI":"ພີພີໄອ","Buy":"ບາຍ","Sell":"ເຊວ","Stop Loss":"ສະຕັອບລອສ","Lot":"ລັອດ","…":", ","15 ຫາ 30":"ສິບຫ້າ ຫາ ສາມສິບ"}
async def main():
    for i,(_,_,t) in enumerate(lines):
        s=t
        for k,v in SAY.items(): s=s.replace(k,v)
        out=f"{V}/tts/{i:02d}.mp3"
        if os.path.exists(out) and os.path.getsize(out)>0: continue
        await edge_tts.Communicate(s,"lo-LA-ChanthavongNeural",rate="+8%",proxy=os.environ.get("HTTPS_PROXY")).save(out)
        print(i,flush=True)
asyncio.run(main())
