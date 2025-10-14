# Suggestions d'évolutions fonctionnelles

Cette liste propose des axes d'amélioration pour aller au-delà des fonctionnalités actuelles de Gestion Stock Pro. Chaque idée s'appuie sur les capacités existantes et indique les bénéfices attendus ainsi que des pistes de mise en œuvre.

## 1. Gestion des fournisseurs et des bons de commande
- **Constat actuel** : les mouvements d'entrées/sorties sont bien journalisés lorsqu'un article est ajusté, mais il n'existe pas de notion de fournisseur ou de commande entrante dédiée.【F:gestion_stock/__init__.py†L155-L191】【F:gestion_stock/__init__.py†L260-L299】
- **Évolution proposée** : ajouter des tables `suppliers` et `purchase_orders` avec workflow de réception partielle/complète, rattacher les mouvements entrants à une commande et générer automatiquement les ajustements de stock.
- **Bénéfices** : meilleure traçabilité des achats, vision sur les commandes en cours, automatisation des réceptions.
- **Pistes techniques** : nouvelles tables SQLite, interface Tkinter pour créer/suivre les commandes, génération de PDF ou d'exports CSV dédiés.

## 2. Workflows d'approbation multi-utilisateurs
- **Constat actuel** : le système gère deux rôles (`admin` et `user`) mais toute modification de stock est appliquée immédiatement si l'utilisateur y a accès.【F:README.md†L23-L32】【F:gestion_stock/__init__.py†L317-L358】
- **Évolution proposée** : introduire des états « en attente » pour les sorties importantes ou les suppressions d'articles, avec validation par un administrateur.
- **Bénéfices** : sécurisation des opérations sensibles, audit renforcé, conformité aux procédures internes.
- **Pistes techniques** : file d'approbation stockée en base, notifications internes (boîte de dialogue ou bannière), journalisation supplémentaire dans `stock_movements`.

## 3. Réapprovisionnement automatique et alertes multicanal
- **Constat actuel** : un seuil de stock faible est configurable et exploité pour les rapports, mais les alertes restent manuelles.【F:gestion_stock/__init__.py†L40-L82】【F:README.md†L116-L119】
- **Évolution proposée** : déclencher des alertes email/Teams/Slack ou SMS dès qu'un article passe sous le seuil, et proposer une génération automatique de bons de commande.
- **Bénéfices** : réactivité accrue, réduction des ruptures, gain de temps pour les équipes.
- **Pistes techniques** : tâches planifiées (thread ou scheduler), intégration SMTP ou API externes, assistant pour confirmer les quantités recommandées.

## 4. Suivi des stocks habillement par collaborateur
- **Constat actuel** : si le journal garde la trace de l'opérateur, il n'existe pas de module dédié pour suivre les dotations d'équipements et vêtements remis à chaque collaborateur, ni les retours ou remplacements associés.【F:gestion_stock/__init__.py†L317-L358】【F:gestion_stock/__init__.py†L268-L306】
- **Évolution proposée** : créer des fiches de dotation qui lient un collaborateur à ses articles d'habillement (type, taille, date de remise, état), automatiser les rappels de renouvellement et gérer les mouvements spécifiques (attribution, échange, restitution) par personne.
- **Bénéfices** : visibilité fine sur les équipements individuels, conformité aux obligations de sécurité, réduction des pertes et des oublis de renouvellement.
- **Pistes techniques** : ajouter des tables `collaborators` et `collaborator_gear`, formulaires de suivi des tailles/états, rapports filtrables par collaborateur et alertes planifiées pour les renouvellements.

## 6. Tableau de bord analytique en temps réel
- **Constat actuel** : un rapport PDF riche est généré ponctuellement à partir des mouvements et des stocks, mais il n'existe pas de visualisation dynamique dans l'application.【F:gestion_stock/__init__.py†L155-L191】【F:README.md†L117-L119】
- **Évolution proposée** : ajouter un onglet « Tableau de bord » dans l'interface, affichant KPIs (valeur stock, rotation, top ventes) et graphiques interactifs mis à jour en continu.
- **Bénéfices** : pilotage opérationnel instantané, aide à la décision, meilleure communication avec la direction.
- **Pistes techniques** : exploitation de `matplotlib` ou intégration de bibliothèques de visualisation temps réel (e.g. Plotly), mise à jour via threads ou tasks périodiques.

