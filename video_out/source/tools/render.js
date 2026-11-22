const {chromium}=require('playwright');const fs=require('fs');const {spawn}=require('child_process');
const W=process.argv[2], mode=process.argv[3]||'preview';
const tl=JSON.parse(fs.readFileSync(W+'/timeline.json','utf8'));
fs.writeFileSync(W+'/comp/render.html',fs.readFileSync(W+'/comp/index.html','utf8').replace('__TIMELINE__',JSON.stringify(tl)));
(async()=>{
 const b=await chromium.launch();const p=await b.newPage({viewport:{width:1080,height:1920},deviceScaleFactor:1});
 p.on('pageerror',e=>console.error('PAGEERR',e.message));
 await p.goto('file://'+W+'/comp/render.html');await p.evaluate(()=>window.ready);await p.waitForTimeout(500);
 if(mode==='preview'){
   const ts=process.argv.slice(4).map(Number);fs.mkdirSync(W+'/prev',{recursive:true});
   for(const t of ts){await p.evaluate(t=>render(t),t);await p.screenshot({path:`${W}/prev/t${t}.jpg`,type:'jpeg',quality:80});}
 } else {
   const fps=30,N=Math.ceil(tl.duration*fps);
   const ff=spawn('ffmpeg',['-v','error','-y','-f','image2pipe','-framerate',''+fps,'-c:v','mjpeg','-i','-','-c:v','libx264','-preset','medium','-crf','17','-pix_fmt','yuv420p',W+'/video_noaudio.mp4'],{stdio:['pipe','inherit','inherit']});
   for(let i=0;i<N;i++){await p.evaluate(t=>render(t),i/fps);const buf=await p.screenshot({type:'jpeg',quality:93});if(!ff.stdin.write(buf))await new Promise(r=>ff.stdin.once('drain',r));if(i%300===0)console.log('frame',i,'/',N);}
   ff.stdin.end();await new Promise(r=>ff.on('close',r));
 }
 await b.close();
})();
