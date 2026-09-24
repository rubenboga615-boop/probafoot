-- T05 — ajouter `npxg` à `stats_match`, et les contraintes qui vont avec.
--
-- POURQUOI
--   understat publie le xG hors penalty. Un penalty est un processus différent
--   du jeu courant, celui que Dixon-Coles modélise : T10 pourra régler le
--   mélange buts / xG / npxG en validation (choix du propriétaire en T05).
--
-- POURQUOI UNE RECRÉATION DE TABLE, ET PAS UN SIMPLE `ADD COLUMN`
--   SQLite sait ajouter une colonne, mais **pas** une contrainte `CHECK` sur
--   une table existante. Un `ALTER TABLE ADD COLUMN` seul laisserait la base
--   peuplée sans `ck_stats_match_npxg` ni `ck_stats_match_xg_positif`, alors
--   que `bdd/modeles.py` les déclare : les tests, qui partent d'une base neuve,
--   seraient protégés et la vraie base ne le serait pas. C'est exactement le
--   genre d'écart silencieux que ce projet refuse. On recrée donc la table
--   selon la procédure SQLite, à l'identique du DDL produit par l'ORM.
--
-- À VÉRIFIER AVANT
--   SELECT COUNT(*) FROM stats_match;                       -- attendu : 36374
--   SELECT COUNT(*) FROM stats_match WHERE xg IS NOT NULL;  -- attendu : 500
--   PRAGMA foreign_key_check;                               -- attendu : vide
--
-- À VÉRIFIER APRÈS — mêmes comptes, colonne présente et `npxg` entièrement vide
--   (c'est `ingestion/understat.py` qui la remplit, pas cette migration) :
--   SELECT COUNT(*) FROM stats_match;
--   SELECT COUNT(*) FROM stats_match WHERE xg IS NOT NULL;
--   SELECT COUNT(*) FROM stats_match WHERE npxg IS NOT NULL;  -- attendu : 0
--   PRAGMA foreign_key_check;
--
-- DOWN: CREATE TABLE stats_match_retour AS SELECT id, match_id, club_id, camp,
-- DOWN: tirs, tirs_cadres, corners, fautes, cartons_jaunes, cartons_rouges,
-- DOWN: xg, source, cree_le, maj_le FROM stats_match;
-- DOWN: puis recréer `stats_match` sans `npxg` ni ses deux contraintes, par la
-- DOWN: même procédure que ci-dessous, et supprimer la ligne du registre.

-- `legacy_alter_table` off : `ALTER TABLE ... RENAME TO` doit réécrire les
-- références, pas les laisser pointer vers un nom disparu.
PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE stats_match_nouveau (
	id INTEGER NOT NULL,
	match_id INTEGER NOT NULL,
	club_id VARCHAR NOT NULL,
	camp VARCHAR NOT NULL,
	tirs INTEGER,
	tirs_cadres INTEGER,
	corners INTEGER,
	fautes INTEGER,
	cartons_jaunes INTEGER,
	cartons_rouges INTEGER,
	xg FLOAT,
	npxg FLOAT,
	source VARCHAR,
	cree_le DATETIME NOT NULL,
	maj_le DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_stats_match_camp UNIQUE (match_id, camp),
	CONSTRAINT uq_stats_match_club UNIQUE (match_id, club_id),
	CONSTRAINT ck_stats_match_camp CHECK (camp IN ('dom', 'ext')),
	CONSTRAINT ck_stats_match_tirs_cadres CHECK (tirs_cadres IS NULL OR tirs IS NULL OR tirs_cadres <= tirs),
	CONSTRAINT ck_stats_match_npxg CHECK (npxg IS NULL OR xg IS NULL OR npxg <= xg + 0.000001),
	CONSTRAINT ck_stats_match_xg_positif CHECK (xg IS NULL OR xg >= 0),
	FOREIGN KEY(match_id) REFERENCES matchs (id),
	FOREIGN KEY(club_id) REFERENCES clubs (club_id)
);

-- Colonnes nommées une à une : un `SELECT *` dépendrait de l'ordre des colonnes
-- de l'ancienne table. `npxg` n'est pas reprise — elle n'existait pas.
INSERT INTO stats_match_nouveau
	(id, match_id, club_id, camp, tirs, tirs_cadres, corners, fautes,
	 cartons_jaunes, cartons_rouges, xg, source, cree_le, maj_le)
SELECT id, match_id, club_id, camp, tirs, tirs_cadres, corners, fautes,
       cartons_jaunes, cartons_rouges, xg, source, cree_le, maj_le
FROM stats_match;

DROP TABLE stats_match;
ALTER TABLE stats_match_nouveau RENAME TO stats_match;

CREATE INDEX ix_stats_match_club_id ON stats_match (club_id);
CREATE INDEX ix_stats_match_match_id ON stats_match (match_id);

COMMIT;

-- Après une recréation de table, les clés étrangères se vérifient à la main :
-- `PRAGMA foreign_keys` était désactivé pendant la manœuvre.
PRAGMA foreign_key_check;
PRAGMA foreign_keys = ON;
