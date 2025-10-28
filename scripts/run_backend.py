#!/usr/bin/env python3
"""Helper script to prepare and launch the FastAPI dev server with one command."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from subprocess import TimeoutExpired

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
VENV_DIR = BACKEND_DIR / ".venv"
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prépare et lance le backend FastAPI en mode développement",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port sur lequel exposer l'API (défaut: 8000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Adresse d'écoute d'uvicorn (défaut: 127.0.0.1)",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Ne pas installer les dépendances (pip install)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Ne pas exécuter pytest avant le lancement",
    )
    return parser.parse_args()


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_step(description: str, command: list[str], cwd: Path) -> None:
    print(f"➡️  {description} : {' '.join(command)}")
    subprocess.run(command, cwd=str(cwd), check=True)


def main() -> int:
    args = parse_args()
    if not VENV_DIR.exists():
        print("➡️  Création de l'environnement virtuel .venv")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    python_bin = _venv_python()
    if not python_bin.exists():
        raise SystemExit(
            "Python de l'environnement virtuel introuvable. Vérifiez la création de .venv."
        )

    if not args.skip_install:
        if not REQUIREMENTS_FILE.exists():
            raise SystemExit(
                "requirements.txt est introuvable dans le dossier backend."
            )
        run_step(
            "Installation des dépendances",
            [str(python_bin), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            BACKEND_DIR,
        )

    if not args.skip_tests:
        run_step("Exécution des tests", [str(python_bin), "-m", "pytest"], BACKEND_DIR)

    command = [
        str(python_bin),
        "-m",
        "uvicorn",
        "backend.app:app",
        "--reload",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]

    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV_DIR)
    env["PATH"] = f"{python_bin.parent}:{env.get('PATH', '')}" if os.name != "nt" else f"{python_bin.parent};{env.get('PATH', '')}"

    print(f"➡️  Lancement du backend FastAPI : {' '.join(command)}")

    process = subprocess.Popen(command, cwd=str(BACKEND_DIR), env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt du backend...")
        process.terminate()
        try:
            return process.wait(timeout=10)
        except TimeoutExpired:
            process.kill()
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
