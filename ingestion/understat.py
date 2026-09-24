#!/usr/bin/env python3
"""
T05 — Ingestion understat : les xG, rattachés aux matchs de T04
===============================================================

Remplit `stats_match.xg` et `stats_match.npxg` à partir des CSV déjà présents
dans `data/raw/understat/`. **Aucun accès réseau**, pour les mêmes raisons qu'en
T04 : les saisons terminées ne bougent plus, et la tâche reste rejouable et
testable hors ligne.

understat est la source des xG (D03). Cette tâche **n'insère jamais de match** :
elle enrichit des lignes de `stats_match` que T04 a créées. Un match understat
sans correspondance en base est signalé, jamais créé — sinon un match absent de
football-data entrerait ici sans score, sans mi-temps et sans statistiques, et
la table `matchs` n'aurait plus une seule source de vérité.

Le rattachement se fait sur la **clé logique** `(code_fd, saison, dom, ext)`,
celle de `source_match_id` en T04, et non sur la date. Mesuré sur les 11
saisons : les deux sources donnent la même heure pour 12 061 matchs mais
divergent d'une heure ou plus sur 445 — understat publie en heure locale du
pays, football-data en heure britannique. Un rattachement par date perdrait ces
445 matchs, et pire, en perdrait un nombre variable selon la saison.

Les noms d'équipes passent par `clubs.nom_understat` (règle 10) : les 165 clubs
du référentiel y sont renseignés depuis T00, et les 165 noms que produisent les
CSV understat sont tous reconnus.

Ce qui est repris de T04 : les trois propriétés du chargeur (rien n'est écrit si
quelque chose ne va pas, idempotence stricte, rien n'est supprimé), la
surveillance des colonnes disparues et l'invariant de comptage.

Usage :
    python3 ingestion/understat.py --dry-run        # ce qui changerait
    python3 ingestion/understat.py                  # écrit
    python3 ingestion/understat.py --saisons 2024 2026
    python3 ingestion/understat.py --ligues E0 SP1
    python3 ingestion/understat.py --source autre/dossier
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from bdd.modeles import Club, Ligue, Match, StatsMatch  # noqa: E402
from bdd.session import (  # noqa: E402
    fabrique_sessions,
    maintenant_utc,
    moteur,
)

SOURCE = "understat"
DOSSIER_DEFAUT = Path("data") / "raw" / "understat"

# understat nomme ses saisons par leur année de départ : `2024` = 2024-2025.
MOTIF_SAISON = re.compile(r"^\d{4}$")

FICHIER_MATCHS = "matches.csv"
FICHIER_EQUIPES = "team_matches.csv"

# Colonnes sans lesquelles un fichier n'est pas exploitable.
COLONNES_MATCHS = (
    "date", "is_result", "home_team", "away_team", "home_xg", "away_xg",
)
COLONNES_EQUIPES = ("team", "date", "h_a", "xG", "npxG")

# Colonnes surveillées de `team_matches.csv` : leur disparition est signalée,
# jamais subie en silence (même principe qu'en T04). `matches.csv` n'a pas de
# colonne surveillée : les six dont il a besoin sont déjà obligatoires, et il
# ne porte ni npxG ni deep — les chercher là produirait un faux signalement
# sur les onze saisons, qui finirait par masquer une vraie absence.
COLONNES_SURVEILLEES_EQUIPES = ("npxG", "deep", "xpts")

# Champs de `stats_match` que cette tâche tient à jour.
CHAMPS_STATS = ("xg", "npxg")

# Au-delà de cet écart entre le xG de `matches.csv` et celui de
# `team_matches.csv`, les deux fichiers ne parlent pas du même match : c'est
# un rattachement faux, pas un arrondi. understat écrit 5 à 6 décimales.
TOLERANCE_XG = 1e-4

# Seuil d'acceptation de T05 (ROADMAP) : part des matchs de la base, saisons
# terminées, à laquelle un xG doit être rattaché.
SEUIL_LIAISON = 0.99


class TacheInterrompue(Exception):
    """La tâche s'arrête sans rien écrire."""


# -- saisons et ligues -------------------------------------------------------


