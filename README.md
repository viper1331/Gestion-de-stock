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
- `python scripts/run_backend.py` : crée/active `.venv`, installe les dépendances, exécute `pytest` puis lance FastAPI (`--host`/`--port`, `--skip-install`, `--skip-tests`).
- `python scripts/run_frontend.py` : exécute `npm install` puis lance Vite (`--host`/`--open`).
- `python scripts/update_repo.py` : récupère les dernières modifications Git, installe automatiquement les dépendances modifiées et laisse tourner les serveurs déjà lancés.
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

### Administration & sécurité
- Authentification JWT complète (login, refresh, profil `me`).【F:backend/api/auth.py†L27-L60】
- Provision automatique d'un administrateur `admin/admin123` et protection contre sa désactivation ou suppression accidentelle.【F:backend/core/services.py†L144-L188】【F:backend/tests/test_app.py†L392-L460】
- Gestion des utilisateurs (création, mise à jour du rôle/mot de passe, activation) réservée aux administrateurs.【F:backend/api/users.py†L10-L54】
- Droits modulaires fins (`suppliers`, `dotations`, `pharmacy`, etc.) via l'API `/permissions/modules` pour déléguer la vue/l'édition par utilisateur.【F:backend/api/permissions.py†L12-L66】【F:backend/tests/test_app.py†L300-L349】

### Stock & inventaire
- CRUD d'articles avec recherche nom/SKU, tailles, seuils de réapprovisionnement et rattachement à un fournisseur.【F:backend/api/items.py†L12-L42】【F:backend/core/services.py†L309-L358】
- Gestion des catégories et tailles normalisées (tri, suppression des doublons/cases) pour l'habillement.【F:backend/api/categories.py†L11-L41】【F:backend/tests/test_app.py†L549-L597】
- Journal des mouvements (entrées/sorties) avec contrôle des droits et mise à jour du stock en temps réel.【F:backend/api/items.py†L44-L61】【F:backend/core/services.py†L540-L577】
- Création automatique de bons de commande suggérés lorsqu'un article passe sous son seuil et dispose d'un fournisseur, consolidation des quantités sur un ordre existant.【F:backend/core/services.py†L81-L141】【F:backend/tests/test_app.py†L210-L287】
- Modules spécialisés pour l'inventaire véhicules et l'inventaire remises partageant la logique commune (CRUD, catégories, mouvements) et protégés par les mêmes permissions granulaires.【F:backend/app.py†L5-L50】【F:backend/api/vehicle_inventory.py†L1-L112】【F:backend/api/remise_inventory.py†L1-L112】【F:backend/core/services.py†L23-L1132】【F:backend/tests/test_app.py†L1-L1204】

### Fournisseurs & achats
- Module fournisseurs complet (CRUD, consultation, suppression) conditionné par les droits modulaires.【F:backend/api/suppliers.py†L13-L63】
- Stockage des coordonnées (contact, email, téléphone) et liaison aux articles pour déclencher les réapprovisionnements automatiques.【F:backend/core/models.py†L123-L158】【F:backend/core/services.py†L613-L684】

### Dotations & collaborateurs
- Fiches collaborateurs (identité, service, contacts) et allocation d'équipements par collaborateur.【F:backend/api/dotations.py†L15-L67】【F:backend/core/services.py†L687-L858】
- Restitution/restock optionnel lors de la suppression d'une dotation afin de réintégrer le stock.【F:backend/api/dotations.py†L85-L105】【F:backend/tests/test_app.py†L464-L509】

### Pharmacie & consommables
- Inventaire dédié aux produits pharmaceutiques avec dosage, date de péremption et localisation interne.【F:backend/api/pharmacy.py†L15-L57】【F:backend/tests/test_app.py†L512-L546】

### Rapports, exports & sauvegardes
- Rapport « stock bas » filtrable par seuil et export CSV de l'inventaire en un clic.【F:backend/api/reports.py†L15-L26】
- Sauvegarde à la demande des bases SQLite (stock + utilisateurs) en archive ZIP horodatée.【F:backend/api/backup.py†L17-L34】

### Codes-barres & intégrations temps réel
- Génération/suppression de codes-barres PNG Code128 prêts à l'impression.【F:backend/services/barcode.py†L33-L93】
- WebSockets `camera` et `voice` fournissant des accusés JSON pour le scan ou les commandes vocales côté navigateur.【F:backend/ws/camera.py†L9-L17】【F:backend/ws/voice.py†L9-L18】

### Frontend & expérience utilisateur
- SPA React/TypeScript avec thème sombre persistant, store Zustand et helpers Axios/WebSocket centralisés.【F:frontend/src/app/theme.tsx†L1-L36】【F:frontend/src/app/store.ts†L1-L11】【F:frontend/src/lib/api.ts†L1-L23】【F:frontend/src/lib/ws.ts†L1-L6】
- Tests unitaires front (Vitest + Testing Library) et couverture backend (pytest) pour sécuriser les régressions.【F:frontend/package.json†L7-L33】【F:backend/tests/test_app.py†L1-L520】

## Données de démonstration
Un administrateur `admin/admin123` est généré automatiquement au premier lancement. Créez vos propres comptes via l'API `/auth`.

## Roadmap & TODO
- Finaliser les composants shadcn/ui et DataGrid avancé.
- Intégrer la génération PDF/CSV côté backend ou frontend.
- Ajouter des tests E2E (Playwright/Cypress).
- Mettre en place une CI GitHub Actions (lint + tests + build).

## Licence
Projet livré sans licence explicite. Veuillez contacter l'auteur pour la redistribution.
