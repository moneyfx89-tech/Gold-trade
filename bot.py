"""
Gold Record Bot: ห้องรีคอร์ดผลเทรดทองคำบน Discord (ภาษาไทย + ภาษาลาว)

คำสั่ง
  /setup                    สร้างหมวด RECORD ROOM + ห้อง + Role "Recorder" (แอดมิน)
  /language                 เลือกภาษาของตัวเอง: ไทย / ລາວ / สองภาษา
  /record open              บันทึกออเดอร์ใหม่ลงห้องบันทึกเทรด
  /record close             ปิดออเดอร์ คำนวณ R และ pips อัตโนมัติ
  /record cancel            ยกเลิกออเดอร์ (ไม่นับในสถิติ)
  /record list              ดูออเดอร์ที่ยังเปิดอยู่
  /stats                    สถิติ วันนี้ / 7 วัน / 30 วัน / ทั้งหมด
  + สรุปผลอัตโนมัติทุกวัน 23:30 น. (เวลาไทย) ในห้องสถิติ
  + รับสัญญาณจาก TradingView ผ่าน POST /webhook แล้วบันทึกให้อัตโนมัติ
  /news                     ข่าวแรงวันนี้ / สัปดาห์นี้
  + เตือนข่าวแรงก่อน 30 นาทีและตอนข่าวออก + สรุปข่าวทุกเช้า 07:00 น.
  /journal open|close|cancel|list|stats   สมุดเทรดส่วนตัวของสมาชิกทุกคน
  /leaderboard              อันดับเทรดเดอร์ + ประกาศอันดับทุกวันอาทิตย์ 20:00 น.

ภาษา
  ข้อความที่ตอบคนพิมพ์คำสั่ง = ภาษาที่คนนั้นเลือกด้วย /language (ยังไม่เลือก = DEFAULT_LANG)
  ข้อความที่บอทโพสต์ให้ทุกคน (การ์ด เตือนข่าว สรุป อันดับ) = PUBLIC_LANG
"""
import asyncio
import io
import json
import os
from datetime import datetime, time, timedelta, timezone

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks

from chart import EN_LABELS, can_render, equity_png
from db import JournalDB, TradeDB, summarize
from i18n import LANGS, both, day_name, t
from news import Calendar, between, blackout, due_alerts, group_by_time
from rooms import ROOMS

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = os.environ.get("GUILD_ID")          # ใส่เพื่อให้คำสั่งขึ้นทันทีในเซิร์ฟเวอร์เดียว
DB_PATH = os.environ.get("DB_PATH", "records.db")
PIP_SIZE = float(os.environ.get("PIP_SIZE", "0.1"))   # XAUUSD: 1 pip = 0.10
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")     # ไม่ใส่ = ปิดระบบรับสัญญาณ TradingView
PORT = int(os.environ.get("PORT", "8080"))
NEWS_CURRENCIES = set(os.environ.get("NEWS_CURRENCIES", "USD").split(","))
NEWS_IMPACT = set(os.environ.get("NEWS_IMPACT", "High").split(","))   # High,Medium
NEWS_LEAD = int(os.environ.get("NEWS_LEAD", "30"))           # เตือนก่อนข่าวกี่นาที
NEWS_BLACKOUT = int(os.environ.get("NEWS_BLACKOUT", "30"))   # ช่วงห้ามเทรด ± นาที
MIN_TRADES = int(os.environ.get("LEADERBOARD_MIN_TRADES", "5"))  # ขั้นต่ำที่จะติดอันดับ
PUBLIC_LANG = os.environ.get("PUBLIC_LANG", "both")     # th / lo / both
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "both")   # ภาษาของคนที่ยังไม่ได้เลือก
assert PUBLIC_LANG in LANGS and DEFAULT_LANG in LANGS, "PUBLIC_LANG/DEFAULT_LANG ต้องเป็น th, lo หรือ both"

BKK = timezone(timedelta(hours=7))   # ไทยและลาวใช้เวลาเดียวกัน
CATEGORY = "📊 RECORD ROOM"
# คีย์ของห้อง ชื่อจริง (ไทย・ລາວ) อยู่ใน rooms.py
RECORD_CH, STATS_CH, NEWS_CH = "record", "stats", "news"
JOURNAL_CH, RANK_CH, TALK_CH = "journal", "rank", "talk"
RECORDER_ROLE = "Recorder"

db = TradeDB(DB_PATH)
jdb = JournalDB(db.conn)
calendar = Calendar(NEWS_CURRENCIES, NEWS_IMPACT)
sent_alerts: set = set()


class RecordBot(commands.Bot):
    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        daily_summary.start()
        news_loop.start()
        morning_brief.start()
        weekly_rank.start()
        if WEBHOOK_SECRET:
            await start_webhook_server()


bot = RecordBot(command_prefix="!", intents=discord.Intents.default())


# ---------- helpers ----------

