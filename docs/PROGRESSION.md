# Journal de progression

## 23/09/2026 — Dossier de cadrage
- Documents créés : SPEC, DECISIONS, QUESTIONS, MOTEUR, ARCHITECTURE, ACCEPTATION, ROADMAP.
- Référentiel : data/reference/clubs.csv (165 clubs 2016-2027, dont 96 en 2026-27), correspondances football-data ↔ understat toutes vérifiées ; colonne API-Football à remplir (T00).
- Analyse de marché sur 67 317 matchs : voir MOTEUR.md section 1.
- État connu du dépôt : pipeline phase 1 testé localement, seule la Premier League importée, aucune prédiction persistée en production, marchés 1re mi-temps absents.
- Prochaine étape : T00 (avant le 6 octobre), puis T01.
- Questions ouvertes : Q1 à Q11.

## 23/09/2026 — Réponses du propriétaire
- Tranchées : Q1 C (APK + web), Q2 C (lancement gratuit), Q3 (1 500 / 3 000 FCFA), Q5 A, Q6 B (API renouvelée), Q7 A (Gemini), Q10 A puis B, Q11 A. Voir DECISIONS.md D19 à D26.
- Restent ouvertes : Q4 (confirmer le détail des offres), Q8 (budget), Q9 (nom).
- Validées ensuite : Q4 (offres), Q8 (plafond 5 000 FCFA/mois), Q9 (nom : ProbaFoot). Plus aucune question ouverte.
- Prochaine étape : T00 puis T01 dans Claude Code.
- Décision : nouveau dépôt `probafoot` ; l'ancien `pronostic-sportif` sert de référence en lecture seule (T02).

## 24/09/2026 — T00 : référentiel API-Football (terminée)

**Résultat** : les 96 clubs de la saison 2026-27 ont leur `nom_api_football` et leur `api_team_id` dans
`data/reference/clubs.csv` ; le calendrier complet des 5 ligues est récupéré et normalisé.

- Code écrit : `ingestion/api_football.py` (client + parseurs), `ingestion/noms_clubs.py` (normalisation
  et appariement des noms), `ingestion/referentiel.py` (tâche T00, CLI avec `--dry-run`, `--force`,
  `--ligues`), `pytest.ini`, environnement `.venv` (pip du système est `EXTERNALLY-MANAGED` sous proot :
  `python3 -m venv --system-site-packages .venv` puis `pip install pytest`).
- Nouvelle colonne **`api_team_id`** dans clubs.csv (validée avec le propriétaire) : la liaison du
  calendrier se fait par identifiant numérique stable, jamais par chaîne de caractères (règle 10).
  ARCHITECTURE.md mis à jour. Les 69 clubs absents de 2026-27 restent sans correspondance API : cette
  source ne sert qu'au calendrier et aux scores à venir (D04).
- **Appariement des noms** : 90 clubs sur 96 appariés par égalité de nom normalisé. Les 6 restants ont été
  tranchés à la main puis inscrits dans la table `ALIAS` de `noms_clubs.py` : `Hull City` → E0-hull,
  `Bayern München` → D1-bayernmunich, `Borussia Mönchengladbach` → D1-mgladbach, `Estac Troyes` → F1-troyes,
  `Stade Brestois 29` → F1-brest, plus le cas `Paris FC` / `Paris SG` (voir ci-dessous). Le module propose,
  il n'applique jamais un appariement approximatif ; un seul cas douteux arrête la tâche sans rien écrire.
- **Piège rencontré** : en retirant les sigles de forme, `Paris FC` et `Paris SG` tombaient sur la même clé
  « paris ». Le garde-fou de bijection l'a signalé au lieu d'apparier au hasard ; `sg` a été retiré de la
  liste des sigles. Le cas est couvert par un test.
