# Migrations SQL

Le schéma initial **n'est pas** une migration : il est créé par l'ORM
(`bdd.session.creer_tables`, schéma dans `bdd/modeles.py`). Ce dossier ne reçoit
que les changements de schéma d'une base **déjà peuplée**, quand recréer les
tables ferait perdre des données.

Convention : un fichier `AAAAMMJJ_objet.sql`, appliqué par
`scripts/appliquer_migrations.py` — qui prend et vérifie une sauvegarde avant
toute écriture (règle 7), et inscrit chaque fichier passé dans la table
`schema_migrations` pour ne jamais le rejouer.

Chaque fichier commence par un en-tête disant *pourquoi*, les requêtes de
vérification à passer avant, et le sens retour en commentaire `-- DOWN:`.
Les instructions doivent être idempotentes quand SQLite le permet
(`CREATE INDEX IF NOT EXISTS`) : `ALTER TABLE ADD COLUMN` ne l'est pas, d'où le
registre.
