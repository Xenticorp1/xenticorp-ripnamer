"""Main window."""

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import APP, VERSION
from ..config import BAKED_KEY, load_config, save_config
from ..media import VIDEO_EXTS, fmt_bytes, fmt_dur, list_videos, scan_folder
from ..mover import Progress, execute, undo
from ..planner import is_ready, plan, row_kind
from ..tmdb import TMDb, scheme_episodes
from .settings import SettingsDialog
from .theme import Theme, draw_brand, prepare_process, set_window_icon

STANDARD = "Standard seasons"
WHEEL = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def _num(var, default):
    try:
        return int(str(var.get()).strip())
    except ValueError:
        return default


class App:
    def __init__(self, test_hook=None):
        prepare_process()
        self.cfg = load_config()
        self.root = tk.Tk(className="XenticorpRipnamer")  # WM_CLASS, matches the Linux .desktop entry
        self.root.title(f"{APP}  ·  Xenticorp")
        set_window_icon(self.root)
        self.ui_scale = self.cfg.get("ui_scale", "auto")
        self.t = Theme(self.root, self.cfg.get("theme", "dark"), self.ui_scale)
        self.theme_name = self.t.name
        self.t.fit_window(1180, 780, 980, 600)
        self.test_hook = test_hook

        # state
        self.results, self.show, self.groups, self.group_subs = [], None, [], []
        self.files, self.episodes, self.rows, self.overrides = [], [], [], {}
        self._tmdb = None
        self.busy = False
        self.stale = True
        self.job = None           # {"prog", "cancel", "label"} while a rename/undo runs
        self.closing = False

        self._make_vars()
        self._build()
        self._wire()

    # ================================================================= setup

    def _make_vars(self):
        c = self.cfg
        V = tk.StringVar
        self.key_var = V(value=c.get("api_key") or BAKED_KEY)
        self.folder_var = V(value=c.get("last_folder", ""))
        self.search_var = V()
        self.season_var = V(value="1")
        self.start_var = V(value="1")
        self.min_var = V(value=str(c.get("min_minutes", 10)))
        self.scheme_var = V(value=STANDARD)
        self.volume_var = V()
        self.naming_var = V(value="standard")
        self.scheme_hint_var = V(value="Normal TMDb seasons.")
        self.org_var = tk.BooleanVar(value=c.get("organize", False))
        self.lib_var = V(value=c.get("library_root", ""))
        self.status_var = V(value="Pick a rip folder to get started.")
        self.filecount_var = V()
        self.overview_var = V()
        self.showname_var = V()
        self.showmeta_var = V()
        self.job_var = V()

    def _build(self):
        S, P, t = self.t.S, self.t.P, self.t
        outer = ttk.Frame(self.root, padding=S(16))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        # header
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, S(14)))
        header.columnconfigure(0, weight=1)
        self.brand = tk.Canvas(header, height=S(66), bg=P["bg"], highlightthickness=0)
        self.brand.grid(row=0, column=0, sticky="ew")
        ttk.Button(header, text="⚙  Settings", command=self.open_settings).grid(row=0, column=1, sticky="ne",
                                                                                padx=(S(12), 0))
        self._build_left(outer)
        self._build_right(outer)

        # status bar
        bar = ttk.Frame(outer)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(bar, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(bar, text=f"XENTICORP  ·  RIPNAMER v{VERSION}", style="Brand.TLabel").pack(side="right")
        self.spinner = ttk.Progressbar(bar, mode="indeterminate", length=S(140))
        self.menu = tk.Menu(self.root, tearoff=0)

    def _card(self, parent, step, title, row):
        f = ttk.LabelFrame(parent, padding=self.t.S(12), text=f" {step}  {title} ")
        f.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        f.columnconfigure(0, weight=1)
        return f

    def _build_left(self, outer):
        S, P = self.t.S, self.t.P
        # scrollable column
        lo = self.left_outer = ttk.Frame(outer)
        lo.grid(row=1, column=0, sticky="nsew", padx=(0, S(16)))
        lo.rowconfigure(0, weight=1)
        self.lcanvas = tk.Canvas(lo, bg=P["bg"], highlightthickness=0, borderwidth=0)
        self.lcanvas.grid(row=0, column=0, sticky="ns")
        self.lsb = ttk.Scrollbar(lo, orient="vertical", command=self.lcanvas.yview)
        self.lcanvas.configure(yscrollcommand=self.lsb.set)
        left = self.left = ttk.Frame(self.lcanvas)
        left.columnconfigure(0, weight=1)
        self.lcanvas.create_window(0, 0, window=left, anchor="nw")

        # 1 folder
        c1 = self._card(left, "1", "Rip folder", 0)
        fr = ttk.Frame(c1)
        fr.grid(row=0, column=0, sticky="ew")
        fr.columnconfigure(0, weight=1)
        ttk.Entry(fr, textvariable=self.folder_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(fr, text="Browse…", command=self.pick_folder).grid(row=0, column=1)
        ttk.Label(c1, textvariable=self.filecount_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w",
                                                                                 pady=(6, 0))

        # 2 show
        c2 = self._card(left, "2", "Show", 1)
        sb = self.search_box = ttk.Frame(c2)
        sb.grid(row=0, column=0, sticky="ew")
        sb.columnconfigure(0, weight=1)
        sr = ttk.Frame(sb)
        sr.grid(row=0, column=0, sticky="ew")
        sr.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(sr, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_btn = ttk.Button(sr, text="Search", command=self.do_search)
        self.search_btn.grid(row=0, column=1)
        self.results_list = tk.Listbox(sb, height=5, exportselection=False, activestyle="none",
                                       bg=P["list_bg"], fg=P["fg"], selectbackground=P["sel"],
                                       selectforeground=P["fg"] if self.t.name == "dark" else "#000",
                                       highlightthickness=0, borderwidth=0, font=("Segoe UI", 10))
        self.results_list.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        ttk.Label(sb, textvariable=self.overview_var, style="Muted.TLabel", wraplength=S(330),
                  justify="left").grid(row=2, column=0, sticky="w")
        self.select_btn = ttk.Button(sb, text="✔  Select this show", style=self.t.accent_button,
                                     command=self.lock_show, state="disabled")
        self.select_btn.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        lb = self.locked_box = ttk.Frame(c2)
        lb.columnconfigure(0, weight=1)
        ttk.Label(lb, textvariable=self.showname_var, style="Show.TLabel", wraplength=S(260)).grid(
            row=0, column=0, sticky="w")
        ttk.Label(lb, textvariable=self.showmeta_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Button(lb, text="Change", command=self.unlock_show).grid(row=0, column=1, rowspan=2, sticky="e")

        # 3 episodes
        c3 = self._card(left, "3", "Episodes", 2)
        sch = ttk.Frame(c3)
        sch.grid(row=0, column=0, sticky="ew")
        sch.columnconfigure(1, weight=1)
        ttk.Label(sch, text="Numbering").grid(row=0, column=0, sticky="w", pady=3)
        self.scheme_box = ttk.Combobox(sch, textvariable=self.scheme_var, state="readonly", values=[STANDARD],
                                       width=22)
        self.scheme_box.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=3)
        ttk.Label(sch, textvariable=self.scheme_hint_var, style="Muted.TLabel", wraplength=S(330),
                  justify="left").grid(row=1, column=0, columnspan=2, sticky="w")
        g3 = ttk.Frame(c3)
        g3.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        g3.columnconfigure(0, weight=1)
        self.season_lbl = ttk.Label(g3, text="Season")
        self.season_lbl.grid(row=0, column=0, sticky="w", pady=3)
        self.season_spin = ttk.Spinbox(g3, from_=0, to=99, width=6, textvariable=self.season_var)
        self.season_spin.grid(row=0, column=1, sticky="e", padx=(12, 0), pady=3)
        self.volume_box = ttk.Combobox(g3, textvariable=self.volume_var, state="readonly", width=16)
        self.start_lbl = ttk.Label(g3, text="First episode on this disc")
        self.start_lbl.grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(g3, from_=1, to=999, width=6, textvariable=self.start_var).grid(row=1, column=1, sticky="e",
                                                                                    padx=(12, 0), pady=3)
        nb = self.naming_box = ttk.Frame(c3)
        ttk.Label(nb, text="Name files with").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(nb, text="Standard SxxExx (recommended)", value="standard",
                        variable=self.naming_var).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Radiobutton(nb, text="This scheme's numbering", value="scheme",
                        variable=self.naming_var).grid(row=2, column=0, sticky="w", pady=(2, 0))
        ttk.Separator(c3).grid(row=3, column=0, sticky="ew", pady=10)
        ttk.Checkbutton(c3, text="Move into Jellyfin library", variable=self.org_var,
                        command=self.lib_state).grid(row=4, column=0, sticky="w")
        lr = ttk.Frame(c3)
        lr.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        lr.columnconfigure(0, weight=1)
        self.lib_entry = ttk.Entry(lr, textvariable=self.lib_var)
        self.lib_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.lib_btn = ttk.Button(lr, text="Browse…", command=self.pick_lib)
        self.lib_btn.grid(row=0, column=1)
        self.lib_hint = ttk.Label(c3, style="Muted.TLabel", wraplength=S(330), justify="left")
        self.lib_hint.grid(row=6, column=0, sticky="w", pady=(6, 0))

    def _build_right(self, outer):
        S, P = self.t.S, self.t.P
        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        top = ttk.Frame(right)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="4   Preview & rename", style="Step.TLabel").pack(side="left")
        self.counts = {}
        for key in ("skip", "bad", "warn", "ok"):
            self.counts[key] = ttk.Label(top, text="", style=f"{key}.Count.TLabel")
            self.counts[key].pack(side="right", padx=(12, 0))

        tf = ttk.Frame(right)
        tf.grid(row=1, column=0, sticky="nsew")
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        tree = self.tree = ttk.Treeview(tf, columns=("file", "len", "new", "status"), show="headings",
                                        selectmode="browse")
        for c, label, w, stretch in (("file", "Rip file", 130, False), ("len", "Length", 70, False),
                                     ("new", "New name", 340, True), ("status", "Status", 230, False)):
            tree.heading(c, text=label, anchor="w")
            tree.column(c, width=S(w), minwidth=S(60), stretch=stretch, anchor="w")
        for key in ("skip", "warn", "bad", "ok"):
            tree.tag_configure(key, foreground=P[key])
        tree.tag_configure("stripe", background=P["stripe"])
        ysb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        self.empty_lbl = ttk.Label(tf, text="Nothing to preview yet.\n\nPick a folder, select a show, then hit "
                                            "Preview.", style="Muted.TLabel", justify="center")
        self.empty_lbl.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(right, text="Tip: double-click or right-click a row to include / skip it. "
                              "Episodes renumber automatically.", style="Muted.TLabel").grid(row=2, column=0,
                                                                                          sticky="w", pady=(6, 0))
        # job panel (progress + cancel), shown only while renaming/undoing
        jp = self.job_panel = ttk.Frame(right)
        jp.columnconfigure(0, weight=1)
        self.job_bar = ttk.Progressbar(jp, mode="determinate", maximum=1000)
        self.job_bar.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ttk.Button(jp, text="Cancel", command=self.cancel_job)
        self.cancel_btn.grid(row=0, column=1, padx=(S(10), 0))
        ttk.Label(jp, textvariable=self.job_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2,
                                                                           sticky="w", pady=(4, 0))
        acts = ttk.Frame(right)
        acts.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.preview_btn = ttk.Button(acts, text="↻  Preview", command=self.preview)
        self.preview_btn.pack(side="left")
        self.undo_btn = ttk.Button(acts, text="↶  Undo a rename…", command=self.do_undo)
        self.undo_btn.pack(side="left", padx=8)
        self.rename_btn = ttk.Button(acts, text="Rename files", style=self.t.accent_button,
                                     command=self.do_rename, state="disabled")
        self.rename_btn.pack(side="right")

    def _wire(self):
        self.brand.bind("<Configure>", lambda e: draw_brand(self.brand, self.t))
        self.left.bind("<Configure>", self._left_layout)
        self.lcanvas.bind("<Configure>", self._left_layout)
        self.left_outer.bind("<Enter>", lambda e: [self.lcanvas.bind_all(q, self._left_wheel) for q in WHEEL])
        self.left_outer.bind("<Leave>", lambda e: [self.lcanvas.unbind_all(q) for q in WHEEL])
        self.search_entry.bind("<Return>", self.do_search)
        self.results_list.bind("<<ListboxSelect>>", self.on_highlight)
        self.scheme_box.bind("<<ComboboxSelected>>", self.on_scheme)
        self.volume_box.bind("<<ComboboxSelected>>", self.mark_stale)
        self.tree.bind("<Double-1>", lambda e: self.toggle_row(self.tree.identify_row(e.y)))
        self.tree.bind("<Button-3>", self.on_right_click)
        self.folder_var.trace_add("write", self.on_folder_change)
        for v in (self.season_var, self.start_var, self.min_var, self.lib_var, self.naming_var):
            v.trace_add("write", self.mark_stale)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.lib_state()
        self.update_filecount()
        if not self.key_var.get():
            self.set_status("No TMDb key yet. Open ⚙ Settings to add one.")

    def run(self):
        if self.test_hook:
            self.test_hook(self)
        self.root.mainloop()

    # ================================================================= helpers

    def tmdb(self) -> TMDb:
        key = self.key_var.get().strip()
        if not key:
            raise RuntimeError("No TMDb API key set. Click ⚙ Settings to add one.")
        if self._tmdb is None or self._tmdb.key != key:
            self._tmdb = TMDb(key)
        return self._tmdb

    def persist(self):
        self.cfg.update({"api_key": self.key_var.get().strip(), "library_root": self.lib_var.get(),
                         "organize": bool(self.org_var.get()), "last_folder": self.folder_var.get(),
                         "min_minutes": _num(self.min_var, 10), "theme": self.theme_name,
                         "ui_scale": self.ui_scale})
        save_config(self.cfg)

    def set_status(self, msg):
        self.status_var.set(msg)

    def error(self, err):
        self.set_status(str(err))
        messagebox.showerror(APP, str(err))

    def _left_layout(self, _=None):
        w, h = self.left.winfo_reqwidth(), self.left.winfo_reqheight()
        self.lcanvas.configure(width=w, scrollregion=(0, 0, w, h))
        if h > self.lcanvas.winfo_height() + 1:
            self.lsb.grid(row=0, column=1, sticky="ns", padx=(self.t.S(4), 0))
        else:
            self.lsb.grid_remove()
            self.lcanvas.yview_moveto(0)

    def _left_wheel(self, e):
        if self.left.winfo_reqheight() > self.lcanvas.winfo_height() + 1:
            self.lcanvas.yview_scroll(int(-e.delta / 120) if e.delta else (-1 if e.num == 4 else 1), "units")

    # ================================================================= background work

    def set_busy(self, busy: bool):
        self.busy = busy
        for w in (self.search_btn, self.preview_btn, self.undo_btn):
            w.state(["disabled"] if busy else ["!disabled"])
        if busy and not self.job:
            self.spinner.pack(side="right", padx=(0, self.t.S(16)))
            self.spinner.start(12)
        else:
            self.spinner.stop()
            self.spinner.pack_forget()
        self.refresh_buttons()

    def run_task(self, work, done, msg="Working…"):
        """Quick background call (network lookups). done(result, error) runs on the UI thread."""
        if self.busy:
            self.set_status("Still working on the last step. Try again in a moment.")
            return
        self.set_busy(True)
        self.set_status(msg)

        def runner():
            try:
                res, err = work(), None
            except Exception as e:
                res, err = None, e
            self.root.after(0, lambda: (self.set_busy(False), done(res, err)))
        threading.Thread(target=runner, daemon=True).start()

    def run_job(self, work, done, label):
        """Long file job with progress + cancel. work(prog, cancel) runs off-thread."""
        if self.busy:
            return
        prog, cancel = Progress(), threading.Event()
        self.job = {"prog": prog, "cancel": cancel, "label": label}
        self.job_bar["value"] = 0
        self.job_var.set(f"{label}…")
        self.cancel_btn.state(["!disabled"])
        self.job_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.set_busy(True)
        self.set_status(f"{label}…")

        def runner():
            try:
                res, err = work(prog, cancel), None
            except Exception as e:
                res, err = None, e
            self.root.after(0, lambda: self._finish_job(done, res, err))
        threading.Thread(target=runner, daemon=True).start()
        self._poll_job()

    def _poll_job(self):
        if not self.job:
            return
        s = self.job["prog"].snapshot()
        if s["bytes_total"]:
            self.job_bar["value"] = 1000 * s["bytes_done"] / s["bytes_total"]
        elif s["count"]:
            self.job_bar["value"] = 1000 * max(s["index"] - 1, 0) / s["count"]
        if not self.job["cancel"].is_set() and s["count"]:
            text = f"{self.job['label']} {s['index']}/{s['count']}  ·  {s['name']}"
            if s["copying"]:
                text += (f"  ·  copying {fmt_bytes(s['file_done'])} / {fmt_bytes(s['file_total'])}"
                         f"  ·  {fmt_bytes(s['rate'])}/s")
                left = s["bytes_total"] - s["bytes_done"]
                if s["rate"] > 0 and left > 0:
                    secs = left / s["rate"]
                    text += f"  ·  ~{int(secs // 60)}m {int(secs % 60)}s left" if secs >= 60 else \
                            f"  ·  ~{int(secs)}s left"
            self.job_var.set(text)
        self.root.after(150, self._poll_job)

    def _finish_job(self, done, res, err):
        self.job = None
        self.job_panel.grid_remove()
        self.set_busy(False)
        if self.closing:
            self.root.destroy()
            return
        done(res, err)

    def cancel_job(self):
        if self.job:
            self.job["cancel"].set()
            self.cancel_btn.state(["disabled"])
            self.job_var.set("Cancelling… finishing the current block, then stopping. Nothing is left half-copied.")

    def on_close(self):
        if self.job:
            if not messagebox.askyesno(APP, "Files are still being moved. Cancel and quit?\n\n"
                                            "The file in progress is left untouched."):
                return
            self.closing = True
            self.cancel_job()
            return
        self.persist()
        self.root.destroy()

    # ================================================================= state

    def refresh_buttons(self):
        ready = sum(1 for r in self.rows if is_ready(r))
        ok = ready and not self.stale and not self.busy
        self.rename_btn.state(["!disabled"] if ok else ["disabled"])
        self.rename_btn.config(text=f"Rename {ready} file{'s' if ready != 1 else ''}" if ok else "Rename files")
        sel = self.results_list.curselection()
        self.select_btn.state(["!disabled"] if sel and not self.show and not self.busy else ["disabled"])

    def mark_stale(self, *_):
        if self.rows and not self.stale:
            self.stale = True
            self.set_status("Settings changed. Hit Preview again before renaming.")
        self.refresh_buttons()

    def lib_state(self):
        on = self.org_var.get()
        for w in (self.lib_entry, self.lib_btn):
            w.state(["!disabled"] if on else ["disabled"])
        self.lib_hint.config(text="→ Library / Show (Year) [tmdbid-X] / Season NN / …" if on
                             else "Off: files are renamed where they are.")
        self.mark_stale()

    def update_filecount(self, *_):
        raw = self.folder_var.get().strip()
        if raw and Path(raw).is_dir():
            try:
                n = len(list_videos(raw))
            except OSError:
                n = 0
            self.filecount_var.set(f"{n} video file{'s' if n != 1 else ''} found (.mkv / .mp4)" if n
                                   else "No .mkv or .mp4 files in this folder")
        else:
            self.filecount_var.set("")

    def on_folder_change(self, *_):
        self.overrides.clear()
        self.update_filecount()
        self.mark_stale()

    def pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get() or None, title="Folder with .mkv / .mp4 rips")
        if d:
            self.folder_var.set(d)

    def pick_lib(self):
        d = filedialog.askdirectory(initialdir=self.lib_var.get() or None, title="Jellyfin TV library root")
        if d:
            self.lib_var.set(d)

    # ================================================================= show search / lock

    def do_search(self, *_):
        q = self.search_var.get().strip()
        if not q or self.show:
            return

        def done(res, err):
            if err:
                return self.error(err)
            self.persist()  # key worked, remember it
            self.results = res
            self.results_list.delete(0, "end")
            self.overview_var.set("")
            for r in res:
                self.results_list.insert("end", f"  {r['name']}  ({r['year'] or '????'})")
            self.set_status(f"{len(res)} result(s). Highlight one, then click Select." if res
                            else "No matches. Try a shorter name.")
            if res:
                self.results_list.selection_set(0)
                self.on_highlight()
            self.refresh_buttons()
        self.run_task(lambda: self.tmdb().search_tv(q), done, "Searching TMDb…")

    def on_highlight(self, *_):
        sel = self.results_list.curselection()
        if sel:
            r = self.results[sel[0]]
            ov = r["overview"] or "No description."
            self.overview_var.set(f"{r['name']} ({r['year'] or '?'}) · tmdb {r['id']}\n"
                                  f"{ov[:160]}{'…' if len(ov) > 160 else ''}")
        self.refresh_buttons()

    def lock_show(self):
        sel = self.results_list.curselection()
        if not sel:
            return
        s = self.show = self.results[sel[0]]
        self.showname_var.set(s["name"])
        self.showmeta_var.set(f"{s['year'] or 'year ?'}  ·  tmdbid-{s['id']}")
        self.search_box.grid_remove()
        self.locked_box.grid(row=0, column=0, sticky="ew")
        self.set_status(f"Locked to {s['name']}. Set season / first episode, then Preview.")
        self.load_schemes(s["id"])
        self.mark_stale()

    def unlock_show(self):
        if self.busy:
            return
        if self.rows and not messagebox.askyesno(APP, "Change show? This clears the current preview."):
            return
        self.show, self.rows = None, []
        self.reset_schemes()
        self.render()
        self.locked_box.grid_remove()
        self.search_box.grid()
        self.search_entry.focus_set()
        self.set_status("Search for a show.")

    # ================================================================= numbering schemes

    def scheme_index(self) -> int:
        """-1 = standard seasons, else index into self.groups."""
        try:
            return list(self.scheme_box.cget("values")).index(self.scheme_var.get()) - 1
        except ValueError:
            return -1

    def set_scheme_ui(self):
        if self.scheme_index() >= 0:
            self.season_spin.grid_remove()
            self.volume_box.grid(row=0, column=1, sticky="e", padx=(12, 0), pady=3)
            self.season_lbl.config(text="Volume")
            self.start_lbl.config(text="First episode (# in volume)")
            self.naming_box.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        else:
            self.volume_box.grid_remove()
            self.season_spin.grid()
            self.season_lbl.config(text="Season")
            self.start_lbl.config(text="First episode on this disc")
            self.naming_box.grid_remove()

    def reset_schemes(self, hint="Normal TMDb seasons."):
        self.groups, self.group_subs = [], []
        self.scheme_box.config(values=[STANDARD])
        self.scheme_var.set(STANDARD)
        self.scheme_hint_var.set(hint)
        self.set_scheme_ui()

    def load_schemes(self, show_id):
        self.reset_schemes("Checking TMDb for DVD / volume orderings…")

        def work():
            t = self.tmdb()
            t.forget_groups()  # always fresh, so newly added TMDb orderings show up on re-select
            return t.episode_groups(show_id)

        def done(res, err):
            if not self.show or self.show["id"] != show_id:
                return
            if err or not res:
                self.scheme_hint_var.set("Normal TMDb seasons. (No other orderings found.)" if not err else
                                         f"Normal TMDb seasons. (Couldn't check orderings: {err})")
                return
            self.groups = res
            self.scheme_box.config(values=[STANDARD] + [f"{g['type']}: {g['name']}" for g in res])
            self.scheme_hint_var.set(f"Normal TMDb seasons. {len(res)} other ordering(s) in the list.")
        self.run_task(work, done, "Looking up orderings…")

    def on_scheme(self, *_):
        i = self.scheme_index()
        self.set_scheme_ui()
        self.mark_stale()
        if i < 0:
            self.scheme_hint_var.set("Normal TMDb seasons.")
            return
        g = self.groups[i]
        self.scheme_hint_var.set(f"{g['type']} order · {g['groups']} part(s), {g['episodes']} episodes. Loading…")
        self.volume_box.config(values=[])
        self.volume_var.set("")

        def done(res, err):
            if err:
                self.scheme_hint_var.set(f"Couldn't load that ordering: {err}")
                return
            self.group_subs = res
            self.volume_box.config(values=[f"{x['name']}  ({len(x['episodes'])} eps)" for x in res])
            if res:
                self.volume_box.current(0)
            self.scheme_hint_var.set(f"{g['type']} order · {len(res)} part(s). Pick this disc's volume.")
        self.run_task(lambda: self.tmdb().episode_group(g["id"]), done, "Loading ordering…")

    # ================================================================= preview

    def render(self):
        self.tree.delete(*self.tree.get_children())
        c = {"ok": 0, "warn": 0, "bad": 0, "skip": 0}
        lib = self.lib_var.get().strip()
        for i, r in enumerate(self.rows):
            kind = row_kind(r)
            c[kind] += 1
            new = ""
            if r["dest"]:
                try:
                    new = str(Path(r["dest"]).relative_to(lib)) if self.org_var.get() and lib \
                        else Path(r["dest"]).name
                except ValueError:
                    new = Path(r["dest"]).name
            icon = {"ok": "✔ ", "warn": "⚠ ", "bad": "✖ ", "skip": "– "}[kind]
            self.tree.insert("", "end", iid=str(i), tags=(kind, "stripe") if i % 2 else (kind,),
                             values=(r["path"].name, fmt_dur(r["duration"]), new, icon + r["status"]))
        names = {"skip": "skipped", "bad": "blocked", "warn": "check", "ok": "ready"}
        for k, lbl in self.counts.items():
            lbl.config(text=f"{c[k]} {names[k]}" if self.rows and c[k] else "")
        if self.rows:
            self.empty_lbl.place_forget()
        else:
            self.empty_lbl.place(relx=0.5, rely=0.45, anchor="center")
        self.refresh_buttons()

    def replan(self):
        library = self.lib_var.get().strip() if self.org_var.get() else None
        self.rows = plan(self.files, self.episodes, self.show, _num(self.start_var, 1),
                         _num(self.min_var, 10), self.overrides, library)
        self.stale = False
        self.render()
        n = sum(1 for r in self.rows if row_kind(r) == "warn")
        self.set_status("Looks good. Hit Rename when ready." if not n
                        else f"{n} runtime mismatch(es) in orange. Check the order before renaming.")

    def preview(self, *_):
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            return messagebox.showwarning(APP, "Pick a rip folder first (step 1).")
        if not self.show:
            return messagebox.showwarning(APP, "Search and select a show first (step 2).")
        if self.org_var.get() and not self.lib_var.get().strip():
            return messagebox.showwarning(APP, "Pick a library folder, or untick 'Move into Jellyfin library'.")
        self.persist()
        show_id, season = self.show["id"], _num(self.season_var, 1)
        if self.scheme_index() >= 0:
            vi = self.volume_box.current()
            if not self.group_subs or vi < 0:
                return messagebox.showwarning(APP, "Pick a volume for that ordering first.")
            sub, naming = self.group_subs[vi], self.naming_var.get()
            fetch = lambda: scheme_episodes(sub, naming)  # noqa: E731
        else:
            fetch = lambda: self.tmdb().season(show_id, season)  # noqa: E731

        def done(res, err):
            if err:
                return self.error(err)
            self.files, self.episodes = res
            if not self.files:
                self.rows = []
                self.render()
                return self.set_status("No .mkv or .mp4 files in that folder.")
            self.replan()
        self.run_task(lambda: (scan_folder(folder), fetch()), done, "Reading files and episode list…")

    def toggle_row(self, iid):
        if not iid or not self.rows or self.stale or self.busy:
            return
        r = self.rows[int(iid)]
        self.overrides[str(r["path"])] = not r["include"]
        self.replan()

    def on_right_click(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid or not self.rows:
            return
        self.tree.selection_set(iid)
        r = self.rows[int(iid)]
        self.menu.delete(0, "end")
        self.menu.add_command(label="Skip this file" if r["include"] else "Include this file",
                              command=lambda: self.toggle_row(iid))
        self.menu.tk_popup(e.x_root, e.y_root)

    # ================================================================= rename / undo

    def do_rename(self):
        rows = self.rows
        todo = [r for r in rows if is_ready(r)]
        if not todo or self.stale or self.busy:
            return
        warn = sum(1 for r in todo if row_kind(r) == "warn")
        where = (f"{self.scheme_var.get()} › {self.volume_var.get().split('  (')[0]}" if self.scheme_index() >= 0
                 else f"season {_num(self.season_var, 1)}")
        msg = f"Rename {len(todo)} file(s) as {self.show['name']}, {where}?"
        if warn:
            msg += f"\n\n⚠ {warn} have runtime mismatches. Double-check the order."
        if not messagebox.askyesno(APP, msg):
            return
        folder = self.folder_var.get().strip()

        def done(res, err):
            if err:
                return self.error(err)
            n, log, errors, cancelled = res
            self.rows, self.overrides = [], {}
            self.render()
            self.update_filecount()
            head = f"Cancelled after {n} file(s)." if cancelled else f"Renamed {n} file(s)."
            text = head
            if log:
                text += f"\n\nUndo log saved as {log.name}"
            if errors:
                text += "\n\nProblems:\n" + "\n".join(errors[:15])
            self.set_status(head if cancelled else
                            f"Renamed {n} file(s). Next disc: pick the folder and bump 'First episode'.")
            (messagebox.showwarning if errors or cancelled else messagebox.showinfo)(APP, text)
        self.run_job(lambda prog, cancel: execute(rows, folder, prog, cancel), done, "Renaming")

    def do_undo(self):
        f = filedialog.askopenfilename(initialdir=self.folder_var.get() or None, title="Pick an undo log",
                                       filetypes=[("RipNamer undo log", "ripnamer_undo_*.json")])
        if not f or f.endswith(".undone.json"):
            return

        def done(res, err):
            if err:
                return self.error(err)
            n, errors, cancelled = res
            text = f"Restored {n} file(s)."
            if cancelled:
                text += "\n\nCancelled. Run Undo on the same log again to finish."
            if errors:
                text += "\n\nProblems:\n" + "\n".join(errors[:15])
            self.set_status(text.splitlines()[0])
            (messagebox.showwarning if errors or cancelled else messagebox.showinfo)(APP, text)
            self.rows = []
            self.render()
            self.update_filecount()
        self.run_job(lambda prog, cancel: undo(f, prog, cancel), done, "Undoing")

    # ================================================================= settings / restart

    def open_settings(self):
        SettingsDialog(self)

    def restart(self):
        self.persist()
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # fresh unpack for the new process
        for k in list(env):
            if k.startswith(("_PYI", "_MEIPASS")):
                env.pop(k)
        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.abspath(sys.argv[0])]
        subprocess.Popen(args, env=env, close_fds=True)
        self.root.destroy()


def main(test_hook=None):
    App(test_hook).run()
