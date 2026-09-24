"""T00 de bout en bout, sur un référentiel jouet — aucun appel réseau."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ingestion.referentiel import SAISON, TacheInterrompue, executer

FIXTURES = Path(__file__).parent / "fixtures" / "api_football"

COLONNES_CLUBS = [
    "ligue",
    "code_fd",
    "slug_understat",
    "api_league_id",
    "club_id",
    "nom_affiche",
    "nom_football_data",
    "nom_understat",
    "nom_api_football",
    "saisons",
    "nb_saisons",
    "statut",
    "saison_2026_27",
]


class FauxClient:
    """Rejoue des réponses enregistrées et compte les appels."""

    def __init__(self, reponses: dict[str, list]) -> None:
        self._reponses = reponses
        self.appels = 0
        self.requetes_emises = 0

    def appeler_tout(self, chemin: str, **params) -> list:
        self.appels += 1
        self.requetes_emises += 1
        return self._reponses[chemin]


def _ligne_club(club_id: str, nom: str, en_2026: str) -> dict[str, str]:
    return {
        "ligue": "Allemagne - Bundesliga",
        "code_fd": "D1",
        "slug_understat": "Bundesliga",
        "api_league_id": "78",
        "club_id": club_id,
        "nom_affiche": nom,
        "nom_football_data": nom,
        "nom_understat": nom,
        "nom_api_football": "",
        "saisons": "2016-2027",
        "nb_saisons": "11",
        "statut": "verifie",
        "saison_2026_27": en_2026,
    }


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    reference = tmp_path / "data" / "reference"
    reference.mkdir(parents=True)

    with (reference / "ligues.csv").open("w", encoding="utf-8", newline="") as f:
        redacteur = csv.DictWriter(
            f,
            fieldnames=["code_fd", "slug_understat", "api_league_id", "nom", "pays",
                        "equipes", "matchs_saison"],
            lineterminator="\n",
        )
        redacteur.writeheader()
        redacteur.writerow(
            {
                "code_fd": "D1",
                "slug_understat": "Bundesliga",
                "api_league_id": "78",
                "nom": "Bundesliga",
                "pays": "Allemagne",
                "equipes": "2",
                "matchs_saison": "2",
            }
        )

    with (reference / "clubs.csv").open("w", encoding="utf-8", newline="") as f:
        redacteur = csv.DictWriter(f, fieldnames=COLONNES_CLUBS, lineterminator="\n")
        redacteur.writeheader()
        redacteur.writerow(_ligne_club("D1-bayernmunich", "Bayern Munich", "oui"))
        redacteur.writerow(_ligne_club("D1-dortmund", "Borussia Dortmund", "oui"))
        redacteur.writerow(_ligne_club("D1-hertha", "Hertha", "non"))
    return tmp_path


@pytest.fixture
def client() -> FauxClient:
    return FauxClient(
        {
            "teams": json.loads((FIXTURES / "teams_extrait.json").read_text(encoding="utf-8")),
            "fixtures": json.loads(
                (FIXTURES / "fixtures_extrait.json").read_text(encoding="utf-8")
            ),
        }
    )


def _lire(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_remplit_les_clubs_de_la_saison(racine, client) -> None:
    assert executer(racine, client, sortie=lambda *_: None) == 2

    lignes = _lire(racine / "data" / "reference" / "clubs.csv")
    par_id = {l["club_id"]: l for l in lignes}
    assert par_id["D1-bayernmunich"]["nom_api_football"] == "Bayern München"
    assert par_id["D1-bayernmunich"]["api_team_id"] == "157"
    assert par_id["D1-dortmund"]["api_team_id"] == "165"
    # Club absent de 2026-27 : API-Football ne sert qu'aux matchs à venir (D04).
    assert par_id["D1-hertha"]["nom_api_football"] == ""
    assert par_id["D1-hertha"]["api_team_id"] == ""


def test_colonnes_et_ordre_des_lignes_preserves(racine, client) -> None:
    executer(racine, client, sortie=lambda *_: None)

    chemin = racine / "data" / "reference" / "clubs.csv"
    with chemin.open(encoding="utf-8", newline="") as f:
        colonnes = next(csv.reader(f))
    assert colonnes == COLONNES_CLUBS[:9] + ["api_team_id"] + COLONNES_CLUBS[9:]
    assert [l["club_id"] for l in _lire(chemin)] == [
        "D1-bayernmunich",
        "D1-dortmund",
        "D1-hertha",
    ]


def test_idempotence_octet_pour_octet(racine, client) -> None:
    chemin = racine / "data" / "reference" / "clubs.csv"

    executer(racine, client, sortie=lambda *_: None)
    premier = chemin.read_bytes()
    appels_apres_premier = client.appels

    executer(racine, client, sortie=lambda *_: None)

    assert chemin.read_bytes() == premier
    # Le cache disque a servi : aucun appel supplémentaire.
    assert client.appels == appels_apres_premier


def test_calendrier_normalise_sans_nom_brut(racine, client) -> None:
    executer(racine, client, sortie=lambda *_: None)

    chemin = racine / "data" / "raw" / "api-football" / "fixtures" / str(SAISON) / "D1.csv"
    lignes = _lire(chemin)
    assert len(lignes) == 2
    assert lignes[0]["club_id_dom"] == "D1-bayernmunich"
    assert lignes[0]["club_id_ext"] == "D1-dortmund"
    assert lignes[0]["date_utc"] == "2026-08-21T18:30:00Z"
    assert lignes[0]["buts_dom"] == ""
    assert lignes[1]["buts_dom"] == "2" and lignes[1]["mt_ext"] == "1"
    assert "Bayern München" not in chemin.read_text(encoding="utf-8")


def test_manifest_ecrit(racine, client) -> None:
    executer(racine, client, sortie=lambda *_: None)

    manifest = _lire(
        racine / "data" / "raw" / "api-football" / "fixtures" / str(SAISON) / "manifest.csv"
    )
    assert manifest[0]["code_fd"] == "D1"
    assert manifest[0]["nb_matchs"] == "2"
    assert manifest[0]["nb_clubs"] == "2"


def test_un_club_non_apparie_laisse_le_referentiel_intact(racine, client) -> None:
    chemin = racine / "data" / "reference" / "clubs.csv"
    lignes = _lire(chemin)
    lignes[1]["nom_affiche"] = lignes[1]["nom_football_data"] = "Nom Sans Rapport"
    lignes[1]["nom_understat"] = "Nom Sans Rapport"
    with chemin.open("w", encoding="utf-8", newline="") as f:
        redacteur = csv.DictWriter(f, fieldnames=COLONNES_CLUBS, lineterminator="\n")
        redacteur.writeheader()
        redacteur.writerows(lignes)
    avant = chemin.read_bytes()

    with pytest.raises(TacheInterrompue):
        executer(racine, client, sortie=lambda *_: None)

    assert chemin.read_bytes() == avant


def test_dry_run_n_ecrit_rien(racine, client) -> None:
    chemin = racine / "data" / "reference" / "clubs.csv"
    avant = chemin.read_bytes()

    executer(racine, client, ecrire=False, sortie=lambda *_: None)

    assert chemin.read_bytes() == avant
    assert not (racine / "data" / "raw" / "api-football" / "fixtures" / str(SAISON) / "D1.csv").exists()


def test_ligue_inconnue(racine, client) -> None:
    with pytest.raises(TacheInterrompue):
        executer(racine, client, codes_demandes=["XX"], sortie=lambda *_: None)


def test_sans_client_ni_cache(racine) -> None:
    with pytest.raises(TacheInterrompue):
        executer(racine, None, sortie=lambda *_: None)
