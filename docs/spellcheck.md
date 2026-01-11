# Correcteur orthographique intégré

## Vue d'ensemble
Le correcteur orthographique est disponible via les composants `AppTextInput` et `AppTextArea`.
Il fonctionne en local (Hunspell via `nspell`) et n'applique jamais de correction automatique.

## Ajouter un dictionnaire
1. Installer un dictionnaire Hunspell compatible (ex: `dictionary-fr`, `dictionary-en`).
2. Ajouter la dépendance dans `frontend/package.json`.
3. Mettre à jour `frontend/src/lib/spellcheck.ts` pour charger la langue :
   - Ajouter la langue dans le type `SpellcheckLanguage`.
   - Ajouter un branchement dans `loadDictionary`.
4. Ajouter l'option dans l'écran des préférences (`SettingsPage`).

## Désactiver le correcteur pour un champ
Utilisez la prop `noSpellcheck` sur `AppTextInput` ou `AppTextArea` :

```tsx
<AppTextInput noSpellcheck {...props} />
<AppTextArea noSpellcheck {...props} />
```

## Paramètres globaux
Les préférences sont stockées en localStorage (`gsp/spellcheck/settings`) :
- `enabled` : active ou désactive le correcteur globalement.
- `language` : langue sélectionnée (`fr` par défaut).
- `live` : vérification pendant la saisie (désactivée par défaut).

## Dépannage Vite (504 Outdated Optimize Dep)
Si le correcteur ne fonctionne plus après une mise à jour et que Vite affiche une erreur `504 Outdated Optimize Dep`, supprimez le cache d'optimisation puis relancez le serveur :

```sh
rm -rf node_modules/.vite
npm run dev
```
