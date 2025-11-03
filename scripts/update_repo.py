#!/usr/bin/env python3
"""Automatise la mise à jour du dépôt et l'installation des dépendances."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"


class CommandError(RuntimeError):
    """Raised when a subprocess exits with a non-zero status."""


def run_command(command: Iterable[str], cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command with optional output capture."""
    cwd = cwd or ROOT_DIR
    printable = " ".join(command)
    print(f"\n➡️  Exécution: {printable}")
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        message = [f"La commande '{printable}' a échoué avec le code {exc.returncode}."]
        if stdout:
            message.append(f"Sortie standard:\n{stdout}")
        if stderr:
            message.append(f"Sortie d'erreur:\n{stderr}")
        raise CommandError("\n".join(message)) from exc

    return completed


def ensure_clean_worktree(allow_dirty: bool) -> None:
    if allow_dirty:
        return
    status = run_command(["git", "status", "--porcelain"], capture=True)
    if status.stdout.strip():
        raise SystemExit(
            "Le dépôt contient des modifications locales. Validez/annulez-les ou "
            "relancez la commande avec --allow-dirty."
        )


def current_revision() -> str:
    return (
        run_command(["git", "rev-parse", "HEAD"], capture=True)
        .stdout.strip()
    )


def changed_files(old_rev: str, new_rev: str) -> list[str]:
    diff = run_command(["git", "diff", "--name-only", f"{old_rev}..{new_rev}"], capture=True)
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def backend_python_executable() -> str:
    if os.name == "nt":
        candidate = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = BACKEND_DIR / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable or "python"


def install_backend_dependencies() -> None:
    python_exe = backend_python_executable()
    run_command([python_exe, "-m", "pip", "install", "-r", "requirements.txt"], cwd=BACKEND_DIR)


def install_frontend_dependencies() -> None:
    run_command(["npm", "install"], cwd=FRONTEND_DIR)


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Met à jour le dépôt local et les dépendances.")
    parser.add_argument(
        "--branch",
        default="main",
        help="Branche distante à synchroniser (défaut: main).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Autorise une working tree non vide (utiliser avec précaution).",
    )
    parser.add_argument(
        "--skip-backend-install",
        action="store_true",
        help="N'installe pas les dépendances Python même si requirements.txt a changé.",
    )
    parser.add_argument(
        "--skip-frontend-install",
        action="store_true",
        help="N'installe pas les dépendances npm même si package.json/lock a changé.",
    )
    parser.add_argument(
        "--force-install",
        action="store_true",
        help="Force la réinstallation des dépendances backend et frontend.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_clean_worktree(args.allow_dirty)

    start_rev = current_revision()

    run_command(["git", "fetch", "origin", args.branch])
    run_command(["git", "pull", "--ff-only", "origin", args.branch])

    end_rev = current_revision()
    if start_rev == end_rev:
        print("\n✅ Aucun changement détecté : le dépôt est déjà à jour.")
        if args.force_install:
            if not args.skip_backend_install:
                install_backend_dependencies()
            if not args.skip_frontend_install:
                install_frontend_dependencies()
        return 0

    files = changed_files(start_rev, end_rev)
    if files:
        print("\nFichiers modifiés lors de la mise à jour :")
        for path in files:
            print(f"  • {path}")

    backend_changed = args.force_install or any(
        path.startswith("backend/") and Path(path).name in {"requirements.txt", "pyproject.toml"}
        for path in files
    )
    frontend_changed = args.force_install or any(
        path.startswith("frontend/")
        and Path(path).name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
        for path in files
    )

    if backend_changed and not args.skip_backend_install:
        print("\n📦 Mise à jour des dépendances backend...")
        install_backend_dependencies()

    if frontend_changed and not args.skip_frontend_install:
        print("\n📦 Mise à jour des dépendances frontend...")
        install_frontend_dependencies()

    print("\n✅ Mise à jour terminée. Les serveurs en cours d'exécution rechargeront automatiquement leurs fichiers.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CommandError as error:
        raise SystemExit(str(error))
