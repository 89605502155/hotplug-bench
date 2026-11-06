# -*- coding: utf-8 -*-
"""
diaglib -- минимальная библиотека построения блок-схем на Pillow.

Координаты задаются в миллиметрах, растеризация выполняется с
суперсэмплингом (SS) и последующим уменьшением по Ланцошу, итоговый
файл сохраняется в TIFF с заданным разрешением (по умолчанию 600 dpi).

Все соединительные линии ортогональны и задаются явными путевыми
точками; метод check() проверяет, что ни один сегмент не пересекает
внутреннюю область блоков, к которым он не относится.
"""
import os
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "/usr/share/fonts/truetype/liberation"
F_REG = os.path.join(FONT_DIR, "LiberationSans-Regular.ttf")
F_BLD = os.path.join(FONT_DIR, "LiberationSans-Bold.ttf")
F_MON = os.path.join(FONT_DIR, "LiberationMono-Regular.ttf")

INK        = (0, 0, 0)
GREY_LINE  = (105, 105, 105)
LANE_FILL  = (243, 243, 243)
LANE_EDGE  = (150, 150, 150)
BOX_FILL   = (255, 255, 255)
ACC_FILL   = (224, 224, 224)   # выделенные блоки (серый)
CODE_FILL  = (240, 240, 240)   # блоки-пояснения (серый)
WHITE      = (255, 255, 255)


