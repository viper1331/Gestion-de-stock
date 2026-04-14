# Specification Google Forms V1 (GSTK)

Objectif:

1. conserver une saisie terrain ultra legere
2. injecter directement dans les onglets `*_RAW`
3. respecter strictement l'ordre des colonnes attendues

## Regles globales

1. Ne pas ajouter de question intermediaire non prevue.
2. Garder exactement l'ordre ci-dessous (mappage par position).
3. Connecter chaque formulaire a la feuille OPS cible (pas au dashboard central).
4. Nommer l'onglet reponse exactement comme la destination ci-dessous.
5. Mettre a jour `FORM_LINKS` dans le dashboard central apres creation.

## FORM_FIRE_MOVEMENT_JLL

Cle FORM_LINKS:

1. `FORM_FIRE_MOVEMENT_JLL`

Destination:

1. Fichier: `GSTK_OPS_INCENDIE_TEMPLATE`
2. URL: `https://docs.google.com/spreadsheets/d/1BZoNqQBRAcwHt6ME_a0VrGZvCltRnpeOxzeuzD4eXzE/edit`
3. Onglet: `MOVEMENTS_RAW`
4. Colonnes attendues:
   `Timestamp | SiteKey | Module | MovementType | ItemCode | Quantity | Reason | Actor | Comment`

Questions exactes:

1. `SiteKey` - Reponse courte - obligatoire - valeur attendue: `JLL`
2. `Module` - Reponse courte - obligatoire - valeur par defaut: `INCENDIE`
3. `MovementType` - Liste deroulante - obligatoire - choix: `IN`, `OUT`
4. `ItemCode` - Liste deroulante - obligatoire - source: `ITEMS!A2:A`
5. `Quantity` - Reponse courte (validation nombre > 0) - obligatoire
6. `Reason` - Reponse courte - obligatoire
7. `Actor` - Reponse courte - obligatoire
8. `Comment` - Paragraphe - optionnel

Note:

1. `Timestamp` est genere automatiquement par Google Forms en colonne A.

## FORM_FIRE_REPLENISH_JLL

Cle FORM_LINKS:

1. `FORM_FIRE_REPLENISH_JLL`

Destination:

1. Fichier: `GSTK_OPS_INCENDIE_TEMPLATE`
2. URL: `https://docs.google.com/spreadsheets/d/1BZoNqQBRAcwHt6ME_a0VrGZvCltRnpeOxzeuzD4eXzE/edit`
3. Onglet: `REPLENISH_RAW`
4. Colonnes attendues:
   `Timestamp | SiteKey | Module | ItemCode | RequestedQty | Reason | Actor | Status | Comment`

Questions exactes:

1. `SiteKey` - Reponse courte - obligatoire - valeur attendue: `JLL`
2. `Module` - Reponse courte - obligatoire - valeur par defaut: `INCENDIE`
3. `ItemCode` - Liste deroulante - obligatoire - source: `ITEMS!A2:A`
4. `RequestedQty` - Reponse courte (validation nombre > 0) - obligatoire
5. `Reason` - Reponse courte - obligatoire
6. `Actor` - Reponse courte - obligatoire
7. `Status` - Liste deroulante - obligatoire - valeur par defaut: `OPEN`
8. `Comment` - Paragraphe - optionnel

Note:

1. `Timestamp` est genere automatiquement par Google Forms en colonne A.

## FORM_PHARMA_MOVEMENT_JLL

Cle FORM_LINKS:

1. `FORM_PHARMA_MOVEMENT_JLL`

Destination:

1. Fichier: `GSTK_OPS_PHARMACIE_TEMPLATE`
2. URL: `https://docs.google.com/spreadsheets/d/1STguLGKB5qJua3y9ayI-rtOLlPwIxmq2U__-OtKEHpk/edit`
3. Onglet: `MOVEMENTS_RAW`
4. Colonnes attendues:
   `Timestamp | SiteKey | Module | MovementType | ItemCode | LotNumber | Quantity | Reason | Actor | Comment`

Questions exactes:

1. `SiteKey` - Reponse courte - obligatoire - valeur attendue: `JLL`
2. `Module` - Reponse courte - obligatoire - valeur par defaut: `PHARMACIE`
3. `MovementType` - Liste deroulante - obligatoire - choix: `IN`, `OUT`
4. `ItemCode` - Liste deroulante - obligatoire - source: `ITEMS_PHARMACY!A2:A`
5. `LotNumber` - Reponse courte - optionnel (obligatoire si `MovementType=OUT` lot trace)
6. `Quantity` - Reponse courte (validation nombre > 0) - obligatoire
7. `Reason` - Reponse courte - obligatoire
8. `Actor` - Reponse courte - obligatoire
9. `Comment` - Paragraphe - optionnel

Note:

1. `Timestamp` est genere automatiquement par Google Forms en colonne A.

## FORM_PHARMA_INVENTORY_JLL

Cle FORM_LINKS:

1. `FORM_PHARMA_INVENTORY_JLL`

Destination:

1. Fichier: `GSTK_OPS_PHARMACIE_TEMPLATE`
2. URL: `https://docs.google.com/spreadsheets/d/1STguLGKB5qJua3y9ayI-rtOLlPwIxmq2U__-OtKEHpk/edit`
3. Onglet: `INVENTORY_RAW`
4. Colonnes attendues:
   `Timestamp | SiteKey | Module | ItemCode | CountedQty | VarianceReason | Actor | Comment`

Questions exactes:

1. `SiteKey` - Reponse courte - obligatoire - valeur attendue: `JLL`
2. `Module` - Reponse courte - obligatoire - valeur par defaut: `PHARMACIE`
3. `ItemCode` - Liste deroulante - obligatoire - source: `ITEMS_PHARMACY!A2:A`
4. `CountedQty` - Reponse courte (validation nombre >= 0) - obligatoire
5. `VarianceReason` - Reponse courte - obligatoire
6. `Actor` - Reponse courte - obligatoire
7. `Comment` - Paragraphe - optionnel

Note:

1. `Timestamp` est genere automatiquement par Google Forms en colonne A.

## Procedure de liaison propre (Google Forms -> onglet cible)

1. Creer le formulaire avec les questions dans l'ordre exact.
2. Ouvrir `Reponses` > cliquer `Lier a Sheets`.
3. Choisir `Selectionner une feuille existante`.
4. Coller l'URL du fichier OPS cible.
5. Dans la feuille reponse creee, renommer l'onglet vers le nom exact attendu (`MOVEMENTS_RAW`, `REPLENISH_RAW`, `INVENTORY_RAW`).
6. Verifier que la premiere colonne est bien le timestamp Forms.
7. Mettre l'URL du formulaire dans `FORM_LINKS.FormUrl`.
8. Lancer `refreshDashboardConsolidations()` puis `runSystemHealthCheckFromDashboard()`.

## Rappel FORM_LINKS (cles a conserver)

1. `FORM_FIRE_MOVEMENT_JLL`
2. `FORM_FIRE_REPLENISH_JLL`
3. `FORM_PHARMA_MOVEMENT_JLL`
4. `FORM_PHARMA_INVENTORY_JLL`
5. `FORM_PHARMA_LOT_IN_JLL`
6. `FORM_PURCHASE_REQUEST_INC_JLL`
7. `FORM_PURCHASE_REQUEST_PHA_JLL`
8. `FORM_FIRE_ITEM_CREATE_JLL`
