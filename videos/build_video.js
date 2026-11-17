// สร้างวิดีโอเล่าเรื่องแนวตั้ง 1080x1920 พร้อมเสียงพากย์ AI ภาษาลาว
// ใช้: node videos/build_video.js videos/rule-1pct [voice]
// ต้องมี: playwright, ffmpeg, python3 + edge-tts (เรียกผ่าน TTS_SCRIPT)
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const dir = path.resolve(process.argv[2]);
const voice = process.argv[3] || 'lo-LA-ChanthavongNeural';
const rate = process.env.TTS_RATE || '-4%';
const tts = process.env.TTS_SCRIPT;
const work = process.env.WORK_DIR || path.join(dir, '.build');
const FPS = 30, W = 1080, H = 1920, PAD = 0.55;
const scenes = JSON.parse(fs.readFileSync(path.join(dir, 'scenes.json'), 'utf8'));
fs.mkdirSync(work, { recursive: true });

const dur = f => parseFloat(execFileSync('ffprobe', ['-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString());

// 1) เสียงพากย์ทีละฉาก
scenes.forEach((s, i) => {
  s.audio = path.join(work, `a${i}.mp3`);
  if (!fs.existsSync(s.audio)) execFileSync('python3', ['-I', tts, voice, rate, s.say, s.audio]);
  s.len = dur(s.audio) + PAD;
});
const total = scenes.reduce((a, s) => a + s.len, 0);
console.log('total seconds', total.toFixed(1));

const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;');
function body(s) {
  const big = s.big ? `<div class="big a" style="--d:.05s">${esc(s.big)}</div>` : '';
  const sub = s.sub ? `<div class="sub a" style="--d:.45s">${esc(s.sub)}</div>` : '';
  switch (s.kind) {
    case 'hook': return `<div class="tag a" style="--d:0s">ກົດບໍລິຫານຄວາມສ່ຽງ</div>${big}${sub}`;
    case 'table': return `<div class="tbl">
      <div class="tr th a" style="--d:0s"><span>${esc(s.head[0])}</span><span>${esc(s.head[1])}</span></div>
      ${s.rows.map((r, k) => `<div class="tr a" style="--d:${0.5 + k * 1.6}s"><span>${esc(r[0])}</span><b>→</b><span class="gold">${esc(r[1])}</span></div>`).join('')}</div>`;
    case 'formula': return `<div class="card a" style="--d:0s">${big}<div class="sub" style="opacity:1">${esc(s.sub)}</div></div>`;
    case 'example': return `${s.lines.map((l, k) => `<div class="line a" style="--d:${k * 1.1}s">${esc(l)}</div>`).join('')}
      <div class="card a" style="--d:${s.lines.length * 1.1 + 0.6}s"><div class="mid">${esc(s.big)}</div></div>`;
    case 'bars': return `<div class="sub a" style="--d:0s;margin-bottom:70px">${esc(s.title)}</div>
      ${s.bars.map((b, k) => `<div class="bar a" style="--d:${0.6 + k * 2.6}s"><div class="bl">${esc(b[0])}</div>
        <div class="track"><div class="fill ${k ? 'red' : ''} grow" style="--d:${0.9 + k * 2.6}s;--w:${b[1]}%"></div></div>
        <div class="bv">${b[1] > 50 ? '~' + Math.round(b[1]) : '&lt;35'}%</div></div>`).join('')}`;
    case 'quote': return `<div class="qm a" style="--d:0s">“</div>${big}<div class="sub gold a" style="--d:1.6s">${esc(s.sub)}</div>`;
    case 'cta': return `<div class="bell a" style="--d:0s">🔔</div>${big}${sub}`;
    default: return big + sub;
  }
}

const candles = (() => { // พื้นหลังแท่งเทียนจาง ๆ
  let x = 0, p = 1150, out = '';
  for (let k = 0; k < 28; k++) {
    const o = p, c = p + (Math.sin(k * 1.7) * 60 - 8 * Math.cos(k)), hi = Math.min(o, c) - 40, lo = Math.max(o, c) + 40;
    const up = c < o;
    out += `<line x1="${x + 15}" x2="${x + 15}" y1="${hi}" y2="${lo}" stroke="${up ? '#3ccf91' : '#e5534b'}" stroke-width="3"/>
      <rect x="${x + 4}" y="${Math.min(o, c)}" width="22" height="${Math.max(6, Math.abs(c - o))}" fill="${up ? '#3ccf91' : '#e5534b'}"/>`;
    x += 40; p = c;
  }
  return `<svg width="1120" height="1920" viewBox="0 0 1120 1920">${out}</svg>`;
})();

const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Lao:wght@400;600;800&display=block" rel="stylesheet">
<style>
:root{--gold:#f2c14e;--ink:#f5f1e6;--bg1:#0b1530;--bg2:#050a18}
*{margin:0;box-sizing:border-box}
body{width:${W}px;height:${H}px;overflow:hidden;font-family:'Noto Sans Lao',sans-serif;color:var(--ink);
 background:radial-gradient(1200px 900px at 50% 30%,#16244d,var(--bg1) 55%,var(--bg2))}
.bgc{position:absolute;left:-20px;top:0;opacity:.07;animation:pan 60s linear both}
@keyframes pan{to{transform:translateX(-160px)}}
.top{position:absolute;top:70px;left:70px;right:70px;display:flex;justify-content:space-between;align-items:center;font-weight:600;font-size:34px;letter-spacing:2px}
.brand{color:var(--gold)} .pair{opacity:.7}
.prog{position:absolute;top:0;left:0;height:10px;background:var(--gold);width:0}
.stage{position:absolute;top:260px;bottom:430px;left:80px;right:80px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center}
.a{opacity:0;animation:up .7s cubic-bezier(.2,.8,.2,1) var(--d) both}
@keyframes up{from{opacity:0;transform:translateY(60px)}to{opacity:1;transform:none}}
.big{font-size:128px;font-weight:800;line-height:1.25;color:#fff;text-shadow:0 8px 40px rgba(0,0,0,.5)}
.sub{font-size:64px;font-weight:600;line-height:1.45;margin-top:34px;opacity:.95}
.gold{color:var(--gold)}
.tag{font-size:40px;padding:14px 36px;border:3px solid var(--gold);color:var(--gold);border-radius:60px;margin-bottom:50px}
.tbl{width:100%}
.tr{display:grid;grid-template-columns:1fr 90px 1fr;align-items:center;font-size:84px;font-weight:800;padding:34px 10px;border-bottom:2px solid rgba(255,255,255,.12)}
.tr b{color:var(--gold)} .th{grid-template-columns:1fr 1fr;font-size:46px;font-weight:600;opacity:.7}
.card{background:rgba(242,193,78,.1);border:3px solid var(--gold);border-radius:40px;padding:60px 50px;margin-top:40px;width:100%}
.card .big{font-size:110px;color:var(--gold)}
.mid{font-size:76px;font-weight:800;color:var(--gold);line-height:1.35}
.line{font-size:72px;font-weight:600;margin:16px 0}
.bar{width:100%;margin:40px 0;text-align:left}
.bl{font-size:54px;font-weight:600;margin-bottom:18px}
.track{height:110px;background:rgba(255,255,255,.08);border-radius:24px;overflow:hidden}
.fill{height:100%;width:var(--w);background:linear-gradient(90deg,#c9962a,var(--gold));border-radius:24px}
.fill.red{background:linear-gradient(90deg,#9e2b25,#e5534b)}
.grow{animation:grow 1.4s cubic-bezier(.2,.8,.2,1) var(--d) both}
@keyframes grow{from{width:0}to{width:var(--w)}}
.bv{font-size:96px;font-weight:800;margin-top:10px}
.qm{font-size:260px;line-height:.6;color:var(--gold);height:150px}
.bell{font-size:170px;animation-name:pop}
@keyframes pop{0%{opacity:0;transform:scale(.3) rotate(-20deg)}70%{transform:scale(1.15) rotate(8deg)}100%{opacity:1;transform:none}}
.cap{position:absolute;left:70px;right:70px;bottom:190px;min-height:180px;display:flex;align-items:center;justify-content:center;text-align:center;
 font-size:48px;font-weight:600;line-height:1.45;padding:26px 40px;background:rgba(0,0,0,.55);border-radius:30px;border-left:8px solid var(--gold)}
.cap:empty{display:none}
.foot{position:absolute;bottom:90px;left:0;right:0;text-align:center;font-size:30px;opacity:.5}
</style></head><body>
<div class="bgc">${candles}</div>
<div class="prog" id="prog"></div>
<div class="top"><span class="brand">GOLD RECORD</span><span class="pair">XAUUSD · ຄຳ</span></div>
<div class="stage" id="stage"></div>
<div class="cap" id="cap"></div>
<div class="foot">ບໍ່ແມ່ນຄຳແນະນຳການລົງທຶນ</div>
</body></html>`;

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: W, height: H } });
  await p.setContent(html, { waitUntil: 'networkidle' });
  await p.evaluate(() => document.fonts.ready);
  if (!(await p.evaluate(() => document.fonts.check('800 100px "Noto Sans Lao"')))) throw new Error('Lao font did not load');

  const frames = path.join(work, 'frames.mjpeg');
  const fd = fs.openSync(frames, 'w');
  let t0 = 0, n = 0;
  for (const s of scenes) {
    await p.evaluate(([h, cap]) => {
      document.getElementById('stage').innerHTML = h;
      document.getElementById('cap').textContent = cap;
      window.__len = 0;
    }, [body(s), s.cap || '']);
    await p.evaluate(l => { window.__len = l; }, s.len);
    const nf = Math.round(s.len * FPS);
    for (let f = 0; f < nf; f++) {
      const t = f / FPS, g = t0 + t;
      await p.evaluate(([t, g, total]) => {
        document.getElementById('prog').style.width = (g / total * 100) + '%';
        for (const a of document.getAnimations()) {
          a.pause();
          a.currentTime = (a.effect.target.closest('.bgc') ? g : t) * 1000;
        }
        const st = document.getElementById('stage'); // fade out ช่วงท้ายฉาก
        st.style.opacity = Math.min(1, Math.max(0, (window.__len - t) / 0.3));
      }, [t, g, total]);
      fs.writeSync(fd, await p.screenshot({ type: 'jpeg', quality: 92 }));
      n++;
    }
    t0 += s.len;
    process.stdout.write(`scene done ${n} frames\n`);
  }
  fs.closeSync(fd);
  await b.close();

  // 2) รวมเสียง: แต่ละฉากเติมความเงียบให้ยาวเท่าฉาก
  const list = path.join(work, 'alist.txt');
  scenes.forEach((s, i) => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', s.audio, '-af', `apad,atrim=0:${s.len.toFixed(3)}`, '-ar', '48000', '-ac', '2', path.join(work, `p${i}.wav`)]));
  fs.writeFileSync(list, scenes.map((_, i) => `file 'p${i}.wav'`).join('\n'));
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, path.join(work, 'voice.wav')]);

  const out = path.join(dir, path.basename(dir) + '.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'mjpeg', '-framerate', String(FPS), '-i', frames, '-i', path.join(work, 'voice.wav'),
    '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out]);
  console.log('OUT', out);
})().catch(e => { console.error(e); process.exit(1); });
