"""T03 — chargement de ligues.csv et clubs.csv en base.

Le référentiel est la source de vérité (règle 10) : ces tests vérifient que la
base en est une copie fidèle, que deux exécutions de suite ne changent rien, et
surtout que **rien n'est écrit** quand un fichier est douteux. Un chargement
partiel serait le pire des cas : la base aurait l'air peuplée.

`data/reference/` est lu, jamais écrit (le garde-fou de `conftest.py` le
vérifie après chaque test) ; les variantes altérées sont des copies dans
`tmp_path`.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from bdd.modeles import Club, Ligue
from bdd.session import creer_tables, fabrique_sessions, moteur
from ingestion.charger_referentiel import (
    anomalies,
    convertir_club,
    convertir_ligue,
    executer,
    main,
)
from ingestion.referentiel import TacheInterrompue, lire_clubs, lire_ligues

RACINE = Path(__file__).resolve().parent.parent
REFERENCE = RACINE / "data" / "reference"


@pytest.fixture
def url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'referentiel.db'}"


@pytest.fixture
def session_de(url):
    """Ouvre une session de lecture sur la base écrite par le chargeur."""

    def ouvrir():
        machine = moteur(url)
        creer_tables(machine)
        return fabrique_sessions(machine)()

    return ouvrir


def copie_du_referentiel(destination: Path) -> Path:
    """Copie de travail des deux CSV, modifiable sans toucher au dépôt."""
    reference = destination / "data" / "reference"
    reference.mkdir(parents=True)
    for nom in ("ligues.csv", "clubs.csv"):
        shutil.copy2(REFERENCE / nom, reference / nom)
    return destination


def reecrire(chemin: Path, lignes: list[dict[str, str]]) -> None:
    with chemin.open("w", encoding="utf-8", newline="") as f:
        redacteur = csv.DictWriter(f, fieldnames=list(lignes[0]), lineterminator="\n")
        redacteur.writeheader()
        redacteur.writerows(lignes)


# --- Le référentiel réel ---------------------------------------------------


def test_charge_les_cinq_ligues_et_les_165_clubs(url, session_de) -> None:
    rapport = executer(RACINE, url=url, sortie=lambda *_: None)
    assert (rapport.ligues.inseres, rapport.clubs.inseres) == (5, 165)

    session = session_de()
    assert session.query(Ligue).count() == 5
    assert session.query(Club).count() == 165
    assert {l.code_fd for l in session.query(Ligue)} == {"E0", "SP1", "I1", "D1", "F1"}
    session.close()


def test_96_clubs_de_la_saison_en_cours_ont_leur_api_team_id(url, session_de) -> None:
    """Les 96 de 2026-27 sont reliables au calendrier (D04) ; les 69 autres non."""
    executer(RACINE, url=url, sortie=lambda *_: None)
    session = session_de()
    courants = session.query(Club).filter_by(saison_courante=True).all()
    assert len(courants) == 96
    assert all(c.api_team_id is not None and c.nom_api_football for c in courants)
    autres = session.query(Club).filter_by(saison_courante=False).count()
    assert autres == 69
    session.close()


def test_chaque_club_est_rattache_a_sa_ligue(url, session_de) -> None:
    executer(RACINE, url=url, sortie=lambda *_: None)
    session = session_de()
    codes = {l.code_fd for l in session.query(Ligue)}
    assert all(c.code_fd in codes for c in session.query(Club))
    session.close()


@pytest.mark.parametrize(
    "club_id, nom_attendu",
    [
        ("D1-bayernmunich", "Bayern München"),
        ("D1-mgladbach", "Borussia Mönchengladbach"),
        ("D1-fckoln", "1. FC Köln"),
    ],
)
def test_accents_restitues_a_l_identique(url, session_de, club_id, nom_attendu) -> None:
    """Un nom tronqué de son accent casserait la jointure de T05 en silence."""
    executer(RACINE, url=url, sortie=lambda *_: None)
    session = session_de()
    club = session.get(Club, club_id)
    assert club is not None, f"{club_id} absent : vérifier clubs.csv"
    assert nom_attendu in {club.nom_affiche, club.nom_understat, club.nom_api_football}
    session.close()


def test_valeurs_conformes_au_csv(url, session_de) -> None:
    """Colonne par colonne, sur les 165 clubs : la base est une copie du CSV."""
    executer(RACINE, url=url, sortie=lambda *_: None)
    session = session_de()
    _, lignes = lire_clubs(REFERENCE / "clubs.csv")
    for ligne in lignes:
        attendu = convertir_club(ligne)
        club = session.get(Club, attendu["club_id"])
        for champ, valeur in attendu.items():
            assert getattr(club, champ) == valeur, f"{attendu['club_id']}.{champ}"
    session.close()


def test_le_referentiel_reel_ne_presente_aucune_anomalie() -> None:
    """Contrôle du dépôt lui-même, sans base : clubs.csv reste cohérent."""
    ligues = [convertir_ligue(l) for l in lire_ligues(REFERENCE / "ligues.csv")]
    _, lignes = lire_clubs(REFERENCE / "clubs.csv")
    assert anomalies(ligues, [convertir_club(c) for c in lignes]) == []


# --- Idempotence -----------------------------------------------------------


def test_deuxieme_execution_ne_change_rien(url, session_de) -> None:
    executer(RACINE, url=url, sortie=lambda *_: None)
    session = session_de()
    horodatages = {c.club_id: c.maj_le for c in session.query(Club)}
    session.close()

    rapport = executer(RACINE, url=url, sortie=lambda *_: None)
    assert (rapport.clubs.inseres, rapport.clubs.majs) == (0, 0)
    assert rapport.clubs.inchanges == 165
    assert (rapport.ligues.inseres, rapport.ligues.majs) == (0, 0)
    assert rapport.rien_change

    session = session_de()
    assert {c.club_id: c.maj_le for c in session.query(Club)} == horodatages
    session.close()


def test_une_valeur_modifiee_dans_le_csv_est_reportee(url, session_de, tmp_path) -> None:
    """Le CSV est la source de vérité : la base le suit, jamais l'inverse."""
    executer(RACINE, url=url, sortie=lambda *_: None)
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    for ligne in lignes:
        if ligne["club_id"] == "E0-arsenal":
            ligne["nom_affiche"] = "Arsenal FC"
    reecrire(chemin, lignes)

    rapport = executer(racine, url=url, sortie=lambda *_: None)
    assert (rapport.clubs.majs, rapport.clubs.inseres) == (1, 0)
    session = session_de()
    assert session.get(Club, "E0-arsenal").nom_affiche == "Arsenal FC"
    session.close()


