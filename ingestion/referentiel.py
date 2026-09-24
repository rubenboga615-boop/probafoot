#!/usr/bin/env python3
"""
T00 — Référentiel API-Football : clubs et calendrier de la saison 2026-27
=========================================================================

Pour les 5 grands championnats :
  1. `/teams`    → identifiants et noms des clubs de la saison ;
  2. `/fixtures` → calendrier complet de la saison ;
  3. remplissage des colonnes `nom_api_football` et `api_team_id` de
     `data/reference/clubs.csv` ;
  4. écriture d'un calendrier normalisé portant les `club_id` (règle 10),
     dates en UTC (règle 11).

Environ 10 requêtes. Les réponses brutes sont archivées dans `data/raw/` : une
seconde exécution les relit sans toucher au réseau, ce qui rend le script
rejouable et son résultat reproductible.

Le script n'écrit **rien** tant que les clubs ne sont pas tous appariés : un
seul cas douteux arrête la tâche et affiche le rapport à trancher.

Usage :
    python3 ingestion/referentiel.py --dry-run     # ce qui serait appelé
    python3 ingestion/referentiel.py               # récupère et écrit
    python3 ingestion/referentiel.py --force       # ignore le cache
    python3 ingestion/referentiel.py --ligues E0 SP1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.api_football import (  # noqa: E402
    ApiFootballError,
    ClientApiFootball,
    parser_equipes,
    parser_matchs,
)
from ingestion.noms_clubs import ClubInterne, EquipeApi, apparier  # noqa: E402

SAISON = 2026  # saison 2026-27 au sens API-Football
QUOTA_MINIMAL = 30  # marge sous laquelle on ne démarre pas
COLONNE_NOM = "nom_api_football"
COLONNE_ID = "api_team_id"

COLONNES_CALENDRIER = [
    "fixture_id",
    "code_fd",
    "saison",
    "journee",
    "date_utc",
    "statut_court",
    "club_id_dom",
    "club_id_ext",
    "api_team_id_dom",
    "api_team_id_ext",
    "buts_dom",
    "buts_ext",
    "mt_dom",
    "mt_ext",
    "stade",
    "ville",
]


class TacheInterrompue(Exception):
    """La tâche s'arrête sans rien écrire."""


# -- lecture du référentiel ------------------------------------------------


