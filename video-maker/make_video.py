"""สร้างคลิปแนวตั้ง "ແຜນເທຣດຄຳປະຈຳວັນ" ภาษาลาว จากไฟล์ตอน (episode JSON)

ขั้นตอน: ดึงราคาทอง -> วาดทุกช็อตเป็นภาพ (Playwright) -> พากย์ลาว (Edge TTS) -> รวมเป็น MP4 (ffmpeg)

ใช้งาน:
    python make_video.py episodes/2026-11-16.json --fetch      # ดึงราคาล่าสุดแล้วทำคลิป
    python make_video.py episodes/2026-11-16.json              # ใช้ราคาที่ดึงไว้แล้วใน data/
    python make_video.py ... --only 3                          # เรนเดอร์แค่ภาพช็อตที่ 3 (ไว้เช็กหน้าตา)
    python make_video.py ... --music bgm.mp3                   # ใส่เพลงพื้นหลัง (เบา ๆ)
"""
import argparse
import asyncio
import json
import math
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
TZ = "Asia/Vientiane"
TF_NAME = {"4h": ("4H", "ກຣາຟ 4 ຊົ່ວໂມງ"), "1h": ("1H", "ກຣາຟ 1 ຊົ່ວໂມງ"), "15m": ("15M", "ກຣາຟ 15 ນາທີ")}
CA = "/root/.ccr/ca-bundle.crt"


