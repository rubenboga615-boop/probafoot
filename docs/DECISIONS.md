# Décisions

Chaque décision a une raison. Pour en changer, l'écrire ici avec la date.

| # | Décision | Raison |
| --- | --- | --- |
| D01 | Version 1 limitée aux 5 grands championnats | Meilleures données (xG, cotes de clôture), public le plus large, périmètre finissable |
| D02 | football-data.co.uk = source principale des résultats, stats, scores mi-temps et cotes de clôture | Gratuit, 10 saisons, cotes Pinnacle de clôture à 92 % : indispensable pour valider le moteur |
| D03 | understat = source des xG (match et équipe) | Seule source gratuite d'xG sur 10 saisons pour ces 5 ligues |
| D04 | API-Football sert uniquement au calendrier, aux statuts et aux scores des matchs | Décision du propriétaire. Environ 10 à 30 requêtes par jour ; repli : football-data.org |
| D05 | Référentiel interne `club_id` (data/reference/clubs.csv), 165 clubs vérifiés | Les trois sources nomment les clubs différemment ; sans référentiel, rien ne se relie |
| D06 | Un seul modèle de score (Dixon-Coles pondéré dans le temps, enrichi Elo et xG) produit tous les marchés match entier ; un second modèle sur les buts de 1re mi-temps produit les marchés mi-temps | Cohérence entre marchés, un seul endroit à valider |
| D07 | Backtest en avance progressive (walk-forward) obligatoire avant toute publication d'un marché | Prouver avant de vendre ; éviter de publier un marché mal calibré |
| D08 | Référence de comparaison : cotes Pinnacle de clôture, marge retirée | Marché le plus précis mesuré (calibration à ±1 point sur 62 000 matchs) |
| D09 | Pronostics figés : calcul la veille, dernière vérification IA avant le match, gel 60 min avant le coup d'envoi, stockage en ajout seul avec horodatage et empreinte (hash) | Historique vérifiable = argument de vente et protection |
| D10 | Aucun hasard dans les pronostics publiés | L'ancienne application changeait de pronostic à chaque clic : rédhibitoire |
| D11 | Coupons : une seule sélection par match, 2 à 10 sélections, les paliers de confiance décident du nombre | Éviter les sélections corrélées ; logique déjà validée |
| D12 | Gemini (offre gratuite) explique et vérifie les infos de dernière minute ; il peut ajuster une probabilité de ±10 points au maximum, jamais la créer ; l'application fonctionne sans lui | Coût nul, risque contenu |
| D13 | Stack : Python 3.11+ et FastAPI (backend), SQLite en local et PostgreSQL en production, HTML/CSS/JavaScript sans framework (front) | Choix du propriétaire, simple à maintenir seul |
| D14 | Le front est une application web installable (PWA) légère : moins de 300 Ko au premier chargement, utilisable en 3G | Réseau mobile variable en Côte d'Ivoire ; base réutilisable pour Android via Capacitor |
| D15 | Dates stockées en UTC, affichées en heure locale | Utilisateurs dans plusieurs fuseaux ; la Côte d'Ivoire est en GMT sans heure d'été |
| D16 | Interface en français d'abord, anglais ensuite | Marché prioritaire francophone |
| D17 | Hébergement : un petit serveur Linux (1 vCPU, 1 à 2 Go de RAM), tâches planifiées par cron, sauvegarde quotidienne de la base hors serveur | Charge faible ; le téléphone ne doit jamais être un serveur |
| D18 | Mentions obligatoires : 18 ans et plus, jeu responsable, aucune garantie de gain, historique complet affiché | Règles des stores, loi, confiance |
| D19 | Distribution : application Android (APK) et version web à partir du même code (Q1 : C). Web et APK hors store dès le lancement, Google Play ensuite | Objectif du propriétaire : une APK ; le même code HTML/JS est emballé avec Capacitor |
| D20 | Lancement gratuit, sans paiement, le temps de régulariser le statut juridique (Q2 : C). Pendant cette phase, tout le contenu est ouvert | Construit l'audience et l'historique vérifiable avant de vendre |
| D21 | Prix Côte d'Ivoire : Standard 1 500 FCFA/mois, Premium 3 000 FCFA/mois (Q3). Pas de pass semaine pour l'instant | Choix du propriétaire |
| D22 | Essai gratuit de 7 jours sur l'offre Premium, une fois par numéro de téléphone vérifié (Q5 : A) | Limite les abus |
| D23 | Abonnement API-Football Pro renouvelé (Q6 : B). Usage inchangé : calendrier, statuts, scores | Choix du propriétaire ; plus de contrainte de date sur T00 |
| D24 | Gemini au lancement (Q7 : A), avec recherche web via « Grounding with Google Search ». Repli possible : DeepSeek, mais son API n'a pas de recherche web intégrée (il faudrait un moteur de recherche séparé) | Le module gemini_analyste.py fait déjà de la recherche web ; volume faible (moins de 20 matchs par jour) |
| D25 | Pays : Côte d'Ivoire au lancement, puis Afrique de l'Ouest francophone en FCFA (Q10) | Même monnaie, mêmes moyens de paiement |
| D26 | Vérification juridique locale (LONACI, ARTCI) avant le lancement payant (Q11 : A) | Sécurité juridique |
| D27 | Contenu des offres validé (Q4) : voir tableau ci-dessous | Validé par le propriétaire |
| D28 | Budget serveur : plafond 5 000 FCFA par mois pendant le lancement gratuit ; petit serveur Linux en Europe (1 vCPU, 2 Go de RAM) et un nom de domaine (Q8) | Validé par le propriétaire |
| D29 | Nom de l'application : ProbaFoot (Q9). Vérifier la disponibilité sur Google Play, en nom de domaine et sur les réseaux sociaux avant tout dépôt | Choix du propriétaire ; aucune application de ce nom trouvée lors d'une première recherche |
| D30 | Socle technique repris de l'ancien dépôt : SQLAlchemy (ORM) pour la base, pandas, numpy et scipy pour le moteur. Chaque bibliothèque reste ajoutée par la tâche qui l'utilise en premier | Rend la reprise des modules possible au lieu d'une réécriture ; D13 prévoit PostgreSQL en production, l'ORM évite d'y réécrire le SQL. Vérifié le 24/09/2026 : les quatre s'installent et tournent sous Python 3.14 en proot |
| D31 | Référence de l'ancien dépôt : la branche `claude/audit-lecture-seule-s5yd7b`, et non `main` | `main` est 69 commits en arrière et n'a ni Dixon-Coles entraîné, ni backtest, ni les cinq correctifs de fuite de données. Constaté en T02 |

## D27 — Contenu des offres
| Contenu | Gratuit | Standard 1 500 FCFA | Premium 3 000 FCFA |
| --- | --- | --- | --- |
| Pronostic du jour (le plus sûr, match entier) | Oui | Oui | Oui |
| Historique public complet et statistiques globales | Oui | Oui | Oui |
| Tous les pronostics match entier des 5 ligues (1N2, double chance, Over/Under, BTTS, mi-temps la plus prolifique si validée) | Non | Oui | Oui |
| Coupon Sûr du jour | Non | Oui | Oui |
| Fiabilité par équipe | Non | Oui | Oui |
| Pronostics 1re mi-temps (1N2, double chance, Over/Under) | Non | Non | Oui |
| Coupons Équilibré et Audacieux | Non | Non | Oui |
| Explication IA de chaque pronostic (blessures, contexte, enjeu) | Non | Non | Oui |
| Notifications (coupon du jour, changement de dernière minute) | Non | Non | Oui |
L'essai de 7 jours donne accès à tout le Premium. Pendant le lancement gratuit (D20), tout est ouvert.