- **Calendriers** écrits dans `data/raw/api-football/fixtures/2026/<code_fd>.csv` (+ `manifest.csv`),
  avec `club_id` et dates en UTC, aucun nom brut d'équipe : 380 / 380 / 380 / 306 / 306 matchs, chaque club
  y joue 38 (ou 34) matchs dont la moitié à domicile, identifiants de match uniques. Ces fichiers alimentent
  T07 ; `data/raw/` reste hors Git.
- **Requêtes consommées** : 13 au total (5 `/teams`, 5 `/fixtures`, quelques `/status` gratuits et un essai
  raté — `/teams` refuse un paramètre `page` explicite, la pagination n'est plus ajoutée qu'à partir de la
  deuxième page). Une seconde exécution est servie par le cache disque : 0 requête, aucun octet modifié.
- **Point de vigilance** : le compteur de quota du fournisseur est passé de 4 970 à 6 391 requêtes en une
  vingtaine de minutes alors que cette tâche n'en a émis que 13. Une autre application utilise donc la même
  clé, ou le fournisseur décompte des appels non émis ici. À surveiller avant T07 (tâche quotidienne) :
  le budget prévu est de 30 requêtes par jour.
- **Tests** : 46 tests verts (`.venv/bin/python -m pytest -q`), aucun appel réseau — réponses enregistrées
  dans `tests/fixtures/api_football/`. Couvrent notamment l'erreur applicative renvoyée en HTTP 200,
  l'absence de réessai sur quota ou clé refusée, la conversion en UTC, le refus d'apparier
  « Real Sociedad » à « Real Madrid », l'idempotence octet pour octet et le fait qu'un club non apparié
  laisse clubs.csv intact.
- Rien n'a été committé (règle 7). L'ancien dépôt n'a pas été modifié (règle 1) ; ses sources de client
  API-Football et d'appariement ayant été perdues (seuls les `.pyc` subsistent), seuls leurs deux
  enseignements ont été repris.
- Prochaine étape : T01 (arborescence complète, `requirements.txt`, `.gitignore`).

## 24/09/2026 — T01 : mise en ordre du dépôt (terminée)

**Résultat** : le dépôt a l'arborescence de ARCHITECTURE.md, ses dépendances sont déclarées et
épinglées, et `pytest -q` fonctionne enfin depuis la racine. 83 tests verts.

- **Bug trouvé et corrigé** : `pytest -q`, la commande annoncée dans CLAUDE.md, échouait
  (`ModuleNotFoundError: No module named 'ingestion'`, 3 modules de test sur 4 en erreur de
  collecte). Seul `python -m pytest` marchait, parce qu'il ajoute le dossier courant au chemin
  d'import. Corrigé par `pythonpath = .` dans `pytest.ini`. Les deux commandes donnent
  maintenant le même résultat.
- **Arborescence complétée** : `moteur/`, `backtest/`, `publication/`, `api/` (+ `routes/`),
  `jobs/` avec un `__init__.py` portant une ligne de docstring ; `front/` (+ `css/`, `js/`) et
  `reports/` avec un `.gitkeep` (Git ne versionne pas les dossiers vides).
- **`pytest.ini`** : `testpaths`, `pythonpath = .`, `--strict-markers`, et le marqueur `reseau`
  déclaré dès maintenant — la règle « aucun appel réseau dans les tests » est structurante pour
  T04 à T08.
- **Dépendances** : `requirements.txt` (exécution : `requests==2.34.2`) et `requirements-dev.txt`
  (`-r requirements.txt` + `pytest==9.1.1`). Choix du propriétaire : on n'y met que ce qui est
  réellement utilisé, versions exactes ; numpy/scipy (phase 3) et FastAPI (phase 6) seront
  ajoutés par la tâche qui les utilise. Motif : sous Python 3.14 en proot, les paquets
  scientifiques ne sont pas garantis de s'installer, et `pip install -r requirements.txt` doit
  réussir aujourd'hui. Vérifié : installation sans erreur.
