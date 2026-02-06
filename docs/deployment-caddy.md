# Déploiement HTTPS (Caddy + Vite SPA + FastAPI)

## Caddyfile recommandé

Utiliser le `Caddyfile` fourni à la racine du repo, qui garantit :

- proxy prioritaire de `/api/*` vers `127.0.0.1:8000` (toutes méthodes HTTP, POST inclus),
- proxy prioritaire de `/ws/*` pour les WebSockets,
- fallback SPA React via `try_files {path} /index.html` sans intercepter l'API.

## Variable frontend en production

Le frontend doit pointer vers l'API en **same-origin** :

```env
VITE_API_BASE_URL=/api
```

## Commandes Caddy (Windows)

Démarrage au premier lancement :

```powershell
caddy run --config Caddyfile
# ou
caddy start --config Caddyfile
```

Reload de configuration :

```powershell
caddy reload --config Caddyfile
```

Si `caddy reload` échoue (admin endpoint indisponible), c'est généralement que Caddy n'a pas été lancé avec un process gardant l'API admin active. Relancer via `caddy run --config Caddyfile` puis retenter le `reload`.
