# Spécification — ProbaFoot, version 1

## Objectif
Vendre, par abonnement, des pronostics football mesurés, figés avant le match et vérifiables publiquement. La confiance est le produit : chaque pronostic publié reste visible, gagné ou perdu.

## Utilisateurs
- Priorité : parieurs et passionnés de football francophones, d'abord en Côte d'Ivoire (paiement mobile money, connexion mobile parfois lente, budget serré).
- Ensuite : autres pays francophones, puis marché international avec prix ajustés par région.
- Âge minimum : 18 ans.

## Périmètre version 1
- Sport : football uniquement.
- Compétitions : Premier League, La Liga, Serie A, Bundesliga, Ligue 1 (96 clubs en 2026-27).
- Historique pour le moteur : saisons 2016-17 à 2025-26, plus la saison en cours.
- Marchés match entier : 1N2, double chance, Over/Under 0,5 à 3,5, BTTS, mi-temps la plus prolifique.
- Marchés 1re mi-temps : 1N2, double chance, Over/Under 0,5 à 2,5.
- Un marché n'est publié que s'il passe les critères du backtest (docs/MOTEUR.md).
- Coupons du jour : Sûr (confiance moyenne ≥ 80 %), Équilibré (≥ 68 %), Audacieux (≥ 55 %). Aucun coupon publié si aucun pronostic n'atteint le palier.
- Historique public des performances : taux réel par marché et par palier, depuis le lancement.

## Écrans (liste déjà validée)
Onboarding, accueil, détail d'un pronostic, coupons, historique, statistiques globales, profil, abonnement/paywall, notifications, support/FAQ.
Idées reprises de l'ancienne application : fiabilité par équipe, historique des pronostics avec résultat.

## Modèle économique
- Phase de lancement gratuite : tout le contenu ouvert, sans paiement (D20).
- Ensuite : essai Premium de 7 jours, puis Standard 1 500 FCFA/mois ou Premium 3 000 FCFA/mois en Côte d'Ivoire (contenu détaillé : DECISIONS.md D27).
- Zone euro (référence pour plus tard) : Standard 4,99 €/mois, Premium 9,99 €/mois.
- Distribution : APK Android et version web, même code (D19).
- Jamais de promesse de gains, nulle part.

## Hors périmètre version 1 (section "Plus tard")
- Autres championnats (liste courte de 25 déjà identifiée), autres sports.
- Marchés phase 2 : handicaps, scores exacts, buteurs, penalty, mi-temps/fin de match.
- Affichage des cotes des bookmakers dans l'application (les cotes historiques restent utilisées en interne pour valider le moteur).
- Direct / live, application iOS.
