# Projet : ProbaFoot (dépôt probafoot)

Application de pronostics football (5 grands championnats) vendue par abonnement.
Développeur : un seul, sur Android (Termux + Ubuntu proot). Langue de travail : français.

## Documents de référence (à lire avant toute tâche)
- docs/SPEC.md : quoi et pour qui, périmètre de la version 1
- docs/DECISIONS.md : décisions prises (ne pas les remettre en cause sans demande)
- docs/QUESTIONS.md : questions encore ouvertes (ne pas trancher à la place du propriétaire)
- docs/MOTEUR.md : modèle statistique, marchés, backtest
- docs/ARCHITECTURE.md : stack, dossiers, base de données, tâches planifiées
- docs/ACCEPTATION.md : critères de "terminé" et checklist de mise en production
- docs/ROADMAP.md : tâches numérotées, dans l'ordre
- docs/PROGRESSION.md : journal (à mettre à jour après chaque tâche)
- data/reference/clubs.csv et ligues.csv : référentiel vérifié, source de vérité des noms

## Commandes
- Tests : `pytest -q`
- (compléter au fil du projet : lancement API, tâches planifiées, backtest)

## Règles strictes
1. Ancien dépôt : `pronostic-sportif` (cloné à côté, en lecture seule) contient du travail testé (schéma SQL, elo.py, poisson_engine.py, pipeline d'import anti-fuite, data_fetcher.py, gemini_analyste.py). On y reprend les modules utiles un par un, avec leurs tests, adaptés à ARCHITECTURE.md. Jamais de copie en bloc, jamais de modification de l'ancien dépôt.
2. Une tâche à la fois, dans l'ordre de ROADMAP.md. Plan d'abord (mode plan), code ensuite.
3. Une tâche est terminée seulement si : tests écrits, tests verts, sortie de pytest montrée, PROGRESSION.md mis à jour.
4. Ne jamais dire "c'est fait" sans avoir exécuté le code.
5. Jamais de fuite de données : aucune donnée postérieure à l'instant de prédiction dans les features ou le backtest.
6. Ne jamais modifier une prédiction publiée (table `predictions_publiees` en ajout seul).
7. Ne jamais toucher à la base de production. Ne jamais committer sans demande explicite.
8. Aucune clé secrète dans le code ni dans Git : tout passe par `.env` (modèle : .env.example).
9. Aucun hasard dans les pronostics publiés : même entrée, même sortie (graines fixées si besoin).
10. Noms d'équipes : toujours passer par `club_id` de data/reference/clubs.csv, jamais par un nom brut.
11. Stockage des dates en UTC. Affichage en heure locale (Côte d'Ivoire = GMT).
12. Si une question de docs/QUESTIONS.md bloque une tâche : s'arrêter et le dire, ne pas deviner.
