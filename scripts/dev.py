#!/usr/bin/env python3
"""Utility script to bootstrap the backend and frontend dev servers together."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"


Process = subprocess.Popen


def check_prerequisites(frontend: bool) -> None:
    """Ensure required tools are available before launching services."""
    missing: List[str] = []
    if sys.executable is None:
        missing.append("python")
    if frontend and shutil_which("npm") is None:
        missing.append("npm")

    if missing:
        tools = ", ".join(missing)
        raise SystemExit(f"Outils requis manquants: {tools}.")


def shutil_which(cmd: str) -> str | None:
    """Wrapper around shutil.which to delay import cost."""
    from shutil import which

    return which(cmd)


def start_process(command: List[str], cwd: Path, name: str) -> Process:
    env = os.environ.copy()
    print(f"\n➡️  Lancement de {name} : {' '.join(command)}")
    return subprocess.Popen(command, cwd=str(cwd), env=env)


def terminate_process(name: str, process: Process) -> None:
    if process.poll() is None:
        print(f"\n⏹️  Arrêt de {name}...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"\n⛔ Forçage de l'arrêt de {name}")
            process.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lance backend et frontend ensemble")
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="Ne pas lancer le serveur Vite (frontend)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port du backend FastAPI (défaut: 8000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    check_prerequisites(frontend=not args.no_frontend)

    commands: List[Tuple[str, List[str], Path]] = []
    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app:app",
        "--reload",
        "--port",
        str(args.port),
    ]
    commands.append(("backend FastAPI", backend_cmd, BACKEND_DIR))

    if not args.no_frontend:
        frontend_cmd = ["npm", "run", "dev"]
        commands.append(("frontend Vite", frontend_cmd, FRONTEND_DIR))

    processes: Dict[str, Process] = {}

    def handle_signal(signum: int, frame) -> None:  # type: ignore[no-untyped-def]
        print("\nSignal reçu, arrêt des services...")
        for name, process in processes.items():
            terminate_process(name, process)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        for name, command, cwd in commands:
            process = start_process(command, cwd, name)
            processes[name] = process

        while True:
            time.sleep(0.5)
            finished = [name for name, proc in processes.items() if proc.poll() is not None]
            if finished:
                for name in finished:
                    code = processes[name].returncode
                    print(f"\n{name} terminé avec le code {code}.")
                break
    except KeyboardInterrupt:
        handle_signal(signal.SIGINT, None)  # type: ignore[arg-type]
    finally:
        for name, process in processes.items():
            terminate_process(name, process)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
