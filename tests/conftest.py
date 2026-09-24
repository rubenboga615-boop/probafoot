"""
Isolation des tests : ni la base, ni le référentiel ne doivent être touchés
==========================================================================

Deux biens du dépôt ne se reconstituent pas tout seuls, et les règles du projet
les protègent explicitement : la base (règle 7, « ne jamais toucher à la base de
production ») et `data/reference/clubs.csv`, source de vérité des noms de clubs
(règle 10), rempli à la main en T00. Une suite de tests qui écrit au mauvais
endroit ne le signale pas : elle passe au vert, et le dommage se découvre plus
tard.

Trois garde-fous, repris de l'ancien dépôt (`tests/conftest.py`,
`test_database_isolation.py`, `test_path_isolation.py`) et adaptés :

1. `DATABASE_URL` est **forcée** vers une base temporaire hors du dépôt, avant
   tout import applicatif — écrasée, jamais complétée : une valeur héritée du
   shell ou d'un `.env` ne doit pas décider où les tests écrivent ;
2. la suite **refuse de démarrer** si la base configurée est un fichier du
   dépôt, quelle que soit la façon dont l'URL s'écrit ;
3. l'empreinte SHA-256 de `data/reference/` est relevée avant chaque test et
   vérifiée après : un test qui modifie le référentiel échoue en nommant le
   fichier, au lieu de le laisser altéré.

La **lecture** de `data/reference/` reste libre : `test_referentiel_reel.py` et
`test_structure_depot.py` en vivent.

Ces garde-fous ne dépendent d'aucune bibliothèque de base de données : ils
lisent une variable d'environnement et comparent des chemins. Ils sont donc
actifs dès aujourd'hui, avant que T03 ne crée la base.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
REFERENCE = RACINE / "data" / "reference"

# ─────────────────────────────────────────────────────────────────────
# 1) Base de test temporaire, forcée avant tout import applicatif
# ─────────────────────────────────────────────────────────────────────

_DOSSIER_TEMPORAIRE = Path(tempfile.mkdtemp(prefix="probafoot-tests-"))
atexit.register(shutil.rmtree, _DOSSIER_TEMPORAIRE, ignore_errors=True)

BASE_DE_TEST = _DOSSIER_TEMPORAIRE / "test.db"

# Affectation directe et non `setdefault` : toute valeur venant du shell ou de
# `.env` est écrasée. C'est le seul moyen de garantir qu'aucun test ne puisse
# ouvrir la base de travail, quelle que soit la configuration de la machine.
os.environ["DATABASE_URL"] = f"sqlite:///{BASE_DE_TEST}"


# ─────────────────────────────────────────────────────────────────────
# 2) Garde-fou : la base configurée n'est pas un fichier du dépôt
# ─────────────────────────────────────────────────────────────────────


def chemin_de_base(url: str) -> Path | None:
    """Chemin de fichier désigné par une URL SQLite, ou ``None``.

    Gère les deux écritures du chemin relatif (``sqlite:///data/local.db``) et
    du chemin absolu (``sqlite:////tmp/test.db``). Rend ``None`` pour une URL
    qui ne désigne pas un fichier — PostgreSQL en production (D13), ou la base
    en mémoire ``sqlite:///:memory:`` : dans ces deux cas il n'y a aucun fichier
    du dépôt à protéger.
    """
    prefixe = "sqlite:///"
    if not url.startswith(prefixe):
        return None
    brut = url[len(prefixe) :]
    if not brut or brut.startswith(":"):
        return None
    chemin = Path(brut)
    if not chemin.is_absolute():
        chemin = RACINE / chemin
    return chemin.resolve()


def est_base_du_depot(url: str) -> bool:
    """Dire si une URL de base désigne un fichier situé dans le dépôt.

    Le critère est l'appartenance au dépôt, et non l'égalité avec un nom
    précis : `data/local.db` est la valeur de `.env.example`, mais rien
    n'empêche quelqu'un d'en choisir un autre, et ce serait tout aussi grave.
    """
    chemin = chemin_de_base(url)
    if chemin is None:
        return False
    return chemin == RACINE or RACINE in chemin.parents


@pytest.fixture(scope="session", autouse=True)
def base_hors_du_depot() -> None:
    """Refuser la session de test si la base configurée est dans le dépôt."""
    url = os.environ["DATABASE_URL"]
    if est_base_du_depot(url):
        raise RuntimeError(
            "Refus d'exécuter les tests : DATABASE_URL désigne un fichier du "
            f"dépôt ({url}). Les tests doivent écrire dans une base "
            "temporaire, hors du dépôt."
        )


# ─────────────────────────────────────────────────────────────────────
# 3) Le référentiel doit sortir intact de chaque test
# ─────────────────────────────────────────────────────────────────────


def empreinte_du_referentiel(dossier: Path = REFERENCE) -> dict[str, str]:
    """Empreinte SHA-256 de chaque fichier du référentiel, par nom."""
    if not dossier.is_dir():
        return {}
    return {
        fichier.name: hashlib.sha256(fichier.read_bytes()).hexdigest()
        for fichier in sorted(dossier.iterdir())
        if fichier.is_file()
    }


def fichiers_modifies(avant: dict[str, str], apres: dict[str, str]) -> list[str]:
    """Noms des fichiers ajoutés, supprimés ou modifiés entre deux empreintes."""
    return sorted(
        nom
        for nom in set(avant) | set(apres)
        if avant.get(nom) != apres.get(nom)
    )


@pytest.fixture(autouse=True)
def referentiel_intact() -> None:
    """Vérifier après chaque test qu'aucun fichier de référence n'a bougé."""
    avant = empreinte_du_referentiel()
    yield
    modifies = fichiers_modifies(avant, empreinte_du_referentiel())
    if modifies:
        raise AssertionError(
            "Le test a modifié le référentiel, qui est la source de vérité "
            f"(règle 10) : {', '.join(modifies)}. Un test doit travailler sur "
            "une copie (fixture `tmp_path`), jamais sur data/reference/."
        )