- **`.gitignore` réorganisé et commenté** : ajout de `.env.*` avec l'exception `!.env.example`
  (protège `.env.local`, `.env.prod`…) et de `*.log`. `reports/*.html` reste ignoré mais les
  rapports de backtest en `.md` (T16) restent versionnés.
- **Nouveau test `tests/test_structure_depot.py`** (37 tests) : présence de chaque dossier et de
  chaque `__init__.py`, dépendances épinglées avec `==`, `.gitignore` interrogé par `git
  check-ignore` lui-même, aucun fichier `.env` suivi par Git, aucune valeur dans les clés
  `*_KEY` de `.env.example`, et toute variable d'environnement lue par le code déclarée dans
  `.env.example`. Ces contrôles ont été éprouvés par quatre régressions volontaires
  (version flottante, `__init__.py` supprimé, fausse clé dans le modèle, variable retirée du
  modèle) : chacune a été signalée par le bon test, puis le dépôt a été restauré.
- **Scripts hérités laissés en place** : `ingestion/download_football_data-2.py` et
  `download_understat-1.py` ne sont pas importables (tiret et chiffre dans le nom) et n'ont
  aucun test. Décision du propriétaire : ils seront renommés en `football_data.py` et
  `understat.py`, adaptés et testés en **T04** et **T05**, qui sont leurs tâches.
