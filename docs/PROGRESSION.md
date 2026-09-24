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

## 24/09/2026 — T03 : le référentiel en base (terminée)

**Résultat** : la base existe. `ligues.csv` et `clubs.csv` y sont chargés — 5 ligues, 165 clubs,
dont les 96 de la saison en cours avec leur `api_team_id` — par un script idempotent qui refuse
d'écrire quoi que ce soit si le référentiel est douteux. 165 tests verts.

### Périmètre, tranché avec le propriétaire avant d'écrire

Trois décisions, parce que ROADMAP.md et le tableau d'audit de T02 ne disaient pas la même chose :

- **Schéma** : `ligues` et `clubs` (ROADMAP) **plus `matchs`**, la table qu'attend T04, et rien de
  plus. Le tableau d'audit prévoyait les 12 tables d'ARCHITECTURE.md d'un coup ; on ne fige pas les
  colonnes de `coupons` ou `abonnements` avant de connaître leur usage. Les 9 autres tables seront
  déclarées par la tâche qui les remplit.
- **Configuration** : un module maison de 120 lignes en bibliothèque standard, pas
  `pydantic-settings` comme l'ancien dépôt. D30 n'autorise que SQLAlchemy, pandas, numpy et scipy,
  et `pydantic-core` est une roue Rust dont l'installation n'est pas garantie sous Python 3.14 en
  proot. Seule dépendance ajoutée : **SQLAlchemy 2.0.54** (installée et vérifiée).
- **Migrations** : le lanceur de l'ancien dépôt est repris **maintenant**, parce que c'est cette
  tâche qui fait naître la base, donc le moment où la règle « aucune écriture de schéma sans
  sauvegarde vérifiée » doit exister.

### Code écrit

| Fichier | Rôle |
| --- | --- |
| `bdd/config.py` | `.env` puis l'environnement, qui gagne toujours. `DATABASE_URL` vide = erreur, pas repli |
| `bdd/session.py` | Moteur, sessions, `creer_tables`, et le listener `PRAGMA foreign_keys=ON` |
| `bdd/modeles.py` | Tables `ligues`, `clubs`, `matchs` |
| `ingestion/charger_referentiel.py` | La tâche T03 : contrôle, puis chargement idempotent |
| `scripts/appliquer_migrations.py` + `migrations/` | Changements de schéma d'une base peuplée |

**Le moteur est construit à l'appel, pas à l'import.** L'ancien `app/database.py` créait le sien au
chargement du module, ce qui figeait l'URL de la base : le garde-fou de `conftest.py` n'aurait rien
pu forcer, et chaque test aurait écrit dans la base de travail de la machine.

### Ce que la base refuse désormais elle-même

L'idempotence de l'ancien dépôt reposait sur un `SELECT` applicatif avant écriture, sans filet.
Ici les contraintes sont déclarées sur les **clés logiques** :

- `clubs.nom_football_data` et `clubs.nom_understat` sont **uniques** : ce sont les clés de
  jointure de T04 et T05, et un doublon rendrait la jointure ambiguë — l'ambiguïté se résolvant en
  silence au premier arrivé. Vérifié : aucun doublon sur les 165 lignes, même toutes ligues confondues.
- `api_team_id` unique, mais NULL répétable : les 69 clubs hors saison en cours n'en ont pas (D04).
- une équipe ne peut pas jouer contre elle-même, et les buts de mi-temps ne peuvent pas dépasser le
  score final (une inversion de colonnes dans un CSV source se verrait là, pas trois mois plus tard
  dans les marchés de mi-temps).
- **Mesuré** : `PRAGMA foreign_keys` vaut `0` par défaut sur ce SQLite. Sans le listener repris de
  l'ancien dépôt, les clés étrangères du schéma ne seraient que de la documentation. Deux tests le
  prouvent en insérant un club dans une ligue inconnue et un match avec un club inexistant.

### Écart assumé à ARCHITECTURE.md : la clé unique de `matchs`

Annoncé : `(ligue, date, club_dom, club_ext)`. Retenu : `(code_fd, **saison**, club_dom, club_ext)`.
Dans ces cinq championnats une paire domicile/extérieur ne se rencontre qu'une fois par saison,
alors que l'heure — et parfois le jour — du coup d'envoi change couramment. Avec la date dans la
clé, un match reporté entrerait **deux fois** et l'idempotence de T04 tomberait en silence.
ARCHITECTURE.md a été mis à jour avec cette raison ; un test vérifie qu'un report ne crée pas un
second match, un autre que le match retour (domicile et extérieur inversés) est bien accepté.

