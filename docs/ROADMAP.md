# Feuille de route

Une tâche = 1 à 3 heures. Ordre obligatoire, sauf mention. « Bloquée par Qx » = attendre la réponse dans QUESTIONS.md.

## Phase 0 — Référentiel API (abonnement renouvelé, plus d'urgence)
- **T00** Récupérer via API-Football, pour les 5 ligues : identifiants et noms des clubs de la saison 2026 (`/teams`) et calendrier complet de la saison (`/fixtures`). Remplir la colonne `nom_api_football` de clubs.csv. Environ 10 requêtes.

## Phase 1 — Mise en ordre du dépôt
- **T01** Mise en place du nouveau dépôt : arborescence de ARCHITECTURE.md, `requirements.txt`, configuration pytest, vérification du `.gitignore` (`.env`, `data/raw/`, bases locales). Premier test vert.
- **T02** Audit de l'ancien dépôt `pronostic-sportif` (lecture seule) : lister chaque module, ses tests, et décider « reprendre / adapter / abandonner » ; écrire le tableau dans PROGRESSION.md. Puis reprendre les modules retenus un par un, tests compris.
- **T03** Charger ligues.csv et clubs.csv en base (tables `ligues`, `clubs`) avec tests.

## Phase 2 — Données
- **T04** Ingestion football-data des 5 ligues, 10 saisons + saison en cours, via `club_id`. Tests d'idempotence et de comptage.
- **T05** Ingestion understat (xG) et liaison aux matchs. Test : ≥ 99 % de liaison.
- **T06** Ingestion des cotes de clôture dans `cotes_cloture` (usage interne).
- **T07** Tâche calendrier (API-Football, repli football-data.org). Test avec réponses enregistrées, sans appel réseau.
- **T08** Tâche statistiques de la saison en cours (nouvelles lignes seulement) et indicateur de fraîcheur.

## Phase 3 — Moteur
- **T09** Étendre Dixon-Coles aux 5 ligues avec pondération temporelle et avantage du terrain par ligue.
- **T10** Intégrer Elo et forces xG ; gestion des promus.
- **T11** Module `marches.py` : tous les marchés match entier depuis la matrice des scores.
- **T12** Modèle 1re mi-temps et mi-temps la plus prolifique.
- **T13** Tests de cohérence et de déterminisme (ACCEPTATION.md, section Moteur).

## Phase 4 — Backtest (étape décisive)
- **T14** Walk-forward 2019-20 à 2025-26.
- **T15** Mesures : log-loss, Brier, calibration, paliers, comparaison Pinnacle.
- **T16** Rapport automatique `reports/backtest_<date>.md`.
- **T17** Décision marché par marché selon MOTEUR.md section 6 ; résultat écrit dans DECISIONS.md. Point d'arrêt : le propriétaire valide avant la suite.

## Phase 5 — Publication
- **T18** Composition des coupons par palier.
- **T19** Couche Gemini avec recherche web (Grounding with Google Search) et garde-fous ; vérifier les quotas gratuits dans AI Studio.
- **T20** Gel H-60 min, table en ajout seul, empreinte SHA-256.
- **T21** Tâches planifiées (jobs/) et journal des exécutions.

## Phase 6 — Serveur et API
- **T22** API FastAPI : matchs, pronostics, coupons, historique, statistiques.
- **T23** Comptes utilisateurs et vérification du numéro (essai : D22).
- **T24** Mise en ligne sur serveur HTTPS, cron, sauvegardes (budget : D28).

## Phase 7 — Application
- **T25** PWA : squelette, navigation, thème, manifeste, mode hors ligne minimal.
- **T26** Écrans accueil, détail, coupons (données réelles).
- **T27** Écrans historique, statistiques, fiabilité par équipe.
- **T28** Onboarding, profil, notifications, FAQ, mentions légales (nom : ProbaFoot, D29).

## Phase 8 — Paiement et conformité (après le lancement gratuit)
- **T29** Paiement mobile money sur le web et Google Play Billing dans l'APK du store, offres selon D21 et D27. À faire une fois le statut juridique régularisé.
- **T30** Politique de confidentialité, conditions d'utilisation, vérification juridique (Q11).

## Phase 9 — Lancement
- **T31** Test complet sur téléphones réels, corrections.
- **T32** Lancement gratuit : version web et APK Android (Capacitor) téléchargeable depuis le site.
- **T33** Publication sur Google Play : compte développeur, test fermé, fiche du store.

## Plus tard
Extension aux 25 ligues de la liste courte, marchés phase 2, anglais, iOS.
