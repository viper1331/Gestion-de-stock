# Multi-DB par site

## Contexte
L’application utilise un modèle multi-sites avec une base SQLite par site :

- `JLL` (base existante)
- `GSM`
- `ST_ELOIS`
- `CENTRAL_ENTITY`

## Fichiers et mapping
Un `core.db` central stocke :

- `sites` (mapping `site_key → db_path`)
- `user_site_assignments`
- `user_site_overrides`
- `user_page_layouts`

Les bases de site sont créées automatiquement dans `backend/data/` (ex. `GSM.db`).

### Variable d’environnement
- `JLL_DB_PATH` : chemin explicite vers la base existante JLL.
- Si absent, fallback sur `backend/data/stock.db` (comportement historique).

## Routage runtime
Le site actif est déterminé par ordre de priorité :

1. **Header `X-Site-Key`** (uniquement admin / testing)
2. **Override admin** (UI “Base de Données”)
3. **Site assigné** dans `core.db`
4. **Fallback** `JLL`

Les non-admin restent toujours sur leur site assigné.

## UI Admin
Dans **Paramètres avancés → Base de Données**, l’admin peut :

- Voir le site assigné et le site actif
- Forcer un site (override)
- Réinitialiser l’override

## Provisioning
Script dédié pour créer les bases et appliquer les migrations :

```
python scripts/provision_sites.py
```

Ce script :
- initialise `core.db`
- crée les bases par site si manquantes
- applique les migrations additivement sur chaque DB

## Notes
- Les migrations sont **additives uniquement** (pas de `DROP` / `RENAME`).
- Les données JLL existantes sont conservées.
