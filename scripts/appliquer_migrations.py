#!/usr/bin/env python3
"""
Appliquer les migrations SQL, dans l'ordre, une seule fois chacune
=================================================================

Ce script encode la règle de sécurité la plus stricte du projet : **ne jamais
modifier une base sans sauvegarde préalable vérifiée** (règle 7). Il refuse de
partir sans elle, et la vérifie lui-même — une sauvegarde qu'on n'a pas relue
n'est pas une sauvegarde, c'est un fichier.

Il tient un registre des migrations déjà passées, dans une table
`schema_migrations`. Sans lui, il faut se souvenir de ce qu'on a lancé, et les
migrations SQLite ne sont pas rejouables : `ALTER TABLE ADD COLUMN` échoue sur
une colonne existante.

Le schéma initial n'est pas une migration : il est créé par l'ORM
(`bdd.session.creer_tables`). `migrations/` ne reçoit que les changements de
schéma d'une base **déjà peuplée**, quand recréer les tables ferait perdre des
données.

Repris de `scripts/appliquer_migrations.py` de l'ancien dépôt (D31), adapté :
`bdd.config` remplace la configuration pydantic, la sortie standard remplace
`loguru`, et les fonctions sont paramétrées pour être testables sur une base
temporaire.

Usage :
    python3 scripts/appliquer_migrations.py --etat        # que reste-t-il ?
    python3 scripts/appliquer_migrations.py --simuler     # sans rien écrire
    python3 scripts/appliquer_migrations.py               # applique
    python3 scripts/appliquer_migrations.py --marquer-appliquee FICHIER

La dernière forme sert le cas d'une base modifiée à la main : elle inscrit une
migration au registre **sans l'exécuter**. Sans elle, une migration non
idempotente est rejouée, échoue, et bloque toutes les suivantes.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bdd.config import Config, ErreurConfiguration, charger_config  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
MIGRATIONS = RACINE / "migrations"

TABLE_REGISTRE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    nom        TEXT PRIMARY KEY,
    applique_a TEXT NOT NULL
)
"""


def chemin_base(config: Config) -> Path:
    """Fichier SQLite à migrer, déduit de la configuration."""
    chemin = config.chemin_base
    if chemin is None:
        raise ErreurConfiguration(
            "Ce script ne gère que les bases SQLite sur fichier. "
            f"DATABASE_URL = {config.database_url!r}"
        )
    return chemin


def migrations_disponibles(dossier: Path = MIGRATIONS) -> list[Path]:
    """Fichiers `.sql`, triés par nom — donc par date, vu la convention."""
    if not dossier.is_dir():
        return []
    return sorted(dossier.glob("*.sql"))


def deja_appliquees(con: sqlite3.Connection) -> set[str]:
    con.execute(TABLE_REGISTRE)
    con.commit()
    return {ligne[0] for ligne in con.execute("SELECT nom FROM schema_migrations")}


