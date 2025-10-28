#!/usr/bin/env python3
"""Helper script to prepare and launch the Vite dev server with one command."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from subprocess import TimeoutExpired

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"



def which(cmd: str) -> str | None:
    from shutil import which as shutil_which

    return shutil_which(cmd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lance le frontend Vite en mode développement"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Option --host à transmettre à Vite (ex: 0.0.0.0)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Ouvre automatiquement le navigateur si supporté",
    )
    return parser.parse_args()


def main() -> int:
    npm_path = which("npm")
    if npm_path is None:
        raise SystemExit("npm doit être installé pour lancer le frontend.")

    args = parse_args()

    install_cmd = [npm_path, "install"]
    print(f"➡️  Installation des dépendances frontend : {' '.join(install_cmd)}")
    subprocess.run(install_cmd, cwd=str(FRONTEND_DIR), check=True)

    command = [npm_path, "run", "dev"]
    extra_args: list[str] = []
    if args.host:
        extra_args.extend(["--host", args.host])
    if args.open:
        extra_args.append("--open")

    if extra_args:
        command.extend(["--", *extra_args])

    env = os.environ.copy()
    print(f"➡️  Lancement du frontend Vite : {' '.join(command)}")

    process = subprocess.Popen(command, cwd=str(FRONTEND_DIR), env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt du frontend...")
        process.terminate()
        try:
            return process.wait(timeout=10)
        except TimeoutExpired:
            process.kill()
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
