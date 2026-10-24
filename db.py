"""ฐานข้อมูลบันทึกเทรด (SQLite) และการคำนวณสถิติ"""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    entry       REAL    NOT NULL,
    sl          REAL    NOT NULL,
    tp          REAL,
    note        TEXT,
    status      TEXT    NOT NULL DEFAULT 'OPEN',   -- OPEN / CLOSED / CANCELLED
    exit_price  REAL,
    r_multiple  REAL,
    opened_by   TEXT    NOT NULL,
    opened_at   TEXT    NOT NULL,
    closed_at   TEXT,
    channel_id  INTEGER,
    message_id  INTEGER,
    ref         TEXT                               -- รหัสอ้างอิงจาก TradingView
);

-- สมุดเทรดของสมาชิก แยกจากออเดอร์ทางการ เพื่อไม่ให้ปนกับสถิติของห้อง
CREATE TABLE IF NOT EXISTS journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    entry       REAL    NOT NULL,
    sl          REAL    NOT NULL,
    tp          REAL,
    note        TEXT,
    status      TEXT    NOT NULL DEFAULT 'OPEN',
    exit_price  REAL,
    r_multiple  REAL,
    opened_by   TEXT    NOT NULL,                  -- ชื่อที่แสดงตอนบันทึก
    opened_at   TEXT    NOT NULL,
    closed_at   TEXT,
    channel_id  INTEGER,
    message_id  INTEGER
);
CREATE INDEX IF NOT EXISTS journal_user ON journal (user_id, status);

-- ภาษาที่สมาชิกเลือกด้วย /language (th / lo / both)
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id     INTEGER PRIMARY KEY,
    lang        TEXT    NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def calc_r(side: str, entry: float, sl: float, exit_price: float) -> float:
    """ผลลัพธ์เป็นเท่าของความเสี่ยง (R): +2 = ได้ 2 เท่าของที่เสี่ยง, -1 = โดน SL"""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    move = exit_price - entry if side == "BUY" else entry - exit_price
    return round(move / risk, 2)


class TradeDB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(trades)")]
        if "ref" not in cols:  # อัปเกรดฐานข้อมูลเวอร์ชันแรก
            self.conn.execute("ALTER TABLE trades ADD COLUMN ref TEXT")

    def get_lang(self, user_id: int) -> str | None:
        row = self.conn.execute("SELECT lang FROM user_prefs WHERE user_id = ?",
                                (user_id,)).fetchone()
        return row["lang"] if row else None

    def set_lang(self, user_id: int, lang: str):
        self.conn.execute("INSERT INTO user_prefs (user_id, lang) VALUES (?, ?)"
                          " ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
                          (user_id, lang))
        self.conn.commit()

    def open_trade(self, symbol, side, entry, sl, tp, note, opened_by, ref=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO trades (symbol, side, entry, sl, tp, note, opened_by, opened_at, ref)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, side, entry, sl, tp, note, opened_by, now_iso(), ref),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_message(self, trade_id: int, channel_id: int, message_id: int):
        self.conn.execute(
            "UPDATE trades SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, trade_id),
        )
        self.conn.commit()

    def get(self, trade_id: int):
        return self.conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()

    def close_trade(self, trade_id: int, exit_price: float):
        t = self.get(trade_id)
        r = calc_r(t["side"], t["entry"], t["sl"], exit_price)
        self.conn.execute(
            "UPDATE trades SET status = 'CLOSED', exit_price = ?, r_multiple = ?, closed_at = ?"
            " WHERE id = ?",
            (exit_price, r, now_iso(), trade_id),
        )
        self.conn.commit()
        return self.get(trade_id)

    def cancel_trade(self, trade_id: int):
        self.conn.execute(
            "UPDATE trades SET status = 'CANCELLED', closed_at = ? WHERE id = ?",
            (now_iso(), trade_id),
        )
        self.conn.commit()
        return self.get(trade_id)

    def find_open(self, ref: str | None = None, symbol: str | None = None):
        """หาออเดอร์ที่เปิดอยู่จาก ref หรือถ้าไม่มี ref ใช้ออเดอร์ล่าสุดของ symbol นั้น"""
        if ref:
            return self.conn.execute(
                "SELECT * FROM trades WHERE status = 'OPEN' AND ref = ?", (ref,)).fetchone()
        return self.conn.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' AND symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,)).fetchone()

    def open_trades(self):
        return self.conn.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY id"
        ).fetchall()

    def closed_since(self, since_iso: str | None):
        sql = "SELECT * FROM trades WHERE status = 'CLOSED'"
        args = ()
        if since_iso:
            sql += " AND closed_at >= ?"
            args = (since_iso,)
        return self.conn.execute(sql + " ORDER BY closed_at", args).fetchall()