def lire_ligues(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def lire_clubs(chemin: Path) -> tuple[list[str], list[dict[str, str]]]:
    with chemin.open(encoding="utf-8", newline="") as f:
        lecteur = csv.DictReader(f)
        return list(lecteur.fieldnames or []), list(lecteur)


def clubs_de_la_saison(lignes: Iterable[dict[str, str]], code_fd: str) -> list[ClubInterne]:
    """Clubs internes d'une ligue présents en 2026-27."""
    return [
        ClubInterne(
            club_id=l["club_id"],
            nom_affiche=l.get("nom_affiche", ""),
            nom_football_data=l.get("nom_football_data", ""),
            nom_understat=l.get("nom_understat", ""),
        )
        for l in lignes
        if l["code_fd"] == code_fd and l.get("saison_2026_27") == "oui"
    ]


# -- écriture ---------------------------------------------------------------


def _ecrire_csv_atomique(chemin: Path, colonnes: list[str], lignes: list[dict[str, Any]]) -> None:
    """Écrit un CSV complet, ou rien : pas de fichier à moitié réécrit."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur, provisoire = tempfile.mkstemp(dir=chemin.parent, suffix=".tmp")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8", newline="") as f:
            redacteur = csv.DictWriter(f, fieldnames=colonnes, lineterminator="\n")
            redacteur.writeheader()
            redacteur.writerows(lignes)
        os.replace(provisoire, chemin)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise


def completer_clubs(
    colonnes: list[str],
    lignes: list[dict[str, str]],
    equipes_par_club: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Remplit `nom_api_football` et `api_team_id`, colonnes et ordre préservés.

    Les clubs absents de la saison 2026-27 gardent des colonnes vides :
    API-Football ne sert qu'au calendrier et aux scores à venir (D04).
    """
    nouvelles = list(colonnes)
    if COLONNE_ID not in nouvelles:
        nouvelles.insert(nouvelles.index(COLONNE_NOM) + 1, COLONNE_ID)

    completees = []
    for ligne in lignes:
        copie = {c: ligne.get(c, "") for c in nouvelles}
        equipe = equipes_par_club.get(ligne["club_id"])
        if equipe:
            copie[COLONNE_NOM] = equipe["nom_api"]
            copie[COLONNE_ID] = str(equipe["api_team_id"])
        completees.append(copie)
    return nouvelles, completees


def construire_calendrier(
    matchs: list[dict[str, Any]], code_fd: str, club_par_api_id: dict[int, str]
) -> list[dict[str, Any]]:
    """Matchs normalisés portant les `club_id` ; aucun nom brut d'équipe."""
    lignes = []
    for match in matchs:
        dom = club_par_api_id.get(match["api_team_id_dom"])
        ext = club_par_api_id.get(match["api_team_id_ext"])
        if dom is None or ext is None:
            manquant = match["api_team_id_dom"] if dom is None else match["api_team_id_ext"]
            raise TacheInterrompue(
                f"{code_fd} : match {match['fixture_id']} — équipe API {manquant} "
                "absente du référentiel"
            )
        lignes.append(
            {
                "fixture_id": match["fixture_id"],
                "code_fd": code_fd,
                "saison": match["saison"],
                "journee": match["journee"],
                "date_utc": match["date_utc"],
                "statut_court": match["statut_court"],
                "club_id_dom": dom,
                "club_id_ext": ext,
                "api_team_id_dom": match["api_team_id_dom"],
                "api_team_id_ext": match["api_team_id_ext"],
                "buts_dom": "" if match["buts_dom"] is None else match["buts_dom"],
                "buts_ext": "" if match["buts_ext"] is None else match["buts_ext"],
                "mt_dom": "" if match["mt_dom"] is None else match["mt_dom"],
                "mt_ext": "" if match["mt_ext"] is None else match["mt_ext"],
                "stade": match["stade"],
                "ville": match["ville"],
            }
        )
    return lignes


# -- récupération (cache disque) -------------------------------------------


def recuperer(
    client: ClientApiFootball | None,
    cache: Path,
    chemin_api: str,
    params: dict[str, Any],
    force: bool,
) -> list[Any]:
    """Lit le cache, ou appelle l'API et archive la réponse brute."""
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))
    if client is None:
        raise TacheInterrompue(f"{chemin_api} absent du cache et aucun appel autorisé")
    reponse = client.appeler_tout(chemin_api, **params)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(reponse, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return reponse


def _recupere_le(cache: Path) -> str:
    """Date d'archivage de la réponse brute, en UTC.

    C'est la date du fichier, pas l'instant courant : une seconde exécution
    servie par le cache réécrit donc exactement les mêmes octets.
    """
    moment = datetime.fromtimestamp(cache.stat().st_mtime, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# -- orchestration ----------------------------------------------------------


def executer(
    racine: Path,
    client: ClientApiFootball | None,
    codes_demandes: list[str] | None = None,
    force: bool = False,
    ecrire: bool = True,
    sortie=print,
) -> int:
    """Déroule T00. Retourne le nombre de clubs complétés."""
    reference = racine / "data" / "reference"
    brut = racine / "data" / "raw" / "api-football"

    ligues = lire_ligues(reference / "ligues.csv")
    if codes_demandes:
        ligues = [l for l in ligues if l["code_fd"] in codes_demandes]
        if not ligues:
            raise TacheInterrompue(f"aucune ligue ne correspond à {codes_demandes}")
    colonnes, lignes_clubs = lire_clubs(reference / "clubs.csv")

    equipes_par_club: dict[str, dict[str, Any]] = {}
    calendriers: dict[str, list[dict[str, Any]]] = {}
    manifest: list[dict[str, Any]] = []
    incomplet = False

    for ligue in ligues:
        code_fd, api_id = ligue["code_fd"], ligue["api_league_id"]
        attendus = clubs_de_la_saison(lignes_clubs, code_fd)

        cache_equipes = brut / "teams" / str(SAISON) / f"{code_fd}.json"
        equipes_brutes = recuperer(
            client, cache_equipes, "teams", {"league": api_id, "season": SAISON}, force
        )
        equipes = parser_equipes(equipes_brutes)

        resultat = apparier(
            attendus, [EquipeApi(e["api_team_id"], e["nom_api"]) for e in equipes]
        )
        sortie(f"\n{code_fd} ({ligue['nom']}) — {len(equipes)} équipes API, "
               f"{len(attendus)} clubs attendus")
        sortie("  " + resultat.rapport().replace("\n", "\n  "))
        if not resultat.complet:
            incomplet = True
            continue

        nom_par_api_id = {e["api_team_id"]: e["nom_api"] for e in equipes}
        for api_team_id, club_id in resultat.appariements.items():
            equipes_par_club[club_id] = {
                "api_team_id": api_team_id,
                "nom_api": nom_par_api_id[api_team_id],
            }

        cache_matchs = brut / "fixtures" / str(SAISON) / f"{code_fd}.json"
        matchs_bruts = recuperer(
            client, cache_matchs, "fixtures", {"league": api_id, "season": SAISON}, force
        )
        matchs = parser_matchs(matchs_bruts)
        calendriers[code_fd] = construire_calendrier(
            matchs, code_fd, resultat.appariements
        )
        attendu_matchs = int(ligue["matchs_saison"])
        marque = "OK" if len(matchs) == attendu_matchs else "ÉCART"
        sortie(f"  calendrier : {len(matchs)} matchs (attendu {attendu_matchs}) — {marque}")
        manifest.append(
            {
                "code_fd": code_fd,
                "api_league_id": api_id,
                "saison": SAISON,
                "nb_clubs": len(equipes),
                "nb_matchs": len(matchs),
                "nb_matchs_attendu": attendu_matchs,
                "recupere_le": _recupere_le(cache_matchs),
            }
        )

    if incomplet:
        raise TacheInterrompue(
            "des clubs restent à trancher : ajouter les alias dans "
            "ingestion/noms_clubs.py puis relancer (le cache évite de "
            "reconsommer le quota). Rien n'a été écrit."
        )

    if not ecrire:
        sortie("\n[dry-run] aucune écriture.")
        return len(equipes_par_club)

    nouvelles_colonnes, lignes_completees = completer_clubs(
        colonnes, lignes_clubs, equipes_par_club
    )
    _ecrire_csv_atomique(reference / "clubs.csv", nouvelles_colonnes, lignes_completees)

    for code_fd, lignes_calendrier in calendriers.items():
        _ecrire_csv_atomique(
            brut / "fixtures" / str(SAISON) / f"{code_fd}.csv",
            COLONNES_CALENDRIER,
            lignes_calendrier,
        )
    if manifest:
        _ecrire_csv_atomique(
            brut / "fixtures" / str(SAISON) / "manifest.csv",
            list(manifest[0].keys()),
            manifest,
        )

    sortie(f"\nclubs.csv : {len(equipes_par_club)} clubs complétés "
           f"sur {len(lignes_completees)} lignes.")
    return len(equipes_par_club)


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    parseur.add_argument("--force", action="store_true", help="ignore le cache local")
    parseur.add_argument("--ligues", nargs="+", metavar="CODE_FD", help="ex. E0 SP1")
    arguments = parseur.parse_args(argv)

    racine = Path(__file__).resolve().parent.parent
    client: ClientApiFootball | None = None
    try:
        client = ClientApiFootball()
        consommees, plafond = client.quota()
        restantes = plafond - consommees
        print(f"Quota API-Football : {consommees}/{plafond} utilisées, "
              f"{restantes} restantes.")
        if restantes < QUOTA_MINIMAL:
            print(f"Moins de {QUOTA_MINIMAL} requêtes restantes : on ne démarre pas.",
                  file=sys.stderr)
            return 2
    except ApiFootballError as exc:
        print(f"API indisponible ({exc}) : lecture du cache local uniquement.",
              file=sys.stderr)
        client = None

    try:
        executer(
            racine,
            client,
            codes_demandes=arguments.ligues,
            force=arguments.force,
            ecrire=not arguments.dry_run,
        )
    except (TacheInterrompue, ApiFootballError) as exc:
        print(f"\nTâche interrompue : {exc}", file=sys.stderr)
        return 1

    if client is not None:
        print(f"Requêtes émises : {client.requetes_emises}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
