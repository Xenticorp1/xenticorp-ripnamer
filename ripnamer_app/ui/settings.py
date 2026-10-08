"""⚙ Settings dialog: TMDb key, theme, interface size, detection threshold, about."""

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .. import APP, VERSION
from ..config import BAKED_KEY


def _num(s, default):
    try:
        return int(str(s).strip())
    except ValueError:
        return default


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        t = app.t
        win = self.win = tk.Toplevel(app.root)
        win.title("Settings")
        win.transient(app.root)
        win.grab_set()
        win.resizable(False, False)
        body = ttk.Frame(win, padding=t.S(16))
        body.pack(fill="both", expand=True)
        row = 0

        def section(title, hint=None):
            nonlocal row
            if row:
                ttk.Separator(body).grid(row=row, column=0, columnspan=2, sticky="ew", pady=12)
                row += 1
            ttk.Label(body, text=title, style="Step.TLabel").grid(row=row, column=0, sticky="w")
            row += 1
            if hint:
                ttk.Label(body, text=hint, style="Muted.TLabel").grid(row=row, column=0, columnspan=2,
                                                                      sticky="w", pady=(0, 6))
                row += 1

        # --- key
        section("TMDb API key", "v3 API key or v4 read access token · themoviedb.org → Settings → API")
        self.key = tk.StringVar(value=app.key_var.get())
        ke = ttk.Entry(body, textvariable=self.key, show="•", width=52)
        ke.grid(row=row, column=0, sticky="ew")
        show = tk.BooleanVar()
        ttk.Checkbutton(body, text="Show", variable=show,
                        command=lambda: ke.config(show="" if show.get() else "•")).grid(row=row, column=1, padx=(8, 0))
        row += 1
        src = "built into this app" if BAKED_KEY and self.key.get() == BAKED_KEY else \
              "saved" if self.key.get() else "none"
        ttk.Label(body, text=f"Current key: {src}", style="Muted.TLabel").grid(row=row, column=0, sticky="w",
                                                                              pady=(4, 0))
        row += 1
        if BAKED_KEY:
            ttk.Button(body, text="Reset to built-in key", command=lambda: self.key.set(BAKED_KEY)).grid(
                row=row, column=0, sticky="w", pady=(8, 0))
            row += 1

        # --- theme
        section("Theme")
        self.theme = tk.StringVar(value=t.name)
        tr = ttk.Frame(body)
        tr.grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Radiobutton(tr, text="Dark", value="dark", variable=self.theme).pack(side="left")
        ttk.Radiobutton(tr, text="Light", value="light", variable=self.theme).pack(side="left", padx=12)
        row += 1
        if not t.has_sv:
            ttk.Label(body, text="(theme package not bundled)", style="Muted.TLabel").grid(row=row, column=0,
                                                                                          sticky="w")
            row += 1

        # --- size
        section("Interface size", "Saved per device. Auto follows this screen's scaling.")
        self.auto_label = f"Auto ({round(t.auto_scale * 100)}%)"
        choices = [self.auto_label] + [f"{p}%" for p in (100, 125, 150, 175, 200, 250)]
        cur = self.auto_label if app.ui_scale == "auto" else f"{round(float(app.ui_scale) * 100)}%"
        self.size = tk.StringVar(value=cur if cur in choices else self.auto_label)
        ttk.Combobox(body, textvariable=self.size, values=choices, state="readonly", width=14).grid(
            row=row, column=0, sticky="w", pady=(6, 0))
        row += 1

        # --- detection
        section("Detection")
        mr = ttk.Frame(body)
        mr.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(mr, text="Skip files shorter than").pack(side="left")
        self.minutes = tk.StringVar(value=app.min_var.get())
        ttk.Spinbox(mr, from_=0, to=120, width=5, textvariable=self.minutes).pack(side="left", padx=6)
        ttk.Label(mr, text="min  (treats them as extras)").pack(side="left")
        row += 1

        # --- about
        section("About")
        ttk.Label(body, text=f"Xenticorp Ripnamer v{VERSION}").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Label(body, text="This product uses the TMDB API but is not endorsed or certified by TMDB.",
                  style="Muted.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1
        link = ttk.Label(body, text="themoviedb.org", style="Link.TLabel", cursor="hand2")
        link.grid(row=row, column=0, sticky="w", pady=(2, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://www.themoviedb.org/"))
        row += 1

        btns = ttk.Frame(body)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Save", style=t.accent_button, command=self.save).pack(side="right", padx=8)

    def save(self):
        app = self.app
        app.key_var.set(self.key.get().strip())
        app.min_var.set(str(_num(self.minutes.get(), 10)))
        new_scale = "auto" if self.size.get().startswith("Auto") else str(int(self.size.get().rstrip("%")) / 100)
        new_theme = self.theme.get() if app.t.has_sv else app.t.name
        restart = new_theme != app.t.name or new_scale != app.ui_scale
        app.theme_name, app.ui_scale = new_theme, new_scale
        app.persist()
        self.win.destroy()
        if restart and messagebox.askyesno(APP, "Restart RipNamer now to apply the new look?"):
            app.restart()
