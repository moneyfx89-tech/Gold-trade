const {chromium}=require('playwright');const {spawn}=require('child_process');
const [V,FPS,A,B,OUT,SHOTS]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1080,height:1920}});
await p.goto('file://'+V+'/page.html');await p.evaluate(()=>document.fonts.ready);
if(SHOTS){for(const t of SHOTS.split(',')){await p.evaluate(t=>draw(+t),t);await p.screenshot({path:`${OUT}_${t}.jpg`,type:'jpeg',quality:80})}await b.close();return}
const ff=spawn('ffmpeg',['-loglevel','error','-y','-f','image2pipe','-framerate',FPS,'-i','-','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',OUT]);
for(let f=+A;f<+B;f++){await p.evaluate(t=>draw(t),f/FPS);const buf=await p.screenshot({type:'jpeg',quality:88});if(!ff.stdin.write(buf))await new Promise(r=>ff.stdin.once('drain',r))}
ff.stdin.end();await new Promise(r=>ff.on('close',r));await b.close()})();
