#!/usr/bin/env python3
"""
T03 — Charger le référentiel en base (tables `ligues` et `clubs`)
=================================================================

`data/reference/ligues.csv` et `data/reference/clubs.csv` sont la **source de
vérité** des ligues, des clubs et de leurs noms dans les trois sources (D05,
règle 10). Ce script les recopie en base, sans rien y interpréter.

Trois propriétés, dans cet ordre d'importance :

1. **Rien n'est écrit si quelque chose ne va pas.** Les deux fichiers sont
   entièrement contrôlés avant la première écriture, et toutes les anomalies
   sont affichées ensemble — pas seulement la première.
2. **Idempotent.** Une deuxième exécution n'insère rien, ne met rien à jour, et
   ne touche pas `maj_le` : une ligne n'est écrite que si une de ses valeurs
   diffère réellement.
3. **Rien n'est supprimé.** Une ligue ou un club présent en base mais absent du
   CSV est signalé, jamais effacé : `matchs` peut déjà le référencer.

Usage :
    python3 ingestion/charger_referentiel.py --dry-run   # ce qui changerait
    python3 ingestion/charger_referentiel.py             # écrit
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from bdd.modeles import Club, Ligue  # noqa: E402
from bdd.session import creer_tables, fabrique_sessions, maintenant_utc, moteur  # noqa: E402
from ingestion.referentiel import TacheInterrompue, lire_clubs, lire_ligues  # noqa: E402

# Colonnes du CSV recopiées telles quelles, hors conversions ci-dessous.
CHAMPS_LIGUE = ("code_fd", "slug_understat", "api_league_id", "nom", "pays",
                "equipes", "matchs_saison")
CHAMPS_CLUB = ("club_id", "code_fd", "nom_affiche", "nom_football_data",
               "nom_understat", "nom_api_football", "api_team_id", "saisons",
               "nb_saisons", "statut", "saison_courante")

COLONNE_SAISON_COURANTE = "saison_2026_27"


# -- lecture et conversion --------------------------------------------------


def _entier(valeur: str, quoi: str) -> int:
    try:
        return int(valeur)
    except (TypeError, ValueError):
        raise TacheInterrompue(f"{quoi} : entier attendu, lu {valeur!r}") from None


def _entier_ou_rien(valeur: str, quoi: str) -> int | None:
    return _entier(valeur, quoi) if (valeur or "").strip() else None


def convertir_ligue(ligne: dict[str, str]) -> dict[str, Any]:
    """Une ligne de ligues.csv en valeurs de colonnes."""
    code = (ligne.get("code_fd") or "").strip()
    return {
        "code_fd": code,
        "slug_understat": (ligne.get("slug_understat") or "").strip(),
        "api_league_id": _entier(ligne.get("api_league_id", ""), f"ligue {code} api_league_id"),
        "nom": (ligne.get("nom") or "").strip(),
        "pays": (ligne.get("pays") or "").strip(),
        "equipes": _entier(ligne.get("equipes", ""), f"ligue {code} equipes"),
        "matchs_saison": _entier(ligne.get("matchs_saison", ""), f"ligue {code} matchs_saison"),
    }


def convertir_club(ligne: dict[str, str]) -> dict[str, Any]:
    """Une ligne de clubs.csv en valeurs de colonnes.

    `saison_2026_27` du CSV devient le booléen `saison_courante` : le sens de la
    colonne ne change pas d'une saison à l'autre, son intitulé ne doit donc pas
    imposer de migration.
    """
    club_id = (ligne.get("club_id") or "").strip()
    brut = (ligne.get(COLONNE_SAISON_COURANTE) or "").strip().lower()
    if brut not in {"oui", "non"}:
        raise TacheInterrompue(
            f"club {club_id} : {COLONNE_SAISON_COURANTE} vaut {brut!r}, attendu « oui » ou « non »"
        )
    nom_api = (ligne.get("nom_api_football") or "").strip()
    return {
        "club_id": club_id,
        "code_fd": (ligne.get("code_fd") or "").strip(),
        "nom_affiche": (ligne.get("nom_affiche") or "").strip(),
        "nom_football_data": (ligne.get("nom_football_data") or "").strip(),
        "nom_understat": (ligne.get("nom_understat") or "").strip(),
        "nom_api_football": nom_api or None,
        "api_team_id": _entier_ou_rien(ligne.get("api_team_id", ""), f"club {club_id} api_team_id"),
        "saisons": (ligne.get("saisons") or "").strip(),
        "nb_saisons": _entier(ligne.get("nb_saisons", ""), f"club {club_id} nb_saisons"),
        "statut": (ligne.get("statut") or "").strip(),
        "saison_courante": brut == "oui",
    }


# -- contrôles avant écriture ------------------------------------------------


def _doublons(valeurs: list[Any]) -> list[Any]:
    vus: set[Any] = set()
    doubles: set[Any] = set()
    for valeur in valeurs:
        if valeur in vus:
            doubles.add(valeur)
        vus.add(valeur)
    return sorted(doubles)


def anomalies(ligues: list[dict[str, Any]], clubs: list[dict[str, Any]]) -> list[str]:
    """Tout ce qui empêche le chargement, en une seule liste.

    Toutes les anomalies sont rendues ensemble : corriger le référentiel une
    fois vaut mieux que relancer cinq fois de suite pour les découvrir une par
    une.
    """
    problemes: list[str] = []

    if not ligues:
        problemes.append("ligues.csv est vide")
    if not clubs:
        problemes.append("clubs.csv est vide")

    for champ in ("code_fd", "slug_understat", "api_league_id"):
        for double in _doublons([l[champ] for l in ligues]):
            problemes.append(f"ligues.csv : {champ} en doublon — {double!r}")
    for ligue in ligues:
        vides = [c for c in CHAMPS_LIGUE if ligue.get(c) in (None, "")]
        if vides:
            problemes.append(f"ligue {ligue['code_fd']!r} : colonne(s) vide(s) {', '.join(vides)}")

    connues = {l["code_fd"] for l in ligues}
    for double in _doublons([c["club_id"] for c in clubs]):
        problemes.append(f"clubs.csv : club_id en doublon — {double!r}")
    # Les noms par source sont les clés de jointure de T04 et T05 : un doublon
    # rendrait la jointure ambiguë, et l'ambiguïté se résoudrait en silence.
    for champ in ("nom_football_data", "nom_understat"):
        for double in _doublons([c[champ] for c in clubs]):
            problemes.append(f"clubs.csv : {champ} en doublon — {double!r}")
    for double in _doublons([c["api_team_id"] for c in clubs if c["api_team_id"] is not None]):
        problemes.append(f"clubs.csv : api_team_id en doublon — {double!r}")

    for club in clubs:
        if club["code_fd"] not in connues:
            problemes.append(
                f"club {club['club_id']!r} : ligue {club['code_fd']!r} absente de ligues.csv"
            )
        obligatoires = ("club_id", "nom_affiche", "nom_football_data", "nom_understat",
                        "saisons", "statut")
        vides = [c for c in obligatoires if not club.get(c)]
        if vides:
            problemes.append(
                f"club {club['club_id']!r} : colonne(s) vide(s) {', '.join(vides)}"
            )
        # Un club de la saison en cours sans correspondance API-Football ne peut
        # pas être relié au calendrier (D04, T07). L'inverse est permis : un club
        # relégué garde l'identifiant appris quand il était en première division.
        if club["saison_courante"] and (club["api_team_id"] is None or not club["nom_api_football"]):
            problemes.append(
                f"club {club['club_id']!r} : de la saison en cours mais sans "
                "api_team_id ou nom_api_football (relancer T03 après T00)"
            )

    return problemes


# -- écriture ----------------------------------------------------------------


@dataclass
class Compte:
    inseres: int = 0
    majs: int = 0
    inchanges: int = 0
    absents_du_csv: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        texte = f"{self.inseres} insérés, {self.majs} mis à jour, {self.inchanges} inchangés"
        if self.absents_du_csv:
            texte += f", {len(self.absents_du_csv)} en base et absents du CSV (conservés)"
        return texte


@dataclass
class Rapport:
    ligues: Compte = field(default_factory=Compte)
    clubs: Compte = field(default_factory=Compte)

    @property
    def rien_change(self) -> bool:
        return not (self.ligues.inseres or self.ligues.majs
                    or self.clubs.inseres or self.clubs.majs)


def _synchroniser_table(
    session: Session, modele: type, cle: str, valeurs: list[dict[str, Any]]
) -> Compte:
    """Insère ou met à jour, sans jamais supprimer."""
    compte = Compte()
    attendus = {v[cle] for v in valeurs}

    for donnees in valeurs:
        existant = session.get(modele, donnees[cle])
        if existant is None:
            session.add(modele(**donnees))
            compte.inseres += 1
            continue
        differences = {
            champ: valeur
            for champ, valeur in donnees.items()
            if getattr(existant, champ) != valeur
        }
        if not differences:
            # Aucune écriture : `maj_le` ne doit pas bouger sans raison, sinon
            # l'horodatage ne dit plus rien et l'idempotence n'est pas vérifiable.
            compte.inchanges += 1
            continue
        for champ, valeur in differences.items():
            setattr(existant, champ, valeur)
        existant.maj_le = maintenant_utc()
        compte.majs += 1

    en_base = {getattr(o, cle) for o in session.query(modele).all()}
    compte.absents_du_csv = sorted(en_base - attendus)
    return compte


def synchroniser(
    session: Session, ligues: list[dict[str, Any]], clubs: list[dict[str, Any]]
) -> Rapport:
    """Aligne la base sur les deux CSV. Les contrôles ont déjà été passés."""
    rapport = Rapport()
    rapport.ligues = _synchroniser_table(session, Ligue, "code_fd", ligues)
    # Les ligues sont émises avant les clubs : la clé étrangère `clubs.code_fd`
    # est réellement vérifiée par SQLite (PRAGMA foreign_keys=ON).
    session.flush()
    rapport.clubs = _synchroniser_table(session, Club, "club_id", clubs)
    return rapport


# -- orchestration -----------------------------------------------------------


def executer(
    racine: Path,
    url: str | None = None,
    ecrire: bool = True,
    sortie=print,
) -> Rapport:
    """Déroule T03 : contrôle les CSV, crée les tables, charge, rend le compte."""
    reference = racine / "data" / "reference"
    ligues = [convertir_ligue(l) for l in lire_ligues(reference / "ligues.csv")]
    _, lignes_clubs = lire_clubs(reference / "clubs.csv")
    clubs = [convertir_club(c) for c in lignes_clubs]

    problemes = anomalies(ligues, clubs)
    if problemes:
        raise TacheInterrompue(
            "référentiel refusé, rien n'a été écrit :\n  - " + "\n  - ".join(problemes)
        )

    machine = moteur(url)
    creer_tables(machine)
    session = fabrique_sessions(machine)()
    try:
        rapport = synchroniser(session, ligues, clubs)
        if ecrire:
            session.commit()
        else:
            session.rollback()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
        machine.dispose()

    sortie(f"ligues : {rapport.ligues}")
    sortie(f"clubs  : {rapport.clubs}")
    for table, compte in (("ligues", rapport.ligues), ("clubs", rapport.clubs)):
        if compte.absents_du_csv:
            sortie(f"  {table} en base et absents du CSV, conservés : "
                   f"{', '.join(compte.absents_du_csv)}")
    if not ecrire:
        sortie("[dry-run] aucune écriture.")
    return rapport


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    arguments = parseur.parse_args(argv)

    racine = Path(__file__).resolve().parent.parent
    try:
        executer(racine, ecrire=not arguments.dry_run)
    except TacheInterrompue as exc:
        print(f"\nTâche interrompue : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
