import importlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class UiImports(unittest.TestCase):
    def test_theme_and_ui_import(self):
        try:
            import tkinter
        except Exception:
            self.skipTest("tkinter not available")
        del tkinter
        theme = importlib.import_module("installer.theme")
        ui = importlib.import_module("installer.ui")
        self.assertTrue(hasattr(theme, "apply_theme"))
        self.assertTrue(hasattr(ui, "run"))


if __name__ == "__main__":
    unittest.main()