def libelle_saison(annee: str) -> str:
    """Année understat en libellé de saison : ``2024`` → ``2024-2025``.

    Même forme que `Match.saison`, que produit `libelle_saison` de T04 à partir
    du code football-data à quatre chiffres. Les deux doivent coïncider, sans
    quoi aucun rattachement ne se fait : un test les compare saison par saison.
    """
    if not MOTIF_SAISON.match(annee):
        raise TacheInterrompue(f"année de saison attendue sur 4 chiffres, lue {annee!r}")
    debut = int(annee)
    return f"{debut}-{debut + 1}"


def lire_manifeste(racine: Path) -> dict[str, str]:
    """Slug understat (`EPL`, `La_liga`…) → code football-data (`E0`, `SP1`…).

    Le manifeste du scraper porte cette correspondance, mais il n'en est pas
    la source : `ligues.slug_understat` l'est (règle 10). Il sert ici de
    **contrôle** — si le scraper a rangé la Serie A sous un slug que le
    référentiel donne à une autre ligue, les xG d'un championnat entier
    partiraient dans un autre, et rien ne le dirait.
    """
    chemin = racine / "manifest.csv"
    if not chemin.exists():
        raise TacheInterrompue(
            f"manifeste introuvable : {chemin}. Il porte la correspondance "
            "slug understat → code football-data."
        )
    correspondance: dict[str, str] = {}
    with chemin.open(encoding="utf-8-sig", newline="") as flux:
        lecteur = csv.DictReader(flux)
        attendues = {"ligue", "code_football_data"}
        manquantes = attendues - set(lecteur.fieldnames or ())
        if manquantes:
            raise TacheInterrompue(
                f"colonne(s) absente(s) du manifeste : {', '.join(sorted(manquantes))}"
            )
        for ligne in lecteur:
            slug = (ligne.get("ligue") or "").strip()
            code = (ligne.get("code_football_data") or "").strip()
            if not slug or not code:
                continue
            connu = correspondance.setdefault(slug, code)
            if connu != code:
                raise TacheInterrompue(
                    f"le manifeste donne deux codes pour {slug} : {connu} et {code}"
                )
    if not correspondance:
        raise TacheInterrompue(f"manifeste vide : {chemin}")
    return correspondance


def localiser_racine(dossier: Path, profondeur_max: int = 6) -> Path:
    """Dossier qui contient réellement les saisons, sous `dossier`.

    Même précaution qu'en T04 : les fichiers se sont trouvés un temps sous
    `data/raw/scraper/data/raw/understat/`, arborescence dupliquée par
    l'extraction d'une archive. Le dossier a été remis à plat en T05, et cette
    fonction couvre les deux rangements.
    """
    if not dossier.is_dir():
        raise TacheInterrompue(f"dossier de données introuvable : {dossier}")
    courant = dossier
    for _ in range(profondeur_max):
        if any(
            chemin.is_dir() and MOTIF_SAISON.match(chemin.name)
            for chemin in courant.iterdir()
        ):
            return courant
        sous_dossiers = [c for c in sorted(courant.iterdir()) if c.is_dir()]
        if len(sous_dossiers) != 1:
            break
        courant = sous_dossiers[0]
    raise TacheInterrompue(
        f"aucun dossier de saison (quatre chiffres, ex. 2024) trouvé sous {dossier}"
    )


def fichiers_a_lire(
    racine: Path,
    slugs_par_code: dict[str, str],
    codes_ligues: list[str],
    saisons: list[str] | None = None,
) -> list[tuple[str, str, Path]]:
    """Triplets (année understat, code football-data, dossier de la ligue)."""
    disponibles = sorted(
        chemin.name
        for chemin in racine.iterdir()
        if chemin.is_dir() and MOTIF_SAISON.match(chemin.name)
    )
    if saisons is not None:
        inconnues = sorted(set(saisons) - set(disponibles))
        if inconnues:
            raise TacheInterrompue(
                f"saison(s) absente(s) de {racine} : {', '.join(inconnues)}"
            )
        disponibles = [s for s in disponibles if s in saisons]

    trouves: list[tuple[str, str, Path]] = []
    manquants: list[str] = []
    for annee in disponibles:
        for code_fd in codes_ligues:
            slug = slugs_par_code[code_fd]
            dossier = racine / annee / slug
            if (dossier / FICHIER_MATCHS).exists():
                trouves.append((annee, code_fd, dossier))
            else:
                manquants.append(f"{annee}/{slug}")
    if manquants:
        raise TacheInterrompue(
            "dossier(s) ou fichier(s) absent(s), rien n'a été lu : "
            + ", ".join(manquants)
        )
    if not trouves:
        raise TacheInterrompue(f"aucun fichier à lire sous {racine}")
    return trouves