def ulang(inter: discord.Interaction) -> str:
    """ภาษาของคนที่พิมพ์คำสั่ง"""
    return db.get_lang(inter.user.id) or DEFAULT_LANG


def find_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    """หาห้องจากชื่อใหม่ (ไทย・ລາວ) หรือชื่อเดิมภาษาไทยของเซิร์ฟเวอร์ที่ตั้งไว้ก่อนแล้ว"""
    room = ROOMS[key]
    return (discord.utils.get(guild.text_channels, name=room.name)
            or discord.utils.get(guild.text_channels, name=room.legacy))


def is_recorder():
    def predicate(inter: discord.Interaction) -> bool:
        m = inter.user
        return m.guild_permissions.manage_guild or any(r.name == RECORDER_ROLE for r in m.roles)
    return app_commands.check(predicate)


def fmt(price: float | None) -> str:
    return "-" if price is None else f"{price:,.2f}"


def pips(a: float, b: float) -> float:
    return round(abs(a - b) / PIP_SIZE, 1)


def tid(t_, prefix: str = "#") -> str:
    return f"{prefix}{t_['id']:04d}"


def trade_embed(tr, prefix: str = "#", lang: str = PUBLIC_LANG) -> discord.Embed:
    side = "🟢 BUY" if tr["side"] == "BUY" else "🔴 SELL"
    r = tr["r_multiple"]

    if tr["status"] == "OPEN":
        colour, status = discord.Colour.blue(), t("st_open", lang)
    elif tr["status"] == "CANCELLED":
        colour, status = discord.Colour.dark_grey(), t("st_cancel", lang)
    elif r > 0:
        colour, status = discord.Colour.green(), t("st_win", lang, r=f"{r:+.2f}R")
    elif r < 0:
        colour, status = discord.Colour.red(), t("st_loss", lang, r=f"{r:+.2f}R")
    else:
        colour, status = discord.Colour.light_grey(), t("st_be", lang)

    e = discord.Embed(
        title=f"{tid(tr, prefix)} • {tr['symbol']} {side}",
        description=f"**{t('status', lang)}:** {status}",
        colour=colour,
        timestamp=datetime.fromisoformat(tr["opened_at"]),
    )
    e.add_field(name="Entry", value=fmt(tr["entry"]))
    e.add_field(name="SL", value=f"{fmt(tr['sl'])}\n({pips(tr['entry'], tr['sl'])} pips)")
    if tr["tp"] is not None:
        rr = abs(tr["tp"] - tr["entry"]) / abs(tr["entry"] - tr["sl"])
        e.add_field(name="TP", value=f"{fmt(tr['tp'])}\n(RR 1:{rr:.1f})")
    else:
        e.add_field(name="TP", value="-")

    if tr["status"] == "CLOSED":
        move = tr["exit_price"] - tr["entry"] if tr["side"] == "BUY" else tr["entry"] - tr["exit_price"]
        e.add_field(name=t("exit", lang), value=fmt(tr["exit_price"]))
        e.add_field(name=t("result", lang), value=f"{r:+.2f}R")
        e.add_field(name="Pips", value=f"{move / PIP_SIZE:+.1f}")

    if tr["note"]:
        e.add_field(name=t("note", lang), value=tr["note"], inline=False)
    e.set_footer(text=t("by", lang, name=tr["opened_by"]))
    return e


def stats_embed(title: str, s: dict, lang: str) -> discord.Embed:
    colour = discord.Colour.green() if s["total_r"] > 0 else (
        discord.Colour.red() if s["total_r"] < 0 else discord.Colour.light_grey())
    e = discord.Embed(title=f"📊 {title}", colour=colour, timestamp=datetime.now(timezone.utc))
    if s["count"] == 0:
        e.description = t("no_closed", lang)
        return e
    pf = "∞" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
    e.add_field(name=t("trades", lang), value=f"{s['count']}")
    e.add_field(name=t("wld", lang), value=f"{s['wins']} - {s['losses']} - {s['breakeven']}")
    e.add_field(name="Win rate", value=f"{s['win_rate']:.1f}%")
    e.add_field(name=t("total_r", lang), value=f"**{s['total_r']:+.2f}R**")
    e.add_field(name=t("avg_r", lang), value=f"{s['avg_r']:+.2f}R")
    e.add_field(name="Profit factor", value=pf)
    e.add_field(name="Max drawdown", value=f"-{s['max_dd']:.2f}R")
    e.add_field(name=t("streak", lang), value=t("n_trades", lang, n=s["worst_streak"]))
    e.add_field(name=t("best_worst", lang), value=f"{s['best']:+.2f}R / {s['worst']:+.2f}R")
    e.set_footer(text=t("stats_footer", lang))
    return e


