"""กราฟ R สะสม (equity curve) เป็นรูป PNG สำหรับแนบใน Discord"""
import io

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager, pyplot as plt  # noqa: E402

# โทนมืดให้เข้ากับ Discord (ผ่านการตรวจสีและ contrast กับพื้นหลังแล้ว)
SURFACE = "#1a1a19"
TEXT = "#f0efec"
TEXT_2 = "#c3c2b7"
GRID = "#383835"
LINE = "#3987e5"
DRAWDOWN = "#d03b3b"

THAI_FONTS = ["Noto Sans Thai", "Noto Sans Thai UI", "Sarabun", "Loma", "Garuda",
              "Waree", "Umpush", "Norasi", "Kinnari"]
LAO_FONTS = ["Noto Sans Lao", "Noto Sans Lao UI", "Phetsarath OT", "Saysettha OT", "DejaVu Sans"]
EN_LABELS = {"x": "Trade #", "dd": "Drawdown"}


def _pick(candidates) -> str | None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in candidates if n in names), None)


THAI_FONT, LAO_FONT = _pick(THAI_FONTS), _pick(LAO_FONTS)
# ใส่หลายฟอนต์ให้ matplotlib เลือกตามตัวอักษร ข้อความไทยปนลาวจึงแสดงได้ในรูปเดียว
FONTS = [f for f in (THAI_FONT, LAO_FONT, "DejaVu Sans") if f]


def can_render(lang: str) -> bool:
    """มีฟอนต์ครบสำหรับภาษานี้ไหม ถ้าไม่ครบใช้ป้ายภาษาอังกฤษแทน กันตัวอักษรเป็นกล่อง"""
    need_th = lang in ("th", "both")
    need_lo = lang in ("lo", "both")
    return bool((THAI_FONT or not need_th) and (LAO_FONT or not need_lo))


def equity_png(rs: list[float], title: str, subtitle: str = "",
               labels: dict | None = None) -> bytes:
    """rs = ผลแต่ละไม้เป็น R เรียงตามเวลาปิด, labels = {"x": ..., "dd": ...} คืนค่าเป็น PNG"""
    lab = labels or EN_LABELS
    x = list(range(len(rs) + 1))
    equity, peak, e, p = [0.0], [0.0], 0.0, 0.0
    for r in rs:
        e += r
        p = max(p, e)
        equity.append(e)
        peak.append(p)

    rc = {"font.family": FONTS}
    with plt.rc_context(rc):
        lines = title.count("\n") + 1
        fig, ax = plt.subplots(figsize=(8, 4.2 + 0.45 * (lines - 1)), dpi=150)
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)

        # พื้นที่ระหว่างจุดสูงสุดเดิมกับเส้นปัจจุบัน = ช่วงที่ยังติด Drawdown
        ax.fill_between(x, equity, peak, color=DRAWDOWN, alpha=0.28, linewidth=0,
                        label=lab["dd"])
        ax.axhline(0, color=TEXT_2, linewidth=0.8, alpha=0.6)
        ax.plot(x, equity, color=LINE, linewidth=2.2, solid_capstyle="round",
                solid_joinstyle="round")

        # ป้ายค่าล่าสุดที่ปลายเส้น
        last = equity[-1]
        ax.scatter([x[-1]], [last], s=46, color=LINE, edgecolors=SURFACE, linewidths=2, zorder=3)
        ax.annotate(f"{last:+.2f}R", (x[-1], last), xytext=(8, 0), textcoords="offset points",
                    va="center", ha="left", color=TEXT, fontsize=11, fontweight="bold")

        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True, nbins=8))
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+g}R" if v else "0R"))
        ax.set_xlabel(lab["x"], color=TEXT_2, fontsize=9)
        ax.set_xlim(0, max(len(rs), 1) * 1.08)   # เว้นที่ให้ป้ายค่าล่าสุด

        if any(q > v for v, q in zip(equity, peak)):
            leg = fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.95), frameon=False,
                             fontsize=9)
            for t in leg.get_texts():
                t.set_color(TEXT_2)

        # วัดขนาดหัวกราฟจริง (ไทย/ลาวสูงไม่เท่ากัน และสองภาษามี 2 บรรทัด)
        # แล้ววางคำบรรยายกับตัวกราฟต่อลงมา ข้อความจึงไม่ทับกัน
        renderer = fig.canvas.get_renderer()
        to_fig = fig.transFigure.inverted()
        head = fig.text(0.06, 0.95, title, color=TEXT, fontsize=14, fontweight="bold", va="top")
        bottom = head.get_window_extent(renderer).transformed(to_fig).y0
        if subtitle:
            sub = fig.text(0.06, bottom - 0.015, subtitle, color=TEXT_2, fontsize=10, va="top")
            bottom = sub.get_window_extent(renderer).transformed(to_fig).y0
        fig.subplots_adjust(left=0.08, right=0.95, top=bottom - 0.07, bottom=0.13)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=SURFACE)
        plt.close(fig)
    return buf.getvalue()