# -- conversion --------------------------------------------------------------


class ValeurIllisible(Exception):
    """Une cellule ne se convertit pas ; la ligne sera refusée."""


def nombre(brut: str | None, colonne: str) -> float | None:
    """Cellule understat en flottant. Vide → `None`, illisible → refus."""
    texte = (brut or "").strip()
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError as exc:
        raise ValeurIllisible(f"{colonne} illisible : {texte!r}") from exc


def est_joue(brut: str | None) -> bool:
    """`is_result` d'understat. Un match à venir n'a pas d'xG à rattacher.

    Le fichier de la saison en cours porte le calendrier complet : au moment
    de T05, 207 matchs joués sur 1 752 lignes. Les 1 545 autres sont des
    matchs futurs, dont les colonnes d'xG valent 0 — les prendre écrirait des
    zéros là où il n'y a pas de donnée, et fausserait toute force calculée
    dessus (règle 5 : aucune donnée postérieure, mais surtout aucune donnée
    inventée).
    """
    return (brut or "").strip().lower() in {"true", "1", "vrai"}


@dataclass(frozen=True)
class LigneXg:
    """Les xG d'un match understat, prêts à être rattachés. Aucun nom brut."""

    code_fd: str
    saison: str
    annee: str
    club_id_dom: str
    club_id_ext: str
    xg_dom: float | None
    xg_ext: float | None
    npxg_dom: float | None
    npxg_ext: float | None
    date_source: str

    @property
    def cle(self) -> tuple[str, str, str, str]:
        """Clé logique du match, identique à celle de T04."""
        return (self.code_fd, self.saison, self.club_id_dom, self.club_id_ext)

    def valeurs(self, camp: str) -> dict[str, float | None]:
        if camp == "dom":
            return {"xg": self.xg_dom, "npxg": self.npxg_dom}
        return {"xg": self.xg_ext, "npxg": self.npxg_ext}


@dataclass(frozen=True)
class Refus:
    """Une ligne écartée, et pourquoi."""

    fichier: str
    numero: int
    motif: str

    def __str__(self) -> str:
        return f"{self.fichier} ligne {self.numero} : {self.motif}"


@dataclass
class Lecture:
    """Ce que la lecture des fichiers a produit, avant toute écriture."""

    lignes: list[LigneXg] = field(default_factory=list)
    refus: list[Refus] = field(default_factory=list)
    # Matchs à venir : ni retenus, ni refusés, mais comptés pour que
    # l'invariant de comptage retombe juste.
    a_venir: int = 0
    lues: int = 0
    colonnes_absentes: dict[str, set[str]] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    @property
    def comptage_juste(self) -> bool:
        return self.lues == len(self.lignes) + len(self.refus) + self.a_venir


def _npxg_par_equipe(
    dossier: Path, code_fd: str, clubs_par_nom: dict[tuple[str, str], str]
) -> tuple[
    dict[tuple[str, str], tuple[float | None, float | None]], list[str], set[str]
]:
    """npxG et xG de `team_matches.csv`, indexés par (club_id, date source).

    Ce fichier est déjà dans la forme « une ligne par équipe » de
    `stats_match`. Son xG sert de **contrôle croisé** de celui de
    `matches.csv` : les deux doivent coïncider, sinon le rattachement a
    apparié deux matchs différents — c'est le seul risque sérieux ici, et il
    est silencieux sans ce contrôle.
    """
    chemin = dossier / FICHIER_EQUIPES
    if not chemin.exists():
        return (
            {},
            [f"{chemin.parent.name} : {FICHIER_EQUIPES} absent, npxG non repris"],
            set(COLONNES_SURVEILLEES_EQUIPES),
        )

    par_equipe: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    avertissements: list[str] = []
    with chemin.open(encoding="utf-8-sig", newline="") as flux:
        lecteur = csv.DictReader(flux)
        colonnes = set(lecteur.fieldnames or ())
        absentes = {c for c in COLONNES_SURVEILLEES_EQUIPES if c not in colonnes}
        manquantes = set(COLONNES_EQUIPES) - colonnes
        if manquantes:
            return (
                {},
                [
                    f"{chemin.parent.name}/{FICHIER_EQUIPES} : colonne(s) "
                    f"absente(s) ({', '.join(sorted(manquantes))}), npxG non repris"
                ],
                absentes,
            )
        for ligne in lecteur:
            club_id = clubs_par_nom.get((code_fd, (ligne.get("team") or "").strip()))
            if club_id is None:
                continue
            date_source = (ligne.get("date") or "").strip()
            try:
                xg = nombre(ligne.get("xG"), "xG")
                npxg = nombre(ligne.get("npxG"), "npxG")
            except ValeurIllisible as exc:
                avertissements.append(f"{chemin.parent.name}/{FICHIER_EQUIPES} : {exc}")
                continue
            par_equipe[(club_id, date_source)] = (xg, npxg)
    return par_equipe, avertissements, absentes


