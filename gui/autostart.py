r"""
Autostart Manager for FQoF Nexus.
Manages automatic launch on user logon using Windows Registry (HKCU\Run)
and Windows Task Scheduler (for seamless elevated startup without UAC prompt on Windows 10/11).
Also supports Linux XDG autostart (~/.config/autostart).
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Tuple

APP_NAME = "FQoF_Nexus"
TASK_NAME = "FQoF_Nexus"

def get_target_command(minimized: bool = True) -> str:
    """
    Returns the executable command line for startup.
    """
    flag = " --minimized" if minimized else ""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}"{flag}'
    else:
        root_exe = Path(__file__).parent.parent / f"{APP_NAME}.exe"
        if root_exe.exists():
            return f'"{root_exe.resolve()}"{flag}'
        main_py = (Path(__file__).parent.parent / "main.py").resolve()
        py_exe = Path(sys.executable).resolve()
        return f'"{py_exe}" "{main_py}"{flag}'

def is_autostart_enabled() -> bool:
    """
    Returns True if autostart is configured in Registry, Task Scheduler, or Linux autostart.
    """
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except Exception:
            pass

        try:
            res = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME],
                capture_output=True
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        return False
    else:
        desktop_file = Path.home() / ".config" / "autostart" / "fqof_nexus.desktop"
        return desktop_file.exists()

def set_autostart(enable: bool, minimized: bool = True) -> Tuple[bool, str]:
    """
    Enables or disables autostart on system boot/logon.
    """
    if os.name == "nt":
        import winreg
        cmd = get_target_command(minimized=minimized)

        if enable:
            errors = []
            reg_ok = False
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                    reg_ok = True
            except Exception as e:
                errors.append(f"Реестр: {e}")

            try:
                res = subprocess.run(
                    ["schtasks", "/create", "/tn", TASK_NAME, "/tr", cmd, "/sc", "onlogon", "/rl", "highest", "/f"],
                    capture_output=True
                )
                if res.returncode == 0:
                    reg_ok = True
            except Exception as e:
                errors.append(f"Планировщик: {e}")

            if reg_ok:
                return True, "Автозапуск успешно включен"
            return False, f"Ошибка включения автозапуска: {'; '.join(errors)}"

        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, APP_NAME)
            except Exception:
                pass

            try:
                subprocess.run(
                    ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                    capture_output=True
                )
            except Exception:
                pass

            return True, "Автозапуск отключен"

    else:
        desktop_dir = Path.home() / ".config" / "autostart"
        desktop_file = desktop_dir / "fqof_nexus.desktop"
        if enable:
            desktop_dir.mkdir(parents=True, exist_ok=True)
            cmd = get_target_command(minimized=minimized)
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=FQoF Nexus\n"
                f"Exec={cmd}\n"
                "Hidden=false\n"
                "NoDisplay=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            desktop_file.write_text(content, encoding="utf-8")
            return True, "Автозапуск включен (~/.config/autostart)"
        else:
            if desktop_file.exists():
                try:
                    desktop_file.unlink()
                except Exception:
                    pass
            return True, "Автозапуск отключен"
