#!/usr/bin/env python3
"""Automate l'installation des dépendances et la génération de l'exécutable.

Ce script installe automatiquement les dépendances listées dans
``requirements.txt`` ainsi que PyInstaller, puis génère un exécutable
``GestionStockPro`` grâce au fichier ``GestionStockPro.spec``.

Utilisation :
    python build_exe.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
SPEC_FILE = ROOT_DIR / "GestionStockPro.spec"


def run_command(command: list[str], description: str) -> None:
    """Exécute une commande système tout en affichant une description."""
    print(f"\n=== {description} ===")
    print("Commande :", " ".join(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(
            f"La commande '{' '.join(command)}' s'est terminée avec le code "
            f"{completed.returncode}. Abandon."
        )


def ensure_requirements() -> None:
    """Installe pip, PyInstaller et les dépendances du projet."""
    # Mise à jour optionnelle de pip pour éviter les incompatibilités.
    run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "Mise à jour de pip")

    # PyInstaller est requis pour générer l'exécutable.
    run_command([sys.executable, "-m", "pip", "install", "pyinstaller"], "Installation de PyInstaller")

    if REQUIREMENTS_FILE.exists():
        run_command(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            "Installation des dépendances du projet",
        )
    else:
        print("Aucun fichier requirements.txt trouvé, étape ignorée.")


def build_executable() -> None:
    """Construit l'exécutable en utilisant le fichier SPEC fourni."""
    if not SPEC_FILE.exists():
        raise SystemExit("Le fichier GestionStockPro.spec est introuvable. Impossible de construire l'exécutable.")

    run_command(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE)],
        "Génération de l'exécutable avec PyInstaller",
    )


def main() -> None:
    ensure_requirements()
    build_executable()
    print("\nExécutable généré avec succès. Les fichiers se trouvent dans le dossier 'dist/'.")


if __name__ == "__main__":
    main()
