import os
import sys
import subprocess
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
ICON_PATH = ROOT_DIR / "assets" / "icon.ico"

def build():
    print("=" * 60)
    print("Building FQoF Nexus Standalone Executable (.exe)")
    print("=" * 60)

    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            print(f"Cleaning {d}...")
            shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--name", "FQoF_Nexus",
        f"--icon={str(ICON_PATH)}",
        f"--add-data={str(ROOT_DIR / 'bin')};bin",
        f"--add-data={str(ROOT_DIR / 'assets')};assets",
        f"--add-data={str(ROOT_DIR / 'wintun.dll')};.",
        f"--add-data={str(ROOT_DIR / 'ru-bypass.json')};.",
    ]
    if (ROOT_DIR / "secrets.json").exists():
        cmd.append(f"--add-data={str(ROOT_DIR / 'secrets.json')};.")

    cmd.extend([
        "--hidden-import=PyQt6",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=sqlite3",
        "--hidden-import=winreg",
        "--hidden-import=ctypes",
        "--hidden-import=psutil",
        "--hidden-import=gui.secrets",
        "--hidden-import=gui.presets",
        "--hidden-import=gui.backend",
        "--hidden-import=gui.system_proxy",
        "--hidden-import=gui.profile_manager",
        "--hidden-import=gui.theme",
        "--hidden-import=gui.app_finder",
        "--hidden-import=gui.autostart",
        str(ROOT_DIR / "main.py")
    ])

    print("Running command:")
    print(" ".join(cmd))
    print("-" * 60)

    res = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if res.returncode != 0:
        print("\n[ERROR] Build failed!")
        sys.exit(res.returncode)

    exe_path = DIST_DIR / "FQoF_Nexus.exe"
    if exe_path.exists():
        root_exe = ROOT_DIR / "FQoF_Nexus.exe"
        try:
            shutil.copy2(exe_path, root_exe)
        except Exception as e:
            print(f"Warning copying to root: {e}")
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("=" * 60)
        print(f"[SUCCESS] Executable built successfully!")
        print(f"Location: {exe_path}")
        print(f"Root Copy: {root_exe}")
        print(f"Size: {size_mb:.2f} MB")
        print("UAC Admin Manifest: Enabled (--uac-admin)")
        print("=" * 60)
    else:
        print("[ERROR] Executable not found in dist/")
        sys.exit(1)

if __name__ == "__main__":
    build()