- **Tests** : `.venv/bin/pytest -q` → `83 passed in 1.07s`, sans aucun appel réseau.
- Rien n'a été committé (règle 7).
- Prochaine étape : T02 (audit de l'ancien dépôt `pronostic-sportif`, en lecture seule).

## Idées v2

**Collecte API-Football déjà sur le disque** (`data/raw/api-football/stats/`, hors Git) :
- 18 championnats, 68 015 matchs de 2016 à 2026.
- Statistiques détaillées — 18 types, match entier **et chaque mi-temps séparément**, dont les xG — pour
  13 808 matchs seulement, de 2024-25 à 2026-27.
- Les fichiers portent les noms d'équipes mais pas d'identifiants ; la liaison se fait par `fixture id`.

Usages envisagés :
- xG des championnats qu'understat ne couvre pas, pour l'extension à d'autres ligues.
- Statistiques par mi-temps pour alimenter le modèle de 1re mi-temps.
- Corners et cartons.
- Contrôle croisé des xG understat.

Hors périmètre de la version 1.

## 24/09/2026 — T02 : audit de l'ancien dépôt (terminée)

**Résultat** : l'ancien dépôt a été audité module par module. Le tableau ci-dessous dit, pour chacun,
s'il est repris, adapté ou abandonné, et par quelle tâche. Seuls les garde-fous d'isolation des tests
ont été repris tout de suite ; tout le reste est repris par sa tâche. 98 tests verts.

### La branche `main` n'était pas l'état de l'ancien dépôt

L'audit devait porter sur `main`. Il s'est avéré que la branche
**`claude/audit-lecture-seule-s5yd7b`** est **69 commits devant** (+21 487 lignes, 132 fichiers,
dernier commit le 23/09/2026) et contient presque toute la valeur du projet : Dixon-Coles réellement
entraîné, modèles de mi-temps et xG, calibration, imports Understat et API-Football, backtest complet,
et **cinq corrections de fuite de données** absentes de `main`. Sur `main`, `dixon_coles.py` ne fait
qu'une moyenne de buts et les tests anti-fuite n'affirment rien (« pas de crash = les données passées
sont bien filtrées »). Décision du propriétaire : **l'audit porte sur cette branche** (D31).

**Les tests hérités ont été exécutés, pas crus sur parole.** Clone de la branche dans un dossier
temporaire (`git clone` ne touche pas la source), suite lancée avec l'environnement Python de l'ancien
dépôt : **743 réussis, 3 ignorés en 2 min 49 s**. Les 3 ignorés sont les garde-fous anti-production,
sans objet dans un clone où la base n'existe pas. C'est plus que les 645 annoncés dans leur
`ETAT_ACTUEL.md` du 19/09 : quatre commits ont suivi.

### Tableau d'audit

Trois verdicts : **reprendre** (le code est bon, il faut l'adapter aux noms français et au `club_id`),
**adapter** (l'idée est bonne, l'implémentation doit changer), **abandonner**.

**Socle base de données**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `app/models.py` | 291 | Adapter | Schéma des 12 tables d'ARCHITECTURE.md. À garder : index et contraintes d'unicité déclarés sur les clés logiques (`matchs`, `features`, `predictions`, `actual_results`) | T03 |
| `app/database.py` | 47 | Reprendre | Clés étrangères activées par listener `connect` — SQLite ne le fait pas seul | T03 |
| `app/config.py` | 46 | Adapter | Configuration par `.env` (pydantic-settings) | T03 |
| `app/main.py`, `routes/`, `schemas.py`, `dependencies.py` | 11 à 48 | Abandonner | Squelettes FastAPI sans contenu | T22 |
| `app/logging_config.py` | 33 | Adapter | Journalisation ; à relier à `journal_taches` | T21 |
| `migrations/` + `scripts/appliquer_migrations.py` | 235 | Reprendre | Sauvegarde vérifiée obligatoire avant toute migration, registre des migrations appliquées, option `--marquer-appliquee` | T03 |

**Ingestion**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `collectors/football_data/parser.py` | 394 | Reprendre | `ingestion/football_data.py`. Surveillance des colonnes disparues (`inspecter_colonnes`) : une colonne de cotes qui change de nom est une perte sèche silencieuse | T04 |
| `collectors/football_data/downloader.py` | 158 | Reprendre | Réessais opérants, écriture atomique, refus des réponses vides | T04 |
| `collectors/football_data/league_config.py` | 122 | Adapter | Remplacé par `ligues.csv` ; garder l'idée de **saison de chauffe** (2014/15 importée mais exclue de l'entraînement) | T04 |
| `collectors/football_data/team_normalizer.py` | 347 | Abandonner | Remplacé par `clubs.csv` + `ingestion/noms_clubs.py` (règle 10) | — |
| `pipelines/historical_import.py` | 908 | Adapter | `ingestion/football_data.py`. Idempotence par clé logique, invariant de comptage (`lues == insérées + doublons + invalides + erreurs`), rapport de qualité horodaté | T04 |
| `collectors/understat/game_stats.py` | 238 | Reprendre | `ingestion/understat.py`. Rattachement par (club, jour, camp) : une équipe ne joue qu'un match par jour — vérifié sur 41 722 lignes | T05 |
| `pipelines/understat_import.py` | 218 | Reprendre | Rattache sans jamais créer de match : un match Understat n'a ni cotes ni score de mi-temps | T05 |
| `pipelines/completer_cotes.py` | 196 | Reprendre | Un match déjà en base ne reçoit jamais les colonnes apprises après coup ; ce module rattrape | T06 |
| `collectors/api_football/` (client, cache, quota, erreurs, parsers) | 918 | Abandonner | Déjà refait et testé en T00. **Mais** relire `parsers.py` (374 l., 33 tests) avant T07 : il couvre des cas de statut de match que T00 n'a pas | T07 |
| `pipelines/api_football_import.py` | 652 | Adapter | Import du calendrier et des statuts, par `club_id` | T07 |
| `collectors/mapping/` | 365 | Abandonner | `noms_clubs.py` remplit ce rôle ; l'enseignement (le module propose, il n'applique pas) est déjà repris | — |

