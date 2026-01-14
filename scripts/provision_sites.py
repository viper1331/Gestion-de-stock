"""Provisionne les bases de données multi-sites."""
from __future__ import annotations

from backend.core import db, services


def main() -> None:
    db.init_databases()
    services.apply_site_schema_migrations()
    site_paths = db.list_site_db_paths()
    print("Provisioning terminé. Sites disponibles:")
    for site_key, path in site_paths.items():
        print(f"- {site_key}: {path}")


if __name__ == "__main__":
    main()
