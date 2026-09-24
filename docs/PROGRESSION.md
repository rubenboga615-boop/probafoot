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
