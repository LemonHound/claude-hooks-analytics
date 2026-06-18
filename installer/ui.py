import sys
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, Text, filedialog, ttk, END, DISABLED, NORMAL, W

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from installer import core
from installer.manifest import COMPONENTS, managed_scripts
from installer.theme import apply_theme

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


def run():
    defaults = core.default_paths()
    root = Tk()
    root.title("Claude Hooks Analytics Installer")
    root.geometry("780x680")
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
        ttk.Checkbutton(row, text=c["label"], variable=v).pack(side="left")
        ttk.Label(row, text="  " + c["description"], style="Muted.TLabel").pack(side="left")

    tools = [c for c in COMPONENTS if c["kind"] == "tool"]
    if tools:
        ttk.Label(frm, text="Included tools (run from the repo)", style="Muted.TLabel").pack(anchor=W, pady=(8, 2))
        for c in tools:
            ttk.Label(frm, text=f"  {c['label']}: {c['path']}", style="Muted.TLabel").pack(anchor=W)

    status = Text(frm, height=9, wrap="word", bg="#2b2d31", fg="#e6e6e6", insertbackground="#e6e6e6", relief="flat")

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
        log("Run your analytics with:")
        py = sys.executable
        log(f'  "{py}" "{REPO_ROOT / "analytics" / "analyze.py"}" --runs-dir "{runs_var.get()}"')
        log(f'  "{py}" "{REPO_ROOT / "analytics" / "dashboard.py"}" --runs-dir "{runs_var.get()}"')

    ttk.Button(frm, text="Install", command=do_install, style="Accent.TButton").pack(pady=12)
    status.pack(fill="both", expand=True)

    root.mainloop()