def lire_ligue(
    annee: str,
    code_fd: str,
    dossier: Path,
    clubs_par_nom: dict[tuple[str, str], str],
) -> Lecture:
    """Lit `matches.csv` et `team_matches.csv` d'une ligue et d'une saison."""
    lecture = Lecture()
    saison = libelle_saison(annee)
    nom_court = f"{annee}/{dossier.name}"
    npxg_par_equipe, avertissements, absentes = _npxg_par_equipe(
        dossier, code_fd, clubs_par_nom
    )
    lecture.anomalies.extend(avertissements)
    for colonne in absentes:
        lecture.colonnes_absentes.setdefault(colonne, set()).add(annee)

    chemin = dossier / FICHIER_MATCHS
    with chemin.open(encoding="utf-8-sig", newline="") as flux:
        lecteur = csv.DictReader(flux)
        colonnes = set(lecteur.fieldnames or ())
        manquantes = set(COLONNES_MATCHS) - colonnes
        if manquantes:
            raise TacheInterrompue(
                f"{nom_court}/{FICHIER_MATCHS} : colonne(s) obligatoire(s) "
                f"absente(s) : {', '.join(sorted(manquantes))}"
            )
        for numero, ligne in enumerate(lecteur, start=2):
            lecture.lues += 1
            if not est_joue(ligne.get("is_result")):
                lecture.a_venir += 1
                continue

            nom_dom = (ligne.get("home_team") or "").strip()
            nom_ext = (ligne.get("away_team") or "").strip()
            club_dom = clubs_par_nom.get((code_fd, nom_dom))
            club_ext = clubs_par_nom.get((code_fd, nom_ext))
            if club_dom is None or club_ext is None:
                inconnu = nom_dom if club_dom is None else nom_ext
                lecture.refus.append(Refus(
                    nom_court, numero,
                    f"nom understat inconnu du référentiel pour {code_fd} : "
                    f"{inconnu!r} — renseigner `nom_understat` dans clubs.csv",
                ))
                continue
            if club_dom == club_ext:
                lecture.refus.append(Refus(
                    nom_court, numero, f"{club_dom} joue contre lui-même",
                ))
                continue

            try:
                xg_dom = nombre(ligne.get("home_xg"), "home_xg")
                xg_ext = nombre(ligne.get("away_xg"), "away_xg")
            except ValeurIllisible as exc:
                lecture.refus.append(Refus(nom_court, numero, str(exc)))
                continue

            date_source = (ligne.get("date") or "").strip()
            npxg_dom = npxg_ext = None
            for camp, club_id, xg_matchs in (
                ("dom", club_dom, xg_dom), ("ext", club_ext, xg_ext),
            ):
                cote = npxg_par_equipe.get((club_id, date_source))
                if cote is None:
                    continue
                xg_equipe, npxg = cote
                # Contrôle croisé : les deux fichiers doivent donner le même xG.
                if (
                    xg_equipe is not None and xg_matchs is not None
                    and abs(xg_equipe - xg_matchs) > TOLERANCE_XG
                ):
                    lecture.anomalies.append(
                        f"{nom_court} ligne {numero} : {club_id} à {xg_matchs} "
                        f"dans {FICHIER_MATCHS} et {xg_equipe} dans "
                        f"{FICHIER_EQUIPES} ; npxG non repris pour ce camp"
                    )
                    continue
                if camp == "dom":
                    npxg_dom = npxg
                else:
                    npxg_ext = npxg

            # Un npxG supérieur au xG est une inversion de colonnes chez la
            # source : le schéma le refuserait, autant le voir ici et nommer
            # le match plutôt que de laisser tomber une contrainte SQL.
            for camp, xg, npxg in (
                ("dom", xg_dom, npxg_dom), ("ext", xg_ext, npxg_ext),
            ):
                if xg is not None and npxg is not None and npxg > xg + TOLERANCE_XG:
                    lecture.anomalies.append(
                        f"{nom_court} ligne {numero} : {nom_dom}–{nom_ext} camp "
                        f"{camp} annoncé à {npxg} npxG pour {xg} xG ; npxG écarté"
                    )
                    if camp == "dom":
                        npxg_dom = None
                    else:
                        npxg_ext = None

            lecture.lignes.append(LigneXg(
                code_fd=code_fd,
                saison=saison,
                annee=annee,
                club_id_dom=club_dom,
                club_id_ext=club_ext,
                xg_dom=xg_dom,
                xg_ext=xg_ext,
                npxg_dom=npxg_dom,
                npxg_ext=npxg_ext,
                date_source=date_source,
            ))
    return lecture


