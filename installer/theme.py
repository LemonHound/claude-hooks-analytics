from tkinter import ttk

BG = "#1e1f22"
PANEL = "#2b2d31"
FG = "#e6e6e6"
MUTED = "#9aa0a6"
ACCENT = "#3b82f6"


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Heading.TLabel", background=BG, foreground=FG, font=("", 12, "bold"))
    style.configure("TButton", background=PANEL, foreground=FG)
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.configure("Link.TLabel", background=BG, foreground=ACCENT)
    style.configure("TEntry", fieldbackground=PANEL, foreground=FG)
    style.map("TButton", background=[("active", ACCENT)])
    style.map("TCheckbutton", background=[("active", BG)])