def test_dry_run_n_ecrit_rien(url, session_de) -> None:
    rapport = executer(RACINE, url=url, ecrire=False, sortie=lambda *_: None)
    assert rapport.clubs.inseres == 165  # ce qui *serait* écrit
    session = session_de()
    assert session.query(Club).count() == 0
    assert session.query(Ligue).count() == 0
    session.close()


# --- Refus : rien n'est écrit ---------------------------------------------


def base_vide(session) -> bool:
    return session.query(Ligue).count() == 0 and session.query(Club).count() == 0


def test_refus_si_la_ligue_d_un_club_est_inconnue(url, session_de, tmp_path) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    lignes[0]["code_fd"] = "XX"
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="absente de ligues.csv"):
        executer(racine, url=url, sortie=lambda *_: None)
    session = session_de()
    assert base_vide(session)
    session.close()


def test_refus_si_api_team_id_en_doublon(url, session_de, tmp_path) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    courants = [l for l in lignes if l["api_team_id"]]
    courants[1]["api_team_id"] = courants[0]["api_team_id"]
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="api_team_id en doublon"):
        executer(racine, url=url, sortie=lambda *_: None)
    session = session_de()
    assert base_vide(session)
    session.close()


def test_refus_si_un_club_de_la_saison_en_cours_n_a_pas_d_api_team_id(
    url, session_de, tmp_path
) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    for ligne in lignes:
        if ligne["saison_2026_27"] == "oui":
            ligne["api_team_id"] = ""
            break
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="saison en cours"):
        executer(racine, url=url, sortie=lambda *_: None)
    session = session_de()
    assert base_vide(session)
    session.close()