### Le chargeur : trois propriétés, dans cet ordre

1. **Rien n'est écrit si quelque chose ne va pas.** Les deux CSV sont entièrement contrôlés avant la
   première écriture, et **toutes** les anomalies sont affichées ensemble — corriger le référentiel
   une fois vaut mieux que cinq relances pour les découvrir une par une. Quatre refus testés
   (ligue inconnue, `api_team_id` en doublon, nom de source en doublon, club de la saison en cours
   sans identifiant API) laissent la base **vide**.
2. **Idempotent.** Une ligne n'est écrite que si une valeur diffère réellement, et `maj_le` ne bouge
   pas sans raison. Deuxième exécution : `0 insérés, 0 mis à jour, 165 inchangés`.
3. **Rien n'est supprimé.** Un club en base et absent du CSV est signalé, jamais effacé : `matchs`
   peut déjà le référencer.

Un contrôle a été volontairement **assoupli** par rapport au plan : on exige que tout club de la
saison en cours ait son `api_team_id`, mais on n'interdit pas l'inverse. Un club relégué garde
l'identifiant appris quand il était en première division ; l'exiger vide aurait bloqué T03 à la
première relégation, pour rien.

### Faiblesse trouvée dans un garde-fou de T02, corrigée

Le test `test_aucune_base_creee_dans_le_depot` de T02 exigeait **aucun** fichier `.db` dans `data/`.
Il est tombé dès la première exécution réelle de T03 : `data/local.db` est la base locale de
travail, valeur de `.env.example`, ignorée par Git — elle est légitime. Deux corrections :

- le critère devient la **nouveauté** (relevé des bases présentes avant la suite), pas l'absence ;
- le contrôle passe d'un test ordinaire à un **démontage de session**. Éprouvé : un test ajouté
  exprès pour créer `data/essai_interdit.db` ne faisait rien tomber, parce que `test_isolation.py`
  s'exécute avant lui dans l'ordre alphabétique. Le garde-fou hérité avait donc ce trou depuis T02 ;
  le même essai échoue maintenant en nommant le fichier.

### Divers

- `charger_env` de `ingestion/api_football.py` délègue désormais son analyse de `.env` à
  `bdd.config.lire_env` : un seul endroit décide de ce qu'est une ligne de `.env`. Ses tests
  passent inchangés.
- `.gitignore` : ajout de `data/backups/` — le motif `data/*.db` ne couvre pas un sous-dossier, et
  la première sauvegarde du lanceur de migrations aurait été proposée au commit.
- `.env.example` : `DOSSIER_SAUVEGARDES`. `tests/test_structure_depot.py` reconnaît la façon dont
  `bdd/config.py` lit l'environnement, pour que le contrôle « toute variable lue est déclarée »
  continue de mordre.
- `migrations/` part vide (un README expose la convention) : le schéma initial vient de l'ORM.

### Vérifications exécutées

- `.venv/bin/pytest -q` → **165 passed in 8.75s** (98 de T02 + 67 nouveaux), aucun appel réseau.
  `pytest` sans option donne le même résultat.
- Tâche lancée pour de vrai : `--dry-run` (rien écrit), puis écriture (5 + 165), puis relance
  (0 + 0). En base : 5 ligues, 165 clubs, 96 avec `api_team_id`, 96 en saison courante, 0 match,
  31/35/33/34/32 clubs par ligue, `1. FC Köln` intact.
- Lanceur de migrations éprouvé sur une **copie** de la base (hors dépôt) avec une migration
  d'essai : sauvegarde vérifiée (92 Ko, 4 tables) prise avant l'écriture, index créé, second
  passage « rien à faire ».
- **Quatre régressions volontaires**, comme en T01 et T02 : listener `PRAGMA` retiré (2 tests de
  clé étrangère tombent), `maj_le` touché à chaque passage (l'idempotence tombe), sauvegarde prise
  après l'écriture (2 tests de migration tombent), test écrivant une base dans `data/` (le
  démontage de session le nomme). Dépôt restauré ensuite ; empreinte de `clubs.csv` identique.
