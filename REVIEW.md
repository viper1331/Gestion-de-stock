# Analyse de code et tâches proposées

## 1. Corriger une faute de frappe
- **Constat** : Les libellés d'interface utilisent « Configurer Générales »/« Configuration Générales », formulation grammaticalement incorrecte.
- **Tâche proposée** : Renommer ces libellés (et la documentation associée) en « Configuration générale » ou un intitulé équivalent.
- **Emplacement** : `gestion_stock/__init__.py` (menu Paramètres et titre de la boîte de dialogue). `README.md` reflète la même faute.

## 2. Corriger un bug fonctionnel
- **Constat** : `init_user_db` appelle `conn.close()` dans le bloc `finally` sans garantir l'initialisation de `conn`. Si `sqlite3.connect` échoue, une `UnboundLocalError` masque l'erreur initiale.
- **Tâche proposée** : Initialiser `conn = None` avant le `try` et ne fermer la connexion que si elle est définie.
- **Emplacement** : `gestion_stock/__init__.py`, fonction `init_user_db`.

## 3. Résoudre une incohérence de documentation/commentaire
- **Constat** : La documentation décrit `camera_index` comme l'index caméra, mais le code réutilise cette valeur pour sélectionner le microphone (fonction `configure_microphone`/`init_recognizer`). Cela rend la description trompeuse.
- **Tâche proposée** : Aligner la doc et/ou le code : soit introduire un paramètre distinct pour le micro, soit expliciter dans la doc que la valeur est partagée.
- **Emplacement** : `README.md` (section Configuration) et `gestion_stock/__init__.py` (configuration micro).

## 4. Améliorer les tests
- **Constat** : Le projet ne contient aucun test automatisé. Des fonctions critiques comme `adjust_item_quantity` (gestion des quantités + journalisation) ne sont pas couvertes.
- **Tâche proposée** : Ajouter un module de tests (ex. `tests/test_inventory.py`) vérifiant la mise à jour des quantités et l'écriture dans `stock_movements`, idéalement avec une base SQLite en mémoire.
- **Emplacement** : `gestion_stock/__init__.py`, fonction `adjust_item_quantity`; absence de fichiers de test dans le dépôt.
