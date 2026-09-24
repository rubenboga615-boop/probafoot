"""Normalisation et appariement des noms de clubs — aucun appel réseau."""

from __future__ import annotations

import pytest

from ingestion.noms_clubs import (
    ALIAS,
    ClubInterne,
    EquipeApi,
    apparier,
    normaliser,
)


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Bayern München", "bayern munchen"),
        ("1. FC Köln", "koln"),
        ("Borussia Mönchengladbach", "borussia monchengladbach"),
        ("Atlético Madrid", "atletico madrid"),
        ("Nott'm Forest", "nott m forest"),
        ("Paris SG", "paris sg"),
        ("Paris FC", "paris"),
        ("Stade Brestois 29", "stade brestois 29"),
        ("  Real   Madrid  ", "real madrid"),
    ],
)
def test_normaliser(brut: str, attendu: str) -> None:
    assert normaliser(brut) == attendu


def test_normaliser_conserve_un_nom_entierement_fait_de_tokens_de_forme() -> None:
    # Vider le nom rendrait deux clubs indistinguables : on garde la forme brute.
    assert normaliser("FC") == "fc"


def _club(club_id: str, *noms: str) -> ClubInterne:
    affiche = noms[0]
    fd = noms[1] if len(noms) > 1 else noms[0]
    understat = noms[2] if len(noms) > 2 else noms[0]
    return ClubInterne(club_id, affiche, fd, understat)


def test_appariement_exact() -> None:
    clubs = [_club("E0-arsenal", "Arsenal"), _club("E0-chelsea", "Chelsea")]
    equipes = [EquipeApi(42, "Arsenal"), EquipeApi(49, "Chelsea")]

    resultat = apparier(clubs, equipes)

    assert resultat.complet
    assert resultat.appariements == {42: "E0-arsenal", 49: "E0-chelsea"}


def test_appariement_par_alias() -> None:
    assert ALIAS["hull city"] == "E0-hull"
    clubs = [_club("E0-hull", "Hull")]

    resultat = apparier(clubs, [EquipeApi(64, "Hull City")])

    assert resultat.complet
    assert resultat.appariements == {64: "E0-hull"}


def test_real_sociedad_n_est_jamais_apparie_a_real_madrid() -> None:
    """Deux clubs sans rapport qui se ressemblent : aucun appariement d'office."""
    clubs = [_club("SP1-realmadrid", "Real Madrid")]

    resultat = apparier(clubs, [EquipeApi(548, "Real Sociedad")])

    assert not resultat.complet
    assert resultat.appariements == {}
    assert resultat.clubs_sans_equipe == ["SP1-realmadrid"]
    assert resultat.propositions[0].nom_api == "Real Sociedad"


def test_un_candidat_probable_reste_une_proposition() -> None:
    """Au-dessus du seuil, le module propose ; il n'applique pas.

    Cas typique : une coquille côté fournisseur. La ressemblance est franche,
    mais seul un humain confirme — en ajoutant l'alias.
    """
    clubs = [_club("E0-nottmforest", "Nottingham Forest"), _club("E0-everton", "Everton")]

    resultat = apparier(clubs, [EquipeApi(65, "Nottingham Forrest")])

    assert resultat.appariements == {}
    proposition = resultat.propositions[0]
    assert proposition.candidats[0][0] == "E0-nottmforest"
    assert proposition.candidats[0][1] >= 0.88
    assert "confirmer" in proposition.motif


def test_deux_clubs_sur_la_meme_cle_ne_sont_pas_tranches() -> None:
    """Le piège Paris FC / Paris SG : ambiguïté signalée, rien d'appliqué."""
    clubs = [_club("F1-parisfc", "Paris FC"), _club("F1-parissg", "Paris", "Paris")]

    resultat = apparier(clubs, [EquipeApi(116, "Paris FC")])

    assert resultat.appariements == {}
    assert "plusieurs clubs" in resultat.propositions[0].motif


def test_appariement_bijectif() -> None:
    """Un club interne ne reçoit qu'une équipe API."""
    clubs = [_club("E0-arsenal", "Arsenal")]
    equipes = [EquipeApi(42, "Arsenal"), EquipeApi(999, "Arsenal")]

    resultat = apparier(clubs, equipes)

    assert resultat.appariements == {42: "E0-arsenal"}
    assert len(resultat.propositions) == 1
    assert resultat.propositions[0].equipe.api_team_id == 999


def test_rapport_lisible() -> None:
    resultat = apparier([_club("SP1-realmadrid", "Real Madrid")], [EquipeApi(548, "Real Sociedad")])

    rapport = resultat.rapport()

    assert "À TRANCHER" in rapport
    assert "Real Sociedad" in rapport
    assert "SANS ÉQUIPE API" in rapport