- Rien n'a été committé (règle 7). L'ancien dépôt n'a pas été modifié (règle 1) : lecture par
  `git show` sur la branche de D31, `HEAD` toujours sur `main`.
- Prochaine étape : T04 (ingestion football-data des 5 ligues, 10 saisons + saison en cours).

## 24/09/2026 — T04 : ingestion football-data (terminée)

**Résultat** : les 11 saisons (2016-17 à 2026-27) des 5 ligues sont en base — **18 187 matchs** et
**36 374 lignes de statistiques d'équipe**, soit exactement deux par match — chargés par un script
idempotent, sans un seul accès réseau. 242 tests verts (165 de T03 + 77 nouveaux).

### Périmètre

ROADMAP dit « 10 saisons + saison en cours » : ce sont 2016-17 à 2025-26 plus 2026-27, déjà sur le
disque depuis T02. **Aucun téléchargement** : les saisons terminées ne bougent plus, et
football-data.co.uk renvoyait des 503 systématiques en septembre (constaté en T02).
`ingestion/telecharger_football_data.py` reste le seul module qui parle au réseau ; l'ingestion lit
le disque, ce qui rend la tâche entièrement rejouable et testable hors ligne.

### Code écrit

| Fichier | Rôle |
| --- | --- |
| `ingestion/football_data.py` | La tâche T04 : lit, contrôle tout, puis écrit — ou rien |
| `bdd/modeles.py` | Table `stats_match` ajoutée (les 8 tables restantes attendent leur tâche) |
| `tests/test_football_data.py` | 77 tests, 16 classes |
| `tests/fixtures/football_data/` | Jeux d'essai : `sain/`, `casse/`, `anomalies/` |

### `stats_match` : une ligne par équipe, pas par match

Pas de colonnes `tirs_dom` / `tirs_ext`, mais deux lignes portant `camp` et `club_id`. C'est la
forme qu'annonce ARCHITECTURE.md, c'est celle qu'attend le rattachement understat de T05 (par
`(club, jour, camp)`), et c'est la seule où « les tirs cadrés de ce club sur ses cinq derniers
matchs » se lit sans distinguer le camp à chaque fois. Deux contraintes d'unicité la tiennent :
`(match_id, camp)` et `(match_id, club_id)` — un match a exactement deux lignes, et jamais le même
club deux fois.

`xg` est nullable et reste vide pour l'historique : la source ne publie `HxG`/`AxG` que depuis
2026-27. En base, exactement **500 valeurs**, soit les 250 matchs de la saison en cours. T05 la
remplira pour le reste depuis understat (D03) — et l'ingestion **n'écrase jamais un xG existant par
une colonne vide**, sans quoi le prochain passage de T04 effacerait le travail de T05.

### Le fuseau de football-data : une heure d'écart, silencieuse

La source publie l'heure du coup d'envoi en **heure locale britannique**, pas en UTC. Rien ne le
dit dans ses fichiers. Vérifié en confrontant les 250 matchs de 2026-27 au calendrier API-Football
de T00 : tous à exactement +1 h, l'heure d'été britannique en août et septembre. Non corrigé,
c'était une heure de décalage sur tout l'historique récent — et la bascule d'octobre l'aurait fait
disparaître par intermittence, le pire cas pour s'en apercevoir. Un test compare désormais les deux
sources ; la régression volontaire correspondante le fait tomber.

Cas limite : **2016-17 à 2018-19 n'ont pas de colonne `Time`**. La date est alors stockée à
**00:00 UTC sans conversion de fuseau** — convertir minuit depuis Londres reculerait la date d'un
jour pendant tout l'été, bien pire qu'une heure inconnue. Aucun match de ces championnats ne débute
à minuit pile : `00:00:00` se lit donc comme « heure inconnue » sans colonne supplémentaire. En
base : **5 478 matchs**, soit exactement 3 × 1 826, les trois saisons concernées.

### Ce que la tâche refuse de subir en silence

