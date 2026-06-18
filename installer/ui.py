import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import BooleanVar, Checkbutton, StringVar, Tk, Text, filedialog, ttk, END, DISABLED, NORMAL, W

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from installer import core
from installer.manifest import COMPONENTS, managed_scripts
from installer.theme import apply_theme, ACCENT, BG, FG

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_HOOKS = REPO_ROOT / "hooks"


def _browse_dir(var):
    chosen = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
    if chosen:
        var.set(chosen)


def _browse_file(var):
    chosen = filedialog.askopenfilename(initialfile=var.get())
    if chosen:
        var.set(chosen)


def _open_path(path):
    p = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


def run():
    defaults = core.default_paths()
    root = Tk()
    root.title("Claude Hooks Analytics")
    root.geometry("780x740")
    apply_theme(root)

    hooks_var = StringVar(value=str(defaults["hooks_dir"]))
    runs_var = StringVar(value=str(defaults["runs_dir"]))
    settings_var = StringVar(value=str(defaults["settings_path"]))

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Install locations", style="Heading.TLabel").pack(anchor=W, pady=(0, 8))

    def path_row(label, var, browse):
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Browse", command=lambda: browse(var)).pack(side="left")

    path_row("Hooks dir", hooks_var, _browse_dir)
    path_row("Data dir", runs_var, _browse_dir)
    path_row("settings.json", settings_var, _browse_file)

    ttk.Separator(frm).pack(fill="x", pady=10)
    ttk.Label(frm, text="Components", style="Heading.TLabel").pack(anchor=W, pady=(0, 8))

    comp_vars = {}
    for c in COMPONENTS:
        if c["kind"] == "tool":
            continue
        v = BooleanVar(value=c.get("default_enabled", True))
        comp_vars[c["id"]] = v
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=1)
        Checkbutton(
            row, text=c["label"], variable=v,
            bg=BG, fg=FG, selectcolor=ACCENT,
            activebackground=BG, activeforeground=FG,
            highlightthickness=0, bd=0, anchor="w",
        ).pack(side="left")
        ttk.Label(row, text="  " + c["description"], style="Muted.TLabel").pack(side="left")

    status = Text(frm, height=6, wrap="word", bg="#2b2d31", fg="#e6e6e6", insertbackground="#e6e6e6", relief="flat", state=DISABLED)

    def log(msg):
        status.configure(state=NORMAL)
        status.insert(END, msg + "\n")
        status.configure(state=DISABLED)
        status.see(END)

    def do_install():
        selected = [
            c for c in COMPONENTS
            if c["kind"] in ("hook", "support") and comp_vars.get(c["id"]) is not None and comp_vars[c["id"]].get()
        ]
        try:
            core.install(selected, hooks_var.get(), runs_var.get(), settings_var.get(), sys.executable, SRC_HOOKS, managed_scripts())
        except Exception as exc:
            log(f"Install failed: {exc}")
            return
        log("Install complete.")
        log(f"Hooks -> {hooks_var.get()}")
        log(f"Data  -> {runs_var.get()}")

    ttk.Button(frm, text="Install", command=do_install, style="Accent.TButton").pack(anchor=W, pady=12)
    status.pack(fill="x")

    ttk.Separator(frm).pack(fill="x", pady=10)
    ttk.Label(frm, text="Analytics", style="Heading.TLabel").pack(anchor=W, pady=(0, 8))

    results = ttk.Frame(frm)

    def _show_message(text):
        for w in results.winfo_children():
            w.destroy()
        ttk.Label(results, text=text, style="Muted.TLabel").pack(anchor=W)

    def _run_tool(tool, output_path, on_done):
        cmd = core.analytics_command(sys.executable, REPO_ROOT, tool, runs_var.get(), output_path)

        def work():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
            except Exception as exc:
                root.after(0, lambda: _show_message(f"Failed: {exc}"))
                return
            root.after(0, lambda: on_done(proc))

        threading.Thread(target=work, daemon=True).start()

    def _run_report():
        _show_message("Running report...")
        out = Path(runs_var.get()) / "report.txt"

        def done(proc):
            if proc.returncode != 0:
                _show_message((proc.stderr or "No session data found.").strip())
                return
            try:
                out.write_text(proc.stdout, encoding="utf-8")
            except Exception as exc:
                _show_message(f"Could not save report: {exc}")
                return
            _open_path(out)
            _show_message(f"Opened {out}")

        _run_tool("analyze", None, done)

    def _run_dashboard():
        _show_message("Building dashboard...")
        out = Path(runs_var.get()) / "dashboard.html"

        def done(proc):
            if proc.returncode != 0:
                _show_message((proc.stderr or "No session data found.").strip())
                return
            _open_path(out)
            _show_message(f"Opened {out}")

        _run_tool("dashboard", out, done)

    btns = ttk.Frame(frm)
    btns.pack(fill="x")
    ttk.Button(btns, text="Text report", command=_run_report).pack(side="left")
    ttk.Button(btns, text="Open dashboard", command=_run_dashboard).pack(side="left", padx=8)
    results.pack(fill="x", pady=(8, 0))

    root.mainloop()
