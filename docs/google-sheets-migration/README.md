# Migration 100% Google Sheets

Ce dossier contient un kit de demarrage pour construire un systeme de gestion de stock:

1. Materiel incendie
2. Pharmacie
3. Dashboard central unique qui pilote tous les modules

Contraintes respectees:

1. Pas de AppSheet
2. Pas de Apps Script en exploitation quotidienne
3. Pas de QR code / barcode
4. Pilotage centralise via une seule feuille `DASHBOARD`
5. Saisie operationnelle via Google Forms

Mode de deploiement:

1. Deploiement manuel (CSV + formules)
2. Deploiement automatique via Google Apps Script (recommande)

## Architecture recommandee

Pour garder des droits d'acces robustes et une UX centralisee:

1. `DASHBOARD_GLOBAL` (lecture + pilotage)
2. `OPS_INCENDIE_<SITE>` (saisie operationnelle incendie)
3. `OPS_PHARMACIE_<SITE>` (saisie operationnelle pharmacie)

Le dashboard central recupere les donnees via `IMPORTRANGE`.
Les operateurs remplissent les donnees depuis des Google Forms relies aux fichiers OPS.

## Contenu du kit

1. `templates/dashboard/`: onglets du dashboard central
2. `templates/modules/incendie/`: onglets module incendie
3. `templates/modules/pharmacie/`: onglets module pharmacie
4. `formulas/`: formules pretes a coller
5. `security/`: matrice de droits et registre utilisateurs
6. `forms/`: specification des formulaires Google Forms
7. `google-apps-deployer/`: script Apps Script pour deploiement total
8. `google-apps-deployer/dashboard_global_local_v1_light/`: package V1 ultra leger (menu, refresh, health check)

## Mise en place rapide

1. Cree les fichiers Google Sheets:
   - `DASHBOARD_GLOBAL`
   - `OPS_INCENDIE_JLL` (adapter le site)
   - `OPS_PHARMACIE_JLL` (adapter le site)
2. Cree les onglets en important les CSV du dossier `templates/`.
3. Dans `DASHBOARD_GLOBAL`, complete `CONFIG_SOURCES` avec les URLs reelles.
4. Dans `DASHBOARD_GLOBAL`, colle les formules du fichier `formulas/dashboard_formulas.md`.
5. Cree les formulaires selon `forms/FORM_SPEC.md` et connecte les reponses aux fichiers OPS.
6. Dans les fichiers OPS, colle les formules du fichier `formulas/module_formulas.md`.
7. Active les permissions partage Drive selon `security/ACCESS_MATRIX.csv`.

## Mode deploiement automatique (recommande)

1. Ouvre `google-apps-deployer/README.md`.
2. Lance `deployTotalSystem()` dans Google Apps Script.
3. Utilise ensuite uniquement Sheets + Forms.

## Onglets dashboard a creer en priorite

1. `CONFIG_SOURCES`
2. `FORM_LINKS`
3. `NAVIGATION`
4. `KPI_OVERVIEW`
5. `ACTIONS_RAPIDES`
6. `STOCK_CONSOLIDE`
7. `ALERTS_CONSOLIDE`
8. `LOTS_CONSOLIDE`
9. `PURCHASE_CONSOLIDE`

## Regles de gouvernance minimales

1. Les onglets de calcul (`STOCK_VIEW`, `ALERTS`) doivent etre proteges.
2. Seuls les responsables peuvent modifier `ITEMS` et `SUPPLIERS`.
3. Les operateurs saisissent via Google Forms; les onglets `MOVEMENTS*` et `INVENTORY_COUNT*` sont alimentes par formules depuis les onglets `*_RAW`.
4. Le dashboard est en lecture seule pour les utilisateurs non admins.