- **Colonnes disparues** (repris de `collectors/football_data/parser.py` de l'ancien dépôt) : 18
  colonnes surveillées. Une absence déjà comprise est affichée avec son explication ; toute autre
  ressort marquée `← INATTENDU`. Une colonne qui change de nom chez la source est sinon une perte
  sèche invisible.
- **Invariant de comptage** (repris de `pipelines/historical_import.py`) :
  `lues == insérées + mises à jour + inchangées + refusées + ignorées`, contrôlé à la lecture puis
  à l'écriture. Faux = la tâche s'arrête.
- **Valeurs invraisemblables** : plus de tirs cadrés que de tirs, c'est une inversion de colonnes.
  Les deux valeurs sont écartées, le match est importé quand même, et le cas est **nommé** dans le
  rapport. Un seul sur 18 187 : `2122/E0`, Newcastle–West Ham. Le schéma tient le même invariant
  (`ck_stats_match_tirs_cadres`) : la régression volontaire qui retire le contrôle applicatif fait
  lever la contrainte SQL sur cette ligne réelle.
- **Écarts de calendrier** : 6 signalés, tous expliqués — `1920/F1` à 279 matchs (Ligue 1 arrêtée
  pour le Covid) et les 5 fichiers de 2026-27, saison en cours.

### Les trois propriétés de T03, reprises

1. **Rien n'est écrit si quelque chose ne va pas.** Tout est lu et contrôlé avant la première
   écriture, et toutes les anomalies sortent ensemble. `--tolerer` importe en écartant les lignes
   fautives.
2. **Idempotent.** Une ligne n'est écrite que si une valeur diffère réellement, et `maj_le` ne
   bouge qu'alors. `source_match_id` est construit sur la clé logique
   (`saison:ligue:dom:ext`), jamais sur le numéro de ligne : un match reporté ou un fichier de
   saison en cours qui grossit ne change pas d'identité.
3. **Rien n'est supprimé.** Un match en base et absent des fichiers est compté et signalé, jamais
   effacé — et la comparaison est limitée au périmètre réellement lu, pour que `--saisons 2627` ne
   déclare pas « absentes » les dix autres saisons.

### Rangement des données brutes

Les CSV étaient sous `data/raw/football-data/data/raw/football-data/<saison>/`, arborescence
dupliquée par l'extraction d'une archive (antérieure à T04). Remis à plat : les 199 fichiers sont
maintenant directement sous `data/raw/football-data/`. `localiser_racine` descend tant qu'un seul
sous-dossier s'offre et qu'aucune saison n'est visible, donc les deux rangements fonctionnent —
c'est pourquoi le chemin n'a jamais été figé dans le code.

### Vérifications exécutées

- `.venv/bin/pytest -q` → **242 passed in 47.71s**, aucun appel réseau.
- Tâche lancée pour de vrai sur les 55 fichiers du périmètre, puis relancée au chemin par défaut :
  **0 inséré, 0 mis à jour, 18 187 inchangés** — `18187 lues = 0 + 0 + 18187 + 0 refusées + 0
  ignorées`.
- Contrôles en base : 36 374 stats = 2 × 18 187, **0 match** sans ses deux lignes, **0** `club_id`
  orphelin (règle 10), **0** incohérence entre `camp` et le club du match, **0** mi-temps
  supérieure au score final, **0** tirs cadrés supérieurs aux tirs, **0** match d'un club contre
  lui-même. Répartition par ligue : D1 3 096, E0 3 850, F1 3 522, I1 3 850, SP1 3 869 — les creux
  correspondent aux Ligue 1 et Bundesliga à 18 clubs et au Covid.
- **Quatre régressions volontaires**, comme en T01 à T03 : fuseau source ramené à UTC (6 tests
  tombent, dont la confrontation à API-Football), écriture systématique au lieu des seules
  différences (4 tests, dont `maj_le`), contrôle de plausibilité désactivé (4 tests, plus la
  contrainte SQL sur la ligne réelle), synchronisation commitée avant le contrôle des refus (2
  tests). Fichier restauré à l'identique ensuite (empreinte MD5 vérifiée).
  - Une cinquième tentative n'a **rien** fait tomber : un `commit` placé avant toute écriture en
    attente est un no-op, pas une régression. Déplacé après `synchroniser`, il a mordu. À retenir :
    une régression qui ne casse rien doit d'abord être suspectée d'être mal posée.
- Référentiel intact (empreintes de `clubs.csv` et `ligues.csv` inchangées). Rien n'a été committé
  (règle 7). L'ancien dépôt n'a pas été modifié (règle 1) : `HEAD` sur `main`, ses seuls fichiers
  non suivis datent d'avant T02.
- Prochaine étape : T05 (ingestion understat, liaison aux matchs, ≥ 99 % de liaison).
