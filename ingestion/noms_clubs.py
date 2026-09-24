#!/usr/bin/env python3
"""
Appariement des noms d'équipes API-Football ↔ `club_id` interne
===============================================================

Le référentiel `data/reference/clubs.csv` est la source de vérité des noms
(règle 10). Chaque source nomme les clubs autrement : ce module ramène un nom
API-Football sur le `club_id` correspondant.

Principe repris de l'ancien dépôt : **le module propose, il n'applique jamais
tout seul**. Les noms de clubs sont un piège particulier — « Real Sociedad » et
« Real Madrid » partagent la moitié de leurs caractères sans avoir le moindre
rapport, tandis que « Wolves » et « Wolverhampton Wanderers » n'en partagent
presque aucun tout en désignant le même club. Aucun seuil ne sépare
correctement ces deux cas ; un humain, oui, une fois pour toutes.

L'appariement se fait donc en trois passes de confiance décroissante :

1. égalité sur nom normalisé (sûr, silencieux) ;
2. table d'alias écrite à la main ci-dessous (sûr, explicite, relu) ;
3. ressemblance approximative — jamais appliquée : seulement proposée à la
   relecture, pour que l'alias soit ajouté en passe 2.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Mots qui n'identifient pas un club : formes juridiques, sigles sportifs,
# années de fondation. Les retirer rapproche « 1. FC Köln » de « FC Cologne ».
TOKENS_DE_FORME = frozenset(
    {
        "fc", "cf", "ac", "as", "sc", "cs", "ss", "ssc", "us", "usl", "ud", "cd",
        "rc", "rcd", "rcd.", "sd", "sv", "tsv", "vfl", "vfb", "tsg", "fsv",
        "bsc", "msv", "spvgg", "afc", "club", "calcio", "deportivo", "de", "the",
        "1", "04", "05", "07", "08", "09", "1846", "1848", "1860", "1899", "1900",
        "1904", "1909", "1913", "united", "olympique",
    }
)

# Alias validés à la main : nom API-Football normalisé → club_id interne.
# Toute entrée ajoutée ici l'est après lecture du rapport de la passe 3.
#
# Note : « sg » n'est volontairement pas un token de forme. Le retirer ramenait
# « Paris SG » et « Paris FC » sur la même clé — deux clubs bien distincts de la
# même ligue.
ALIAS: dict[str, str] = {
    # Premier League
    "hull city": "E0-hull",
    # Bundesliga
    "bayern munchen": "D1-bayernmunich",
    "borussia monchengladbach": "D1-mgladbach",
    # Ligue 1
    "estac troyes": "F1-troyes",
    "stade brestois 29": "F1-brest",
}

SEUIL_RESSEMBLANCE = 0.88
ECART_MINIMAL = 0.08


def normaliser(nom: str) -> str:
    """Ramène un nom de club à sa forme comparable."""
    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFKD", nom)
        if not unicodedata.combining(c)
    )
    # L'eszett et les ligatures ne se décomposent pas : on les traite à part.
    sans_accents = sans_accents.replace("ß", "ss").replace("Æ", "AE").replace("æ", "ae")
    propre = "".join(c if c.isalnum() else " " for c in sans_accents.lower())
    tokens = [t for t in propre.split() if t not in TOKENS_DE_FORME]
    if not tokens:  # nom entièrement composé de tokens de forme : on les garde
        tokens = propre.split()
    return " ".join(tokens)


def ressemblance(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class ClubInterne:
    """Une ligne de clubs.csv, réduite à ce qui sert à l'appariement."""

    club_id: str
    nom_affiche: str
    nom_football_data: str
    nom_understat: str

    def noms_connus(self) -> list[str]:
        return [
            n
            for n in (self.nom_affiche, self.nom_football_data, self.nom_understat)
            if n
        ]


@dataclass(frozen=True)
class EquipeApi:
    """Une équipe telle que renvoyée par /teams."""

    api_team_id: int
    nom_api: str


@dataclass(frozen=True)
class Proposition:
    """Un cas que le module refuse de trancher seul."""

    equipe: EquipeApi
    candidats: list[tuple[str, float]]  # (club_id, score), du meilleur au pire
    motif: str

    @property
    def nom_api(self) -> str:
        return self.equipe.nom_api


