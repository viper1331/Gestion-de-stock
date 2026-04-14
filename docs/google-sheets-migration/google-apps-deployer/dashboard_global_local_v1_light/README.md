# GSTK Dashboard V1 Light (Apps Script minimal)

Ce dossier fournit une version volontairement legere du script du dashboard central GSTK.

Objectif:

1. garder la V1 simple et robuste
2. ne pas utiliser de HTML dialog ou sidebar
3. rester sur un menu simple + checks defensifs
4. limiter les scopes OAuth

## Fichiers

1. `00_config.gs`: constantes + helpers defensifs.
2. `10_menu.gs`: `onOpen()` + menu GSTK V1.
3. `20_refresh.gs`: `refreshDashboardConsolidations()`.
4. `30_health.gs`: `runSystemHealthCheckFromDashboard()`.
5. `40_admin_tools.gs`: outils admin legers.
6. `appsscript.json`: manifeste minimal.

## Fonctions exposees

1. `onOpen()`
2. `buildGSTKMenu_()`
3. `refreshDashboardConsolidations()`
4. `runSystemHealthCheckFromDashboard()`
5. `validateSpreadsheetUrl_()`
6. `safeWriteBlock_()`
7. `openFormLinksSheet_()`

## Deploiement minimal (sans refonte)

1. Ouvrir le projet Apps Script lie au dashboard central.
2. Copier/coller ces fichiers (ou pousser via clasp dans ce meme ordre).
3. Verifier que `GSTK_DASHBOARD_ID` pointe bien vers le dashboard central.
4. Recharger le spreadsheet pour afficher le menu `GSTK V1`.
5. Executer `refreshDashboardConsolidations()`.
6. Executer `runSystemHealthCheckFromDashboard()`.

## Notes

1. Aucun trigger installe automatiquement (hors `onOpen` simple trigger).
2. Aucun scope Drive/Form/userinfo.
3. Aucune auto-reparation complexe.