def test_refus_si_un_nom_de_source_est_en_doublon(url, session_de, tmp_path) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    lignes[1]["nom_understat"] = lignes[0]["nom_understat"]
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="nom_understat en doublon"):
        executer(racine, url=url, sortie=lambda *_: None)
    session = session_de()
    assert base_vide(session)
    session.close()


def test_toutes_les_anomalies_sont_rapportees_ensemble() -> None:
    """Corriger le référentiel une fois, pas cinq relances de suite."""
    ligues = [convertir_ligue(l) for l in lire_ligues(REFERENCE / "ligues.csv")]
    _, lignes = lire_clubs(REFERENCE / "clubs.csv")
    clubs = [convertir_club(c) for c in lignes]
    clubs[0]["code_fd"] = "XX"
    clubs[1]["nom_affiche"] = ""
    clubs[2]["api_team_id"] = clubs[3]["api_team_id"]
    rapportees = anomalies(ligues, clubs)
    assert len(rapportees) >= 3


def test_valeur_non_entiere_refusee(tmp_path) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "ligues.csv"
    lignes = lire_ligues(chemin)
    lignes[0]["api_league_id"] = "trente-neuf"
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="entier attendu"):
        executer(racine, url="sqlite:///:memory:", sortie=lambda *_: None)


def test_saison_courante_mal_remplie_refusee(tmp_path) -> None:
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    lignes[0]["saison_2026_27"] = "peut-être"
    reecrire(chemin, lignes)

    with pytest.raises(TacheInterrompue, match="attendu"):
        executer(racine, url="sqlite:///:memory:", sortie=lambda *_: None)


# --- Rien n'est supprimé --------------------------------------------------


def test_un_club_absent_du_csv_est_signale_jamais_supprime(url, session_de, tmp_path) -> None:
    """`matchs` peut déjà le référencer : la suppression ne s'improvise pas."""
    executer(RACINE, url=url, sortie=lambda *_: None)
    racine = copie_du_referentiel(tmp_path / "depot")
    chemin = racine / "data" / "reference" / "clubs.csv"
    _, lignes = lire_clubs(chemin)
    retire = next(l for l in lignes if l["saison_2026_27"] == "non")
    reecrire(chemin, [l for l in lignes if l["club_id"] != retire["club_id"]])

    rapport = executer(racine, url=url, sortie=lambda *_: None)
    assert rapport.clubs.absents_du_csv == [retire["club_id"]]
    session = session_de()
    assert session.get(Club, retire["club_id"]) is not None
    assert session.query(Club).count() == 165
    session.close()


# --- Ligne de commande ----------------------------------------------------


def test_cli_dry_run_puis_ecriture(monkeypatch, tmp_path, capsys) -> None:
    """Le CLI complet, sur une base temporaire : dry-run, écriture, idempotence."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")

    assert main(["--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    machine = moteur(f"sqlite:///{tmp_path / 'cli.db'}")
    session = fabrique_sessions(machine)()
    assert session.query(Club).count() == 0
    session.close()
    machine.dispose()

    assert main([]) == 0
    assert "165 insérés" in capsys.readouterr().out

    assert main([]) == 0
    assert "0 insérés, 0 mis à jour, 165 inchangés" in capsys.readouterr().out


def test_cli_rend_1_sur_referentiel_refuse(monkeypatch, capsys) -> None:
    """Un référentiel douteux sort en erreur, sans trace d'exception brute."""

    def refuser(*_, **__):
        raise TacheInterrompue("club E0-x : ligue 'XX' absente de ligues.csv")

    monkeypatch.setattr("ingestion.charger_referentiel.executer", refuser)
    assert main([]) == 1
    assert "Tâche interrompue" in capsys.readouterr().err
