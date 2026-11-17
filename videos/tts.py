"""Usage: tts.py VOICE RATE TEXT OUT.mp3 [OUT.json]  -- edge-tts via proxy CA bundle, saves word timings."""
import sys, ssl, json, asyncio, edge_tts, edge_tts.communicate as c
c._SSL_CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
voice, rate, text, out = sys.argv[1:5]
async def main():
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(out, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio": f.write(ch["data"])
            elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
                words.append({"t": ch["offset"]/1e7, "d": ch["duration"]/1e7, "w": ch["text"]})
    if len(sys.argv) > 5: json.dump(words, open(sys.argv[5], "w"), ensure_ascii=False)
asyncio.run(main())
