"""Socle base de données : configuration, moteur, contraintes du schéma.

Ces tests portent sur ce que la base **refuse**. Un schéma ne se juge pas aux
colonnes qu'il déclare mais aux erreurs qu'il rend impossibles : sans le
`PRAGMA foreign_keys=ON` de `bdd/session.py`, les clés étrangères de
`bdd/modeles.py` ne sont que de la documentation, et un match pourrait désigner
un club inexistant sans que rien ne le signale.

Aucun accès réseau, aucune écriture hors de `tmp_path`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from bdd.config import (
    DATABASE_URL_DEFAUT,
    ErreurConfiguration,
    charger_config,
    chemin_sqlite,
    lire_env,
)
from bdd.modeles import Club, Ligue, Match
from bdd.session import creer_tables, fabrique_sessions, maintenant_utc, moteur

# --- Configuration ---------------------------------------------------------


def test_lire_env_ignore_commentaires_et_lignes_vides(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "# commentaire\n\nDATABASE_URL=sqlite:///a.db\nAPP_ENV = prod \nsans_egal\n",
        encoding="utf-8",
    )
    assert lire_env(tmp_path / ".env") == {
        "DATABASE_URL": "sqlite:///a.db",
        "APP_ENV": "prod",
    }


def test_lire_env_sans_fichier_ne_leve_pas(tmp_path) -> None:
    assert lire_env(tmp_path / ".env") == {}


def test_lire_env_retire_les_guillemets(tmp_path) -> None:
    (tmp_path / ".env").write_text('DATABASE_URL="sqlite:///a.db"\n', encoding="utf-8")
    assert lire_env(tmp_path / ".env")["DATABASE_URL"] == "sqlite:///a.db"


def test_config_valeurs_par_defaut(tmp_path) -> None:
    config = charger_config(racine=tmp_path, environnement={})
    assert config.database_url == DATABASE_URL_DEFAUT
    assert config.app_env == "dev"
    assert config.dossier_sauvegardes == tmp_path / "data" / "backups"


def test_config_lit_le_fichier_env(tmp_path) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite:///du_fichier.db\n", encoding="utf-8")
    config = charger_config(racine=tmp_path, environnement={})
    assert config.database_url == "sqlite:///du_fichier.db"


def test_environnement_prioritaire_sur_le_fichier_env(tmp_path) -> None:
    """Le garde-fou de conftest.py force DATABASE_URL : rien ne doit l'écraser.

    Si un `.env` gagnait, la suite de tests écrirait dans la base de travail de
    la machine (règle 7).
    """
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite:///du_fichier.db\n", encoding="utf-8")
    config = charger_config(
        racine=tmp_path, environnement={"DATABASE_URL": "sqlite:///de_l_environnement.db"}
    )
    assert config.database_url == "sqlite:///de_l_environnement.db"


def test_database_url_vide_est_une_erreur(tmp_path) -> None:
    """Pas de repli silencieux : on refuse d'ouvrir une base au hasard."""
    with pytest.raises(ErreurConfiguration, match="DATABASE_URL"):
        charger_config(racine=tmp_path, environnement={"DATABASE_URL": "   "})


@pytest.mark.parametrize(
    "url",
    ["postgresql://serveur/probafoot", "sqlite:///:memory:", "sqlite://"],
)
def test_aucun_fichier_a_proteger(url: str) -> None:
    assert chemin_sqlite(url) is None


def test_chemin_sqlite_absolu_et_relatif(tmp_path) -> None:
    assert chemin_sqlite(f"sqlite:///{tmp_path / 'a.db'}") == tmp_path / "a.db"
    assert chemin_sqlite("sqlite:///data/local.db").name == "local.db"


# --- Moteur ----------------------------------------------------------------