def lire_tout(
    fichiers: list[tuple[str, str, Path]],
    clubs_par_nom: dict[tuple[str, str], str],
) -> Lecture:
    """Lit tous les fichiers du périmètre, sans rien écrire."""
    total = Lecture()
    for annee, code_fd, dossier in fichiers:
        partielle = lire_ligue(annee, code_fd, dossier, clubs_par_nom)
        total.lignes.extend(partielle.lignes)
        total.refus.extend(partielle.refus)
        total.anomalies.extend(partielle.anomalies)
        total.a_venir += partielle.a_venir
        total.lues += partielle.lues
        for colonne, annees in partielle.colonnes_absentes.items():
            total.colonnes_absentes.setdefault(colonne, set()).update(annees)

    doublons = [
        f"{cle[1]}/{cle[0]} {cle[2]}–{cle[3]}"
        for cle, nombre_ in Counter(ligne.cle for ligne in total.lignes).items()
        if nombre_ > 1
    ]
    if doublons:
        raise TacheInterrompue(
            f"{len(doublons)} match(s) en double dans les fichiers understat, "
            "rien n'a été lu : " + ", ".join(sorted(doublons)[:10])
        )
    return total


# -- écriture ----------------------------------------------------------------


@dataclass
class Comptes:
    inseres: int = 0
    majs: int = 0
    inchanges: int = 0

    def __str__(self) -> str:
        return f"{self.inseres} insérés, {self.majs} mis à jour, {self.inchanges} inchangés"


@dataclass
class Rapport:
    stats: Comptes = field(default_factory=Comptes)
    lues: int = 0
    refusees: int = 0
    a_venir: int = 0
    # Matchs understat joués dont aucun match de la base ne porte la clé.
    sans_match: list[str] = field(default_factory=list)
    # Lignes de `stats_match` attendues mais absentes : T04 en crée toujours
    # deux par match, donc un zéro ici est la règle et non un espoir.
    stats_absentes: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    # Couverture, par saison : (matchs en base, matchs pourvus d'un xG).
    couverture: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Lignes understat effectivement rattachées à un match de la base.
    rattachees: int = 0

    @property
    def comptage_juste(self) -> bool:
        """`lues == rattachées + sans match + refusées + à venir`."""
        return (
            self.lues
            == self.rattachees + len(self.sans_match) + self.refusees + self.a_venir
        )


def _appliquer(objet: object, valeurs: dict[str, object]) -> bool:
    """Pose les valeurs qui diffèrent réellement. Dit si quelque chose a bougé.

    Même règle qu'en T04 : `maj_le` ne bouge pas sans raison, sans quoi
    l'horodatage ne dit plus rien et l'idempotence n'est plus vérifiable.
    Une valeur absente d'understat (`None`) **n'écrase jamais** une valeur
    déjà en base : c'est ce qui protège les 500 xG que football-data a fournis
    pour 2026-27 les jours où understat est en retard.
    """
    differences = {
        champ: valeur
        for champ, valeur in valeurs.items()
        if valeur is not None and getattr(objet, champ) != valeur
    }
    for champ, valeur in differences.items():
        setattr(objet, champ, valeur)
    return bool(differences)


def _source_enrichie(source: str | None) -> str:
    """Ajoute `understat` à la source, sans doublon ni perte de l'existante."""
    sources = {part for part in (source or "").split("+") if part}
    sources.add(SOURCE)
    return "+".join(sorted(sources))


