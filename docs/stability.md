# Stabilité

- Migration et persistance des réglages de sauvegarde par site dans `backup_settings` (clé `site_key`) et chargement des tâches au démarrage.
- Planificateur de sauvegardes stabilisé (état interne, démarrage multi-site, annulation propre des tâches).
- Détection automatique des bases sites existantes au démarrage sans import de sauvegarde.
- Réduction des boucles de rendu dans `EditablePageLayout` et la page Updates.
- `system_config.json` exclu du versionnage (template disponible via `system_config.json.example`).