async def with_chart(e: discord.Embed, trades, title: str, lang: str) -> dict:
    """แนบกราฟ R สะสมไว้ใน embed (ต้องมีอย่างน้อย 2 ไม้) คืนค่าเป็น kwargs สำหรับ send"""
    if len(trades) < 2:
        return {"embed": e}
    s = summarize(trades)
    if can_render(lang):
        sub = t("chart_sub", lang, n=s["count"], wr=f"{s['win_rate']:.0f}", dd=f"{s['max_dd']:.1f}")
        labels = {"x": t("chart_x", lang), "dd": t("chart_dd", lang)}
    else:   # เครื่องไม่มีฟอนต์ภาษานี้ ใช้ภาษาอังกฤษในกราฟแทน
        title = "Equity curve"
        sub = f"{s['count']} trades • Win {s['win_rate']:.0f}% • Max DD -{s['max_dd']:.1f}R"
        labels = EN_LABELS
    png = await asyncio.to_thread(equity_png, [x["r_multiple"] for x in trades], title, sub, labels)
    e.set_image(url="attachment://equity.png")
    return {"embed": e, "file": discord.File(io.BytesIO(png), filename="equity.png")}


def since_iso(period: str) -> str | None:
    now = datetime.now(BKK)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    else:
        return None
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def period_choices(keys) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=both(f"p_{k}"), value=k) for k in keys]


SIDE_CHOICES = [app_commands.Choice(name="🟢 BUY", value="BUY"),
                app_commands.Choice(name="🔴 SELL", value="SELL")]
TRADE_PARAMS = dict(side="BUY / SELL", entry="ราคาเข้า / ລາຄາເຂົ້າ", sl="Stop loss",
                    tp="Take profit (ไม่ใส่ก็ได้ / ບໍ່ໃສ່ກໍໄດ້)",
                    note="เหตุผล/หมายเหตุ / ເຫດຜົນ/ໝາຍເຫດ",
                    symbol="สินค้า / ສິນຄ້າ (XAUUSD)")


async def open_trade_autocomplete(inter: discord.Interaction, current: str):
    return [
        app_commands.Choice(
            name=f"#{x['id']:04d} {x['symbol']} {x['side']} @ {fmt(x['entry'])}", value=x["id"])
        for x in db.open_trades()
        if current in str(x["id"])
    ][:25]


# ---------- /language ----------

@bot.tree.command(name="language", description="เลือกภาษาของบอท / ເລືອກພາສາຂອງບອດ")
@app_commands.choices(lang=[app_commands.Choice(name="🇹🇭 ภาษาไทย", value="th"),
                            app_commands.Choice(name="🇱🇦 ພາສາລາວ", value="lo"),
                            app_commands.Choice(name="🇹🇭🇱🇦 ไทย + ລາວ", value="both")])
@app_commands.describe(lang="ภาษา / ພາສາ")
async def language_cmd(inter: discord.Interaction, lang: app_commands.Choice[str]):
    db.set_lang(inter.user.id, lang.value)
    await inter.response.send_message(
        t("lang_set", lang.value, name=t(f"lang_{lang.value}", lang.value)), ephemeral=True)


# ---------- /setup ----------

@bot.tree.command(name="setup", description="สร้างห้องรีคอร์ด (แอดมิน) / ສ້າງຫ້ອງ (ແອດມິນ)")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def setup_cmd(inter: discord.Interaction):
    await inter.response.defer(ephemeral=True)
    g, lang = inter.guild, ulang(inter)

    role = discord.utils.get(g.roles, name=RECORDER_ROLE) or await g.create_role(
        name=RECORDER_ROLE, colour=discord.Colour.gold(), reason="Gold Record Bot")

    me = discord.PermissionOverwrite(send_messages=True, embed_links=True, attach_files=True,
                                     manage_messages=True)   # manage_messages ใช้ปักหมุดคู่มือ
    read_only = {
        g.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                    add_reactions=True),
        g.me: me,
        role: discord.PermissionOverwrite(send_messages=True),
    }
    open_talk = {
        g.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        g.me: me,
    }

    category = discord.utils.get(g.categories, name=CATEGORY) or await g.create_category(CATEGORY)
    created, renamed = [], []
    for key, room in ROOMS.items():
        topic = f"{room_text(room.topic_th)}\n{room_text(room.topic_lo)}"
        ch = find_channel(g, key)
        if ch is None:
            ch = await g.create_text_channel(room.name, category=category, topic=topic,
                                             overwrites=open_talk if room.public else read_only)
            created.append(ch)
        elif ch.name != room.name:   # ห้องเดิมภาษาไทย → เปลี่ยนชื่อ ข้อความเก่ายังอยู่ครบ
            await ch.edit(name=room.name, topic=topic)
            await ch.set_permissions(g.me, overwrite=me)
            renamed.append(ch)
        else:
            continue
        guide = await ch.send(embed=guide_embed(room))
        try:
            await guide.pin()
        except discord.HTTPException:
            pass   # ไม่มีสิทธิ์ปักหมุดก็ไม่เป็นไร คู่มือยังอยู่ในห้อง

    lines = []
    if created:
        lines.append(t("setup_created", lang) + " " + " ".join(c.mention for c in created))
    if renamed:
        lines.append(t("setup_renamed", lang) + " " + " ".join(c.mention for c in renamed))
    if not lines:
        lines.append(t("setup_none", lang))
    lines.append(t("setup_role", lang, role=RECORDER_ROLE))
    await inter.followup.send("\n".join(lines), ephemeral=True)