class Fig:
    def __init__(self, w_mm, h_mm, dpi=600, ss=2):
        self.w_mm, self.h_mm, self.dpi, self.ss = w_mm, h_mm, dpi, ss
        self.k = dpi * ss / 25.4                       # пикселей на миллиметр
        self.img = Image.new("RGB",
                             (int(round(w_mm * self.k)), int(round(h_mm * self.k))),
                             WHITE)
        self.d = ImageDraw.Draw(self.img)
        self._fonts = {}
        self.boxes = {}          # id -> (x, y, w, h)
        self.nocross = []        # прямоугольники, которые линии пересекать не должны
        self.segments = []       # (p0, p1, owner_a, owner_b)
        self.overflow = []       # (bid, строка, ширина_мм, доступно_мм)
        self.notes = []          # (первая строка, x0, y0, x1, y1) в мм
        self.lanes = []          # (x, y, w, h)

    # ---------- служебное ----------
    def px(self, v):
        return v * self.k

    def font(self, pt, bold=False, mono=False):
        key = (pt, bold, mono)
        if key not in self._fonts:
            path = F_MON if mono else (F_BLD if bold else F_REG)
            self._fonts[key] = ImageFont.truetype(path, int(round(pt * self.dpi * self.ss / 72.0)))
        return self._fonts[key]

    def _xy(self, x, y):
        return (self.px(x), self.px(y))

    # ---------- примитивы ----------
    def text(self, x, y, s, pt=7.0, bold=False, mono=False, anchor="mm",
             fill=INK, spacing_mm=0.0):
        self.d.multiline_text(self._xy(x, y), s, font=self.font(pt, bold, mono),
                              fill=fill, anchor=anchor, align="center",
                              spacing=self.px(spacing_mm))

    def lane(self, x, y, w, h, title, pt=8.0):
        self.d.rounded_rectangle([self._xy(x, y), self._xy(x + w, y + h)],
                                 radius=self.px(1.8), fill=LANE_FILL,
                                 outline=LANE_EDGE, width=max(1, int(self.px(0.22))))
        self.text(x + w / 2.0, y + 3.1, title, pt=pt, bold=True, fill=(60, 60, 60))
        self.lanes.append((x, y, w, h))
        tw = self.font(pt, True).getlength(title) / self.k
        if tw > w - 2.0:
            self.overflow.append(("lane", title, round(tw, 1), round(w - 2.0, 1)))

    def box(self, bid, x, y, w, h, lines, pt=6.6, fill=BOX_FILL, title=None,
            title_pt=6.9, mono_from=None, grey_from=None, radius=1.2, lw=0.30):
        """lines -- список строк; mono_from -- индекс, с которого строки
        печатаются моноширинным шрифтом; grey_from -- индекс, с которого
        строки печатаются серым (пояснение, а не основной текст)."""
        self.d.rounded_rectangle([self._xy(x, y), self._xy(x + w, y + h)],
                                 radius=self.px(radius), fill=fill,
                                 outline=INK, width=max(1, int(self.px(lw))))
        seq = list(lines)
        lh = pt * 25.4 / 72.0 * 1.28          # межстрочный интервал, мм
        n = len(seq) + (1 if title else 0)
        # --- контроль вместимости: ширина строк и суммарная высота ---
        pad = 1.6
        avail = w - 2 * pad
        for i, s in enumerate([title] if title else []):
            tw = self.font(title_pt, True).getlength(s) / self.k
            if tw > avail:
                self.overflow.append((bid, s, round(tw, 1), round(avail, 1)))
        for i, s in enumerate(seq):
            mono = (mono_from is not None and i >= mono_from)
            tw = self.font(pt - (0.5 if mono else 0), False, mono).getlength(s) / self.k
            if tw > avail:
                self.overflow.append((bid, s, round(tw, 1), round(avail, 1)))
        if n * lh > h - 1.2:
            self.overflow.append((bid, "<высота>", round(n * lh, 1), round(h - 1.2, 1)))
        total = n * lh
        cy = y + h / 2.0 - total / 2.0 + lh / 2.0
        if title:
            self.text(x + w / 2.0, cy, title, pt=title_pt, bold=True)
            cy += lh
        for i, s in enumerate(seq):
            mono = (mono_from is not None and i >= mono_from)
            grey = mono or (grey_from is not None and i >= grey_from)
            self.text(x + w / 2.0, cy, s, pt=pt - (0.5 if grey else 0), mono=mono,
                      fill=(80, 80, 80) if grey else INK)
            cy += lh
        self.boxes[bid] = (x, y, w, h)
        self.nocross.append((bid, x, y, w, h))
        return bid

    # ---------- соединения ----------
    def _head(self, p_from, p_to, size=1.9):
        (x0, y0), (x1, y1) = p_from, p_to
        dx, dy = x1 - x0, y1 - y0
        ln = max((dx * dx + dy * dy) ** 0.5, 1e-9)
        ux, uy = dx / ln, dy / ln
        bx, by = x1 - ux * size, y1 - uy * size
        nx, ny = -uy, ux
        pts = [(x1, y1),
               (bx + nx * size * 0.42, by + ny * size * 0.42),
               (bx - nx * size * 0.42, by - ny * size * 0.42)]
        self.d.polygon([self._xy(*p) for p in pts], fill=INK)

    def link(self, pts, owners=(), lw=0.30, head=True, dashed=False):
        """Ортогональная ломаная по точкам pts (мм). owners -- id блоков,
        внутренние области которых данной линии разрешено касаться."""
        w = max(1, int(self.px(lw)))
        for a, b in zip(pts, pts[1:]):
            if dashed:
                self._dash(a, b, w)
            else:
                self.d.line([self._xy(*a), self._xy(*b)], fill=INK, width=w,
                            joint="curve")
            self.segments.append((a, b, owners))
        if head:
            self._head(pts[-2], pts[-1])

    def _dash(self, a, b, w, dash=1.1, gap=0.9):
        (x0, y0), (x1, y1) = a, b
        ln = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if ln < 1e-9:
            return
        ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
        t = 0.0
        while t < ln:
            t2 = min(t + dash, ln)
            self.d.line([self._xy(x0 + ux * t, y0 + uy * t),
                         self._xy(x0 + ux * t2, y0 + uy * t2)], fill=INK, width=w)
            t += dash + gap

    def badge(self, x, y, n, r=2.45, pt=7.0):
        self.d.ellipse([self._xy(x - r, y - r), self._xy(x + r, y + r)],
                       fill=WHITE, outline=INK, width=max(1, int(self.px(0.34))))
        self.text(x, y - 0.06, str(n), pt=pt, bold=True)
        self.nocross.append(("badge%s" % n, x - r, y - r, 2 * r, 2 * r))

    def label(self, x, y, s, pt=5.8, anchor="mm"):
        """Короткая подпись к стрелке на белой подложке (без проверки наложений)."""
        font = self.font(pt, False, False)
        bb = self.d.textbbox(self._xy(x, y), s, font=font, anchor=anchor)
        pad = self.px(0.5)
        self.d.rectangle([bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad], fill=WHITE)
        self.d.text(self._xy(x, y), s, font=font, fill=(60, 60, 60), anchor=anchor)

    def note(self, x, y, s, pt=6.0, anchor="la", fill=(70, 70, 70), mono=False):
        font = self.font(pt, False, mono)
        self.d.multiline_text(self._xy(x, y), s, font=font, fill=fill,
                              anchor=anchor, align="left", spacing=self.px(0.5))
        bb = self.d.multiline_textbbox(self._xy(x, y), s, font=font, anchor=anchor,
                                       spacing=self.px(0.5))
        self.notes.append((s.split("\n")[0], bb[0] / self.k, bb[1] / self.k,
                           bb[2] / self.k, bb[3] / self.k))

    # ---------- контроль качества ----------
    def check(self, margin=0.45):
        """Возвращает список пересечений линий с блоками."""
        bad = []
        for a, b, owners in self.segments:
            for item in self.nocross:
                bid, bx, by, bw, bh = item
                if bid in owners or str(bid).startswith("badge"):
                    continue
                if _seg_rect(a, b, bx + margin, by + margin,
                             bx + bw - margin, by + bh - margin):
                    bad.append((bid, a, b))
        return bad

    def check_notes(self):
        """Заметки не должны накладываться на блоки, заголовки дорожек
        и выходить за пределы листа."""
        bad = []
        def inter(a, b):
            return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
        for name, x0, y0, x1, y1 in self.notes:
            r = (x0, y0, x1, y1)
            if x0 < 0 or y0 < 0 or x1 > self.w_mm or y1 > self.h_mm:
                bad.append(("лист", name))
            for bid, (bx, by, bw, bh) in self.boxes.items():
                if inter(r, (bx, by, bx + bw, by + bh)):
                    bad.append((bid, name))
            for lx, ly, lw, lh in self.lanes:
                if inter(r, (lx, ly, lx + lw, ly + 6.2)):
                    bad.append(("заголовок дорожки", name))
                if inter(r, (lx - 0.3, ly, lx + 0.3, ly + lh)) or inter(r, (lx + lw - 0.3, ly, lx + lw + 0.3, ly + lh)):
                    bad.append(("граница дорожки", name))
        return bad

    def report(self):
        """Единый отчёт контроля качества; пустой список -- схема корректна."""
        return {"collisions": self.check(), "overflow": self.overflow,
                "notes": self.check_notes()}

    def save(self, path):
        out = self.img.resize((int(round(self.w_mm * self.dpi / 25.4)),
                               int(round(self.h_mm * self.dpi / 25.4))),
                              Image.LANCZOS) if self.ss != 1 else self.img
        out.save(path, format="TIFF", dpi=(self.dpi, self.dpi),
                 compression="tiff_lzw")
        return path


def _seg_rect(p, q, x0, y0, x1, y1):
    """Пересекает ли отрезок p-q внутренность прямоугольника."""
    if x1 <= x0 or y1 <= y0:
        return False
    (px_, py), (qx, qy) = p, q
    t0, t1 = 0.0, 1.0
    dx, dy = qx - px_, qy - py
    for pp, qq in ((-dx, px_ - x0), (dx, x1 - px_), (-dy, py - y0), (dy, y1 - py)):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
        else:
            r = qq / pp
            if pp < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t1 - t0 > 1e-9


def stage(f, n, x, y, w, h, title, body, ref=None, fill=BOX_FILL,
          pt=6.4, title_pt=6.8, bid=None):
    """Нумерованный блок-этап: заголовок, пояснение и ссылка на исходный код."""
    bid = bid or ("b%s" % n)
    lines = list(body) + ([ref] if ref else [])
    f.box(bid, x, y, w, h, lines, title=title,
          mono_from=len(body) if ref else None, fill=fill, pt=pt, title_pt=title_pt)
    if n is not None:
        f.badge(x + 1.6, y + 1.5, n, r=2.35, pt=6.8)
    return bid
