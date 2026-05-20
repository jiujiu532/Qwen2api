#!/usr/bin/env python3
"""
Qwen2api 启动脚本
后端: uvicorn http://localhost:7860
"""
import os
import sys
import subprocess
import time
import signal
import threading
from pathlib import Path

WORKSPACE_DIR = Path(__file__).parent.absolute()
BACKEND_DIR = WORKSPACE_DIR / "backend"
LOGS_DIR = WORKSPACE_DIR / "logs"
DATA_DIR = WORKSPACE_DIR / "data"


def ensure_dirs():
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def check_python():
    if sys.version_info < (3, 10):
        print("[x] Python 3.10+ required, current:", sys.version)
        sys.exit(1)


def install_deps():
    print("[1/2] Installing backend dependencies...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKSPACE_DIR)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
            cwd=BACKEND_DIR,
            env=env,
        )
        print("[ok] Dependencies ready")
    except Exception as e:
        print(f"[!] Dependency install error: {e}")


def kill_port(port: int):
    """Kill any process occupying the given port."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    if pid.isdigit():
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                        print(f"  -> Killed old process on port {port} (PID: {pid})")
                        time.sleep(1)
                        return
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True, timeout=5
            )
            pid = result.stdout.strip()
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True)
                time.sleep(1)
    except Exception:
        pass


def start_backend() -> subprocess.Popen:
    print("[2/2] Starting backend...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKSPACE_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    port = env.get("PORT", "7860")
    kill_port(int(port))

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", "0.0.0.0",
            "--port", port,
            "--workers", "1",
        ],
        cwd=WORKSPACE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    print(f"[ok] Backend started (PID: {proc.pid})")

    ready_event = threading.Event()

    def read_output():
        for line in iter(proc.stdout.readline, b""):
            try:
                decoded = line.decode("utf-8", errors="replace")
            except Exception:
                decoded = str(line)
            print(decoded, end="")
            if "Application startup complete" in decoded:
                ready_event.set()

    threading.Thread(target=read_output, daemon=True).start()

    started = ready_event.wait(timeout=120)
    if not started:
        print("[!] Backend startup timeout, service may not be fully ready")
    else:
        print("[ok] Service ready")

    return proc


def main():
    ensure_dirs()
    check_python()
    install_deps()
    backend_proc = start_backend()

    port = os.environ.get("PORT", "7860")
    print()
    print("=" * 50)
    print("  Qwen2api is running")
    print(f"  Admin:  http://127.0.0.1:{port}/admin/login")
    print(f"  API:    http://127.0.0.1:{port}/v1/chat/completions")
    print(f"  WebUI:  http://127.0.0.1:{port}/webui/chat")
    print("=" * 50)
    print("  Press Ctrl+C to stop")
    print()

    def signal_handler(sig, frame):
        print("\nShutting down...")
        try:
            backend_proc.terminate()
        except Exception:
            pass
        backend_proc.wait()
        print("Service stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            if backend_proc.poll() is not None:
                print(f"[x] Backend exited (code: {backend_proc.returncode})")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if backend_proc.poll() is None:
                backend_proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
