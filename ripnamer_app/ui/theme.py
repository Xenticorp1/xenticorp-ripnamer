"""Xenticorp look: palette, interface scaling, fonts, ttk styles, and the drawn logo."""

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .. import VERSION
from ..config import resource
from .fonts import load_fonts

# Xenticorp design system (xenticorp.net): neutral black/gray surfaces; yellow = actions,
# green = live / circuit, rust = danger. Dark is the system; light is an unofficial extra with
# the yellow/green text darkened so it stays readable on white.
PALETTES = {
    "dark": {"bg": "#111111", "panel": "#1c1c1c", "raised": "#181818", "line": "#2a2a2a",
             "fg": "#ffffff", "muted": "#a8a8a8", "skip": "#8a8a8a",
             "action": "#ffd60a", "action_fg": "#111111", "action_hover": "#ffe14d", "focus": "#ffd60a",
             "eyebrow": "#ffd60a", "live": "#3db87a", "live_glow": "#225139", "green_bright": "#2f8a5b",
             "danger": "#a8531a", "danger_text": "#e07a3a", "control": "#4a4a4a",
             "ok": "#3db87a", "warn": "#ffd60a", "bad": "#e07a3a",
             "hover": "#232323", "disabled_bg": "#222222", "disabled_fg": "#6a6a6a",
             "stripe": "#1b1b1b", "list_bg": "#181818", "sel": "#22382d",
             "trace": "#204b36", "trace_hi": "#3db87a", "accent": "#3db87a"},
    "light": {"bg": "#efefed", "panel": "#ffffff", "raised": "#f7f7f5", "line": "#d6d6d2",
              "fg": "#141414", "muted": "#5a5a5a", "skip": "#8c8c8c",
              "action": "#ffd60a", "action_fg": "#111111", "action_hover": "#ffe14d", "focus": "#b08f00",
              "eyebrow": "#806600", "live": "#1f8a55", "live_glow": "#bfe3cf", "green_bright": "#1e7a4a",
              "danger": "#a8531a", "danger_text": "#a8531a", "control": "#b8b8b4",
              "ok": "#1f8a55", "warn": "#806600", "bad": "#a8531a",
              "hover": "#f0f0ee", "disabled_bg": "#ececea", "disabled_fg": "#9a9a9a",
              "stripe": "#fafaf8", "list_bg": "#ffffff", "sel": "#d6efe2",
              "trace": "#c4e4d2", "trace_hi": "#1f8a55", "accent": "#1f8a55"},
}

DISPLAY_FONTS = ("Anton", "Impact", "Archivo Black", "Bahnschrift SemiBold", "Ubuntu Medium", "DejaVu Sans")
BODY_FONTS = ("Montserrat", "Segoe UI", "Ubuntu", "Cantarell", "DejaVu Sans")


