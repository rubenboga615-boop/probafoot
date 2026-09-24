# Architecture

## Vue d'ensemble
```
[football-data.co.uk]  [understat]  [API-Football / football-data.org]
          \                 |                  /
           v                v                 v
        ingestion/ (scripts idempotents, club_id obligatoire)
                        |
                     base SQL
                        |
     moteur/ (features anti-fuite, Dixon-Coles, Elo, xG, marchés)
                        |
     publication/ (coupons, couche IA, gel H-60 min, historique)
                        |
             api/ (FastAPI, HTTPS)  --->  front/ (PWA HTML/CSS/JS)
                                             |
                                    Android plus tard (Capacitor)
```

## Arborescence cible
```
ingestion/     football_data.py, understat.py, calendrier.py, referentiel.py
moteur/        features.py, elo.py, dixon_coles.py, marches.py, mi_temps.py
backtest/      walk_forward.py, mesures.py, rapport.py
publication/   coupons.py, ia_gemini.py, gel.py
api/           main.py, routes/, auth.py, abonnements.py
front/         index.html, css/, js/, manifest.json, service-worker.js
jobs/          quotidien.py, apres_match.py (appelés par cron)
data/raw/      données brutes téléchargées (hors Git si volumineuses)
data/reference/ clubs.csv, ligues.csv (dans Git)
reports/       rapports de backtest
tests/         un fichier de test par module + fixtures/ (petit jeu de matchs fixes)
docs/          ce dossier
```
Nouveau dépôt `probafoot`. Les modules utiles de l'ancien dépôt `pronostic-sportif` (schéma SQL, elo.py, poisson_engine.py, pipeline anti-fuite) sont repris dans cette arborescence avec leurs tests.

## Base de données (tables principales)
| Table | Contenu | Règle |
| --- | --- | --- |
| ligues | code_fd, slug_understat, api_league_id, nom | Chargée depuis ligues.csv |
| clubs | club_id, noms par source | Chargée depuis clubs.csv |
| matchs | match_id, ligue, saison, date_utc, club_dom, club_ext, statut, score final et mi-temps | Clé unique (ligue, date, club_dom, club_ext) |
| stats_match | tirs, cadrés, corners, cartons, xG par équipe | Liée à matchs |
| cotes_cloture | Pinnacle et moyenne marché 1N2, O/U 2,5 | Usage interne uniquement, jamais affiché |
| predictions_brutes | probabilités calculées par marché, version du modèle, date de calcul | Recalculable |
| predictions_publiees | probabilité finale, ajustement IA, explication, horodatage, empreinte SHA-256 | Ajout seul, jamais modifiée |
| coupons | palier, sélections, confiance moyenne, cote globale calculée | Figés comme les prédictions |
| utilisateurs, abonnements, paiements | compte, offre, dates, statut, référence de paiement | Aucune donnée de paiement sensible stockée |
| journal_taches | exécution des jobs, durée, erreurs | Pour la supervision |

## Tâches planifiées (heure UTC = heure d'Abidjan)
| Heure | Tâche | Détail |
| --- | --- | --- |
| 06:00 chaque jour | Calendrier | Matchs des 14 jours suivants, 5 requêtes |
| 07:00 chaque jour | Statistiques | Saison en cours football-data et understat, insertion des nouvelles lignes seulement |
| 07:30 chaque jour | Recalcul | Seulement si nouvelles données ; prédictions des matchs à venir |
| Toutes les 15 min les jours de match | Statuts et gel | Scores, statut ; dernière vérification IA puis gel 60 min avant le coup d'envoi |
| 23:00 chaque jour | Sauvegarde | Export de la base hors du serveur |

Chaque tâche indique la fraîcheur des données (date du dernier match intégré). Si les statistiques d'un club ont plus de 10 jours de retard sur son dernier match joué, la prédiction est marquée « données incomplètes » et n'entre pas dans les coupons.

## Sécurité
- Secrets dans `.env` sur le serveur, jamais dans Git.
- Authentification par numéro de téléphone vérifié ou e-mail, mots de passe hachés.
- Paiements : confirmation côté serveur via la notification de l'agrégateur ou du store, jamais sur la seule parole du navigateur.
