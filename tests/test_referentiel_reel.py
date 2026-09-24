"""Intégrité du référentiel versionné — il est la source de vérité des noms.

Ces contrôles protègent toutes les tâches suivantes : dès que `clubs.csv` ou
`ligues.csv` est modifié à la main, ils disent si le fichier reste utilisable.
"""

from __future__ import annotations

import csv
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
REFERENCE = RACINE / "data" / "reference"

MATCHS_ATTENDUS = {"E0": 380, "SP1": 380, "I1": 380, "D1": 306, "F1": 306}


def _lire(nom: str) -> list[dict[str, str]]:
    with (REFERENCE / nom).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_club_id_uniques() -> None:
    clubs = _lire("clubs.csv")
    identifiants = [c["club_id"] for c in clubs]
    assert len(set(identifiants)) == len(identifiants)


def test_chaque_club_appartient_a_une_ligue_connue() -> None:
    codes = {l["code_fd"] for l in _lire("ligues.csv")}
    assert codes == set(MATCHS_ATTENDUS)
    assert {c["code_fd"] for c in _lire("clubs.csv")} <= codes


def test_les_96_clubs_de_la_saison_ont_leur_correspondance_api() -> None:
    clubs = _lire("clubs.csv")
    saison = [c for c in clubs if c["saison_2026_27"] == "oui"]

    assert len(saison) == 96
    assert all(c["nom_api_football"] and c["api_team_id"] for c in saison)
    assert len({c["api_team_id"] for c in saison}) == 96


def test_les_autres_clubs_restent_sans_correspondance_api() -> None:
    """API-Football ne sert qu'au calendrier et aux scores à venir (D04)."""
    autres = [c for c in _lire("clubs.csv") if c["saison_2026_27"] != "oui"]

    assert autres
    assert all(not c["nom_api_football"] and not c["api_team_id"] for c in autres)


def test_effectif_par_ligue() -> None:
    clubs = [c for c in _lire("clubs.csv") if c["saison_2026_27"] == "oui"]

    for ligue in _lire("ligues.csv"):
        attendu = int(ligue["equipes"])
        present = sum(1 for c in clubs if c["code_fd"] == ligue["code_fd"])
        assert present == attendu, f"{ligue['code_fd']} : {present} clubs, attendu {attendu}"