def room_text(text: str) -> str:
    return text.replace("{min_trades}", str(MIN_TRADES))


def guide_embed(room) -> discord.Embed:
    e = discord.Embed(title=f"📌 {room.name}", colour=discord.Colour.gold())
    e.add_field(name="🇹🇭 ภาษาไทย", value=room_text(room.guide_th), inline=False)
    e.add_field(name="🇱🇦 ພາສາລາວ", value=room_text(room.guide_lo), inline=False)
    e.set_footer(text=f"{t('guide_footer', 'both')}\n{t('lang_hint', 'both')}")
    return e


# ---------- /record ----------

record = app_commands.Group(name="record", description="บันทึกออเดอร์ทางการ / ບັນທຶກອໍເດີທາງການ",
                            guild_only=True)


@record.command(name="open", description="บันทึกออเดอร์ใหม่ / ບັນທຶກອໍເດີໃໝ່")
@app_commands.describe(**TRADE_PARAMS)
@app_commands.choices(side=SIDE_CHOICES)
@is_recorder()
async def record_open(inter: discord.Interaction, side: app_commands.Choice[str], entry: float,
                      sl: float, tp: float | None = None, note: str | None = None,
                      symbol: str = "XAUUSD"):
    lang = ulang(inter)
    if not prices_valid(side.value, entry, sl, tp):
        await inter.response.send_message(t("price_rule", lang), ephemeral=True)
        return

    channel = find_channel(inter.guild, RECORD_CH)
    if channel is None:
        await inter.response.send_message(t("no_room", lang), ephemeral=True)
        return

    tr, msg = await post_new_trade(channel, symbol, side.value, entry, sl, tp, note,
                                   inter.user.display_name)
    await inter.response.send_message(t("recorded", lang, id=tid(tr), url=msg.jump_url),
                                      ephemeral=True)


def prices_valid(side: str, entry: float, sl: float, tp: float | None) -> bool:
    if (side == "BUY" and sl >= entry) or (side == "SELL" and sl <= entry):
        return False
    return tp is None or (side == "BUY" and tp > entry) or (side == "SELL" and tp < entry)


def tag_news(note: str | None) -> str | None:
    """บันทึกตามจริง แต่ติดป้ายให้เห็นว่าเปิดในช่วงข่าวแรง"""
    hot = blackout(calendar.events, datetime.now(timezone.utc), NEWS_BLACKOUT)
    if not hot:
        return note
    warn = t("news_tag", PUBLIC_LANG, titles=", ".join(e.title for e in hot))
    return f"{note}\n{warn}" if note else warn


async def post_new_trade(channel, symbol, side, entry, sl, tp, note, opened_by, ref=None):
    note = tag_news(note)
    trade_id = db.open_trade(symbol.upper(), side, entry, sl, tp, note, opened_by, ref)
    msg = await channel.send(embed=trade_embed(db.get(trade_id)))
    db.set_message(trade_id, channel.id, msg.id)
    return db.get(trade_id), msg


@record.command(name="close", description="ปิดออเดอร์และบันทึกผล / ປິດອໍເດີ ແລະ ບັນທຶກຜົນ")
@app_commands.describe(trade_id="เลขออเดอร์ / ເລກອໍເດີ", exit_price="ราคาที่ปิด / ລາຄາທີ່ປິດ")
@app_commands.autocomplete(trade_id=open_trade_autocomplete)
@is_recorder()
async def record_close(inter: discord.Interaction, trade_id: int, exit_price: float):
    lang = ulang(inter)
    tr = db.get(trade_id)
    if tr is None or tr["status"] != "OPEN":
        await inter.response.send_message(t("not_found", lang), ephemeral=True)
        return

    tr = db.close_trade(trade_id, exit_price)
    await update_record_message(tr, announce=True)
    await inter.response.send_message(closed_text(tr, "#", lang), ephemeral=True)


@record.command(name="cancel", description="ยกเลิกออเดอร์ที่ไม่ได้เข้า / ຍົກເລີກອໍເດີທີ່ບໍ່ໄດ້ເຂົ້າ")
@app_commands.describe(trade_id="เลขออเดอร์ / ເລກອໍເດີ")
@app_commands.autocomplete(trade_id=open_trade_autocomplete)
@is_recorder()
async def record_cancel(inter: discord.Interaction, trade_id: int):
    lang = ulang(inter)
    tr = db.get(trade_id)
    if tr is None or tr["status"] != "OPEN":
        await inter.response.send_message(t("not_found", lang), ephemeral=True)
        return
    tr = db.cancel_trade(trade_id)
    await update_record_message(tr, announce=False)
    await inter.response.send_message(t("cancelled", lang, id=tid(tr)), ephemeral=True)


