# Logging

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