**Features (moteur)**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `features/context.py` | 256 | Reprendre | `moteur/features.py`. Vue de l'historique avançable match par match : ~17 ms par match au lieu d'un rejeu complet | T09 |
| `features/elo.py` | 119 | Reprendre | `moteur/elo.py`. Rating pré-match, régression vers la moyenne en début de saison | T10 |
| `features/half_time.py` | 155 | Reprendre | Dix variables de première période — quinze des trente et une sélections en dépendent | T12 |
| `features/rest_days.py` | 121 | Reprendre | Repos **et** encombrement du calendrier (matchs sur 7 et 14 jours) | T09 |
| `features/xg.py` | 141 | Reprendre après correctif | Fenêtre sur les matchs **joués**, pas sur les matchs couverts par la source ; filtre anti-fuite sur la date du match, jamais sur la date de collecte | T10 |
| `features/odds_movement.py` | 129 | Adapter | Étanche par construction : ne lit que des cotes disponibles avant la coupure. Restera vide sans plusieurs relevés horodatés | T06 |
| `features/form.py`, `goals.py`, `home_away.py`, `shots.py`, `standings.py` | 47 à 94 | Reprendre | Moyennes glissantes, classement — toutes bornées à la saison | T09 |
| `features/comparable_teams.py` | 123 | Reprendre | Force du calendrier déjà joué : onze points contre le haut du tableau ne valent pas onze points contre le bas | T10 |
| `features/mapping.py` | 202 | Adapter | Correspondance explicite sorties de features → colonnes ; rend auditable ce qui est réellement persisté | T09 |
| `features/injuries.py` | 42 | Abandonner | Source jamais collectée ; la couche Gemini (D12) traite les absences | — |
| `pipelines/feature_pipeline.py` | 351 | Adapter | Le calcul et la persistance ; anti-fuite par construction | T09 |

