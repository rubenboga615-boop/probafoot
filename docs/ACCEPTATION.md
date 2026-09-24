# Critères d'acceptation

Une fonctionnalité est terminée quand tous ses critères ont un test automatique vert (ou une vérification manuelle notée dans PROGRESSION.md quand un test automatique est impossible).

## Données
- [ ] Les 10 saisons des 5 ligues sont en base : nombre de matchs par saison = 380 (E0, SP1, I1) ou 306 (D1, F1), sauf saison en cours.
- [ ] 100 % des matchs ont un `club_id` domicile et extérieur valide ; aucun nom brut dans les tables métier.
- [ ] Au moins 99 % des matchs des 5 ligues ont leurs xG understat reliés.
- [ ] Relancer une ingestion deux fois de suite n'ajoute aucune ligne (idempotence).
- [ ] Le calendrier des 14 prochains jours est à jour chaque matin, en 30 requêtes maximum.

## Moteur
- [ ] Même entrée, même sortie : deux calculs successifs donnent des probabilités identiques.
- [ ] Pour chaque match : somme 1N2 = 1 (±0,001), somme des scores de la matrice ≥ 0,999.
- [ ] Double chance, Over/Under et BTTS sont cohérents avec la matrice des scores (test de dérivation).
- [ ] Test anti-fuite : aucune feature d'un match n'utilise un match daté après lui.
- [ ] Rapport de backtest généré, avec calibration par marché et comparaison Pinnacle.
- [ ] Chaque marché publié respecte les critères de docs/MOTEUR.md section 6 ; les autres sont désactivés dans la configuration.

## Publication
- [ ] Une prédiction publiée ne peut plus être modifiée (test : tentative de mise à jour refusée).
- [ ] Chaque prédiction publiée a un horodatage antérieur au coup d'envoi et une empreinte SHA-256 vérifiable.
- [ ] Coupon non publié si aucun pronostic n'atteint son palier.
- [ ] Jamais deux sélections du même match dans un coupon.
- [ ] Sans Gemini (clé absente ou erreur), la publication fonctionne avec les probabilités brutes.
- [ ] L'ajustement IA ne dépasse jamais ±10 points.

## Application
- [ ] Premier chargement de la PWA sous 300 Ko ; utilisable avec une connexion 3G.
- [ ] Tous les écrans de SPEC.md existent et affichent des données réelles de l'API (aucune donnée fictive).
- [ ] Historique : chaque pronostic passé affiche son résultat ; taux par marché et par palier calculés automatiquement.
- [ ] Mentions 18+, jeu responsable et absence de garantie de gain visibles à l'inscription et sur le paywall.

## Paiement (selon réponse à Q1)
- [ ] Essai, abonnement, renouvellement, expiration et annulation testés en mode test du fournisseur de paiement.
- [ ] L'accès Premium est accordé uniquement après confirmation côté serveur.

## Checklist de mise en production
- [ ] Aucune clé secrète dans le code ni dans l'historique Git
- [ ] Backend sur serveur en HTTPS, indépendant du téléphone
- [ ] Sauvegarde quotidienne testée par une restauration réelle
- [ ] Tâches planifiées actives avec alerte en cas d'échec
- [ ] Politique de confidentialité et conditions d'utilisation en ligne
- [ ] Vérification juridique locale faite (Q11)
- [ ] Parcours complet testé sur un vrai téléphone Android par quelqu'un d'autre que le développeur
- [ ] Journal d'erreurs actif
