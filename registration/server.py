"""เว็บลงทะเบียนเรียนเทรด Forex & ทองคำ

ใช้แค่ Python standard library (ไม่ต้องติดตั้งอะไรเพิ่ม)
  python registration/server.py

ตัวแปรแวดล้อม (ไม่ใส่ก็ได้):
  REG_PORT             พอร์ต (ค่าเริ่มต้น 8090)
  REG_DB_PATH          ไฟล์ฐานข้อมูล SQLite (ค่าเริ่มต้น registrations.db)
  REG_CONFIG           ไฟล์ตั้งค่าเนื้อหา (ค่าเริ่มต้น config.json ข้างไฟล์นี้)
  REG_ADMIN_TOKEN      รหัสเข้าหน้าแอดมิน /admin (ไม่ใส่ = ปิดหน้าแอดมิน)
  REG_DISCORD_WEBHOOK  URL Discord webhook แจ้งเตือนเมื่อมีคนลงทะเบียน (ไม่ใส่ก็ได้)
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PORT = int(os.getenv("REG_PORT", "8090"))
DB_PATH = os.getenv("REG_DB_PATH", "registrations.db")
CONFIG_PATH = Path(os.getenv("REG_CONFIG", HERE / "config.json"))
ADMIN_TOKEN = os.getenv("REG_ADMIN_TOKEN", "")
DISCORD_WEBHOOK = os.getenv("REG_DISCORD_WEBHOOK", "")
BKK = timezone(timedelta(hours=7))
MAX_BODY = 16 * 1024

_db_lock = threading.Lock()
_rate: dict[str, list[float]] = {}


# ---------------------------------------------------------------- config / db
def load_config() -> dict:
    # อ่านใหม่ทุกครั้ง: แก้ config.json แล้วมีผลทันทีโดยไม่ต้องรีสตาร์ท
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_lock, db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                line_id TEXT,
                class_id TEXT,
                class_label TEXT,
                class_date TEXT,
                answers TEXT,
                note TEXT,
                src TEXT,
                ip TEXT,
                user_agent TEXT,
                status TEXT NOT NULL DEFAULT 'new'
            );
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                src TEXT,
                referrer TEXT
            );
            """
        )


def now_iso() -> str:
    return datetime.now(BKK).isoformat(timespec="seconds")


# ---------------------------------------------------------------- validation
PHONE_RE = re.compile(r"^0?[689]\d{8}$")  # มือถือไทย 06/08/09 + 8 หลัก
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean(value, limit: int = 100) -> str:
    return str(value or "").strip()[:limit]


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("66"):
        digits = "0" + digits[2:]
    if not digits.startswith("0"):
        digits = "0" + digits
    return digits if PHONE_RE.match(digits) else None


