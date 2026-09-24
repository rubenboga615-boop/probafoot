"""
Configuration lue dans `.env`, sans dépendance
==============================================

Un seul endroit décide où la base est ouverte. La priorité est toujours la
même : valeur par défaut < `.env` à la racine < variables d'environnement.
L'environnement gagne, et ce n'est pas un détail : `tests/conftest.py` **force**
`DATABASE_URL` vers une base temporaire hors du dépôt avant tout import (règle 7).
Si un `.env` pouvait l'écraser, la suite de tests écrirait dans la base de
travail de la machine.

Pas de pydantic-settings, contrairement à l'ancien dépôt : D30 n'autorise que
SQLAlchemy, pandas, numpy et scipy, et `pydantic-core` est une roue Rust dont
l'installation n'est pas garantie sous Python 3.14 en proot. Trente lignes de
bibliothèque standard suffisent ici.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Valeur de .env.example : un fichier local, ignoré par Git. Jamais une base de
# production — celle du serveur est nommée dans son propre .env (règle 7).
DATABASE_URL_DEFAUT = "sqlite:///data/local.db"
APP_ENV_DEFAUT = "dev"
DOSSIER_SAUVEGARDES_DEFAUT = "data/backups"


class ErreurConfiguration(Exception):
    """La configuration est inutilisable ; on s'arrête au lieu de deviner."""


@dataclass(frozen=True)
class Config:
    """Configuration effective, immuable une fois lue."""

    database_url: str
    app_env: str
    dossier_sauvegardes: Path

    @property
    def chemin_base(self) -> Path | None:
        """Fichier SQLite désigné par l'URL, ou ``None``.

        ``None`` pour PostgreSQL (D13) et pour `sqlite:///:memory:` : il n'y a
        alors aucun fichier à sauvegarder ni à protéger.
        """
        return chemin_sqlite(self.database_url)


def lire_env(chemin: Path | None = None) -> dict[str, str]:
    """Contenu de `.env` sous forme de dictionnaire, sans rien modifier.

    Fonction pure : elle ne touche pas à `os.environ`. C'est ce qui permet de
    la tester sans polluer le processus, et de garder la priorité de
    l'environnement explicite dans `charger_config`.
    """
    chemin = chemin or RACINE / ".env"
    if not chemin.exists():
        return {}
    valeurs: dict[str, str] = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        valeurs[cle.strip()] = valeur.strip().strip("\"'")
    return valeurs


def chemin_sqlite(url: str) -> Path | None:
    """Chemin du fichier désigné par une URL SQLite, ou ``None``.

    Même logique que `tests/conftest.py:chemin_de_base`, qui doit rester
    indépendant du code applicatif pour protéger la suite avant tout import.
    """
    prefixe = "sqlite:///"
    if not url.startswith(prefixe):
        return None
    brut = url[len(prefixe) :]
    if not brut or brut.startswith(":"):
        return None
    chemin = Path(brut)
    return chemin if chemin.is_absolute() else (RACINE / chemin).resolve()


def charger_config(
    racine: Path | None = None, environnement: dict[str, str] | None = None
) -> Config:
    """Configuration effective : défauts, puis `.env`, puis l'environnement."""
    racine = racine or RACINE
    environnement = os.environ if environnement is None else environnement
    fichier = lire_env(racine / ".env")

    def valeur(cle: str, defaut: str) -> str:
        if cle in environnement:
            return environnement[cle]
        return fichier.get(cle, defaut)

    url = valeur("DATABASE_URL", DATABASE_URL_DEFAUT).strip()
    if not url:
        # Un repli silencieux ici ouvrirait une base au hasard : leçon de T02,
        # « tout repli silencieux doit être remplacé par une erreur ».
        raise ErreurConfiguration(
            "DATABASE_URL est vide. Renseigner .env (modèle : .env.example) "
            f"ou la retirer pour prendre le défaut {DATABASE_URL_DEFAUT!r}."
        )

    sauvegardes = Path(valeur("DOSSIER_SAUVEGARDES", DOSSIER_SAUVEGARDES_DEFAUT))
    if not sauvegardes.is_absolute():
        sauvegardes = racine / sauvegardes

    return Config(
        database_url=url,
        app_env=valeur("APP_ENV", APP_ENV_DEFAUT).strip(),
        dossier_sauvegardes=sauvegardes,
    )
