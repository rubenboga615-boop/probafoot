"""
Moteur SQLAlchemy et fabrique de sessions
=========================================

Repris de `app/database.py` de l'ancien dépôt pour une raison précise : le
listener `connect` qui pose `PRAGMA foreign_keys=ON`. **SQLite n'applique pas
les clés étrangères par défaut** ; sans ce listener, les `ForeignKey` du schéma
ne sont que de la documentation, et un match pourrait désigner un club
inexistant sans que rien ne le signale.

Différence avec l'ancien dépôt : le moteur y était construit à l'import du
module, ce qui figeait l'URL de la base au chargement. Ici il est construit à
l'appel. C'est ce qui permet aux tests d'ouvrir chacun leur base temporaire, et
au garde-fou de `tests/conftest.py` de rester efficace.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from bdd.config import charger_config


class Base(DeclarativeBase):
    """Classe de base des modèles ORM (schéma dans `bdd/modeles.py`)."""


def maintenant_utc() -> datetime:
    """Horodatage technique, en UTC et sans fuseau (règle 11).

    `datetime.utcnow()` est déprécié et renvoie un datetime naïf qui prétend
    être local : piège classique. La base stocke des datetimes naïfs ; on
    retire donc le fuseau après coup plutôt que de mélanger, dans une même
    colonne, des valeurs naïves et des valeurs conscientes du fuseau.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _activer_cles_etrangeres(connexion, _enregistrement) -> None:
    """`PRAGMA foreign_keys=ON` sur chaque nouvelle connexion SQLite."""
    curseur = connexion.cursor()
    curseur.execute("PRAGMA foreign_keys=ON")
    curseur.close()


def moteur(url: str | None = None, echo: bool = False) -> Engine:
    """Moteur SQLAlchemy sur l'URL donnée, ou celle de la configuration."""
    url = url or charger_config().database_url
    arguments = {"check_same_thread": False} if url.startswith("sqlite") else {}
    machine = create_engine(url, echo=echo, connect_args=arguments)
    if url.startswith("sqlite"):
        event.listen(machine, "connect", _activer_cles_etrangeres)
    return machine


def fabrique_sessions(machine: Engine) -> sessionmaker:
    """Fabrique de sessions liée à un moteur."""
    return sessionmaker(bind=machine, autocommit=False, autoflush=False)


def creer_tables(machine: Engine) -> None:
    """Crée les tables manquantes. Sans effet si elles existent déjà.

    Ne modifie **jamais** une table existante : un changement de schéma sur une
    base peuplée passe par `scripts/appliquer_migrations.py`, qui impose une
    sauvegarde vérifiée.
    """
    import bdd.modeles  # noqa: F401  (enregistre les tables sur Base.metadata)

    Base.metadata.create_all(bind=machine)