def prepare_process():
    """Call before creating Tk: bundled fonts, crisp high-DPI text + own taskbar icon on Windows."""
    load_fonts()
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

        self.name = theme if theme in PALETTES else "dark"
        self.P = PALETTES[self.name]
        self.accent_button = "Accent.TButton"

        # pixel-sized fonts don't follow tk scaling
        for name in tkfont.names(root):
            fo = tkfont.nametofont(name)
            if fo.cget("size") < 0:
                fo.configure(size=round(fo.cget("size") * self.f))

        families = set(tkfont.families(root))
        self.display_family = next((f for f in DISPLAY_FONTS if f in families), "TkDefaultFont")
        self.body_family = body = next((f for f in BODY_FONTS if f in families), "TkDefaultFont")
        for name, size, weight in (("TkDefaultFont", 10, "normal"), ("TkTextFont", 10, "normal"),
                                   ("TkMenuFont", 10, "normal"), ("TkTooltipFont", 9, "normal"),
                                   ("TkHeadingFont", 9, "bold"), ("TkCaptionFont", 10, "bold")):
            try:
                tkfont.nametofont(name).configure(family=body, size=size, weight=weight)
            except tk.TclError:
                pass
        S = self.S
        self.body_bold = tkfont.Font(family=body, size=10, weight="bold")
        self.eyebrow = tkfont.Font(family=body, size=8, weight="bold")
        self.heading = tkfont.Font(family=body, size=11, weight="bold")
        self.display = tkfont.Font(family=self.display_family, size=17)
        self.brand_big = tkfont.Font(family=self.display_family, size=-S(36))
        self.brand_small = tkfont.Font(family=body, size=-S(11), weight="bold")
        self.brand_tiny = tkfont.Font(family=body, size=-S(11))
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
        root, style = self.root, ttk.Style()
        style.theme_use("clam")  # flat base; everything below is the Xenticorp look
        root.configure(bg=P["bg"])
        flat = {"bordercolor": P["line"], "lightcolor": P["raised"], "darkcolor": P["raised"]}

        style.configure(".", background=P["panel"], foreground=P["fg"], fieldbackground=P["raised"],
                        troughcolor=P["raised"], selectbackground=P["sel"], selectforeground=P["fg"],
                        insertcolor=P["fg"], focuscolor=P["focus"], arrowcolor=P["muted"],
                        font="TkDefaultFont", **flat)
        style.map(".", foreground=[("disabled", P["disabled_fg"])])
        # surfaces: window = bg, cards and dialogs = panel
        style.configure("TFrame", background=P["panel"])
        style.configure("Bg.TFrame", background=P["bg"])
        style.configure("Card.TFrame", background=P["panel"], relief="solid", borderwidth=1,
                        bordercolor=P["line"], lightcolor=P["line"], darkcolor=P["line"])
        style.configure("TSeparator", background=P["line"])
        # text
        style.configure("TLabel", background=P["panel"], foreground=P["fg"])
        style.configure("Bg.TLabel", background=P["bg"])
        style.configure("Muted.TLabel", foreground=P["muted"])
        style.configure("Bg.Muted.TLabel", background=P["bg"], foreground=P["muted"])
        style.configure("Empty.TLabel", background=P["list_bg"], foreground=P["muted"])  # on the preview table
        style.configure("Eyebrow.TLabel", foreground=P["eyebrow"], font=self.eyebrow)
        style.configure("Step.TLabel", font=self.heading)
        style.configure("Show.TLabel", font=self.display, foreground=P["fg"])
        style.configure("Brand.TLabel", background=P["bg"], foreground=P["muted"], font=self.brand_tiny)
        style.configure("Count.TLabel", font=self.body_bold)
        style.configure("Link.TLabel", foreground=P["eyebrow"], font=(self.body_family, 9, "underline"))
        for key in ("skip", "bad", "warn", "ok"):
            style.configure(f"{key}.Count.TLabel", foreground=P[key])
        # buttons: ghost (border turns green on hover) and primary (yellow, actions only)
        pad = (S(14), S(6))
        ghost = {"bordercolor": P["control"], "lightcolor": P["panel"], "darkcolor": P["panel"]}
        # clam draws no border at all for relief="flat"; "raised" with bevel colours = fill is a clean 1px edge
        style.configure("TButton", background=P["panel"], foreground=P["fg"], padding=pad, relief="raised",
                        anchor="center", **ghost)
        style.map("TButton", background=[("disabled", P["disabled_bg"]), ("pressed", P["hover"]),
                                         ("active", P["hover"])],
                  bordercolor=[("disabled", P["line"]), ("focus", P["focus"]), ("active", P["live"])],
                  lightcolor=[("pressed", P["hover"]), ("active", P["hover"])],
                  darkcolor=[("pressed", P["hover"]), ("active", P["hover"])],
                  relief=[("pressed", "raised")], foreground=[("disabled", P["disabled_fg"])])
        primary = {"background": P["action"], "bordercolor": P["action"], "lightcolor": P["action"],
                   "darkcolor": P["action"]}
        style.configure("Accent.TButton", foreground=P["action_fg"], font=self.body_bold, padding=pad,
                        relief="raised", **primary)
        style.map("Accent.TButton",
                  background=[("disabled", P["disabled_bg"]), ("pressed", P["action_hover"]),
                              ("active", P["action_hover"])],
                  bordercolor=[("disabled", P["line"]), ("focus", P["fg"]), ("active", P["action_hover"])],
                  lightcolor=[("disabled", P["disabled_bg"]), ("active", P["action_hover"])],
                  darkcolor=[("disabled", P["disabled_bg"]), ("active", P["action_hover"])],
                  relief=[("pressed", "raised")], foreground=[("disabled", P["disabled_fg"])])
        # fields: raised surface, 1px line, yellow focus ring
        field = {"fieldbackground": P["raised"], "foreground": P["fg"], "padding": S(5),
                 "bordercolor": P["control"], "lightcolor": P["raised"], "darkcolor": P["raised"]}
        focus = {"bordercolor": [("focus", P["focus"])], "lightcolor": [("focus", P["focus"])],
                 "darkcolor": [("focus", P["focus"])]}
        for w in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(w, **field)
            style.map(w, fieldbackground=[("disabled", P["disabled_bg"]), ("readonly", P["raised"])],
                      foreground=[("disabled", P["disabled_fg"])], **focus)
        style.configure("TSpinbox", arrowsize=S(10), background=P["raised"])
        style.configure("TCombobox", arrowsize=S(12), background=P["raised"])
        style.map("TCombobox", background=[("active", P["hover"])], selectbackground=[("readonly", P["raised"])],
                  selectforeground=[("readonly", P["fg"])])
        root.option_add("*TCombobox*Listbox.background", P["raised"])
        root.option_add("*TCombobox*Listbox.foreground", P["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", P["sel"])
        root.option_add("*TCombobox*Listbox.selectForeground", P["fg"])
        root.option_add("*TCombobox*Listbox.font", "TkDefaultFont")
        # checkboxes and radio buttons: drawn indicators, yellow when on (the active toggle)
        self._toggle_images(style)
        for w in ("TCheckbutton", "TRadiobutton"):
            style.configure(w, background=P["panel"], foreground=P["fg"], focuscolor=P["focus"])
            style.map(w, background=[("active", P["panel"])])
        # preview table
        body = tkfont.nametofont("TkDefaultFont")
        style.configure("Treeview", background=P["list_bg"], fieldbackground=P["list_bg"], foreground=P["fg"],
                        rowheight=body.metrics("linespace") + S(12), borderwidth=0, **flat)
        style.map("Treeview", background=[("selected", P["sel"])], foreground=[("selected", P["fg"])])
        style.configure("Treeview.Heading", background=P["panel"], foreground=P["muted"], font="TkHeadingFont",
                        relief="flat", padding=(S(6), S(6)), bordercolor=P["line"], lightcolor=P["panel"],
                        darkcolor=P["panel"])
        style.map("Treeview.Heading", background=[("active", P["raised"])])
        # scrollbars, progress
        for w in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(w, background=P["line"], troughcolor=P["raised"], bordercolor=P["raised"],
                            lightcolor=P["line"], darkcolor=P["line"], arrowcolor=P["muted"], gripcount=0,
                            arrowsize=S(12))
            style.map(w, background=[("active", P["skip"])])
        style.configure("TProgressbar", background=P["live"], troughcolor=P["raised"], bordercolor=P["line"],
                        lightcolor=P["live"], darkcolor=P["live"])
        # classic Tk widgets: menus, listboxes
        root.option_add("*Menu.background", P["panel"])
        root.option_add("*Menu.foreground", P["fg"])
        root.option_add("*Menu.activeBackground", P["sel"])
        root.option_add("*Menu.activeForeground", P["fg"])
        root.option_add("*Menu.disabledForeground", P["disabled_fg"])
        root.option_add("*Menu.relief", "flat")
        root.option_add("*Menu.borderWidth", 1)
        root.option_add("*Toplevel.background", P["panel"])

    def _toggle_images(self, style):
        """Checkbox / radio indicators drawn pixel by pixel at the current scale (the stock clam
        check reads as an X, and its edges vanish on dark cards)."""
        P, n, gap = self.P, max(12, self.S(16)), self.S(8)

        def image(paint):  # n x n indicator plus a transparent gap before the label
            img = tk.PhotoImage(master=self.root, width=n + gap, height=n)
            rows = []
            for y in range(n):
                row = []
                for x in range(n + gap):
                    row.append(paint(x + 0.5, y + 0.5) if x < n else None)
                rows.append(row)
            img.put(" ".join("{" + " ".join(c or "#000000" for c in r) + "}" for r in rows))
            for y, r in enumerate(rows):
                for x, c in enumerate(r):
                    if c is None:
                        img.transparency_set(x, y, True)
            return img

        def box(edge, fill, mark=None):
            rad, t = n * 0.18, max(1.0, n / 16)
            def paint(x, y):
                dx, dy = max(rad - x, 0, x - (n - rad)), max(rad - y, 0, y - (n - rad))
                d = (dx * dx + dy * dy) ** 0.5
                if d > rad and (dx and dy):
                    return None
                inner = x > t and y > t and x < n - t and y < n - t and (not (dx and dy) or d < rad - t)
                if mark and inner and _near_check(x / n, y / n, n):
                    return mark
                return fill if inner else edge
            return image(paint)

        def radio(edge, fill, dot=None):
            c, r, t = n / 2, n / 2 - 0.5, max(1.0, n / 16)
            def paint(x, y):
                d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
                if d > r:
                    return None
                if dot and d < n * 0.2:
                    return dot
                return fill if d < r - t else edge
            return image(paint)

        imgs = {
            "box": box(P["control"], P["raised"]), "box_hover": box(P["live"], P["raised"]),
            "box_on": box(P["action"], P["action"], P["action_fg"]),
            "box_off": box(P["line"], P["disabled_bg"]),
            "radio": radio(P["control"], P["raised"]), "radio_hover": radio(P["live"], P["raised"]),
            "radio_on": radio(P["action"], P["action"], P["action_fg"]),
            "radio_off": radio(P["line"], P["disabled_bg"]),
        }
        self._imgs = imgs  # keep references alive
        for kind, base in (("Checkbutton", "box"), ("Radiobutton", "radio")):
            elem = f"Xenticorp.{kind}.indicator"
            if elem not in style.element_names():
                style.element_create(elem, "image", imgs[base],
                                     ("disabled", imgs[f"{base}_off"]), ("selected", imgs[f"{base}_on"]),
                                     ("active", imgs[f"{base}_hover"]), sticky="")
            style.layout(f"T{kind}", [(f"{kind}.padding", {"sticky": "nswe", "children": [
                (elem, {"side": "left", "sticky": ""}),
                (f"{kind}.focus", {"side": "left", "sticky": "w", "children": [
                    (f"{kind}.label", {"sticky": "nswe"})]})]})])

    def listbox_options(self) -> dict:
        """Colours for classic tk.Listbox widgets (show results, episode picker)."""
        P = self.P
        return {"bg": P["list_bg"], "fg": P["fg"], "selectbackground": P["sel"], "selectforeground": P["fg"],
                "highlightthickness": 1, "highlightbackground": P["line"], "highlightcolor": P["focus"],
                "borderwidth": 0, "activestyle": "none", "font": "TkDefaultFont"}


def _near_check(u, v, n) -> bool:
    """Is (u, v) (0-1 box coords) on the checkmark stroke: (.24,.52) -> (.43,.71) -> (.77,.32)."""
    half = max(1.1, n / 11) / n
    for (x0, y0), (x1, y1) in (((.24, .52), (.43, .71)), ((.43, .71), (.77, .32))):
        dx, dy = x1 - x0, y1 - y0
        k = max(0.0, min(1.0, ((u - x0) * dx + (v - y0) * dy) / (dx * dx + dy * dy)))
        if ((u - x0 - k * dx) ** 2 + (v - y0 - k * dy) ** 2) ** 0.5 <= half:
            return True
    return False


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
    """Header: XENTIC(trefoil)RP // RIPNAMER vX.Y.Z in Anton, a yellow eyebrow tagline with a trace,
    green circuit traces, and a green underline under the title (the design system's live accent)."""
    P, S = t.P, t.S
    c.delete("all")
    c.configure(bg=P["bg"])
    w, h = c.winfo_width(), int(c.cget("height"))
    mid, track = S(24), S(2)
    asc, desc = t.brand_big.metrics("ascent"), t.brand_big.metrics("descent")
    cap = asc * 0.78
    x = 0
    for ch in "XENTICORP":
        if ch == "O":
            d = cap * 1.08
            draw_trefoil(c, x + d / 2, mid + S(1), d, P["action"], P["bg"])
            x += d + track
        else:
            item = c.create_text(x, mid, text=ch, font=t.brand_big, fill=P["fg"], anchor="w")
            x = c.bbox(item)[2] + track
    # "//" glows: a soft halo of offset copies behind it
    gx = x + S(12)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-2, 0), (2, 0)):
        c.create_text(gx + S(dx), mid + S(dy), text="//", font=t.brand_big, fill=P["live_glow"], anchor="w")
    item = c.create_text(gx, mid, text="//", font=t.brand_big, fill=P["live"], anchor="w")
    item = c.create_text(c.bbox(item)[2] + S(12), mid, text="RIPNAMER", font=t.brand_big,
                         fill=P["green_bright"], anchor="w")
    title_end = c.bbox(item)[2]
    baseline = c.bbox(item)[3] - desc
    item = c.create_text(title_end + S(10), baseline, text=f"v{VERSION}", font=t.brand_small,
                         fill=P["muted"], anchor="sw")
    x_end = c.bbox(item)[2]
    # eyebrow tagline, followed by a trace line ending in a pad
    tag = c.create_text(0, S(56), text="MAKEMKV RIPS  →  JELLYFIN EPISODE NAMES", font=t.brand_small,
                        fill=P["eyebrow"], anchor="w")
    tx = c.bbox(tag)[2] + S(12)
    if title_end - tx > S(30):
        c.create_line(tx, S(56), title_end - S(6), S(56), fill=P["trace"], width=max(1, S(1)))
        c.create_oval(title_end - S(6), S(53), title_end, S(59), outline=P["live"], width=max(1, S(1)))
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
    c.create_line(0, h - 1, w, h - 1, fill=P["line"])
    c.create_line(0, h - 1, title_end, h - 1, fill=P["live"], width=max(1, S(2)))
