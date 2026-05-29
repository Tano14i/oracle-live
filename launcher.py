"""
Launcher for HF Spaces.
- Mounts persistent files from /data to /app
- Starts oracle_live.py as a subprocess (controlled via control.json)
- Starts Streamlit dashboard on port 7860
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
HF_SPACE_REPO = "Fabio14i/oracle-live"

LFS_FILES = [
    "oracle_brain.pkl",
    "Matches.csv",
]
CONTROL_FILE = os.path.join(DATA_DIR, "control.json")
BOT_PROCESS: subprocess.Popen | None = None
BOT_LOCK = threading.Lock()

PERSISTENT_FILES = [
    "Matches.csv",
    "oracle_brain.pkl",
    "oracle_brain_candidate.pkl",
    "oracle_data.db",
    "vip_members.db",
    "live_training_data.csv",
    "web_stats.json",
    "oracle_live.log",
    "missing_teams_queue.json",
    "Performance_Log.csv",
    "EloRatings.csv",
]


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def sync_files_to_data():
    """Copy initial files from /app to /data if they don't exist there yet."""
    for fname in PERSISTENT_FILES:
        src = os.path.join(BASE_DIR, fname)
        dst = os.path.join(DATA_DIR, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def link_data_files():
    """Replace /app files with symlinks pointing to /data."""
    for fname in PERSISTENT_FILES:
        app_path = os.path.join(BASE_DIR, fname)
        data_path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(data_path):
            # create empty placeholder
            open(data_path, "a").close()
        if os.path.exists(app_path) and not os.path.islink(app_path):
            os.remove(app_path)
        if not os.path.islink(app_path):
            os.symlink(data_path, app_path)


def read_control() -> dict:
    try:
        with open(CONTROL_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"bot_enabled": True}


def write_control(data: dict):
    with open(CONTROL_FILE, "w") as f:
        json.dump(data, f)


def start_bot():
    global BOT_PROCESS
    with BOT_LOCK:
        if BOT_PROCESS and BOT_PROCESS.poll() is None:
            return
        log_path = os.path.join(DATA_DIR, "oracle_live.log")
        log_file = open(log_path, "a")
        BOT_PROCESS = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "oracle_live.py")],
            stdout=log_file,
            stderr=log_file,
            cwd=BASE_DIR,
        )


def stop_bot():
    global BOT_PROCESS
    with BOT_LOCK:
        if BOT_PROCESS and BOT_PROCESS.poll() is None:
            BOT_PROCESS.terminate()
            try:
                BOT_PROCESS.wait(timeout=10)
            except subprocess.TimeoutExpired:
                BOT_PROCESS.kill()
        BOT_PROCESS = None


def bot_watcher():
    """Background thread: monitors control.json and restarts bot if it crashes."""
    while True:
        time.sleep(10)
        ctrl = read_control()
        if ctrl.get("bot_enabled", True):
            with BOT_LOCK:
                dead = BOT_PROCESS is None or BOT_PROCESS.poll() is not None
            if dead:
                start_bot()
        else:
            with BOT_LOCK:
                alive = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
            if alive:
                stop_bot()


def resolve_lfs_files():
    """Download actual LFS file content from HF Space repo if only pointer is present."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("huggingface_hub not installed, skipping LFS resolve")
        return
    for fname in LFS_FILES:
        local_path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(local_path):
            continue
        with open(local_path, "rb") as f:
            header = f.read(50)
        if header.startswith(b"version https://git-lfs.github.com"):
            print(f"Downloading LFS file: {fname}")
            try:
                downloaded = hf_hub_download(
                    repo_id=HF_SPACE_REPO,
                    filename=fname,
                    repo_type="space",
                )
                shutil.copy2(downloaded, local_path)
                print(f"  OK: {fname}")
            except Exception as e:
                print(f"  ERROR downloading {fname}: {e}")


def main():
    ensure_data_dir()
    resolve_lfs_files()
    sync_files_to_data()
    link_data_files()

    # Write default control file if missing
    if not os.path.exists(CONTROL_FILE):
        write_control({"bot_enabled": True})

    ctrl = read_control()
    if ctrl.get("bot_enabled", True):
        start_bot()

    watcher = threading.Thread(target=bot_watcher, daemon=True)
    watcher.start()

    # Start Streamlit on port 7860 (HF Spaces default)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m", "streamlit", "run",
            os.path.join(BASE_DIR, "dashboard.py"),
            "--server.port", "7860",
            "--server.address", "0.0.0.0",
            "--server.headless", "true",
            "--server.enableCORS", "false",
            "--server.enableXsrfProtection", "false",
        ],
    )


if __name__ == "__main__":
    main()
