# Logging

## Niveaux et variables

- `LOG_LEVEL` contrôle les logs applicatifs et `uvicorn.error` (par défaut `INFO`).
- `ACCESS_LOG_LEVEL` contrôle uniquement `uvicorn.access` (par défaut `WARNING`) pour réduire
  le bruit sur les endpoints de télémétrie.

Pour réactiver le détail des requêtes en debug :

```bash
export ACCESS_LOG_LEVEL=INFO
```

## Access log exclusions

The backend can skip access log entries for noisy telemetry endpoints while keeping
useful request logs enabled. Configure the exclusion list with the
`ACCESS_LOG_EXCLUDE_PATHS` environment variable.

- **Default:** `/logs/frontend,/logs/backend`
- **Matching:** Exact path match after stripping whitespace and query strings.

Example:

```bash
export ACCESS_LOG_EXCLUDE_PATHS="/logs/frontend,/logs/backend"
```

With this setting, requests like `POST /logs/frontend` and
`POST /logs/frontend?batch=true` will not be written to the `uvicorn.access` logs.