@record.command(name="list", description="ดูออเดอร์ที่ยังเปิดอยู่ / ເບິ່ງອໍເດີທີ່ເປີດຢູ່")
async def record_list(inter: discord.Interaction):
    lang = ulang(inter)
    rows = db.open_trades()
    if not rows:
        await inter.response.send_message(t("none_open", lang), ephemeral=True)
        return
    await inter.response.send_message(t("open_list", lang) + "\n" + open_lines(rows, "#"),
                                      ephemeral=True)


def open_lines(rows, prefix: str) -> str:
    return "\n".join(f"`{tid(x, prefix)}` {x['symbol']} **{x['side']}** @ {fmt(x['entry'])} "
                     f"| SL {fmt(x['sl'])} | TP {fmt(x['tp'])}" for x in rows)


def closed_text(tr, prefix: str, lang: str) -> str:
    r = tr["r_multiple"]
    icon = "✅" if r > 0 else "❌" if r < 0 else "➖"
    return t("closed", lang, icon=icon, id=tid(tr, prefix), price=fmt(tr["exit_price"]),
             r=f"{r:+.2f}R")


async def update_record_message(tr, announce: bool, prefix: str = "#"):
    """แก้การ์ดเดิมในห้องบันทึก และตอบกลับใต้การ์ดเมื่อปิดออเดอร์"""
    channel = bot.get_channel(tr["channel_id"]) if tr["channel_id"] else None
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(tr["message_id"])
    except discord.NotFound:
        return
    await msg.edit(embed=trade_embed(tr, prefix))
    if announce:
        await msg.reply(closed_text(tr, prefix, PUBLIC_LANG), mention_author=False)


bot.tree.add_command(record)


# ---------- /stats ----------

@bot.tree.command(name="stats", description="ดูสถิติผลงาน / ເບິ່ງສະຖິຕິຜົນງານ")
@app_commands.describe(period="ช่วงเวลา / ຊ່ວງເວລາ")
@app_commands.choices(period=period_choices(["today", "7d", "30d", "all"]))
async def stats_cmd(inter: discord.Interaction, period: app_commands.Choice[str] | None = None):
    lang, key = ulang(inter), period.value if period else "30d"
    await inter.response.defer()
    trades = db.closed_since(since_iso(key))
    title = t("stats_title", lang, p=lambda l: t(f"p_{key}", l))
    e = stats_embed(title, summarize(trades), lang)
    await inter.followup.send(**await with_chart(e, trades, title, lang))


# ---------- สมุดเทรดสมาชิก ----------

journal = app_commands.Group(name="journal", description="สมุดเทรดส่วนตัว / ປຶ້ມບັນທຶກສ່ວນຕົວ",
                             guild_only=True)


async def my_open_autocomplete(inter: discord.Interaction, current: str):
    return [
        app_commands.Choice(
            name=f"{tid(x, 'J')} {x['symbol']} {x['side']} @ {fmt(x['entry'])}", value=x["id"])
        for x in jdb.open_trades(inter.user.id)
        if current in str(x["id"])
    ][:25]


@journal.command(name="open", description="บันทึกเทรดของตัวเอง / ບັນທຶກເທຣດຂອງຕົນເອງ")
@app_commands.describe(**TRADE_PARAMS)
@app_commands.choices(side=SIDE_CHOICES)
async def journal_open(inter: discord.Interaction, side: app_commands.Choice[str], entry: float,
                       sl: float, tp: float | None = None, note: str | None = None,
                       symbol: str = "XAUUSD"):
    lang = ulang(inter)
    if not prices_valid(side.value, entry, sl, tp):
        await inter.response.send_message(t("price_rule", lang), ephemeral=True)
        return
    channel = find_channel(inter.guild, JOURNAL_CH)
    if channel is None:
        await inter.response.send_message(t("no_room", lang), ephemeral=True)
        return

    trade_id = jdb.open_trade(inter.user.id, inter.user.display_name, symbol.upper(), side.value,
                              entry, sl, tp, tag_news(note))
    msg = await channel.send(embed=trade_embed(jdb.get(trade_id), "J"))
    jdb.set_message(trade_id, channel.id, msg.id)
    await inter.response.send_message(
        t("recorded", lang, id=tid(jdb.get(trade_id), "J"), url=msg.jump_url), ephemeral=True)


async def own_open_trade(inter: discord.Interaction, trade_id: int, allow_admin: bool = False):
    tr = jdb.get(trade_id)
    mine = tr is not None and tr["user_id"] == inter.user.id
    admin = allow_admin and inter.user.guild_permissions.manage_guild
    if tr is None or tr["status"] != "OPEN" or not (mine or admin):
        await inter.response.send_message(t("not_found_own", ulang(inter)), ephemeral=True)
        return None
    return tr


