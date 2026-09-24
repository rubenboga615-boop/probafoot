"""Lanceur de migrations : aucune écriture de schéma sans sauvegarde vérifiée.

C'est la règle 7 mise en code. Ces tests portent donc autant sur ce que le
script fait que sur l'**ordre** dans lequel il le fait : la sauvegarde est prise
et relue *avant* la première écriture, et un nom de migration inconnu est refusé
*avant* la sauvegarde — sinon une faute de frappe laisse derrière elle une copie
de base dont personne n'aura l'usage.

Tout se passe sur une base temporaire ; `migrations/` du dépôt n'est pas utilisé.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bdd.config import Config, ErreurConfiguration
from scripts.appliquer_migrations import (
    MigrationInconnue,
    chemin_base,
    deja_appliquees,
    executer,
    migrations_disponibles,
)

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def base(tmp_path) -> Path:
    """Base minimale à migrer : une table, une ligne."""
    chemin = tmp_path / "base.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE clubs (club_id TEXT PRIMARY KEY, nom TEXT)")
    con.execute("INSERT INTO clubs VALUES ('E0-arsenal', 'Arsenal')")
    con.commit()
    con.close()
    return chemin


@pytest.fixture
def dossiers(tmp_path) -> tuple[Path, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    return migrations, tmp_path / "backups"


def ecrire_migration(dossier: Path, nom: str, sql: str) -> Path:
    fichier = dossier / nom
    fichier.write_text(sql, encoding="utf-8")
    return fichier


def lancer(base: Path, dossiers: tuple[Path, Path], **options) -> tuple[int, list[str]]:
    lignes: list[str] = []
    code = executer(
        base,
        dossier_migrations=dossiers[0],
        dossier_sauvegardes=dossiers[1],
        sortie=lignes.append,
        **options,
    )
    return code, lignes


def colonnes(base: Path, table: str) -> set[str]:
    con = sqlite3.connect(base)
    try:
        return {ligne[1] for ligne in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def registre(base: Path) -> set[str]:
    con = sqlite3.connect(base)
    try:
        return deja_appliquees(con)
    finally:
        con.close()


# --- Configuration ---------------------------------------------------------


def test_refuse_une_base_non_sqlite() -> None:
    config = Config(
        database_url="postgresql://serveur/probafoot",
        app_env="prod",
        dossier_sauvegardes=Path("/tmp"),
    )
    with pytest.raises(ErreurConfiguration, match="SQLite"):
        chemin_base(config)


def test_base_absente_refusee(tmp_path, dossiers) -> None:
    code, lignes = lancer(tmp_path / "jamais.db", dossiers)
    assert code == 1
    assert any("introuvable" in l for l in lignes)


def test_dossier_migrations_du_depot_lisible() -> None:
    """Le dossier existe et ne contient que des `.sql` (ou rien pour l'instant)."""
    assert (RACINE / "migrations").is_dir()
    assert all(f.suffix == ".sql" for f in migrations_disponibles())


# --- Application -----------------------------------------------------------


def test_applique_une_fois_puis_ne_rejoue_pas(base, dossiers) -> None:
    ecrire_migration(dossiers[0], "20260924_ajout_pays.sql",
                     "ALTER TABLE clubs ADD COLUMN pays TEXT;")
    code, lignes = lancer(base, dossiers)
    assert code == 0
    assert "pays" in colonnes(base, "clubs")
    assert registre(base) == {"20260924_ajout_pays.sql"}
    assert any("1 migration(s) appliquée(s)." in l for l in lignes)

    # `ALTER TABLE ADD COLUMN` n'est pas rejouable : sans registre, le second
    # passage échouerait et bloquerait toutes les migrations suivantes.
    code, lignes = lancer(base, dossiers)
    assert code == 0
    assert any("Rien à faire" in l for l in lignes)


def test_ordre_alphabetique_donc_chronologique(base, dossiers) -> None:
    ecrire_migration(dossiers[0], "20260902_b.sql", "ALTER TABLE clubs ADD COLUMN b TEXT;")
    ecrire_migration(dossiers[0], "20260901_a.sql", "ALTER TABLE clubs ADD COLUMN a TEXT;")
    code, lignes = lancer(base, dossiers)
    assert code == 0
    appliquees = [l for l in lignes if l.startswith("Application :")]
    assert appliquees == ["Application : 20260901_a.sql", "Application : 20260902_b.sql"]


def test_sauvegarde_prise_et_verifiee_avant_ecriture(base, dossiers) -> None:
    ecrire_migration(dossiers[0], "20260924_ajout.sql",
                     "ALTER TABLE clubs ADD COLUMN pays TEXT;")
    code, lignes = lancer(base, dossiers)
    assert code == 0

    indice_sauvegarde = next(i for i, l in enumerate(lignes) if "Sauvegarde vérifiée" in l)
    indice_ecriture = next(i for i, l in enumerate(lignes) if l.startswith("Application :"))
    assert indice_sauvegarde < indice_ecriture, "la sauvegarde doit précéder l'écriture"

    copies = list(dossiers[1].glob("*.db"))
    assert len(copies) == 1
    # La copie est l'état d'avant : elle n'a pas la nouvelle colonne, et la
    # donnée y est bien présente.
    assert "pays" not in colonnes(copies[0], "clubs")
    con = sqlite3.connect(copies[0])
    assert con.execute("SELECT COUNT(*) FROM clubs").fetchone()[0] == 1
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_echec_sql_la_migration_n_entre_pas_au_registre(base, dossiers) -> None:
    ecrire_migration(dossiers[0], "20260924_bonne.sql",
                     "ALTER TABLE clubs ADD COLUMN pays TEXT;")
    ecrire_migration(dossiers[0], "20260925_cassee.sql", "CECI N'EST PAS DU SQL;")
    code, lignes = lancer(base, dossiers)

    assert code == 1
    assert registre(base) == {"20260924_bonne.sql"}
    assert any("Échec sur 20260925_cassee.sql" in l for l in lignes)
    assert any("revenir en arrière" in l for l in lignes)

    # Après correction, seule la migration restante est rejouée.
    ecrire_migration(dossiers[0], "20260925_cassee.sql",
                     "ALTER TABLE clubs ADD COLUMN ville TEXT;")
    code, _ = lancer(base, dossiers)
    assert code == 0
    assert registre(base) == {"20260924_bonne.sql", "20260925_cassee.sql"}


# --- Modes sans écriture ---------------------------------------------------


@pytest.mark.parametrize("option", ["etat", "simuler"])
def test_etat_et_simuler_n_ecrivent_rien(base, dossiers, option: str) -> None:
    ecrire_migration(dossiers[0], "20260924_ajout.sql",
                     "ALTER TABLE clubs ADD COLUMN pays TEXT;")
    code, lignes = lancer(base, dossiers, **{option: True})
    assert code == 0
    assert "pays" not in colonnes(base, "clubs")
    assert registre(base) == set()
    assert not dossiers[1].exists(), "aucune sauvegarde ne doit être prise"
    assert any("attente" in l or "Simulation" in l for l in lignes)


# --- Inscription sans exécution -------------------------------------------


def test_marquer_appliquee_inscrit_sans_executer(base, dossiers) -> None:
    """Cas d'une base modifiée à la main avant l'existence du lanceur."""
    ecrire_migration(dossiers[0], "20260924_deja_faite.sql",
                     "ALTER TABLE clubs ADD COLUMN pays TEXT;")
    code, lignes = lancer(base, dossiers, marquer=["20260924_deja_faite.sql"])
    assert code == 0
    assert registre(base) == {"20260924_deja_faite.sql"}
    assert "pays" not in colonnes(base, "clubs"), "le SQL ne doit pas avoir été exécuté"
    assert any("SANS exécution" in l for l in lignes)

    code, lignes = lancer(base, dossiers)
    assert any("Rien à faire" in l for l in lignes)


def test_nom_inconnu_refuse_avant_toute_sauvegarde(base, dossiers) -> None:
    with pytest.raises(MigrationInconnue, match="inconnue"):
        lancer(base, dossiers, marquer=["20260924_inventee.sql"])
    assert not dossiers[1].exists(), "aucune copie ne doit rester d'une faute de frappe"
    assert registre(base) == set()
