# Moteur de pronostics et backtest

## 1. Ce que dit déjà l'historique (analyse du 23/09/2026)
Base : 67 317 matchs football-data.co.uk, 18 championnats, saisons 2016-17 à 2026-27.
- Marge moyenne Pinnacle à la clôture : 3,1 %. Moyenne du marché : 6,0 %.
- Calibration Pinnacle clôture (victoire domicile) : annoncé 42,3 % → observé 42,4 % ; annoncé 71,4 % → observé 74,3 %.
- Parier systématiquement à domicile : −3,2 % au prix Pinnacle, −1,6 % à la meilleure cote du marché.
- Seul biais visible : favoris à domicile sous 1,50 (+0,7 % chez Pinnacle, +3,5 % à la meilleure cote). Effet connu et fragile : ne pas en faire un argument commercial.
Conclusion : battre la clôture Pinnacle est très difficile. Le moteur doit au minimum être aussi bien calibré qu'elle.

## 2. Données d'entrée
- Résultats, scores mi-temps, tirs, tirs cadrés, corners, cartons, cotes : football-data.co.uk (E0, SP1, I1, D1, F1).
- xG et xGA par match : understat.
- Liaison par `club_id` (data/reference/clubs.csv) et par date du match (tolérance ±1 jour pour les décalages de fuseau).
- Règle anti-fuite : une feature calculée pour un match à l'instant t n'utilise que des matchs terminés avant t.

## 3. Modèle
1. **Force des équipes** : Dixon-Coles (attaque, défense, avantage du terrain par ligue, correction des petits scores), pondération exponentielle dans le temps (paramètre ξ réglé sur la saison 2018-19 uniquement).
2. **Enrichissements** : Elo (déjà codé) et forces calculées sur les xG ; mélange buts/xG avec un poids réglé en validation.
3. **Promus** : force initiale = moyenne des relégués de la saison précédente, ajustée par l'Elo.
4. **Sortie** : matrice des probabilités de chaque score exact de 0-0 à 10-10.
5. **1re mi-temps** : même méthode sur les buts de 1re mi-temps. Buts de 2e mi-temps = score final − score mi-temps.
6. **Mi-temps la plus prolifique** : taux de buts de chaque mi-temps, probabilité que la 1re, la 2e ou aucune ne domine.

Tous les marchés se déduisent de la matrice des scores : 1N2, double chance (sommes du 1N2), Over/Under (somme des buts), BTTS (les deux équipes ≥ 1).

## 4. Backtest en avance progressive (walk-forward)
- Échauffement : 2016-17 et 2017-18 (entraînement seul).
- Réglage des paramètres : 2018-19 uniquement.
- Évaluation : 2019-20 à 2025-26, match par match, le modèle ne voit que le passé. Ré-estimation chaque semaine.
- Signaler à part les matchs à huis clos (2020-21) : l'avantage du terrain y est différent.

## 5. Mesures
- Log-loss et score de Brier par marché.
- Calibration : prédictions groupées par tranche de 5 points ; écart entre probabilité annoncée et fréquence observée.
- Comparaison 1N2 et Over/Under 2,5 avec Pinnacle clôture, marge retirée (normalisation proportionnelle).
- Paliers de confiance : taux de réussite observé des sélections ≥ 80 %, ≥ 68 %, ≥ 55 %.
- Rapport généré automatiquement : `reports/backtest_<date>.md` (tableaux + courbes de calibration).

## 6. Critères de publication d'un marché
Un marché est publié seulement si, sur la période d'évaluation :
1. Chaque tranche de calibration avec au moins 100 cas s'écarte de moins de 3 points de la fréquence observée.
2. L'erreur de calibration moyenne pondérée (ECE) est inférieure à 0,02.
3. Pour chaque palier, le taux de réussite observé est au moins égal au seuil moins 2 points (ex. ≥ 78 % pour le palier Sûr).

Mention « fait mieux que le marché » : autorisée seulement si la log-loss du moteur est inférieure à celle de Pinnacle clôture sur au moins deux saisons complètes. Sinon, présenter les pronostics comme des probabilités calibrées, sans comparaison au marché.

## 7. Couche IA (Gemini)
- Entrée : pronostic calculé, blessures et suspensions connues, compositions probables, actualité (recherche web).
- Sortie : explication courte en français et ajustement éventuel de ±10 points au maximum, avec justification écrite.
- Tout ajustement est enregistré à côté de la probabilité brute ; le backtest et l'historique mesurent les deux.
- En cas d'erreur ou d'indisponibilité : publication de la probabilité brute sans explication.
