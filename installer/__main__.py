import sys


def main():
    try:
        import tkinter
    except Exception:
        sys.stderr.write("Tkinter is not available. On Debian/Ubuntu install it with 'sudo apt install python3-tk', then retry.\n")
        return 1
    del tkinter
    from installer.ui import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