def test_moteur_construit_a_l_appel(tmp_path, monkeypatch) -> None:
    """Deux appels, deux URL : le moteur ne fige pas la base à l'import."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'une.db'}")
    premier = moteur()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'autre.db'}")
    second = moteur()
    assert premier.url != second.url
    premier.dispose()
    second.dispose()


def test_creer_tables_deux_fois_sans_effet(tmp_path) -> None:
    machine = moteur(f"sqlite:///{tmp_path / 'base.db'}")
    creer_tables(machine)
    creer_tables(machine)
    from sqlalchemy import inspect

    assert {"ligues", "clubs", "matchs"} <= set(inspect(machine).get_table_names())
    machine.dispose()


# --- Contraintes du schéma -------------------------------------------------


@pytest.fixture
def session(tmp_path):
    machine = moteur(f"sqlite:///{tmp_path / 'base.db'}")
    creer_tables(machine)
    ouverte = fabrique_sessions(machine)()
    yield ouverte
    ouverte.close()
    machine.dispose()


def une_ligue(**extra) -> Ligue:
    valeurs = dict(
        code_fd="E0",
        slug_understat="EPL",
        api_league_id=39,
        nom="Premier League",
        pays="Angleterre",
        equipes=20,
        matchs_saison=380,
    )
    valeurs.update(extra)
    return Ligue(**valeurs)


def un_club(club_id: str = "E0-arsenal", **extra) -> Club:
    valeurs = dict(
        club_id=club_id,
        code_fd="E0",
        nom_affiche=club_id,
        nom_football_data=club_id,
        nom_understat=club_id,
        nom_api_football=club_id,
        api_team_id=abs(hash(club_id)) % 10_000,
        saisons="2016-2027",
        nb_saisons=11,
        statut="verifie",
        saison_courante=True,
    )
    valeurs.update(extra)
    return Club(**valeurs)


def un_match(**extra) -> Match:
    valeurs = dict(
        code_fd="E0",
        saison="2026-2027",
        date_utc=datetime(2026, 9, 26, 14, 0),
        club_id_dom="E0-arsenal",
        club_id_ext="E0-chelsea",
        statut="prevu",
    )
    valeurs.update(extra)
    return Match(**valeurs)


@pytest.fixture
def session_garnie(session):
    session.add(une_ligue())
    session.flush()
    session.add_all([un_club("E0-arsenal"), un_club("E0-chelsea")])
    session.flush()
    return session


def test_cles_etrangeres_reellement_actives(session) -> None:
    """Le test qui prouve le `PRAGMA` : SQLite ne le pose pas de lui-même."""
    session.add(un_club("E0-inconnu", code_fd="XX"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_match_ne_peut_designer_un_club_inexistant(session_garnie) -> None:
    session_garnie.add(un_match(club_id_ext="E0-jamais-vu"))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_club_id_unique(session_garnie) -> None:
    session_garnie.add(un_club("E0-arsenal", nom_football_data="Autre", nom_understat="Autre"))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_api_team_id_unique(session_garnie) -> None:
    api_id = session_garnie.get(Club, "E0-arsenal").api_team_id
    session_garnie.add(un_club("E0-nouveau", api_team_id=api_id))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


@pytest.mark.parametrize("colonne", ["nom_football_data", "nom_understat"])
def test_noms_de_source_uniques(session_garnie, colonne: str) -> None:
    """Ces noms sont les clés de jointure de T04 et T05 : jamais ambigus."""
    session_garnie.add(un_club("E0-nouveau", **{colonne: "E0-arsenal"}))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_plusieurs_clubs_sans_api_team_id(session_garnie) -> None:
    """Les 69 clubs hors saison en cours n'en ont pas (D04) : NULL répétable."""
    session_garnie.add_all(
        [
            un_club("E0-hull", api_team_id=None, nom_api_football=None, saison_courante=False),
            un_club("E0-leeds", api_team_id=None, nom_api_football=None, saison_courante=False),
        ]
    )
    session_garnie.flush()
    assert session_garnie.query(Club).count() == 4


def test_match_unique_sur_la_cle_logique(session_garnie) -> None:
    session_garnie.add(un_match())
    session_garnie.flush()
    session_garnie.add(un_match())
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_match_reporte_reste_un_seul_match(session_garnie) -> None:
    """La raison de l'écart à ARCHITECTURE.md : la clé ne porte pas la date.

    Un report d'horaire ou de jour ne doit pas créer un second match, sinon
    l'idempotence de l'ingestion (T04) tombe en silence.
    """
    session_garnie.add(un_match())
    session_garnie.flush()
    session_garnie.add(un_match(date_utc=datetime(2026, 11, 2, 19, 30)))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_match_retour_accepte(session_garnie) -> None:
    """Le match retour inverse domicile et extérieur : clé différente."""
    session_garnie.add(un_match())
    session_garnie.add(un_match(club_id_dom="E0-chelsea", club_id_ext="E0-arsenal"))
    session_garnie.flush()
    assert session_garnie.query(Match).count() == 2


def test_une_equipe_ne_joue_pas_contre_elle_meme(session_garnie) -> None:
    session_garnie.add(un_match(club_id_ext="E0-arsenal"))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_mi_temps_ne_depasse_pas_le_score_final(session_garnie) -> None:
    """Garde-fou contre une inversion de colonnes dans un CSV source."""
    session_garnie.add(un_match(buts_dom=1, buts_ext=0, mt_dom=2, mt_ext=0))
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_score_de_mi_temps_valide_accepte(session_garnie) -> None:
    session_garnie.add(un_match(buts_dom=3, buts_ext=1, mt_dom=1, mt_ext=1))
    session_garnie.flush()
    assert session_garnie.query(Match).count() == 1


def test_identifiant_de_source_unique(session_garnie) -> None:
    session_garnie.add(un_match(source="api-football", source_match_id="123456"))
    session_garnie.flush()
    session_garnie.add(
        un_match(
            club_id_dom="E0-chelsea",
            club_id_ext="E0-arsenal",
            source="api-football",
            source_match_id="123456",
        )
    )
    with pytest.raises(IntegrityError):
        session_garnie.flush()


def test_horodatage_utc_sans_fuseau() -> None:
    """Les colonnes techniques stockent de l'UTC naïf (règle 11)."""
    moment = maintenant_utc()
    assert moment.tzinfo is None
    ecart = abs((datetime.now(UTC).replace(tzinfo=None) - moment).total_seconds())
    assert ecart < 5
