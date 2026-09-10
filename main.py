import sys
import os
import ctypes
from pathlib import Path

def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_if_needed():
    if os.name == "nt" and not is_admin():
        try:
            if getattr(sys, "frozen", False):
                exe = sys.executable
                params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            else:
                exe = sys.executable
                params = f'"{os.path.abspath(sys.argv[0])}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
            if int(ret) > 32:
                sys.exit(0)
        except Exception:
            pass

elevate_if_needed()

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.resolve()

sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FQoF · Nexus")
    app.setApplicationDisplayName("FQoF · Nexus")

    assets_dir = BASE_DIR / "assets"
    app_icon = QIcon()
    for sz in [16, 32, 48, 64, 128, 256, 512, 1024]:
        p = assets_dir / f"icon_{sz}.png" if sz != 1024 else assets_dir / "icon.png"
        if p.exists():
            app_icon.addFile(str(p))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    minimized = any(arg in sys.argv for arg in ("--minimized", "--tray", "-m"))
    if not minimized:
        window.show()
    else:
        if hasattr(window, "tray_icon") and window.tray_icon.isVisible():
            window.tray_icon.showMessage(
                "FQoF · Nexus",
                "Приложение запущено в трее (автозапуск)"
            )

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