@journal.command(name="close", description="ปิดเทรดของตัวเอง / ປິດເທຣດຂອງຕົນເອງ")
@app_commands.describe(trade_id="เลขออเดอร์ / ເລກອໍເດີ", exit_price="ราคาที่ปิด / ລາຄາທີ່ປິດ")
@app_commands.autocomplete(trade_id=my_open_autocomplete)
async def journal_close(inter: discord.Interaction, trade_id: int, exit_price: float):
    if await own_open_trade(inter, trade_id) is None:
        return
    tr = jdb.close_trade(trade_id, exit_price)
    await update_record_message(tr, announce=True, prefix="J")
    await inter.response.send_message(closed_text(tr, "J", ulang(inter)), ephemeral=True)


@journal.command(name="cancel", description="ยกเลิกเทรดที่ไม่ได้เข้า / ຍົກເລີກເທຣດທີ່ບໍ່ໄດ້ເຂົ້າ")
@app_commands.describe(trade_id="เลขออเดอร์ / ເລກອໍເດີ")
@app_commands.autocomplete(trade_id=my_open_autocomplete)
async def journal_cancel(inter: discord.Interaction, trade_id: int):
    if await own_open_trade(inter, trade_id, allow_admin=True) is None:
        return
    tr = jdb.cancel_trade(trade_id)
    await update_record_message(tr, announce=False, prefix="J")
    await inter.response.send_message(t("cancelled", ulang(inter), id=tid(tr, "J")), ephemeral=True)


@journal.command(name="list", description="ดูเทรดที่เปิดอยู่ของตัวเอง / ເບິ່ງເທຣດທີ່ເປີດຢູ່ຂອງຕົນເອງ")
async def journal_list(inter: discord.Interaction):
    lang = ulang(inter)
    rows = jdb.open_trades(inter.user.id)
    if not rows:
        await inter.response.send_message(t("my_none_open", lang), ephemeral=True)
        return
    await inter.response.send_message(t("my_open_list", lang) + "\n" + open_lines(rows, "J"),
                                      ephemeral=True)


@journal.command(name="stats", description="สถิติและกราฟของสมาชิก / ສະຖິຕິ ແລະ ກຣາຟຂອງສະມາຊິກ")
@app_commands.describe(member="สมาชิก (ไม่ใส่ = ตัวเอง) / ສະມາຊິກ (ບໍ່ໃສ່ = ຕົນເອງ)",
                       period="ช่วงเวลา / ຊ່ວງເວລາ")
@app_commands.choices(period=period_choices(["today", "7d", "30d", "all"]))
async def journal_stats(inter: discord.Interaction, member: discord.Member | None = None,
                        period: app_commands.Choice[str] | None = None):
    lang, who = ulang(inter), member or inter.user
    key = period.value if period else "30d"
    await inter.response.defer()
    trades = jdb.closed_since(since_iso(key), who.id)
    title = t("journal_title", lang, name=who.display_name, p=lambda l: t(f"p_{key}", l))
    e = stats_embed(title, summarize(trades), lang)
    e.set_thumbnail(url=who.display_avatar.url)
    await inter.followup.send(**await with_chart(e, trades, title, lang))


bot.tree.add_command(journal)


MEDALS = ["🥇", "🥈", "🥉"]


def leaderboard_embed(title: str, rows, lang: str) -> discord.Embed:
    e = discord.Embed(title=f"🏆 {title}", colour=discord.Colour.gold(),
                      timestamp=datetime.now(timezone.utc))
    if not rows:
        e.description = t("lb_empty", lang, n=MIN_TRADES)
        return e
    lines = []
    for i, r in enumerate(rows[:10]):
        rank = MEDALS[i] if i < 3 else f"`{i + 1:>2}.`"
        pf = "∞" if r["profit_factor"] is None else f"{r['profit_factor']:.2f}"
        stats = t("lb_line", lang, wr=f"{r['win_rate']:.0f}", n=r["count"])
        lines.append(f"{rank} <@{r['user_id']}> **{r['total_r']:+.2f}R**\n"
                     f"　{stats} • PF {pf} • DD -{r['max_dd']:.1f}R")
    e.description = "\n".join(lines)
    e.set_footer(text=t("lb_footer", lang, n=MIN_TRADES))
    return e


@bot.tree.command(name="leaderboard", description="อันดับเทรดเดอร์ / ອັນດັບເທຣດເດີ")
@app_commands.describe(period="ช่วงเวลา / ຊ່ວງເວລາ")
@app_commands.choices(period=period_choices(["7d", "30d", "all"]))
async def leaderboard_cmd(inter: discord.Interaction,
                          period: app_commands.Choice[str] | None = None):
    lang, key = ulang(inter), period.value if period else "30d"
    rows = jdb.leaderboard(since_iso(key), MIN_TRADES)
    # mention ใน embed ไม่แจ้งเตือนใคร แค่แสดงชื่อ
    title = t("lb_title", lang, p=lambda l: t(f"p_{key}", l))
    await inter.response.send_message(embed=leaderboard_embed(title, rows, lang))


