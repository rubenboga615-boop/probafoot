"""
Épreuve des garde-fous d'isolation de `conftest.py`
===================================================

Un garde-fou que rien ne teste est une intention, pas une protection. Ces tests
vérifient les trois dispositifs : la base utilisée pendant la suite est hors du
dépôt, le détecteur de base reconnaît les formes d'URL qu'il peut rencontrer, et
le contrôle d'empreinte du référentiel voit bien une modification.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.conftest import (
    BASE_DE_TEST,
    RACINE,
    REFERENCE,
    chemin_de_base,
    empreinte_du_referentiel,
    est_base_du_depot,
    fichiers_modifies,
)


# ── La base utilisée par la suite ────────────────────────────────────


def test_la_base_de_test_est_hors_du_depot() -> None:
    """La base temporaire ne doit pas se trouver dans le dépôt."""
    assert RACINE not in BASE_DE_TEST.resolve().parents


def test_database_url_pointe_sur_la_base_de_test() -> None:
    """La variable d'environnement vue par le code est celle qu'on a forcée."""
    assert chemin_de_base(os.environ["DATABASE_URL"]) == BASE_DE_TEST.resolve()


def test_aucune_base_creee_dans_le_depot() -> None:
    """Aucun fichier de base ne doit apparaître dans data/."""
    bases = sorted(p.name for p in (RACINE / "data").glob("*.db"))
    assert bases == [], f"bases trouvées dans data/ : {bases}"


# ── Le détecteur de base du dépôt ────────────────────────────────────


def test_chemin_relatif_resolu_depuis_la_racine() -> None:
    """`sqlite:///data/local.db` désigne bien le fichier du dépôt."""
    assert chemin_de_base("sqlite:///data/local.db") == (RACINE / "data" / "local.db")


def test_chemin_absolu_reconnu() -> None:
    """La forme à quatre barres obliques porte un chemin absolu."""
    assert chemin_de_base("sqlite:////tmp/ailleurs.db") == Path("/tmp/ailleurs.db")


def test_base_en_memoire_sans_fichier() -> None:
    """Une base en mémoire ne met aucun fichier en danger."""
    assert chemin_de_base("sqlite:///:memory:") is None


def test_url_postgresql_ignoree() -> None:
    """La production tourne sur PostgreSQL (D13) : aucun fichier à protéger."""
    assert chemin_de_base("postgresql://utilisateur@serveur/probafoot") is None


def test_base_du_depot_detectee_sous_ses_deux_formes() -> None:
    """Le même fichier, écrit en relatif ou en absolu, est reconnu deux fois."""
    absolu = (RACINE / "data" / "local.db").as_posix()
    assert est_base_du_depot("sqlite:///data/local.db")
    assert est_base_du_depot(f"sqlite:///{absolu}")


def test_autre_nom_de_base_dans_le_depot_detecte() -> None:
    """Le critère est l'appartenance au dépôt, pas le nom du fichier."""
    assert est_base_du_depot("sqlite:///probafoot.db")
    assert est_base_du_depot("sqlite:///data/raw/essai.db")


def test_base_hors_depot_acceptee() -> None:
    """Une base temporaire hors du dépôt ne déclenche rien."""
    assert not est_base_du_depot("sqlite:////tmp/probafoot-tests/test.db")


# ── Le contrôle d'empreinte du référentiel ───────────────────────────


def test_empreinte_couvre_les_fichiers_de_reference() -> None:
    """Les trois fichiers du référentiel sont bien pris en compte."""
    empreinte = empreinte_du_referentiel()
    assert "clubs.csv" in empreinte
    assert "ligues.csv" in empreinte
    assert len(empreinte) == len(list(REFERENCE.iterdir()))


def test_empreinte_stable_sans_modification(tmp_path: Path) -> None:
    """Deux relevés successifs d'un dossier intact sont identiques."""
    (tmp_path / "clubs.csv").write_text("club_id,nom\nE0-arsenal,Arsenal\n")
    assert empreinte_du_referentiel(tmp_path) == empreinte_du_referentiel(tmp_path)


def test_modification_detectee(tmp_path: Path) -> None:
    """Changer une ligne d'un fichier suffit à être vu."""
    fichier = tmp_path / "clubs.csv"
    fichier.write_text("club_id,nom\nE0-arsenal,Arsenal\n")
    avant = empreinte_du_referentiel(tmp_path)

    fichier.write_text("club_id,nom\nE0-arsenal,Arsenal FC\n")

    assert fichiers_modifies(avant, empreinte_du_referentiel(tmp_path)) == ["clubs.csv"]


def test_ajout_et_suppression_detectes(tmp_path: Path) -> None:
    """Un fichier ajouté ou supprimé compte comme une modification."""
    (tmp_path / "ligues.csv").write_text("code_fd,nom\nE0,Premier League\n")
    avant = empreinte_du_referentiel(tmp_path)

    (tmp_path / "clubs.csv").write_text("club_id,nom\nE0-arsenal,Arsenal\n")
    (tmp_path / "ligues.csv").unlink()

    assert fichiers_modifies(avant, empreinte_du_referentiel(tmp_path)) == [
        "clubs.csv",
        "ligues.csv",
    ]


def test_dossier_absent_sans_empreinte(tmp_path: Path) -> None:
    """Un dossier de référence absent ne fait pas échouer le relevé."""
    assert empreinte_du_referentiel(tmp_path / "inexistant") == {}
