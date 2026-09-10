import os
import re
import winreg
from pathlib import Path

def extract_lnk_target(lnk_path):
    try:
        with open(lnk_path, 'rb') as f:
            content = f.read()
        matches = re.findall(rb'[A-Za-z]:\\[^\x00-\x1f\x7f\<\>\"\?:\*\|]+\.exe', content, re.IGNORECASE)
        for m in matches:
            try:
                p = m.decode('utf-8', errors='ignore')
                if os.path.isfile(p):
                    return p
            except Exception:
                pass
        matches16 = re.findall(rb'(?:[A-Za-z]\x00:\x00\\(?:[^\x00-\x1f\x7f\<\>\"\?:\*\|]\x00)+\.e\x00x\x00e\x00)', content, re.IGNORECASE)
        for m in matches16:
            try:
                p = m.decode('utf-16le', errors='ignore')
                if os.path.isfile(p):
                    return p
            except Exception:
                pass
    except Exception:
        pass
    return None

import subprocess

def find_app_binary(name_or_exe: str):
    if not name_or_exe:
        return None
    if os.path.isfile(name_or_exe):
        return str(Path(name_or_exe).resolve())

    name_clean = name_or_exe.lower().replace('.exe', '').strip()
    exe_name = f"{name_clean}.exe"

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe_name}") as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.isfile(val):
                    return val
        except OSError:
            pass

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
            if steam_path:
                sp = Path(steam_path)
                if name_clean == "steam":
                    s_exe = sp / "steam.exe"
                    if s_exe.is_file():
                        return str(s_exe)
                if name_clean in ("cs2", "csgo"):
                    vdf_file = sp / "steamapps" / "libraryfolders.vdf"
                    if vdf_file.exists():
                        lines = vdf_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                        for line in lines:
                            if '"path"' in line:
                                lib_p = line.split('"path"')[1].strip().strip('"').replace("\\\\", "/")
                                cs2_cand = Path(lib_p) / "steamapps/common/Counter-Strike Global Offensive/game/bin/win64/cs2.exe"
                                if cs2_cand.is_file():
                                    return str(cs2_cand)
    except Exception:
        pass

    local_app = os.environ.get("LOCALAPPDATA", "")
    app_data = os.environ.get("APPDATA", "")
    user_prof = os.environ.get("USERPROFILE", "")
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")

    if "discord" in name_clean:
        disc_dir = Path(local_app) / "Discord"
        if disc_dir.is_dir():
            for p in sorted(disc_dir.glob("app-*/Discord.exe"), reverse=True):
                if p.is_file():
                    return str(p)
            upd = disc_dir / "Update.exe"
            if upd.is_file():
                return str(upd)

    if "telegram" in name_clean:
        for cand in [
            Path(user_prof) / "telegram" / "Telegram.exe",
            Path(app_data) / "Telegram Desktop" / "Telegram.exe",
            Path(prog_files) / "Telegram Desktop" / "Telegram.exe",
            Path(prog_files_x86) / "Telegram Desktop" / "Telegram.exe",
        ]:
            if cand.is_file():
                return str(cand)

    if "steam" in name_clean:
        for cand in [
            Path(prog_files_x86) / "Steam" / "steam.exe",
            Path(prog_files) / "Steam" / "steam.exe",
        ]:
            if cand.is_file():
                return str(cand)

    start_dirs = [
        Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    ]
    for sdir in start_dirs:
        if sdir.is_dir():
            for lnk in sdir.rglob("*.lnk"):
                if name_clean in lnk.stem.lower():
                    target = extract_lnk_target(lnk)
                    if target:
                        return target

    import shutil
    w = shutil.which(exe_name)
    if w:
        return w

    return None

def launch_app(app_name: str, exe_path: str) -> None:
    """Launch a GUI app detached from current process with correct working directory."""
    if not exe_path or not os.path.isfile(exe_path):
        raise FileNotFoundError(f"Исполняемый файл не найден: {exe_path}")

    p = Path(exe_path).resolve()
    cwd = str(p.parent)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0

    if "update.exe" in p.name.lower() and "discord" in app_name.lower():
        subprocess.Popen([str(p), "--processStart", "Discord.exe"], cwd=cwd, close_fds=True, **kwargs)
    else:
        subprocess.Popen([str(p)], cwd=cwd, close_fds=True, **kwargs)

def restart_or_launch_app(app_name: str, exe_path: str) -> bool:
    """
    If the application is already running, terminate its old instance so that
    new network sockets are bound inside the active TUN adapter.
    Returns True if an existing instance was restarted, False if it was cleanly started.
    """
    if not exe_path or not os.path.isfile(exe_path):
        raise FileNotFoundError(f"Исполняемый файл не найден: {exe_path}")

    import psutil
    import time
    name_clean = Path(exe_path).name.lower()
    base_name = Path(exe_path).stem.lower()

    was_running = False
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            p_name = (proc.info['name'] or '').lower()
            if p_name == name_clean or p_name == f"{base_name}.exe" or p_name == base_name:
                was_running = True
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if was_running:
        time.sleep(0.4)

    launch_app(app_name, exe_path)
    return was_running

if __name__ == "__main__":
    for app in ["discord", "telegram", "steam", "cs2"]:
        print(f"{app.upper()}: {find_app_binary(app)}")