@dataclass
class Resultat:
    """Sortie d'un appariement : ce qui est sûr, et ce qui reste à trancher."""

    appariements: dict[int, str] = field(default_factory=dict)  # api_team_id → club_id
    propositions: list[Proposition] = field(default_factory=list)
    clubs_sans_equipe: list[str] = field(default_factory=list)  # club_id orphelins

    @property
    def complet(self) -> bool:
        return not self.propositions and not self.clubs_sans_equipe

    def rapport(self) -> str:
        lignes = [f"{len(self.appariements)} club(s) apparié(s)."]
        for p in self.propositions:
            candidats = ", ".join(f"{cid} ({score:.2f})" for cid, score in p.candidats)
            lignes.append(
                f"  À TRANCHER  « {p.nom_api} » — {p.motif}"
                f"{' : ' + candidats if candidats else ''}"
            )
        for club_id in self.clubs_sans_equipe:
            lignes.append(f"  SANS ÉQUIPE API  {club_id}")
        return "\n".join(lignes)


def apparier(clubs: list[ClubInterne], equipes: list[EquipeApi]) -> Resultat:
    """Apparie les équipes API aux clubs internes d'une même ligue.

    L'appariement est bijectif : un `club_id` ne reçoit qu'une équipe, une
    équipe ne reçoit qu'un `club_id`. Tout ce qui n'est pas certain devient une
    proposition à relire, jamais un appariement.
    """
    resultat = Resultat()
    clubs_libres = {c.club_id: c for c in clubs}
    restantes: list[EquipeApi] = []

    # Passe 1 — égalité sur nom normalisé.
    index_exact: dict[str, list[str]] = {}
    for club in clubs:
        for nom in club.noms_connus():
            index_exact.setdefault(normaliser(nom), []).append(club.club_id)

    for equipe in equipes:
        cle = normaliser(equipe.nom_api)
        candidats = {cid for cid in index_exact.get(cle, []) if cid in clubs_libres}
        if len(candidats) == 1:
            club_id = candidats.pop()
            resultat.appariements[equipe.api_team_id] = club_id
            del clubs_libres[club_id]
        elif len(candidats) > 1:
            resultat.propositions.append(
                Proposition(
                    equipe=equipe,
                    candidats=[(cid, 1.0) for cid in sorted(candidats)],
                    motif="plusieurs clubs portent ce nom",
                )
            )
        else:
            restantes.append(equipe)

    # Passe 2 — alias validés à la main.
    encore_restantes: list[EquipeApi] = []
    for equipe in restantes:
        club_id = ALIAS.get(normaliser(equipe.nom_api))
        if club_id and club_id in clubs_libres:
            resultat.appariements[equipe.api_team_id] = club_id
            del clubs_libres[club_id]
        elif club_id:
            resultat.propositions.append(
                Proposition(
                    equipe=equipe,
                    candidats=[(club_id, 1.0)],
                    motif="alias pointant sur un club déjà apparié",
                )
            )
        else:
            encore_restantes.append(equipe)

    # Passe 3 — ressemblance : proposée, jamais appliquée.
    for equipe in encore_restantes:
        cle = normaliser(equipe.nom_api)
        scores = sorted(
            (
                (club.club_id, max(ressemblance(cle, normaliser(n)) for n in club.noms_connus()))
                for club in clubs_libres.values()
                if club.noms_connus()
            ),
            key=lambda x: x[1],
            reverse=True,
        )
        meilleurs = scores[:3]
        if not meilleurs:
            motif = "aucun club interne disponible"
        elif meilleurs[0][1] < SEUIL_RESSEMBLANCE:
            motif = "aucun candidat au-dessus du seuil"
        elif len(meilleurs) > 1 and meilleurs[0][1] - meilleurs[1][1] < ECART_MINIMAL:
            motif = "deux candidats trop proches"
        else:
            motif = "candidat probable, à confirmer par un alias"
        resultat.propositions.append(
            Proposition(equipe=equipe, candidats=meilleurs, motif=motif)
        )

    resultat.clubs_sans_equipe = sorted(clubs_libres)
    return resultat