def sauvegarder_et_verifier(base: Path, dossier: Path, sortie=print) -> Path:
    """Copier la base, puis vérifier la copie. Lever si elle est douteuse.

    La vérification n'est pas une formalité : une copie prise pendant une
    écriture peut être structurellement invalide, et on ne le découvrirait qu'au
    moment d'en avoir besoin.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    copie = dossier / f"{base.stem}_avant_migrations_{horodatage}.db"
    shutil.copy2(base, copie)

    con = sqlite3.connect(copie)
    try:
        integrite = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrite != "ok":
            raise SauvegardeInvalide(
                f"Sauvegarde invalide ({integrite}). Aucune migration n'est appliquée. "
                "Vérifier la base source avant de recommencer."
            )
        tables = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        con.close()

    sortie(f"Sauvegarde vérifiée : {copie} ({copie.stat().st_size // 1024} Ko, {tables} tables)")
    return copie


class SauvegardeInvalide(Exception):
    """La copie de sûreté n'est pas exploitable : on n'écrit rien."""


class MigrationInconnue(Exception):
    """Un nom ne désigne aucune migration du dépôt."""


def valider_noms(noms: list[str], dossier: Path = MIGRATIONS) -> None:
    """Refuser un nom qui ne désigne aucune migration du dépôt.

    Vérifié **avant** la sauvegarde : une faute de frappe ne doit pas laisser
    derrière elle une copie de la base dont personne n'aura l'usage.
    """
    connus = {fichier.name for fichier in migrations_disponibles(dossier)}
    inconnus = sorted(set(noms) - connus)
    if inconnus:
        raise MigrationInconnue(
            f"Migration(s) inconnue(s) : {', '.join(inconnus)}. "
            f"Attendu parmi : {', '.join(sorted(connus)) or 'aucune'}"
        )


def marquer_appliquees(noms: list[str], con: sqlite3.Connection) -> list[str]:
    """Inscrire au registre des migrations dont l'effet est déjà en base.

    Ne touche qu'au registre : aucune donnée, aucun schéma, aucun fichier SQL
    exécuté. Le script ne peut pas deviner ce que chaque migration était censée
    produire — vérifier que l'effet est réellement présent reste à la charge de
    l'opérateur.
    """
    con.execute(TABLE_REGISTRE)
    horodatage = datetime.now(UTC).isoformat()
    for nom in sorted(set(noms)):
        con.execute(
            "INSERT OR REPLACE INTO schema_migrations (nom, applique_a) VALUES (?, ?)",
            (nom, horodatage),
        )
    con.commit()
    return sorted(set(noms))


def appliquer(fichier: Path, con: sqlite3.Connection) -> None:
    """Exécuter une migration et l'inscrire au registre.

    Le script SQL porte sa propre transaction ; l'inscription au registre suit
    immédiatement, dans la même connexion. Une migration appliquée mais non
    inscrite serait rejouée au prochain passage et échouerait.
    """
    con.execute(TABLE_REGISTRE)
    con.executescript(fichier.read_text(encoding="utf-8"))
    con.execute(
        "INSERT OR REPLACE INTO schema_migrations (nom, applique_a) VALUES (?, ?)",
        (fichier.name, datetime.now(UTC).isoformat()),
    )
    con.commit()


def executer(
    base: Path,
    dossier_migrations: Path = MIGRATIONS,
    dossier_sauvegardes: Path | None = None,
    etat: bool = False,
    simuler: bool = False,
    marquer: list[str] | None = None,
    sortie=print,
) -> int:
    """Corps du script, sans argparse : code de retour du processus."""
    marquer = marquer or []
    dossier_sauvegardes = dossier_sauvegardes or (RACINE / "data" / "backups")

    if not base.exists():
        sortie(f"Base introuvable : {base}")
        return 1

    con = sqlite3.connect(base)
    try:
        passees = deja_appliquees(con)
    finally:
        con.close()

    toutes = migrations_disponibles(dossier_migrations)
    restantes = [f for f in toutes if f.name not in passees]

    sortie(f"Base : {base}")
    for fichier in toutes:
        sortie(f"  {'✓ appliquée' if fichier.name in passees else '· à appliquer'}  {fichier.name}")

    if marquer:
        valider_noms(marquer, dossier_migrations)  # avant toute sauvegarde
        copie = sauvegarder_et_verifier(base, dossier_sauvegardes, sortie)
        con = sqlite3.connect(base)
        try:
            inscrites = marquer_appliquees(marquer, con)
        finally:
            con.close()
        for nom in inscrites:
            sortie(f"Inscrite au registre SANS exécution : {nom}")
        sortie(f"Pour revenir en arrière : cp {copie} {base}")
        return 0

    if not restantes:
        sortie("Rien à faire : toutes les migrations sont passées.")
        return 0

    if etat:
        sortie(f"{len(restantes)} migration(s) en attente.")
        return 0

    if simuler:
        sortie(f"Simulation : {len(restantes)} migration(s) seraient appliquées.")
        for fichier in restantes:
            sortie(f"  {fichier.name}")
        sortie("Aucune écriture effectuée.")
        return 0

    copie = sauvegarder_et_verifier(base, dossier_sauvegardes, sortie)
    con = sqlite3.connect(base)
    appliquees: list[str] = []
    fichier = restantes[0]
    try:
        for fichier in restantes:
            sortie(f"Application : {fichier.name}")
            appliquer(fichier, con)
            appliquees.append(fichier.name)
    except sqlite3.Error as erreur:
        sortie(f"Échec sur {fichier.name} : {erreur}")
        sortie(f"Migrations appliquées avant l'échec : {', '.join(appliquees) or 'aucune'}")
        sortie(f"Pour revenir en arrière : cp {copie} {base}")
        return 1
    finally:
        con.close()

    sortie(f"{len(appliquees)} migration(s) appliquée(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--etat", action="store_true", help="lister sans rien appliquer")
    parseur.add_argument("--simuler", action="store_true", help="tout vérifier, ne rien écrire")
    parseur.add_argument(
        "--marquer-appliquee",
        action="append",
        default=[],
        dest="marquer",
        metavar="FICHIER",
        help="inscrire une migration au registre sans l'exécuter. Répétable.",
    )
    arguments = parseur.parse_args(argv)

    config = charger_config()
    try:
        base = chemin_base(config)
    except ErreurConfiguration as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2

    try:
        return executer(
            base,
            dossier_sauvegardes=config.dossier_sauvegardes,
            etat=arguments.etat,
            simuler=arguments.simuler,
            marquer=arguments.marquer,
        )
    except (SauvegardeInvalide, MigrationInconnue) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
