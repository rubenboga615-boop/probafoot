"""
Schéma de la base (docs/ARCHITECTURE.md)
========================================

Trois tables pour l'instant : `ligues` et `clubs`, chargées depuis
`data/reference/` par `ingestion/charger_referentiel.py` (T03), et `matchs`,
que remplira T04. Les neuf autres tables d'ARCHITECTURE.md sont déclarées par la
tâche qui les remplit : on ne fige pas des colonnes avant de connaître leur
usage réel.

Ce qui est repris de `app/models.py` de l'ancien dépôt : les contraintes
d'unicité déclarées sur les **clés logiques**, pas seulement sur les
identifiants techniques. L'idempotence des pipelines y reposait sur un `SELECT`
applicatif avant écriture, sans filet au niveau de la base ; ici la base refuse
elle-même le doublon.

Aucun nom d'équipe brut dans les tables métier : `matchs` désigne les clubs par
`club_id` (règle 10). Les noms par source vivent dans `clubs`, et nulle part
ailleurs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bdd.session import Base, maintenant_utc


class Ligue(Base):
    """Un des 5 grands championnats (D01). Chargée depuis `ligues.csv`."""

    __tablename__ = "ligues"

    # Le code football-data.co.uk (E0, SP1, I1, D1, F1) est la clé primaire :
    # c'est l'identifiant qui apparaît dans les fichiers de la source
    # principale (D02) et dans les `club_id`.
    code_fd: Mapped[str] = mapped_column(String, primary_key=True)
    slug_understat: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    api_league_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String, nullable=False)
    pays: Mapped[str] = mapped_column(String, nullable=False)
    equipes: Mapped[int] = mapped_column(Integer, nullable=False)
    matchs_saison: Mapped[int] = mapped_column(Integer, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)


class Club(Base):
    """Un club du référentiel vérifié (D05). Chargé depuis `clubs.csv`.

    Les trois colonnes de noms sont **uniques** : ce sont les clés de jointure
    de T04 (football-data) et T05 (understat). Deux clubs portant le même nom
    dans une source rendraient la jointure ambiguë, et l'ambiguïté se résoudrait
    en silence au premier arrivé. Vérifié sur les 165 lignes du référentiel :
    aucun doublon, même toutes ligues confondues.
    """

    __tablename__ = "clubs"

    club_id: Mapped[str] = mapped_column(String, primary_key=True)
    code_fd: Mapped[str] = mapped_column(
        String, ForeignKey("ligues.code_fd"), nullable=False, index=True
    )
    nom_affiche: Mapped[str] = mapped_column(String, nullable=False)
    nom_football_data: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    nom_understat: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # API-Football ne sert qu'au calendrier, aux statuts et aux scores (D04) :
    # seuls les clubs de la saison en cours ont une correspondance. Les autres
    # restent à NULL, et SQLite accepte plusieurs NULL sous une contrainte
    # d'unicité — c'est bien ce qu'on veut ici.
    nom_api_football: Mapped[str | None] = mapped_column(String)
    api_team_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    saisons: Mapped[str] = mapped_column(String, nullable=False)
    nb_saisons: Mapped[int] = mapped_column(Integer, nullable=False)
    statut: Mapped[str] = mapped_column(String, nullable=False)
    # Colonne `saison_2026_27` du CSV. Nommée sans l'année en base : sinon
    # chaque nouvelle saison imposerait une migration de schéma pour renommer
    # une colonne dont le sens, lui, ne change pas.
    saison_courante: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)


class Match(Base):
    """Un match de championnat. Rempli par T04 (football-data) et T07 (calendrier).

    **Clé logique** : `(code_fd, saison, club_id_dom, club_id_ext)`.
    ARCHITECTURE.md annonçait `(ligue, date, club_dom, club_ext)` ; la date est
    remplacée par la saison parce que dans ces cinq championnats une paire
    domicile/extérieur ne se rencontre qu'une fois par saison, alors que
    l'heure — et parfois le jour — du coup d'envoi change couramment. Avec la
    date dans la clé, un match reporté entrerait une seconde fois et
    l'idempotence de l'ingestion tomberait en silence.
    """

    __tablename__ = "matchs"
    __table_args__ = (
        UniqueConstraint(
            "code_fd", "saison", "club_id_dom", "club_id_ext", name="uq_matchs_logique"
        ),
        # Un identifiant de source désigne un match et un seul (fixture_id
        # API-Football, ligne de CSV football-data).
        Index("uq_matchs_source", "source", "source_match_id", unique=True),
        # Sélection des matchs d'une ligue sur une période : classement,
        # moyenne de buts de la ligue, fenêtres de features, backtest.
        Index("idx_matchs_ligue_date", "code_fd", "date_utc"),
        CheckConstraint(
            "club_id_dom <> club_id_ext", name="ck_matchs_equipes_distinctes"
        ),
        # Les buts de la mi-temps ne peuvent pas dépasser ceux du match : une
        # inversion de colonnes dans un CSV source se verrait ici, et pas trois
        # mois plus tard dans les marchés de mi-temps (T12).
        CheckConstraint(
            "mt_dom IS NULL OR buts_dom IS NULL OR mt_dom <= buts_dom",
            name="ck_matchs_mi_temps_dom",
        ),
        CheckConstraint(
            "mt_ext IS NULL OR buts_ext IS NULL OR mt_ext <= buts_ext",
            name="ck_matchs_mi_temps_ext",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_fd: Mapped[str] = mapped_column(
        String, ForeignKey("ligues.code_fd"), nullable=False
    )
    # Forme « 2026-2027 », comme la colonne `saisons` de clubs.csv.
    saison: Mapped[str] = mapped_column(String, nullable=False)
    # Coup d'envoi en UTC (règle 11). L'affichage en heure locale est du
    # ressort de l'API et du front.
    date_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    club_id_dom: Mapped[str] = mapped_column(
        String, ForeignKey("clubs.club_id"), nullable=False
    )
    club_id_ext: Mapped[str] = mapped_column(
        String, ForeignKey("clubs.club_id"), nullable=False
    )
    statut: Mapped[str] = mapped_column(String, nullable=False, default="prevu")
    buts_dom: Mapped[int | None] = mapped_column(Integer)
    buts_ext: Mapped[int | None] = mapped_column(Integer)
    mt_dom: Mapped[int | None] = mapped_column(Integer)
    mt_ext: Mapped[int | None] = mapped_column(Integer)
    # Inutilisé en version 1 ; stocké parce que la donnée est gratuite dans le
    # CSV football-data et perdue pour toujours si l'import la jette.
    arbitre: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    source_match_id: Mapped[str | None] = mapped_column(String)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant_utc)