def synchroniser(session: Session, lignes: list[LigneXg]) -> Rapport:
    """Écrit les xG sur les `stats_match` existantes. Ne crée aucun match."""
    rapport = Rapport()

    # Les matchs du périmètre lu, indexés par la clé logique de T04.
    perimetre = {(ligne.code_fd, ligne.saison) for ligne in lignes}
    matchs: dict[tuple[str, str, str, str], Match] = {}
    for match in session.scalars(select(Match)):
        if (match.code_fd, match.saison) in perimetre:
            matchs[
                (match.code_fd, match.saison, match.club_id_dom, match.club_id_ext)
            ] = match

    appariees: list[tuple[LigneXg, Match]] = []
    for ligne in lignes:
        match = matchs.get(ligne.cle)
        if match is None:
            rapport.sans_match.append(
                f"{ligne.annee}/{ligne.code_fd} {ligne.club_id_dom}–"
                f"{ligne.club_id_ext} ({ligne.date_source})"
            )
            continue
        appariees.append((ligne, match))
    rapport.rattachees = len(appariees)

    identifiants = {match.id for _, match in appariees}
    stats_existantes: dict[tuple[int, str], StatsMatch] = {}
    if identifiants:
        for stat in session.scalars(
            select(StatsMatch).where(StatsMatch.match_id.in_(identifiants))
        ):
            stats_existantes[(stat.match_id, stat.camp)] = stat

    for ligne, match in appariees:
        for camp in ("dom", "ext"):
            stat = stats_existantes.get((match.id, camp))
            if stat is None:
                # T04 crée toujours les deux lignes. Une absence veut dire que
                # `matchs` et `stats_match` ont divergé : on le signale au lieu
                # de combler le trou avec une ligne qui n'aurait que des xG.
                rapport.stats_absentes.append(
                    f"{ligne.annee}/{ligne.code_fd} {ligne.club_id_dom}–"
                    f"{ligne.club_id_ext} camp {camp}"
                )
                continue
            if _appliquer(stat, ligne.valeurs(camp)):
                stat.source = _source_enrichie(stat.source)
                stat.maj_le = maintenant_utc()
                rapport.stats.majs += 1
            else:
                rapport.stats.inchanges += 1

    return rapport