@tasks.loop(time=time(hour=20, minute=0, tzinfo=BKK))
async def weekly_rank():
    if datetime.now(BKK).weekday() != 6:   # ประกาศเฉพาะวันอาทิตย์
        return
    rows = jdb.leaderboard(since_iso("7d"), MIN_TRADES)
    for guild in bot.guilds:
        if ch := find_channel(guild, RANK_CH):
            await ch.send(embed=leaderboard_embed(t("lb_week", PUBLIC_LANG), rows, PUBLIC_LANG))


# ---------- สรุปรายวัน ----------

@tasks.loop(time=time(hour=23, minute=30, tzinfo=BKK))
async def daily_summary():
    lang = PUBLIC_LANG
    today = summarize(db.closed_since(since_iso("today")))
    month = db.closed_since(since_iso("30d"))
    date = datetime.now(BKK).strftime("%d/%m/%Y")
    for guild in bot.guilds:
        channel = find_channel(guild, STATS_CH)
        if channel:
            await channel.send(embed=stats_embed(t("daily_title", lang, d=date), today, lang))
            # สร้างกราฟใหม่ทุกครั้ง เพราะ discord.File ใช้ส่งได้ครั้งเดียว
            e = stats_embed(t("month_title", lang), summarize(month), lang)
            await channel.send(**await with_chart(e, month, t("month_chart", lang), lang))


@daily_summary.before_loop
async def before_daily():
    await bot.wait_until_ready()


@bot.tree.error
async def on_app_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    lang = ulang(inter)
    if isinstance(error, app_commands.CheckFailure):
        text = t("no_perm", lang, role=RECORDER_ROLE)
    else:
        text = t("error", lang, e=error)
    if inter.response.is_done():
        await inter.followup.send(text, ephemeral=True)
    else:
        await inter.response.send_message(text, ephemeral=True)
    if not isinstance(error, app_commands.CheckFailure):
        raise error


# ---------- ข่าวเศรษฐกิจ ----------

FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CNY": "🇨🇳",
         "CHF": "🇨🇭", "AUD": "🇦🇺", "CAD": "🇨🇦", "NZD": "🇳🇿"}


def news_line(e, lang: str) -> str:
    local = e.local(lang)
    local = f" ({local})" if local else ""
    return (f"`{e.time.astimezone(BKK):%H:%M}` {FLAGS.get(e.country, e.country)} "
            f"**{e.title}**{local}\n　{t('fc_prev', lang, f=e.forecast, p=e.previous)}")


def news_alert_embed(group, lead: int, lang: str = PUBLIC_LANG) -> discord.Embed:
    at = group[0].time.astimezone(BKK).strftime("%H:%M")
    if lead > 0:
        e = discord.Embed(title=t("alert_lead", lang, m=lead, at=at), colour=discord.Colour.orange())
        advice = t("advice_lead", lang)
    else:
        e = discord.Embed(title=t("alert_now", lang, at=at), colour=discord.Colour.red())
        advice = t("advice_now", lang, m=NEWS_BLACKOUT)
    e.description = "\n".join(news_line(x, lang) for x in group)
    n = len(db.open_trades())
    if n:
        advice += "\n" + t("open_now", lang, n=n)
    e.add_field(name=t("advice", lang), value=advice, inline=False)
    return e


def schedule_embed(title: str, events, lang: str) -> discord.Embed:
    e = discord.Embed(title=title, colour=discord.Colour.gold())
    if not events:
        e.description = t("no_news", lang)
        return e
    days: dict[str, list[str]] = {}
    for x in events:
        d = x.time.astimezone(BKK)
        days.setdefault(f"{day_name(d.weekday(), lang)} {d:%d/%m}", []).append(news_line(x, lang))
    e.description = "\n\n".join(f"**📅 {d}**\n" + "\n".join(lines)
                                  for d, lines in days.items())[:4000]
    e.set_footer(text=t("news_footer", lang, m=NEWS_BLACKOUT))
    return e


def today_range():
    start = datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def send_to_news(**kwargs):
    for guild in bot.guilds:
        if ch := find_channel(guild, NEWS_CH):
            await ch.send(**kwargs)


@tasks.loop(minutes=1)
async def news_loop():
    events = await calendar.refresh()
    now = datetime.now(timezone.utc)
    for lead in (NEWS_LEAD, 0):
        for group in group_by_time(due_alerts(events, now, lead, sent_alerts)):
            await send_to_news(embed=news_alert_embed(group, lead))


