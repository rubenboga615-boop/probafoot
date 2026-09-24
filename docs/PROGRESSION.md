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