def summarize(trades) -> dict:
    rs = [t["r_multiple"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]

    # Drawdown สูงสุด วัดจากกราฟ R สะสม
    peak = equity = max_dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # แพ้ติดกันมากที่สุด
    streak = worst_streak = 0
    for r in rs:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)

    gross_loss = abs(sum(losses))
    return {
        "count": len(rs),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(rs) - len(wins) - len(losses),
        "win_rate": (len(wins) / len(rs) * 100) if rs else 0.0,
        "total_r": round(sum(rs), 2),
        "avg_r": round(sum(rs) / len(rs), 2) if rs else 0.0,
        "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss else None,
        "max_dd": round(max_dd, 2),
        "worst_streak": worst_streak,
        "best": max(rs) if rs else 0.0,
        "worst": min(rs) if rs else 0.0,
    }


class JournalDB:
    """สมุดเทรดของสมาชิก ใช้การเชื่อมต่อเดียวกับ TradeDB"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def open_trade(self, user_id, name, symbol, side, entry, sl, tp, note) -> int:
        cur = self.conn.execute(
            "INSERT INTO journal (user_id, opened_by, symbol, side, entry, sl, tp, note, opened_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, symbol, side, entry, sl, tp, note, now_iso()),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_message(self, trade_id: int, channel_id: int, message_id: int):
        self.conn.execute("UPDATE journal SET channel_id = ?, message_id = ? WHERE id = ?",
                          (channel_id, message_id, trade_id))
        self.conn.commit()

    def get(self, trade_id: int):
        return self.conn.execute("SELECT * FROM journal WHERE id = ?", (trade_id,)).fetchone()

    def close_trade(self, trade_id: int, exit_price: float):
        t = self.get(trade_id)
        r = calc_r(t["side"], t["entry"], t["sl"], exit_price)
        self.conn.execute(
            "UPDATE journal SET status = 'CLOSED', exit_price = ?, r_multiple = ?, closed_at = ?"
            " WHERE id = ?", (exit_price, r, now_iso(), trade_id))
        self.conn.commit()
        return self.get(trade_id)

    def cancel_trade(self, trade_id: int):
        self.conn.execute("UPDATE journal SET status = 'CANCELLED', closed_at = ? WHERE id = ?",
                          (now_iso(), trade_id))
        self.conn.commit()
        return self.get(trade_id)

    def open_trades(self, user_id: int):
        return self.conn.execute(
            "SELECT * FROM journal WHERE status = 'OPEN' AND user_id = ? ORDER BY id",
            (user_id,)).fetchall()

    def closed_since(self, since_iso: str | None, user_id: int | None = None):
        sql, args = "SELECT * FROM journal WHERE status = 'CLOSED'", []
        if since_iso:
            sql += " AND closed_at >= ?"
            args.append(since_iso)
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        return self.conn.execute(sql + " ORDER BY closed_at", args).fetchall()

    def leaderboard(self, since_iso: str | None, min_trades: int) -> list[dict]:
        """จัดอันดับตาม R รวม เสมอกันดู Profit factor แล้วดู Win rate"""
        by_user: dict[int, list] = {}
        for t in self.closed_since(since_iso):
            by_user.setdefault(t["user_id"], []).append(t)
        rows = []
        for uid, trades in by_user.items():
            if len(trades) < min_trades:
                continue
            s = summarize(trades)
            s.update(user_id=uid, name=trades[-1]["opened_by"])
            rows.append(s)
        pf = lambda s: float("inf") if s["profit_factor"] is None else s["profit_factor"]
        return sorted(rows, key=lambda s: (s["total_r"], pf(s), s["win_rate"]), reverse=True)
