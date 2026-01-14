# Editable Page Layout

## Overview
Les pages métiers utilisent `EditablePageLayout` pour permettre un mode édition uniforme (drag & drop, hide/show, reset). Chaque page expose des blocs avec des identifiants stables et un layout par breakpoint.

## Structure attendue
Chaque page déclare une liste de blocs avec :

- `id` (stable et unique)
- `title`
- `render()`
- `defaultLayout` par breakpoint (`lg`, `md`, `sm`, `xs`)
- `minH`, `resizable`, `permissions` si nécessaire

Le wrapper `EditablePageLayout` reçoit `pageKey` et `blocks`, et gère :

- Réorganisation par glisser-déposer.
- Masquage/affichage de blocs.
- Reset du layout par défaut.
- Persistance par utilisateur via l’API `/user-layouts/{pageKey}`.

## API backend
- `GET /user-layouts/{pageKey}` : renvoie le layout et les blocs masqués.
- `PUT /user-layouts/{pageKey}` : sauvegarde le layout.

La validation côté serveur :

- supprime les IDs inconnus,
- applique un layout « safe » (clamp des valeurs et détection de chevauchement),
- respecte les permissions de l’utilisateur.

## Ajout d’une nouvelle page
1. Définir un `pageKey` stable.
2. Ajouter les règles de blocs côté backend dans `backend/api/user_layouts.py`.
3. Déclarer les blocs côté frontend et envelopper la page dans `EditablePageLayout`.
4. Tester le mode édition (drag/drop, hide/show, reset).