def validate(data: dict, cfg: dict) -> tuple[dict | None, str | None]:
    first, last = clean(data.get("firstName")), clean(data.get("lastName"))
    if not first or not last:
        return None, "กรุณากรอกชื่อและนามสกุล"
    phone = normalize_phone(clean(data.get("phone"), 30))
    if not phone:
        return None, "เบอร์โทรไม่ถูกต้อง ตัวอย่าง: 081 234 5678"
    email = clean(data.get("email"), 254)
    if email and not EMAIL_RE.match(email):
        return None, "อีเมลไม่ถูกต้อง"
    if not data.get("consent"):
        return None, "กรุณายินยอมให้ใช้ข้อมูลเพื่อการติดต่อกลับ"

    # คลาส + วันเรียน ต้องตรงกับตัวเลือกใน config เท่านั้น
    classes = cfg.get("classes", {})
    class_id, class_label, class_date = clean(data.get("classId")), "", clean(data.get("classDate"), 200)
    if classes.get("visible"):
        opt = next((o for o in classes.get("options", []) if o["id"] == class_id), None)
        if opt is None:
            if classes.get("required"):
                return None, "กรุณาเลือกคลาสที่ต้องการเรียน"
            class_id = ""
        else:
            class_label = opt["label"]
            dates = opt.get("dates", [])
            if dates and class_date not in dates:
                return None, "กรุณาเลือกวันเรียน"
            if not dates:
                class_date = ""
    else:
        class_id = class_date = ""

    # คำตอบแบบสอบถาม: เก็บเป็น label ให้อ่านง่าย
    raw_answers = data.get("answers") or {}
    answers: dict[str, str] = {}
    for q in cfg.get("questions", []):
        picked = raw_answers.get(q["id"])
        picked = picked if isinstance(picked, list) else ([picked] if picked else [])
        labels = [o["label"] for o in q["options"] if o["value"] in picked]
        if not q.get("multi"):
            labels = labels[:1]
        if q.get("required") and not labels:
            return None, f"กรุณาตอบคำถาม: {q['title']}"
        if labels:
            answers[q["title"]] = ", ".join(labels)

    return {
        "first_name": first,
        "last_name": last,
        "phone": phone,
        "email": email,
        "line_id": clean(data.get("lineId")),
        "class_id": class_id,
        "class_label": class_label,
        "class_date": class_date,
        "answers": json.dumps(answers, ensure_ascii=False),
        "note": clean(data.get("note"), 500),
        "src": clean(data.get("src"), 100),
    }, None


def rate_limited(ip: str, limit: int = 5, window: int = 600) -> bool:
    t = time.time()
    hits = [h for h in _rate.get(ip, []) if t - h < window]
    hits.append(t)
    _rate[ip] = hits
    return len(hits) > limit


def notify_discord(row: dict) -> None:
    if not DISCORD_WEBHOOK:
        return
    answers = json.loads(row["answers"] or "{}")
    lines = [
        f"**{row['first_name']} {row['last_name']}**",
        f"📞 {row['phone']}",
        f"✉️ {row['email']}" if row["email"] else "",
        f"💬 LINE: {row['line_id']}" if row["line_id"] else "",
        f"🎓 {row['class_label']} {('· ' + row['class_date']) if row['class_date'] else ''}" if row["class_label"] else "",
        *[f"• {k}: {v}" for k, v in answers.items()],
        f"🔗 src: {row['src']}" if row["src"] else "",
    ]
    payload = {
        "username": "Registration",
        "allowed_mentions": {"parse": []},
        "embeds": [{"title": "📝 มีผู้ลงทะเบียนใหม่", "description": "\n".join(l for l in lines if l), "color": 0xD4A537}],
    }
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "registration-form"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:  # แจ้งเตือนล้มเหลวไม่ควรทำให้การลงทะเบียนล้มเหลว
        print("discord webhook error:", e)


def csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "RegForm/1.0"

    # -- helpers
    def client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return (fwd.split(",")[0].strip() or self.client_address[0])[:64]

    def send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, status: int, obj) -> None:
        self.send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                  {"Cache-Control": "no-store"})

    def read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def is_admin(self, query: dict) -> bool:
        if not ADMIN_TOKEN:
            return False
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else (query.get("token") or [""])[0]
        return hmac.compare_digest(token.encode(), ADMIN_TOKEN.encode())

    def static(self, name: str) -> None:
        path = STATIC / name
        if not path.is_file():
            return self.json(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(path.suffix, "application/octet-stream")
        self.send(200, path.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    def log_message(self, fmt, *args):  # log สั้น ๆ
        print(f"[{now_iso()}] {self.client_ip()} {fmt % args}")

    # -- routes
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self.static("index.html")
        if url.path == "/admin":
            return self.static("admin.html")
        if url.path == "/favicon.svg":
            return self.static("favicon.svg")
        if url.path == "/healthz":
            return self.json(200, {"ok": True})
        if url.path == "/api/config":
            cfg = load_config()
            return self.json(200, cfg)
        if url.path == "/api/admin/registrations":
            if not self.is_admin(q):
                return self.json(401, {"error": "unauthorized"})
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM registrations ORDER BY id DESC LIMIT 2000")]
                visits = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
                by_src = [dict(r) for r in conn.execute(
                    "SELECT COALESCE(NULLIF(src,''),'(direct)') AS src, COUNT(*) AS visits FROM visits GROUP BY 1 ORDER BY 2 DESC")]
            return self.json(200, {"registrations": rows, "visits": visits, "visitsBySrc": by_src})
        if url.path == "/api/admin/export.csv":
            if not self.is_admin(q):
                return self.json(401, {"error": "unauthorized"})
            with db() as conn:
                rows = conn.execute("SELECT * FROM registrations ORDER BY id").fetchall()
            buf = io.StringIO()
            buf.write("﻿")  # ให้ Excel อ่านภาษาไทยถูก
            w = csv.writer(buf)
            cols = ["id", "created_at", "first_name", "last_name", "phone", "email", "line_id",
                    "class_label", "class_date", "answers", "note", "src", "status"]
            w.writerow(cols)
            for r in rows:
                w.writerow([csv_safe(r[c]) for c in cols])
            name = f"registrations-{datetime.now(BKK):%Y%m%d}.csv"
            return self.send(200, buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
                             {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
        return self.json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/visit":
            data = self.read_json() or {}
            with _db_lock, db() as conn:
                conn.execute("INSERT INTO visits (created_at, src, referrer) VALUES (?,?,?)",
                             (now_iso(), clean(data.get("src")), clean(data.get("ref"), 300)))
            return self.json(200, {"ok": True})

        if url.path == "/api/register":
            data = self.read_json()
            if data is None:
                return self.json(400, {"error": "ข้อมูลไม่ถูกต้อง"})
            if data.get("website"):  # honeypot: ช่องซ่อนที่บอทชอบกรอก
                return self.json(200, {"ok": True, "createdAt": now_iso()})
            ip = self.client_ip()
            if rate_limited(ip):
                return self.json(429, {"error": "ส่งข้อมูลบ่อยเกินไป กรุณาลองใหม่ภายหลัง"})
            row, err = validate(data, load_config())
            if err:
                return self.json(400, {"error": err})
            row.update(created_at=now_iso(), ip=ip, user_agent=clean(self.headers.get("User-Agent"), 300))
            with _db_lock, db() as conn:
                dup = conn.execute(
                    "SELECT id FROM registrations WHERE phone=? AND class_id=? AND class_date=?",
                    (row["phone"], row["class_id"], row["class_date"])).fetchone()
                if dup:
                    return self.json(200, {"ok": True, "duplicate": True, "createdAt": row["created_at"]})
                cols = ",".join(row)
                conn.execute(f"INSERT INTO registrations ({cols}) VALUES ({','.join('?' * len(row))})",
                             list(row.values()))
            threading.Thread(target=notify_discord, args=(row,), daemon=True).start()
            return self.json(200, {"ok": True, "createdAt": row["created_at"]})

        if url.path == "/api/admin/status":
            if not self.is_admin({}):
                return self.json(401, {"error": "unauthorized"})
            data = self.read_json() or {}
            status = clean(data.get("status"), 20)
            if status not in ("new", "contacted", "paid", "cancelled"):
                return self.json(400, {"error": "bad status"})
            with _db_lock, db() as conn:
                conn.execute("UPDATE registrations SET status=? WHERE id=?", (status, int(data.get("id") or 0)))
            return self.json(200, {"ok": True})

        return self.json(404, {"error": "not found"})


def main() -> None:
    init_db()
    load_config()  # ตรวจว่า config.json ถูกต้องตั้งแต่เริ่ม
    print(f"Registration form: http://localhost:{PORT}  (admin: /admin {'เปิด' if ADMIN_TOKEN else 'ปิด — ตั้ง REG_ADMIN_TOKEN'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