# ---------------------------------------------------------------- data
def fetch(symbol: str) -> None:
    """ดึงแท่ง 15 นาทีย้อนหลัง 60 วัน แล้วสร้างแท่ง 1H / 4H เอง (เวลาลาว)"""
    import yfinance as yf
    if os.path.exists(CA):
        os.environ.setdefault("CURL_CA_BUNDLE", CA)
        os.environ.setdefault("SSL_CERT_FILE", CA)
    d = yf.download(symbol, period="60d", interval="15m", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d.index = d.index.tz_convert(TZ)
    d = d[["Open", "High", "Low", "Close"]].dropna()
    DATA.mkdir(exist_ok=True)
    d.to_csv(DATA / "15m.csv")
    d.resample("1h").agg(AGG).dropna().to_csv(DATA / "1h.csv")
    d.resample("4h").agg(AGG).dropna().to_csv(DATA / "4h.csv")
    print(f"fetched {symbol}: last {d.index[-1]} close {d.iloc[-1].Close:.1f}")


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{tf}.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(TZ)
    return df


# ---------------------------------------------------------------- chart spec
def nice_ticks(lo: float, hi: float) -> list[float]:
    span = hi - lo
    step = next(s for s in (2, 5, 10, 20, 25, 50, 100, 200) if span / s <= 9)
    first = math.ceil(lo / step) * step
    return [first + k * step for k in range(int((hi - first) // step) + 1)]


class Window:
    def __init__(self, df: pd.DataFrame):
        self.df, self.n = df, len(df)

    def _rng(self, spec: str) -> pd.DataFrame:
        a, _, b = spec.partition("|")
        return self.df.loc[a: b or a] if b else self.df.loc[a]

    def x(self, v):
        """ตำแหน่งแท่ง: int, "+N" (อนาคต), "t:เวลา", "hi:ช่วง", "lo:ช่วง" """
        if isinstance(v, (int, float)):
            return v if v >= 0 else self.n + v
        if v.startswith("+"):
            return self.n - 1 + float(v[1:])
        kind, _, spec = v.partition(":")
        if kind == "t":
            return int(self.df.index.searchsorted(pd.Timestamp(spec, tz=TZ), side="right") - 1)
        sub = self._rng(spec)
        ts = sub["High"].idxmax() if kind == "hi" else sub["Low"].idxmin()
        return int(self.df.index.get_loc(ts))

    def y(self, v, xspec=None):
        if isinstance(v, (int, float)):
            return v
        if v in ("hi", "lo"):   # ใช้ราคา High/Low ของแท่งที่ x ชี้
            return float(self.df.iloc[int(self.x(xspec))]["High" if v == "hi" else "Low"])
        raise ValueError(v)


def chart_spec(c: dict) -> dict:
    df = load(c["tf"])
    df = df.loc[c["from"]:c.get("to")] if c.get("from") else df.tail(c.get("bars", 80))
    w = Window(df)
    ann, ys = [], []
    for a in c.get("ann", []):
        a = dict(a)
        if "at" in a:                                   # pill วางที่ High/Low ของแท่ง
            a["x"] = w.x(a["at"])
            a["y"] = w.y("hi" if a["at"].startswith("hi") else "lo", a["at"]) if "y" not in a else a["y"]
            a.setdefault("pos", "above" if a["at"].startswith("hi") else "below")
        for k in ("x", "x1", "x2", "lx", "from"):
            if k in a:
                a[k] = w.x(a[k])
        if "pts" in a:
            a["pts"] = [[w.x(p[0]), w.y(p[1], p[0])] for p in a["pts"]]
            ys += [p[1] for p in a["pts"]]
        ys += [a[k] for k in ("y", "y1", "y2") if k in a]
        ann.append(a)
    lo = min(df["Low"].min(), *ys) if ys else df["Low"].min()
    hi = max(df["High"].max(), *ys) if ys else df["High"].max()
    pad = (hi - lo) * 0.09
    lo, hi = c.get("ymin", lo - pad), c.get("ymax", hi + pad)
    # ป้ายแกนเวลา
    xl, last = [], None
    for i, ts in enumerate(df.index):
        if c["tf"] == "15m":
            if ts.minute == 0 and ts.hour % c.get("hourStep", 3) == 0:
                xl.append({"i": i, "t": ts.strftime("%H:%M")})
        elif ts.date() != last:
            last = ts.date()
            if i >= 2 and (not xl or i - xl[-1]["i"] >= len(df) / 9):
                xl.append({"i": i, "t": str(ts.day)})
    tf, name = TF_NAME[c["tf"]]
    return {
        "tf": tf, "tfName": name, "tfSub": c.get("sub", ""),
        "bars": df[["Open", "High", "Low", "Close"]].round(2).values.tolist(),
        "padRight": c.get("padRight", 8), "ymin": lo, "ymax": hi,
        "ticks": nice_ticks(lo, hi), "xlabels": xl, "ann": ann,
    }


# ---------------------------------------------------------------- render
async def render_frames(ep: dict, out: Path, only: int | None) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH") or ("/opt/pw-browsers/chromium" if os.path.isfile("/opt/pw-browsers/chromium") else None)
        b = await p.chromium.launch(executable_path=exe) if exe else await p.chromium.launch()
        page = await b.new_page(viewport={"width": 1080, "height": 1920})
        await page.goto((HERE / "template.html").as_uri())
        await page.evaluate("document.fonts.ready")
        for i, s in enumerate(ep["shots"], 1):
            if only and i != only:
                continue
            shot = {**ep["common"], **s}
            if s.get("chart"):
                shot["kind"] = "chart"
                shot["chart"] = chart_spec(s["chart"])
            shot.setdefault("kind", "chart")
            await page.evaluate("s => window.renderShot(s)", shot)
            await page.evaluate("document.fonts.ready")
            await page.screenshot(path=str(out / f"shot{i:02d}.png"))
        await b.close()


def voice_text(t: str) -> str:
    # ให้ TTS อ่านตัวเลขเป็นจำนวนเต็ม ไม่อ่านเครื่องหมายจุลภาค
    return re.sub(r"(?<=\d),(?=\d{3})", "", t)


async def tts(ep: dict, out: Path) -> None:
    import certifi
    if os.path.exists(CA):
        certifi.where = lambda: CA   # proxy ของเครื่องนี้ใช้ CA ของตัวเอง
    import edge_tts
    v = ep.get("voice", {})
    for i, s in enumerate(ep["shots"], 1):
        f = out / f"vo{i:02d}.mp3"
        if not f.exists():
            await edge_tts.Communicate(voice_text(s["say"]), v.get("name", "lo-LA-ChanthavongNeural"),
                                       rate=v.get("rate", "+8%")).save(str(f))


def dur(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def assemble(ep: dict, out: Path, final: Path, music: str | None) -> None:
    gap = ep.get("voice", {}).get("gap", 0.22)
    lst, alist, srt, t = [], [], [], 0.0
    for i, s in enumerate(ep["shots"], 1):
        vo = out / f"vo{i:02d}.mp3"
        d = dur(vo) + gap + s.get("hold", 0)
        wav = out / f"seg{i:02d}.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(vo), "-af", f"apad=whole_dur={d}",
                        "-ar", "44100", "-ac", "2", str(wav)], check=True)
        lst.append(f"file '{out / f'shot{i:02d}.png'}'\nduration {d:.3f}")
        alist.append(f"file '{wav}'")
        srt.append(f"{i}\n{srt_time(t)} --> {srt_time(t + d - gap)}\n{s['say']}\n")
        t += d
    lst.append(f"file '{out / f'shot{len(ep['shots']):02d}.png'}'")
    (out / "v.txt").write_text("\n".join(lst))
    (out / "a.txt").write_text("\n".join(alist))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(out / "a.txt"),
                    str(out / "voice.wav")], check=True)
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(out / "v.txt"),
           "-i", str(out / "voice.wav")]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                "[2:a]volume=0.12[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)]
    subprocess.run(cmd, check=True)
    final.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"done: {final} ({t:.1f}s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--only", type=int)
    ap.add_argument("--music")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    ep = json.loads(Path(a.episode).read_text(encoding="utf-8"))
    if a.fetch:
        fetch(ep.get("symbol", "GC=F"))
    work = Path(a.out) / Path(a.episode).stem
    work.mkdir(parents=True, exist_ok=True)
    asyncio.run(render_frames(ep, work, a.only))
    if a.only:
        print(f"frame: {work / f'shot{a.only:02d}.png'}")
        return
    asyncio.run(tts(ep, work))
    final = Path(a.out) / f"{Path(a.episode).stem}.mp4"
    assemble(ep, work, final, a.music)
    if ep.get("caption"):
        final.with_suffix(".caption.txt").write_text(ep["caption"], encoding="utf-8")


if __name__ == "__main__":
    main()
