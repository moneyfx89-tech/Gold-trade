"""ปฏิทินข่าวเศรษฐกิจ (ForexFactory weekly JSON) และการคำนวณเวลาเตือน"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REFRESH = timedelta(hours=1)   # ฟีดนี้จำกัดการดึงถี่ ดึงชั่วโมงละครั้งพอ

log = logging.getLogger("news")

# ชื่อข่าวภาษาไทย / ภาษาลาว สำหรับข่าวที่กระทบทองบ่อย (จับคำในชื่อข่าว)
LOCAL_NAMES = [
    ("Non-Farm", "NFP ตัวเลขจ้างงานนอกภาคเกษตร", "NFP ການຈ້າງງານນອກພາກກະສິກຳ"),
    ("Unemployment Rate", "อัตราว่างงาน", "ອັດຕາການຫວ່າງງານ"),
    ("Unemployment Claims", "ผู้ขอรับสวัสดิการว่างงาน", "ຜູ້ຂໍຮັບສະຫວັດດີການຫວ່າງງານ"),
    ("Core CPI", "เงินเฟ้อพื้นฐาน (Core CPI)", "ເງິນເຟີ້ພື້ນຖານ (Core CPI)"),
    ("CPI", "เงินเฟ้อ (CPI)", "ເງິນເຟີ້ (CPI)"),
    ("Core PCE", "เงินเฟ้อ PCE พื้นฐาน (ตัวที่ Fed ดู)", "ເງິນເຟີ້ PCE ພື້ນຖານ (ຕົວທີ່ Fed ເບິ່ງ)"),
    ("PPI", "ดัชนีราคาผู้ผลิต (PPI)", "ດັດຊະນີລາຄາຜູ້ຜະລິດ (PPI)"),
    ("Federal Funds Rate", "🏦 ประกาศดอกเบี้ย Fed", "🏦 ປະກາດອັດຕາດອກເບ້ຍ Fed"),
    ("FOMC", "🏦 Fed / FOMC", "🏦 Fed / FOMC"),
    ("Fed Chair", "🎤 ประธาน Fed แถลง", "🎤 ປະທານ Fed ຖະແຫຼງ"),
    ("GDP", "GDP การเติบโตเศรษฐกิจ", "GDP ການເຕີບໂຕເສດຖະກິດ"),
    ("Retail Sales", "ยอดค้าปลีก", "ຍອດຂາຍຍ່ອຍ"),
    ("ISM", "ดัชนี ISM ภาคการผลิต/บริการ", "ດັດຊະນີ ISM ພາກການຜະລິດ/ບໍລິການ"),
    ("JOLTS", "ตำแหน่งงานว่าง JOLTS", "ຕຳແໜ່ງງານຫວ່າງ JOLTS"),
    ("ADP", "จ้างงานภาคเอกชน ADP", "ການຈ້າງງານພາກເອກະຊົນ ADP"),
]


@dataclass(frozen=True)
class Event:
    title: str
    country: str
    time: datetime          # aware datetime
    impact: str
    forecast: str
    previous: str

    @property
    def key(self) -> str:
        return f"{self.country}|{self.title}|{self.time.isoformat()}"

    def local(self, lang: str) -> str:
        """ชื่อข่าวภาษาท้องถิ่น lang = th / lo / both (ไม่รู้จักข่าวนี้ = "")"""
        for word, th, lo in LOCAL_NAMES:
            if word.lower() in self.title.lower():
                return th if lang == "th" else lo if lang == "lo" else f"{th} | {lo}"
        return ""


def parse_events(raw: list[dict], currencies: set[str], impacts: set[str]) -> list[Event]:
    events = []
    for r in raw:
        if r.get("country") not in currencies or r.get("impact") not in impacts:
            continue
        try:
            t = datetime.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        events.append(Event(r.get("title", "?"), r["country"], t, r["impact"],
                            r.get("forecast") or "-", r.get("previous") or "-"))
    return sorted(events, key=lambda e: e.time)


def due_alerts(events, now: datetime, lead_minutes: int, sent: set, grace: int = 5) -> list[Event]:
    """ข่าวที่ถึงเวลาเตือน lead_minutes ก่อนประกาศ (เผื่อ grace นาทีกันลูปคลาดเคลื่อน)
    lead_minutes = 0 คือเตือนตอนข่าวออก"""
    due = []
    for e in events:
        mins = (e.time - now).total_seconds() / 60
        tag = (e.key, lead_minutes)
        if lead_minutes - grace < mins <= lead_minutes and tag not in sent:
            sent.add(tag)
            due.append(e)
    return due


def blackout(events, now: datetime, minutes: int) -> list[Event]:
    """ข่าวที่อยู่ในช่วง ±minutes นาทีจากตอนนี้ (ช่วงห้ามเทรด)"""
    w = timedelta(minutes=minutes)
    return [e for e in events if e.time - w <= now <= e.time + w]


def between(events, start: datetime, end: datetime) -> list[Event]:
    return [e for e in events if start <= e.time < end]


def group_by_time(events) -> list[list[Event]]:
    """ข่าวที่ออกเวลาเดียวกัน (เช่น NFP + อัตราว่างงาน) รวมเป็นชุดเดียว"""
    groups: dict[datetime, list[Event]] = {}
    for e in events:
        groups.setdefault(e.time, []).append(e)
    return [groups[t] for t in sorted(groups)]


class Calendar:
    def __init__(self, currencies: set[str], impacts: set[str]):
        self.currencies, self.impacts = currencies, impacts
        self.events: list[Event] = []
        self.fetched_at: datetime | None = None   # ดึงสำเร็จล่าสุด
        self.next_fetch: datetime | None = None

    async def refresh(self, force: bool = False) -> list[Event]:
        now = datetime.now(timezone.utc)
        if not force and self.next_fetch and now < self.next_fetch:
            return self.events
        try:
            async with aiohttp.ClientSession(trust_env=True) as s:
                async with s.get(FEED_URL, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    r.raise_for_status()
                    raw = await r.json(content_type=None)
            self.events = parse_events(raw, self.currencies, self.impacts)
            self.fetched_at = now
            self.next_fetch = now + REFRESH
        except Exception as e:  # ดึงไม่ได้ใช้ข้อมูลเดิมไปก่อน แล้วลองใหม่รอบหน้า
            log.warning("ดึงปฏิทินข่าวไม่สำเร็จ: %s", e)
            self.next_fetch = now + timedelta(minutes=5)
        return self.events
