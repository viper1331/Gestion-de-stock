# Gestion Stock Pro 2.0

Ce dépôt contient la refonte moderne de Gestion Stock Pro articulée autour d'un backend FastAPI, d'un frontend React/Vite et d'un empaquetage desktop via Tauri. L'objectif est de conserver la richesse fonctionnelle de l'application Tkinter historique tout en fournissant une architecture maintenable, testable et prête pour le web.

## Structure du projet
```
gestion-stock-pro/
├─ backend/            # API FastAPI + WebSocket + services SQLite
├─ frontend/           # SPA React/TypeScript (Vite, Tailwind, shadcn/ui ready)
├─ desktop/tauri/      # Client desktop Tauri lançant le backend local
├─ scripts/            # Scripts d'aide au développement et au build
└─ README.md           # Ce document
```

### Backend (`backend/`)
- `app.py` : application FastAPI, configuration CORS et enregistrement des routes.
- `api/` : routeurs REST (authentification JWT, catalogue, rapports, configuration, sauvegardes, codes-barres).
- `core/` : accès SQLite, modèles Pydantic, services métiers et sécurité (bcrypt + JWT).
- `ws/` : WebSockets pour le scan caméra et les commandes vocales (ack temps réel).
- `assets/barcodes/` : stockage des PNG générés.
- `requirements.txt` : dépendances Python minimales.
- `tests/` : tests pytest couvrant le healthcheck et le flux de connexion.

### Frontend (`frontend/`)
- Vite + React + TypeScript avec Tailwind configuré en mode sombre par défaut.
- `src/app/` : router, store Zustand et gestion du thème (persisté en localStorage).
- `src/features/` : pages Auth, Inventaire, Codes-barres, Rapports, Paramètres, Voix.
- `src/components/` : layout principal, toggle de thème et composants transverses.
- `src/lib/` : instance Axios (JWT-ready), helpers WebSocket et persistance.
- Tests unitaires avec Vitest + Testing Library.

### Desktop (`desktop/tauri/`)
- Configuration Tauri minimaliste (`src-tauri/tauri.conf.json`, `Cargo.toml`).
- `src/main.rs` : lance le backend FastAPI comme processus enfant et le termine proprement.
- Scripts `pnpm tauri dev/build` pour l'intégration continue.

### Scripts (`scripts/`)
- `dev.ps1` : bootstrap automatique backend + frontend en développement.
- `build_all.ps1` : pipeline de build (backend tests + build frontend + package Tauri).

## Prérequis
- Python 3.10+
- Node.js 18+ et npm/pnpm
- Rust toolchain (pour Tauri)
- SQLite (fourni par Python)

## Installation rapide
```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn backend.app:app --reload
```

```bash
# Frontend
cd frontend
npm install
npm run dev
```

```bash
# Desktop
cd desktop/tauri
npm install
npm run tauri dev
```

## Scripts utiles
- `python scripts/dev.py` : lance simultanément le backend FastAPI (uvicorn) et le frontend Vite. Options : `--no-frontend` pour ne démarrer que l'API et `--port` pour changer le port du backend.
- `pwsh scripts/dev.ps1` : lance FastAPI en mode reload et Vite en parallèle.
- `pwsh scripts/build_all.ps1` : exécute les tests backend, build la SPA et package l'app Tauri.

## Tests
- Backend : `pytest`.
- Frontend : `npm run test` (Vitest, environnement jsdom).

## Données & configuration
- Bases SQLite créées automatiquement dans `backend/data/` (utilisateurs + stock).
- Fichier `backend/config.ini` pour les préférences globales (thème, périphériques audio, etc.).
- Sauvegardes disponibles via l'endpoint `/backup/` (zip horodaté des bases).

## Fonctionnalités couvertes
- Authentification JWT (login, refresh, profil `me`).
- Gestion du catalogue : CRUD articles & catégories, mouvements, seuils.
- Rapports de stock bas + export CSV.
- Génération de codes-barres PNG (mock graphique via Pillow) + suppression.
- Paramètres synchronisés via API config.
- WebSockets caméra/voix (ack JSON) pour intégration future avec le navigateur.
- Persistance UI (thème, largeur colonnes) côté front.

## Données de démonstration
Un administrateur `admin/admin123` est généré automatiquement au premier lancement. Créez vos propres comptes via l'API `/auth`.

## Roadmap & TODO
- Finaliser les composants shadcn/ui et DataGrid avancé.
- Intégrer la génération PDF/CSV côté backend ou frontend.
- Ajouter des tests E2E (Playwright/Cypress).
- Mettre en place une CI GitHub Actions (lint + tests + build).

## Licence
Projet livré sans licence explicite. Veuillez contacter l'auteur pour la redistribution.