def mesurer_couverture(
    session: Session,
    saisons_lues: set[str],
    code_en_cours: str,
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Part des matchs de la base pourvus d'un xG, saison par saison.

    C'est le critère d'acceptation de T05. La saison en cours est mesurée mais
    **exclue du seuil** : understat publie ses xG avec un délai, et un jour de
    retard sur la dernière journée ferait tomber la tâche alors que rien n'est
    cassé. Les saisons terminées, elles, n'ont aucune excuse.
    """
    couverture: dict[str, tuple[int, int]] = {}
    avertissements: list[str] = []

    totaux: dict[str, int] = defaultdict(int)
    pourvus: dict[str, int] = defaultdict(int)
    for (saison,) in session.execute(select(Match.saison)):
        if saison in saisons_lues:
            totaux[saison] += 1
    lignes_xg = session.execute(
        select(Match.saison, StatsMatch.match_id)
        .join(StatsMatch, StatsMatch.match_id == Match.id)
        .where(StatsMatch.xg.is_not(None))
    )
    vus: set[tuple[str, int]] = set()
    for saison, match_id in lignes_xg:
        if saison in saisons_lues and (saison, match_id) not in vus:
            vus.add((saison, match_id))
            pourvus[saison] += 1

    for saison in sorted(totaux):
        couverture[saison] = (totaux[saison], pourvus[saison])
        if saison == code_en_cours:
            continue
        part = pourvus[saison] / totaux[saison] if totaux[saison] else 0.0
        if part < SEUIL_LIAISON:
            avertissements.append(
                f"{saison} : {pourvus[saison]}/{totaux[saison]} matchs pourvus "
                f"d'un xG ({100 * part:.2f} %), seuil {100 * SEUIL_LIAISON:.0f} %"
            )
    return couverture, avertissements


# -- orchestration -----------------------------------------------------------


def saison_en_cours_libelle(racine: Path) -> str:
    """Libellé de la saison la plus récente présente sur le disque."""
    annees = sorted(
        chemin.name
        for chemin in racine.iterdir()
        if chemin.is_dir() and MOTIF_SAISON.match(chemin.name)
    )
    return libelle_saison(annees[-1]) if annees else ""


def executer(
    racine_depot: Path,
    dossier_source: Path | None = None,
    codes_ligues: list[str] | None = None,
    saisons: list[str] | None = None,
    url: str | None = None,
    ecrire: bool = True,
    tolerer: bool = False,
    sortie=print,
) -> Rapport:
    """Déroule T05 : lit les CSV, contrôle tout, puis écrit — ou rien."""
    dossier = dossier_source or (racine_depot / DOSSIER_DEFAUT)
    racine = localiser_racine(dossier)
    manifeste = lire_manifeste(racine)

    machine = moteur(url)
    session = fabrique_sessions(machine)()
    try:
        ligues = {ligue.code_fd: ligue for ligue in session.scalars(select(Ligue))}
        if not ligues:
            raise TacheInterrompue(
                "aucune ligue en base : lancer d'abord "
                "`python3 ingestion/charger_referentiel.py` (T03)."
            )
        if not session.scalar(select(Match).limit(1)):
            raise TacheInterrompue(
                "aucun match en base : lancer d'abord "
                "`python3 ingestion/football_data.py` (T04). T05 rattache des "
                "xG à des matchs existants, elle n'en crée aucun."
            )

        # Le slug understat vient du référentiel (règle 10) ; le manifeste du
        # scraper sert à le contredire s'il se trompe, jamais à le remplacer.
        slugs_par_code = {
            code: ligue.slug_understat
            for code, ligue in ligues.items()
            if ligue.slug_understat
        }
        desaccords = [
            f"{slug} : le référentiel le donne à {code}, le manifeste à "
            f"{manifeste[slug]}"
            for code, slug in sorted(slugs_par_code.items())
            if slug in manifeste and manifeste[slug] != code
        ]
        if desaccords:
            raise TacheInterrompue(
                "le manifeste du scraper et le référentiel ne s'accordent pas "
                "sur les ligues, rien n'a été lu :\n  - " + "\n  - ".join(desaccords)
            )

        if codes_ligues:
            inconnues = sorted(set(codes_ligues) - set(slugs_par_code))
            if inconnues:
                raise TacheInterrompue(
                    "ligue(s) sans slug understat connu : " + ", ".join(inconnues)
                )
        else:
            codes_ligues = sorted(slugs_par_code)

        clubs_par_nom = {
            (club.code_fd, club.nom_understat): club.club_id
            for club in session.scalars(select(Club))
            if club.nom_understat
        }
        if not clubs_par_nom:
            raise TacheInterrompue(
                "aucun club ne porte de `nom_understat` : renseigner la colonne "
                "dans data/reference/clubs.csv, puis relancer T03."
            )

        fichiers = fichiers_a_lire(racine, slugs_par_code, codes_ligues, saisons)
        sortie(f"Source : {racine}")
        sortie(
            f"{len(fichiers)} dossier(s), "
            f"{len({a for a, _, _ in fichiers})} saison(s), "
            f"{len(codes_ligues)} ligue(s)."
        )

        lecture = lire_tout(fichiers, clubs_par_nom)
        if not lecture.comptage_juste:
            raise TacheInterrompue(
                f"comptage de lecture faux : {lecture.lues} lues pour "
                f"{len(lecture.lignes)} retenues + {len(lecture.refus)} refusées "
                f"+ {lecture.a_venir} à venir"
            )

        if lecture.colonnes_absentes:
            sortie("\nColonnes surveillées absentes :")
            for colonne, annees in sorted(lecture.colonnes_absentes.items()):
                sortie(
                    f"  {colonne:<8} absente de {len(annees)} saison(s) : "
                    f"{', '.join(sorted(annees))}"
                )

        if lecture.refus and not tolerer:
            details = "\n  - ".join(str(refus) for refus in lecture.refus[:20])
            reste = len(lecture.refus) - 20
            raise TacheInterrompue(
                f"{len(lecture.refus)} ligne(s) refusée(s), rien n'a été écrit :"
                f"\n  - {details}"
                + (f"\n  - … et {reste} autre(s)" if reste > 0 else "")
                + "\nCorriger le référentiel ou les fichiers, ou relancer avec "
                "--tolerer pour importer sans ces lignes."
            )

        rapport = synchroniser(session, lecture.lignes)
        rapport.lues = lecture.lues
        rapport.refusees = len(lecture.refus)
        rapport.a_venir = lecture.a_venir
        rapport.anomalies = lecture.anomalies

        if not rapport.comptage_juste:
            raise TacheInterrompue(
                f"invariant de comptage faux : {rapport.lues} lues pour "
                f"{rapport.rattachees} rattachées + "
                f"{len(rapport.sans_match)} sans match + {rapport.refusees} "
                f"refusées + {rapport.a_venir} à venir"
            )

        if rapport.stats_absentes:
            raise TacheInterrompue(
                f"{len(rapport.stats_absentes)} ligne(s) de stats_match "
                "attendue(s) et absente(s) — `matchs` et `stats_match` ont "
                "divergé, relancer T04 :\n  - "
                + "\n  - ".join(rapport.stats_absentes[:10])
            )

        # La fabrique de sessions du projet est en `autoflush=False` : sans ce
        # flush, la mesure de couverture interrogerait la base d'avant
        # l'écriture et annoncerait 0 %. Flusher n'est pas commiter — en
        # `--dry-run`, le rollback qui suit annule tout.
        session.flush()

        saisons_lues = {libelle_saison(annee) for annee, _, _ in fichiers}
        rapport.couverture, rapport.avertissements = mesurer_couverture(
            session, saisons_lues, saison_en_cours_libelle(racine)
        )

        if ecrire:
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _afficher(rapport, ecrire, sortie)
    return rapport


def _afficher(rapport: Rapport, ecrire: bool, sortie) -> None:
    sortie(f"\nstats_match : {rapport.stats}")
    sortie(
        f"lignes      : {rapport.lues} lues = "
        f"{rapport.rattachees} rattachées + "
        f"{len(rapport.sans_match)} sans match + {rapport.refusees} refusées + "
        f"{rapport.a_venir} à venir"
    )

    if rapport.couverture:
        sortie("\nCouverture xG (matchs de la base pourvus d'un xG) :")
        for saison, (total, pourvus) in sorted(rapport.couverture.items()):
            part = 100 * pourvus / total if total else 0.0
            sortie(f"  {saison} : {pourvus:>5}/{total:<5} {part:6.2f} %")
        totaux = sum(t for t, _ in rapport.couverture.values())
        atteints = sum(p for _, p in rapport.couverture.values())
        if totaux:
            sortie(f"  {'ensemble':<9} : {atteints:>5}/{totaux:<5} "
                   f"{100 * atteints / totaux:6.2f} %")

    if rapport.anomalies:
        sortie(f"\nValeurs écartées ({len(rapport.anomalies)}) :")
        for anomalie in rapport.anomalies[:20]:
            sortie(f"  {anomalie}")
        if len(rapport.anomalies) > 20:
            sortie(f"  … et {len(rapport.anomalies) - 20} autre(s)")

    if rapport.sans_match:
        sortie(f"\nMatchs understat sans match en base ({len(rapport.sans_match)}) :")
        for detail in rapport.sans_match[:10]:
            sortie(f"  {detail}")
        if len(rapport.sans_match) > 10:
            sortie(f"  … et {len(rapport.sans_match) - 10} autre(s)")
        sortie("  (T05 ne crée aucun match : relancer T04 quand la source aura suivi)")

    if rapport.avertissements:
        sortie("\nCouverture sous le seuil :")
        for avertissement in rapport.avertissements:
            sortie(f"  {avertissement}")

    if not ecrire:
        sortie("\n[dry-run] aucune écriture.")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    parseur.add_argument("--source", type=Path, metavar="DOSSIER",
                         help=f"dossier des CSV (défaut : {DOSSIER_DEFAUT})")
    parseur.add_argument("--ligues", nargs="+", metavar="CODE_FD", help="ex. E0 SP1")
    parseur.add_argument("--saisons", nargs="+", metavar="ANNEE", help="ex. 2024 2026")
    parseur.add_argument("--tolerer", action="store_true",
                         help="importe en écartant les lignes refusées")
    arguments = parseur.parse_args(argv)

    racine = Path(__file__).resolve().parent.parent
    try:
        executer(
            racine,
            dossier_source=arguments.source,
            codes_ligues=arguments.ligues,
            saisons=arguments.saisons,
            ecrire=not arguments.dry_run,
            tolerer=arguments.tolerer,
        )
    except TacheInterrompue as exc:
        print(f"\nTâche interrompue : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
