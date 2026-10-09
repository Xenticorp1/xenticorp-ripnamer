"""'Set episode…' dialog: searchable list of the current mode's episodes."""

import tkinter as tk
from tkinter import ttk


def episode_label(e: dict) -> str:
    """'S01E13 · The Parting of the Ways · 45m'"""
    text = f"S{e['season']:02}E{e['episode']:02} · {e['title']}"
    return f"{text} · {e['runtime']}m" if e.get("runtime") else text


class EpisodePicker:
    """Modal picker. on_pick(number) runs when the user chooses an episode."""

    def __init__(self, app, file_name, episodes, current, on_pick):
        self.app, self.episodes, self.on_pick = app, episodes, on_pick
        t, P = app.t, app.t.P
        win = self.win = tk.Toplevel(app.root)
        win.title("Set episode")
        win.transient(app.root)
        win.grab_set()
        body = ttk.Frame(win, padding=t.S(16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        ttk.Label(body, text=f"Episode for {file_name}", style="Step.TLabel").grid(row=0, column=0, sticky="w")
        self.query = tk.StringVar()
        entry = ttk.Entry(body, textvariable=self.query, width=56)
        entry.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        lf = ttk.Frame(body)
        lf.grid(row=2, column=0, sticky="nsew")
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(lf, height=14, exportselection=False, activestyle="none",
                                  bg=P["list_bg"], fg=P["fg"], selectbackground=P["sel"],
                                  selectforeground=P["fg"] if t.name == "dark" else "#000",
                                  highlightthickness=0, borderwidth=0, font=("Segoe UI", 10))
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        ttk.Label(body, text="Type to filter by title or code, e.g. \"S02\" or \"christmas\". "
                             "Later files continue from the one you pick.",
                  style="Muted.TLabel", wraplength=t.S(420), justify="left").grid(row=3, column=0, sticky="w",
                                                                                pady=(6, 0))
        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        self.ok_btn = ttk.Button(btns, text="Set episode", style=t.accent_button, command=self.choose)
        self.ok_btn.pack(side="right", padx=8)

        self.query.trace_add("write", lambda *_: self.fill())
        self.listbox.bind("<Double-1>", lambda e: self.choose())
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.sync_button())
        for w in (entry, self.listbox):
            w.bind("<Return>", lambda e: self.choose())
        win.bind("<Escape>", lambda e: win.destroy())
        entry.bind("<Down>", lambda e: (self.listbox.focus_set(), self.move(1)))
        self.fill(current)
        entry.focus_set()

    def fill(self, select=None):
        """Show the episodes matching the filter; keep (or set) the selection by episode number."""
        sel = self.listbox.curselection()
        keep = select if select is not None else (self.shown[sel[0]]["number"] if sel else None)
        words = self.query.get().lower().split()
        self.shown = [e for e in self.episodes if all(w in episode_label(e).lower() for w in words)]
        self.listbox.delete(0, "end")
        for e in self.shown:
            self.listbox.insert("end", "  " + episode_label(e))
        idx = next((i for i, e in enumerate(self.shown) if e["number"] == keep), 0 if self.shown else None)
        if idx is not None:
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
        self.sync_button()

    def move(self, step):
        sel = self.listbox.curselection()
        if self.shown:
            i = max(0, min(len(self.shown) - 1, (sel[0] + step) if sel else 0))
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
            self.listbox.see(i)

    def sync_button(self):
        self.ok_btn.state(["!disabled"] if self.listbox.curselection() else ["disabled"])

    def choose(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        number = self.shown[sel[0]]["number"]
        self.win.destroy()
        self.on_pick(number)
