# Checklist de deploiement final V1 (light)

## 1) Script Apps Script

1. Ouvrir le projet Apps Script lie au dashboard central.
2. Coller les fichiers:
   - `00_config.gs`
   - `10_menu.gs`
   - `20_refresh.gs`
   - `30_health.gs`
   - `40_admin_tools.gs`
   - `appsscript.json`
3. Verifier `GSTK_DASHBOARD_ID`.
4. Sauvegarder, recharger le spreadsheet.

## 2) FORM_LINKS

1. Verifier les 8 cles obligatoires.
2. Verifier `Enabled=TRUE` pour les 4 formulaires V1.
3. Laisser les cles V2 en `Enabled=FALSE`.
4. Renseigner les `FormUrl` quand les formulaires sont crees.

## 3) Tests fonctionnels minimum

1. Menu `GSTK V1` visible apres ouverture.
2. `Refresh consolidations` ne plante pas.
3. `Run system health check` ecrit le tableau dans `SYSTEM_HEALTH_AUDIT`.
4. `STOCK_CONSOLIDE` et `ALERTS_CONSOLIDE` remontent incendie + pharmacie.
5. `LOTS_CONSOLIDE` reste propre meme sans lots.
6. `PURCHASE_CONSOLIDE` reste propre meme sans achats.

## 4) Validation terrain

1. Soumettre 1 mouvement incendie test.
2. Soumettre 1 mouvement pharmacie test.
3. Verifier les impacts sur OPS puis dashboard central.
