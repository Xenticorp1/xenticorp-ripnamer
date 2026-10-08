"""Xenticorp look: palette, interface scaling, fonts, ttk styles, and the drawn logo."""

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ..config import resource

# Cyan on near-black
PALETTES = {
    "dark": {"bg": "#1c1c1c", "fg": "#f0f0f0", "muted": "#9a9a9a", "accent": "#3fd0ff",
             "ok": "#6fd08c", "warn": "#f0b429", "bad": "#ff6b6b", "skip": "#6e6e6e",
             "stripe": "#202020", "list_bg": "#262626", "sel": "#0e4d63",
             "trace": "#16414f", "trace_hi": "#1f6a82"},
    "light": {"bg": "#fafafa", "fg": "#1c1c1c", "muted": "#6b6b6b", "accent": "#0089b3",
              "ok": "#1a7f37", "warn": "#9a6700", "bad": "#cf222e", "skip": "#9a9a9a",
              "stripe": "#f3f3f3", "list_bg": "#ffffff", "sel": "#bdeeff",
              "trace": "#cdeef8", "trace_hi": "#8fd7ee"},
}

BRAND_FONTS = ("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold", "Segoe UI",
               "Ubuntu Medium", "Ubuntu", "Cantarell", "DejaVu Sans")


def prepare_process():
    """Call before creating Tk: crisp high-DPI text + own taskbar icon on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Xenticorp.RipNamer")
        except Exception:
            pass


def set_window_icon(root: tk.Tk):
    try:
        if sys.platform == "win32":
            root.iconbitmap(default=resource("xenticorp.ico"))
        else:
            root._icon = tk.PhotoImage(file=resource("xenticorp.png"))
            root.iconphoto(True, root._icon)
    except Exception:
        pass


class Theme:
    """Applies scale + theme to a root window and exposes S() (scale px), P (palette) and fonts."""

    def __init__(self, root: tk.Tk, theme: str, ui_scale: str):
        self.root = root
        self.auto_scale = max(1.0, root.winfo_fpixels("1i") / 96)
        try:
            f = self.auto_scale if ui_scale == "auto" else float(ui_scale)
        except ValueError:
            f = self.auto_scale
        self.f = min(max(f, 0.75), 3.0)
        root.tk.call("tk", "scaling", self.f * 96 / 72)

        try:
            import sv_ttk
            sv_ttk.set_theme(theme)
            self.has_sv, self.name = True, theme
        except Exception:
            self.has_sv, self.name = False, "light"
        self.P = PALETTES[self.name]
        self.accent_button = "Accent.TButton" if self.has_sv else "TButton"

        # pixel-sized fonts (the theme uses these) don't follow tk scaling
        for name in tkfont.names(root):
            fo = tkfont.nametofont(name)
            if fo.cget("size") < 0:
                fo.configure(size=round(fo.cget("size") * self.f))

        families = set(tkfont.families(root))
        brand = next((fam for fam in BRAND_FONTS if fam in families), "TkDefaultFont")
        body = "Bahnschrift" if "Bahnschrift" in families else brand
        S = self.S
        self.brand_big = tkfont.Font(family=brand, size=-S(30), weight="bold")
        self.brand_small = tkfont.Font(family=body, size=-S(13))
        self.brand_tiny = tkfont.Font(family=body, size=-S(12))
        self._styles()

    def S(self, x) -> int:
        return int(round(x * self.f))

    def fit_window(self, w, h, min_w, min_h):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        S = self.S
        self.root.geometry(f"{min(S(w), int(sw * .94))}x{min(S(h), int(sh * .88))}")
        self.root.minsize(min(S(min_w), int(sw * .9)), min(S(min_h), int(sh * .8)))

    def _styles(self):
        P, S = self.P, self.S
        style = ttk.Style()
        body_font = tkfont.nametofont(str(style.lookup("Treeview", "font") or "TkDefaultFont"))
        style.configure("Treeview", rowheight=body_font.metrics("linespace") + S(10))
        style.map("Treeview", background=[("selected", P["sel"])], foreground=[("selected", P["fg"])])
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Muted.TLabel", foreground=P["muted"])
        style.configure("Step.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Show.TLabel", font=("Segoe UI", 12, "bold"), foreground=P["accent"])
        style.configure("Brand.TLabel", font=self.brand_tiny, foreground=P["trace_hi"])
        style.configure("Count.TLabel", font=("Segoe UI", 10, "bold"))
        for key in ("skip", "bad", "warn", "ok"):
            style.configure(f"{key}.Count.TLabel", foreground=P[key])


def draw_trefoil(c: tk.Canvas, cx, cy, d, color, bg):
    """Xenticorp 'O': radiation trefoil inside a ring, diameter d."""
    n = d / 0.92
    ro, ri = 0.46 * n, 0.40 * n
    rm, th = (ro + ri) / 2, ro - ri
    c.create_oval(cx - rm, cy - rm, cx + rm, cy + rm, outline=color, width=max(1, th))
    r = 0.058 * n
    rb = 5.2 * r
    for centre in (270, 30, 150):  # blades: down, upper-right, upper-left
        c.create_arc(cx - rb, cy - rb, cx + rb, cy + rb, start=centre - 30, extent=60,
                     style="pieslice", fill=color, outline="")
    c.create_oval(cx - 1.5 * r, cy - 1.5 * r, cx + 1.5 * r, cy + 1.5 * r, fill=bg, outline="")
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")


def draw_brand(c: tk.Canvas, t: Theme):
    """Header: XENTIC(trefoil)RP // RIPNAMER, tagline, PCB traces, accent underline."""
    P, S = t.P, t.S
    c.delete("all")
    w, h = c.winfo_width(), int(c.cget("height"))
    mid, track = S(24), S(3)
    desc = t.brand_big.metrics("descent")
    cap = t.brand_big.metrics("ascent") * 0.74
    x = 0
    for ch in "XENTICORP":
        if ch == "O":
            d = cap * 1.22
            draw_trefoil(c, x + d / 2, mid - desc / 2 + S(1), d, P["accent"], P["bg"])
            x += d + track
        else:
            item = c.create_text(x, mid, text=ch, font=t.brand_big, fill=P["accent"], anchor="w")
            x = c.bbox(item)[2] + track
    item = c.create_text(x + S(10), mid, text="//", font=t.brand_big, fill=P["trace_hi"], anchor="w")
    item = c.create_text(c.bbox(item)[2] + S(10), mid, text="RIPNAMER", font=t.brand_big, fill=P["fg"], anchor="w")
    x_end = c.bbox(item)[2]
    c.create_text(0, S(54), text="MAKEMKV RIPS  →  JELLYFIN EPISODE NAMES", font=t.brand_small,
                  fill=P["muted"], anchor="w")
    x0 = x_end + S(36)
    if w - x0 > S(90):
        for i, (yf, jog) in enumerate(((0.22, 1), (0.48, -1), (0.74, 1))):
            y = h * yf
            sx = x0 + i * S(22)
            bend = sx + (w - sx) * (0.35 + 0.15 * i)
            y2 = y + jog * S(10)
            ex = w - S(6) - i * S(26)
            col = P["trace_hi"] if i == 1 else P["trace"]
            c.create_line(sx, y, bend, y, bend + S(10), y2, ex, y2, fill=col, width=max(1, S(2)))
            c.create_oval(sx - S(4), y - S(4), sx + S(4), y + S(4), outline=col, width=max(1, S(2)))
            c.create_oval(ex - S(3), y2 - S(3), ex + S(3), y2 + S(3), fill=col, outline="")
    c.create_line(0, h - 1, w, h - 1, fill=P["trace"])
    c.create_line(0, h - 1, x_end, h - 1, fill=P["accent"], width=max(1, S(2)))
