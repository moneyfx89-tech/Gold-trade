# 🎬 video-maker — ສ້າງຄລິບ "ແຜນເທຣດຄຳປະຈຳວັນ" ພາສາລາວ ອັດຕະໂນມັດ

ทำคลิปแนวตั้ง 1080×1920 แบบคลิปต้นแบบ (ดู `../video-playbook/`) แต่พูดและเขียนเป็นภาษาลาวทั้งหมด

## ทำคลิปวันใหม่
1. ก๊อป `episodes/2026-11-16.json` เป็นไฟล์วันใหม่ เช่น `episodes/2026-11-17.json`
2. แก้ในไฟล์: วันที่ (`common`), ช่วงกราฟ (`from`), ตัวเลข/ป้าย/บทพูด (`say`), ข้อความใหญ่ (`caption`), แถวตัวเลข (`rows`), แคปชั่นโพสต์ (`caption` ท้ายไฟล์)
3. รัน
   ```
   pip install yfinance edge-tts playwright pandas
   python make_video.py episodes/2026-11-17.json --fetch           # ดึงราคาใหม่ + ทำคลิป
   python make_video.py episodes/2026-11-17.json --only 5          # ดูภาพช็อต 5 อย่างเดียว
   python make_video.py episodes/2026-11-17.json --music bgm.mp3   # ใส่เพลงพื้นหลัง
   ```
4. ได้ไฟล์ใน `out/`: `.mp4` (คลิป), `.srt` (ซับลาว), `.caption.txt` (แคปชั่นโพสต์)

## ค่าที่ปรับได้
- `common.brand` ชื่อช่อง (ตอนนี้ใส่ไว้ชั่วคราวว่า `GOLD PLAN LAO`)
- `voice.name`: `lo-LA-ChanthavongNeural` (ชาย) / `lo-LA-KeomanyNeural` (หญิง), `voice.rate` ความเร็วพูด
- ป้ายบนกราฟ: `zone` (โซนสี), `hline` (เส้นประ), `pill` (ป้าย, `at: "hi:วันที่"`/`"lo:วันที่"`), `path` (เส้น/ลูกศร, `"+6"` = 6 แท่งในอนาคต), `box`
- ข้อความเน้นสี: `[g]เขียว[/g]` `[r]แดง[/r]` `[y]ทอง[/y]` `[bl]ฟ้า[/bl]`

ข้อมูลราคา: Yahoo Finance `GC=F` (Gold Futures) ซึ่งใกล้กับ XAUUSD spot แต่ไม่เท่ากันเป๊ะ ห่างกันได้ไม่กี่ดอลลาร์