@tasks.loop(time=time(hour=7, minute=0, tzinfo=BKK))
async def morning_brief():
    events = await calendar.refresh()
    if calendar.fetched_at is None:
        return  # ยังดึงข่าวไม่ได้เลย อย่าโพสต์ว่า "ไม่มีข่าว"
    lang = PUBLIC_LANG
    start, end = today_range()
    date = lambda l: f"{day_name(start.weekday(), l)} {start:%d/%m/%Y}"  # noqa: E731
    await send_to_news(embed=schedule_embed(t("brief_title", lang, d=date),
                                            between(events, start, end), lang))


@news_loop.before_loop
@morning_brief.before_loop
@weekly_rank.before_loop
async def before_news():
    await bot.wait_until_ready()


@bot.tree.command(name="news", description="ข่าวแรงที่กระทบทอง / ຂ່າວແຮງທີ່ກະທົບຄຳ")
@app_commands.describe(period="ช่วงเวลา / ຊ່ວງເວລາ")
@app_commands.choices(period=period_choices(["today", "week"]))
async def news_cmd(inter: discord.Interaction, period: app_commands.Choice[str] | None = None):
    lang = ulang(inter)
    await inter.response.defer()
    events = await calendar.refresh()
    if calendar.fetched_at is None:
        await inter.followup.send(t("news_fail", lang))
        return
    if period and period.value == "week":
        upcoming = [e for e in events if e.time >= datetime.now(timezone.utc)]
        await inter.followup.send(embed=schedule_embed(t("news_week", lang), upcoming, lang))
    else:
        start, end = today_range()
        await inter.followup.send(
            embed=schedule_embed(t("news_today", lang), between(events, start, end), lang))


# ---------- TradingView webhook ----------
# ตัวอย่าง JSON ที่ TradingView ส่งมา:
#   {"secret": "...", "action": "open", "side": "BUY", "symbol": "XAUUSD",
#    "entry": 2650.5, "sl": 2640.2, "tp": 2671.1, "ref": "G1234", "note": "EMA pullback"}
#   {"secret": "...", "action": "close", "ref": "G1234", "price": 2671.1}
#   {"secret": "...", "action": "cancel", "ref": "G1234"}
# ถ้าไม่ส่ง ref มา บอทจะปิดหรือยกเลิกออเดอร์ล่าสุดของ symbol นั้นแทน

PRICE_RULE_API = "invalid prices: BUY needs SL < Entry < TP, SELL needs TP < Entry < SL"


def record_channel_any() -> discord.TextChannel | None:
    guilds = [bot.get_guild(int(GUILD_ID))] if GUILD_ID else bot.guilds
    for g in guilds:
        if g and (ch := find_channel(g, RECORD_CH)):
            return ch
    return None


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = json.loads(await request.text())  # TradingView ส่งเป็น text/plain
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    if data.get("secret") != WEBHOOK_SECRET:
        return web.json_response({"error": "bad secret"}, status=403)

    action = str(data.get("action", "")).lower()
    symbol = str(data.get("symbol", "XAUUSD")).upper()
    ref = data.get("ref")
    try:
        if action == "open":
            side = str(data["side"]).upper()
            entry, sl = float(data["entry"]), float(data["sl"])
            tp = float(data["tp"]) if data.get("tp") not in (None, "") else None
            if side not in ("BUY", "SELL") or not prices_valid(side, entry, sl, tp):
                return web.json_response({"error": PRICE_RULE_API}, status=400)
            if ref and db.find_open(ref=ref):
                return web.json_response({"ok": True, "duplicate": True})  # alert ยิงซ้ำ
            channel = record_channel_any()
            if channel is None:
                return web.json_response({"error": "run /setup first"}, status=409)
            tr, _ = await post_new_trade(channel, symbol, side, entry, sl, tp,
                                         data.get("note"), "🤖 TradingView", ref)
            return web.json_response({"ok": True, "id": tr["id"]})

        if action in ("close", "cancel"):
            tr = db.find_open(ref=ref, symbol=symbol)
            if tr is None:
                return web.json_response({"error": "no open trade"}, status=404)
            if action == "close":
                tr = db.close_trade(tr["id"], float(data["price"]))
            else:
                tr = db.cancel_trade(tr["id"])
            await update_record_message(tr, announce=action == "close")
            return web.json_response({"ok": True, "id": tr["id"]})
    except (KeyError, TypeError, ValueError) as e:
        return web.json_response({"error": f"missing/invalid field: {e}"}, status=400)

    return web.json_response({"error": "action must be open/close/cancel"}, status=400)


async def start_webhook_server():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/", lambda _: web.Response(text="Gold Record Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"🌐 Webhook พร้อมรับที่พอร์ต {PORT} → POST /webhook")


@bot.event
async def on_ready():
    print(f"✅ ออนไลน์แล้ว: {bot.user} ({len(bot.guilds)} เซิร์ฟเวอร์)")


if __name__ == "__main__":
    bot.run(TOKEN)
