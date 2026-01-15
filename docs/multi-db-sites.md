# Multi-DB par site

## Contexte
L’application utilise un modèle multi-sites avec une base SQLite par site :

- `JLL` (base existante)
- `GSM`
- `ST_ELOIS`
- `CENTRAL_ENTITY`

## Fichiers et mapping
Un stockage central (users/core DB) conserve :

- `sites` (mapping `site_key → db_path`)
- `users.site_key` (site assigné, défaut `JLL`)
- `users.admin_active_site_key` (override admin)
- `user_page_layouts`
- `user_site_assignments` / `user_site_overrides` (compatibilité historique)

Les bases de site sont créées automatiquement dans `backend/data/` (ex. `GSM.db`).

### Variable d’environnement
- `JLL_DB_PATH` : chemin explicite vers la base existante JLL.
- Si absent, fallback sur `backend/data/stock.db` (comportement historique).

## Routage runtime
Le site actif est déterminé par ordre de priorité :

1. **Header `X-Site-Key`** (uniquement admin / testing)
2. **Override admin** (UI “Base de Données”, stocké dans `users.admin_active_site_key`)
3. **Site assigné** (`users.site_key`)
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

## Migrations au démarrage
Au démarrage du backend, les migrations sont appliquées automatiquement sur
toutes les bases de site actives (JLL, GSM, ST_ELOIS, CENTRAL_ENTITY). En cas
d'erreur « no such table » détectée en runtime, le middleware déclenche une
réapplication des migrations pour le site concerné, puis retente la requête une fois.

## Notes
- Les migrations sont **additives uniquement** (pas de `DROP` / `RENAME`).
- Les données JLL existantes sont conservées.