**Moteur et marchés**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `models/dixon_coles.py` | 435 | Reprendre | `moteur/dixon_coles.py`. Maximum de vraisemblance vectorisé, pondération temporelle (ξ), ajustement **par compétition**, régularisation des forces | T09 |
| `models/poisson.py` | 97 | Reprendre | Matrice des scores | T09 |
| `models/first_half.py` | 129 | Reprendre | `moteur/mi_temps.py`. Deux modèles distincts, première et seconde période | T12 |
| `models/market_derivation.py` | 226 | Reprendre | `moteur/marches.py`. 1N2, double chance, O/U, BTTS, marchés de mi-temps, mi-temps la plus prolifique | T11 |
| `models/market_assembly.py` | 258 | Adapter | Assemblage en mémoire, 31 sélections par match, identifiants de marché normalisés | T11 |
| `models/prediction_context.py` | 179 | Reprendre | Contexte anti-fuite d'un match : aucune écriture en base | T09 |
| `models/dixon_coles_xg.py` | 268 | Adapter | Mesuré : gain net sur le seul BTTS (+2,6 pts d'AUC), rendement inchangé. À rejouer avant d'être retenu | T10 |
| `models/calibration.py`, `calibration_appliquee.py`, `calibration_glissante.py` | 452 | Reprendre | Calibration **avant** persistance (une probabilité publiée ne se retouche pas, règle 6), un calibrateur par marché, renormalisation des groupes exclusifs | T13 |
| `models/model_registry.py` | 147 | Reprendre | Un modèle qui ne se recharge pas à l'identique n'est pas auditable (règle 9) | T13 |
| `pipelines/prediction_pipeline.py` | 462 | Adapter | Contexte → calibration → valorisation → persistance | T13 |

**Backtest**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `evaluation/backtest.py` | 421 | Adapter | `backtest/walk_forward.py`. Voir le piège du ROI sans seuil, plus bas | T14 |
| `evaluation/metrics.py` | 187 | Reprendre | `backtest/mesures.py` : log-loss, Brier, calibration, AUC par groupe exclusif. Jamais l'accuracy seule | T15 |
| `evaluation/settlement.py` | 209 | Reprendre | Du score final au résultat de chaque sélection ; sans cette étape rien n'est mesurable | T14 |
| `evaluation/pricing.py` | 198 | Reprendre | Probabilité de marché, marge retirée par normalisation (D08) | T15 |
| `evaluation/incertitude.py` | 99 | Reprendre | Intervalle de confiance par bootstrap. Un ROI sans intervalle ne dit presque rien | T15 |
| `evaluation/reports.py`, `calibration_report.py`, `roi_simulation.py` | 100 | Adapter | `backtest/rapport.py` → `reports/backtest_<date>.md` | T16 |
| `scripts/mesurer_backtest.py`, `train_models.py`, `ajuster_calibration.py` | 722 | Adapter | Vers `jobs/` | T14, T21 |

**Automatisation et divers**

| Module | Lignes | Verdict | Cible | Tâche |
| --- | --- | --- | --- | --- |
| `pipelines/daily_update.py` | 330 | Adapter | `jobs/quotidien.py`. **API-Football n'archive pas ses cotes** : ce qui n'est pas collecté le jour même est perdu | T21 |
| `scripts/create_backup.py` | 36 | Reprendre | Sauvegarde quotidienne (ARCHITECTURE.md) | T24 |
| `.github/workflows/ci.yml` | 84 | Reprendre plus tard | Tests et style à chaque poussée | T24 |
| `dashboard/streamlit_app.py` | 46 | Abandonner | Le front est une PWA (D14) | — |
| `tests/conftest.py`, `test_database_isolation.py`, `test_path_isolation.py` | 184 | **Reprendre maintenant** | Voir plus bas | **T02** |
| `tests/test_no_data_leakage.py` | 291 | Reprendre | Historique empoisonné et mouchard de dates : c'est ce qui fait tenir la règle 5 | T09 |

### Ce que l'ancien projet a déjà mesuré

Le backtest a été mené jusqu'au bout, avec intervalles de confiance par bootstrap, sur 3 504 matchs de
test des cinq championnats, contre les cotes de clôture. Mesure du 19/09/2026, croisée par marché
**et** par seuil d'edge :

| Marché | Seuil | ROI | Verdict |
| --- | --- | --- | --- |
| 1N2 | ≥ 2 % | −10,0 % (3 567 paris) | **perdant, démontré** |
| 1N2 | ≥ 5 % | −9,9 % (2 328 paris) | **perdant, démontré** |
| Over/Under | ≥ 2 % | −2,3 % (2 603 paris) | indéterminé (l'intervalle contient zéro) |
| Favori du marché | — | +0,3 % | nul |

Trois enseignements à porter en phase 4 :

1. **Sélectionner sur l'edge du 1N2 fait perdre**, quel que soit le seuil, et le modèle ajusté sur les
   xG ne renverse pas le signe. C'est le résultat le plus solide de l'ancien projet.
2. **Le moteur classe bien mais ne bat pas le prix** : AUC 0,77 sur l'Over/Under de mi-temps, 0,76 sur
   l'Over/Under, 0,67 sur le 1N2. Un bon AUC ne vaut rien tant qu'il ne dépasse pas la marge.
3. **Mieux calibrer n'améliore pas le rendement du 1N2** : la calibration glissante réduit l'erreur de
   calibration de 41 % et le ROI ne bouge pas. Sur l'Over/Under, en revanche, une calibration figée
   suffisait à changer le signe.

**Portée pour ProbaFoot.** Ces conclusions portent sur un **critère de pari à la cote**. MOTEUR.md § 6
publie sur des **critères de calibration** (ECE < 0,02, tranches à ±3 points), pas sur un ROI : elles
ne condamnent donc pas la version 1. Elles fixent la barre et ferment une porte — aucun générateur de
coupons ne devra retenir une sélection 1N2 sur l'edge. T14 à T17 doivent les **rejouer** sur le
nouveau pipeline, jamais les recopier.

### Pièges hérités, à ne pas refaire

Quatre défauts **silencieux** — aucun ne levait d'erreur — qui ont coûté des semaines :

- **Un module écrit et jamais appelé.** `features/xg.py` existait depuis le début sans être importé
  par le pipeline : les colonnes xG seraient restées vides même la source peuplée. Même défaut pour
  `evaluation/pricing.py` : 22 420 prédictions sans prix, donc sans rendement calculable.
- **Un chargeur qui se rabat sans le dire.** `charger_modele` prenait n'importe quel Dixon-Coles
  enregistré quand la version demandée manquait, et `lambdas` traitait une équipe inconnue comme
  moyenne au lieu de refuser de prédire. Résultat : tous les championnats prédits par un seul modèle.
- **Un ROI qui ne mesurait pas le moteur.** Le bloc « par marché » misait sur les trois issues de
  chaque 1N2, sans regarder la probabilité du modèle : il mesurait la marge du bookmaker. Deux modèles
  très différents rendaient le même chiffre au centième — c'est ce qui a mis la puce à l'oreille.
- **Un filtre anti-fuite portant sur la mauvaise date.** Le filtre xG comparait la date de *collecte* à
  la date du match : une collecte récente écartait tout l'historique, une collecte ancienne laissait
  entrer des matchs postérieurs à la cible.

Règle à en tirer, applicable dès T04 : **tout module doit être appelé par un chemin testé**, et tout
repli silencieux doit être remplacé par une erreur.

### Données déjà sur le disque, réutilisables

L'ancien dépôt porte 2,1 Go de données hors Git, lues ici sans rien modifier :

- `data/pronostic.db` (245 Mo) : **19 002 matchs** des cinq championnats (2014/15 → 2026/27),
  **373 059 cotes**, **28 004 lignes de xG**, 160 équipes.
- `data/raw/football_data/` : 48 CSV bruts (6,7 Mo) ; `data/raw/api_football/` : 281 Mo.

Cela compte pour T04 et T05 : **football-data.co.uk renvoyait un 503 systématique** en septembre 2026,
y compris depuis cette machine. Ces fichiers sont un repli — à croiser avec understat avant import,
comme l'ancien projet l'avait fait (13 000 matchs comparés, zéro discordance de score).

### Code repris en T02 : l'isolation des tests

Seule reprise de code de cette tâche, parce qu'elle n'appartient à aucune tâche future et protège deux
règles : `tests/conftest.py` et `tests/test_isolation.py` (15 tests), adaptés des trois fichiers
d'isolation de l'ancien dépôt.

- `DATABASE_URL` est **forcée** vers une base temporaire hors du dépôt avant tout import — écrasée, pas
  complétée : une valeur héritée du shell ne doit pas décider où les tests écrivent.
- La suite **refuse de démarrer** si la base configurée est un fichier du dépôt. Le critère est
  l'appartenance au dépôt, pas le nom : `data/local.db` comme n'importe quel autre.
- L'empreinte SHA-256 de `data/reference/` est relevée avant chaque test et vérifiée après. Un test qui
  modifie `clubs.csv` échoue en nommant le fichier. La lecture reste libre.
- Écrit sans dépendre d'une bibliothèque de base de données : actif dès aujourd'hui, et toujours valable
  quand T03 créera la base.

**Éprouvé par deux régressions volontaires**, comme en T01 : un test écrivant dans `clubs.csv` a bien
été arrêté en nommant le fichier ; `DATABASE_URL` pointée sur `data/local.db` a bloqué les 98 tests
d'un coup. Le dépôt a ensuite été restauré (empreinte de `clubs.csv` identique, `git status` propre).

- **Tests** : `.venv/bin/pytest -q` → `98 passed in 2.40s` (83 de T01 + 15 nouveaux), aucun appel réseau.
- Aucune dépendance ajoutée : SQLAlchemy viendra avec T03, pandas/numpy/scipy avec la tâche qui les
  importe la première.
- L'ancien dépôt n'a pas été modifié (règle 1) : travail sur un clone, `HEAD` toujours sur `main`,
  working tree inchangé. Rien n'a été committé (règle 7).
- Prochaine étape : T03 (charger ligues.csv et clubs.csv en base).
