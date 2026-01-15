export const LINK_CATEGORY_FIELD_HELP = {
  module:
    "Module concerné (Véhicules QR / Pharmacie QR). Définit où cette catégorie apparaît.",
  key: "Identifiant technique, unique par module. Utilisez des minuscules + underscore (ex: fds, manuel, fiche_tech). Ne changez pas la clé après usage.",
  label: "Nom affiché à l’utilisateur (ex: FDS, Manuel, Notice…). Court et explicite.",
  placeholder:
    "Exemple affiché dans le champ de saisie côté article (ex: https://...). Aide l’utilisateur à comprendre le format attendu.",
  help_text:
    "Aide affichée à l’utilisateur sur la fiche article. Décrivez quoi coller ici (URL, chemin interne, référence…).",
  is_required:
    "Si activé, l’utilisateur devra renseigner ce lien pour valider/compléter l’article (selon les règles du module).",
  sort_order: "Priorité d’affichage : plus petit = plus haut dans la liste.",
  is_active: "Désactive l’affichage sans supprimer l’historique. Recommandé plutôt que supprimer."
} as const;
