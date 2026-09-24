#!/usr/bin/env python3
"""
T04 — Ingestion football-data.co.uk (5 ligues, 10 saisons + saison en cours)
============================================================================

Remplit `matchs` (scores, mi-temps, coup d'envoi en UTC, arbitre) et
`stats_match` (tirs, cadrés, corners, fautes, cartons, et les xG que la source
publie depuis 2026-27) à partir des CSV déjà présents dans
`data/raw/football-data/`.

Pour les xG, cette tâche est un **secours**, pas la source : D03 donne ce rôle
à understat, et `ingestion/understat.py` (T05) écrit par-dessus. Un `xg` déjà
en base n'est donc jamais remplacé ici, quelle que soit la valeur du CSV — les
deux sources sont deux modèles différents (écart moyen 0,32 mesuré en T05), et
l'ordre des tâches ne doit pas décider laquelle gagne.

**Aucun accès réseau** : le téléchargement est le
travail de `ingestion/telecharger_football_data.py`, et il n'est pas nécessaire
pour des saisons terminées — d'autant que le site renvoyait des 503
systématiques en septembre 2026 (constaté en T02).

Les clubs sont désignés par `club_id` (règle 10) : le nom brut du CSV sert de
clé de jointure vers `clubs.nom_football_data`, et ne va nulle part ailleurs.

Trois propriétés, reprises du chargeur de référentiel de T03 :

1. **Rien n'est écrit si quelque chose ne va pas.** Tous les fichiers sont lus
   et contrôlés avant la première écriture, et toutes les anomalies sont
   affichées ensemble. `--tolerer` importe quand même, en écartant les lignes
   fautives.
2. **Idempotent.** Une deuxième exécution n'insère rien, ne met rien à jour et
   ne touche pas `maj_le` : une ligne n'est écrite que si une de ses valeurs
   diffère réellement.
3. **Rien n'est supprimé.** Un match en base et absent des fichiers est
   signalé, jamais effacé.

Ce qui est repris de l'ancien dépôt : la surveillance des colonnes disparues de
`collectors/football_data/parser.py` (une colonne qui change de nom est une
perte sèche silencieuse) et l'invariant de comptage de
`pipelines/historical_import.py` (`lues == insérées + mises à jour + inchangées
+ refusées + ignorées`). `team_normalizer.py` reste abandonné : `clubs.csv` et
la table `clubs` font ce travail.

Usage :
    python3 ingestion/football_data.py --dry-run          # ce qui changerait
    python3 ingestion/football_data.py                    # écrit
    python3 ingestion/football_data.py --saisons 2526 2627
    python3 ingestion/football_data.py --ligues E0 SP1
    python3 ingestion/football_data.py --source autre/dossier
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from bdd.modeles import Club, Ligue, Match, StatsMatch  # noqa: E402
from bdd.session import (  # noqa: E402
    creer_tables,
    fabrique_sessions,
    maintenant_utc,
    moteur,
)

SOURCE = "football-data"
DOSSIER_DEFAUT = Path("data") / "raw" / "football-data"

# football-data.co.uk publie l'heure du coup d'envoi en **heure locale
# britannique**, pas en UTC. Vérifié en T04 contre le calendrier API-Football de
# T00 : les 250 matchs de 2026-27 sont tous à exactement +1 h de l'UTC, ce qui
# est l'heure d'été britannique en août et septembre.
FUSEAU_SOURCE = ZoneInfo("Europe/London")

MOTIF_SAISON = re.compile(r"^\d{4}$")

# Colonnes sans lesquelles un fichier n'est pas exploitable.
COLONNES_OBLIGATOIRES = ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG")

# Colonnes surveillées : leur disparition est signalée, jamais subie en
# silence. Celles dont l'absence est déjà comprise portent leur explication ;
# toute autre absence apparaît sans mention et mérite un coup d'œil.
COLONNES_SURVEILLEES = (
    "Time", "HTHG", "HTAG", "Referee",
    "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
    "HxG", "AxG",
)
ABSENCES_CONNUES = {
    "Time": "la source ne publie l'heure du coup d'envoi qu'à partir de 2019-20",
    "HxG": "la source ne publie les xG qu'à partir de 2026-27 (T05 : understat)",
    "AxG": "la source ne publie les xG qu'à partir de 2026-27 (T05 : understat)",
    "Referee": "la source ne nomme l'arbitre que pour certaines ligues",
}

# Statistiques d'équipe : colonne du camp domicile, colonne du camp extérieur.
STATS_PAR_CAMP = {
    "tirs": ("HS", "AS"),
    "tirs_cadres": ("HST", "AST"),
    "corners": ("HC", "AC"),
    "fautes": ("HF", "AF"),
    "cartons_jaunes": ("HY", "AY"),
    "cartons_rouges": ("HR", "AR"),
}

# Champs de `matchs` que l'ingestion tient à jour d'une exécution à l'autre.
CHAMPS_MATCH = ("date_utc", "statut", "buts_dom", "buts_ext", "mt_dom", "mt_ext",
                "arbitre")
CHAMPS_STATS = tuple(STATS_PAR_CAMP) + ("xg",)


class TacheInterrompue(Exception):
    """La tâche s'arrête sans rien écrire."""


# -- saisons -----------------------------------------------------------------


def libelle_saison(code: str) -> str:
    """Code football-data d'une saison en libellé : ``2526`` → ``2025-2026``.

    Même forme que la colonne `saisons` de clubs.csv et que `Match.saison`.
    Le siècle est déduit du pivot de football-data : les codes commençant par
    9 désignent les années 1990, les autres les années 2000.
    """
    if not MOTIF_SAISON.match(code):
        raise TacheInterrompue(f"code de saison attendu sur 4 chiffres, lu {code!r}")
    debut = int(code[:2])
    annee = 1900 + debut if debut >= 90 else 2000 + debut
    return f"{annee}-{annee + 1}"


def saison_en_cours(aujourdhui: date | None = None) -> str:
    """Code de la saison en cours. Une saison de championnat démarre en juillet."""
    aujourdhui = aujourdhui or date.today()
    debut = aujourdhui.year if aujourdhui.month >= 7 else aujourdhui.year - 1
    return f"{debut % 100:02d}{(debut + 1) % 100:02d}"


# -- localisation des fichiers -----------------------------------------------


def _contient_des_saisons(dossier: Path) -> bool:
    return any(
        chemin.is_dir() and MOTIF_SAISON.match(chemin.name)
        for chemin in dossier.iterdir()
    )


def localiser_racine(dossier: Path, profondeur_max: int = 6) -> Path:
    """Dossier qui contient réellement les saisons, sous `dossier`.

    Les saisons sont normalement directement sous `dossier`. Elles se sont
    trouvées un temps sous `data/raw/football-data/data/raw/football-data/`,
    arborescence dupliquée par l'extraction d'une archive : plutôt que de figer
    l'un ou l'autre chemin, on descend tant qu'un seul sous-dossier s'offre et
    qu'aucune saison n'est visible. Le dossier a été remis à plat depuis, et
    cette fonction couvre les deux rangements.
    """
    if not dossier.is_dir():
        raise TacheInterrompue(f"dossier de données introuvable : {dossier}")
    courant = dossier
    for _ in range(profondeur_max):
        if _contient_des_saisons(courant):
            return courant
        sous_dossiers = [c for c in sorted(courant.iterdir()) if c.is_dir()]
        if len(sous_dossiers) != 1:
            break
        courant = sous_dossiers[0]
    raise TacheInterrompue(
        f"aucun dossier de saison (quatre chiffres, ex. 2526) trouvé sous {dossier}"
    )


def fichiers_a_lire(
    racine: Path, codes_ligues: list[str], saisons: list[str] | None = None
) -> list[tuple[str, str, Path]]:
    """Triplets (code de saison, code de ligue, chemin), dans l'ordre chronologique."""
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
    for saison in disponibles:
        for code_fd in codes_ligues:
            chemin = racine / saison / f"{code_fd}.csv"
            if chemin.exists():
                trouves.append((saison, code_fd, chemin))
            else:
                manquants.append(f"{saison}/{code_fd}")
    if manquants:
        raise TacheInterrompue(
            "fichier(s) absent(s), rien n'a été lu : " + ", ".join(manquants)
        )
    if not trouves:
        raise TacheInterrompue(f"aucun fichier à lire sous {racine}")
    return trouves


# -- conversion d'une ligne --------------------------------------------------


class ValeurIllisible(Exception):
    """Une cellule ne se convertit pas ; la ligne sera refusée."""


def convertir_date(date_brute: str, heure_brute: str | None) -> datetime:
    """Coup d'envoi en UTC, sans fuseau (règle 11).

    La source écrit la date en `JJ/MM/AA` jusqu'en 2018-19 puis en `JJ/MM/AAAA` ;
    les deux formes sont sans ambiguïté possible l'une pour l'autre.

    Quand l'heure manque — saisons 2016-17 à 2018-19, où la source ne publiait
    pas encore la colonne `Time` — la date est stockée à **00:00 UTC sans
    conversion de fuseau**. Convertir minuit depuis Londres reculerait la date
    d'un jour pendant tout l'été, ce qui serait bien pire qu'une heure inconnue.
    Aucun match de ces cinq championnats ne débute à minuit pile : un coup
    d'envoi à `00:00:00` se reconnaît donc comme une heure inconnue, sans qu'il
    faille une colonne de plus.
    """
    brut = (date_brute or "").strip()
    jour: datetime | None = None
    for format_date in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            jour = datetime.strptime(brut, format_date)
            break
        except ValueError:
            continue
    if jour is None:
        raise ValeurIllisible(f"date illisible : {date_brute!r}")

    heure = (heure_brute or "").strip()
    if not heure:
        return jour
    try:
        moment = datetime.strptime(heure, "%H:%M")
    except ValueError:
        raise ValeurIllisible(f"heure illisible : {heure_brute!r}") from None

    # L'heure ambiguë du retour à l'heure d'hiver (01:00–02:00 une nuit
    # d'octobre) est résolue en heure d'été par défaut. Aucun championnat ne
    # joue à cette heure-là : le cas ne se présente pas.
    local = jour.replace(hour=moment.hour, minute=moment.minute, tzinfo=FUSEAU_SOURCE)
    return local.astimezone(UTC).replace(tzinfo=None)


def _entier_ou_rien(valeur: str | None, quoi: str) -> int | None:
    brut = (valeur or "").strip()
    if not brut:
        return None
    try:
        return int(float(brut))
    except ValueError:
        raise ValeurIllisible(f"{quoi} : entier attendu, lu {brut!r}") from None


def _flottant_ou_rien(valeur: str | None, quoi: str) -> float | None:
    brut = (valeur or "").strip()
    if not brut:
        return None
    try:
        return float(brut)
    except ValueError:
        raise ValeurIllisible(f"{quoi} : nombre attendu, lu {brut!r}") from None


def _texte_ou_rien(valeur: str | None) -> str | None:
    brut = (valeur or "").strip()
    return brut or None


def identifiant_source(saison: str, code_fd: str, dom: str, ext: str) -> str:
    """Identifiant du match chez la source, stable et déterministe.

    Construit sur la clé logique et non sur le numéro de ligne : un match
    reporté, ou un fichier de saison en cours qui grossit semaine après
    semaine, ne doit pas changer d'identité.
    """
    return f"{saison}:{code_fd}:{dom}:{ext}"


@dataclass(frozen=True)
class LigneMatch:
    """Une ligne de CSV convertie, prête à être écrite. Aucun nom brut."""

    code_fd: str
    saison: str
    code_saison: str
    date_utc: datetime
    club_id_dom: str
    club_id_ext: str
    statut: str
    buts_dom: int | None
    buts_ext: int | None
    mt_dom: int | None
    mt_ext: int | None
    arbitre: str | None
    source_match_id: str
    stats_dom: dict[str, int | float | None]
    stats_ext: dict[str, int | float | None]
    # Valeurs invraisemblables écartées à la lecture, nommées dans le rapport.
    anomalies: tuple[str, ...] = ()

    def champs_match(self) -> dict[str, object]:
        return {champ: getattr(self, champ) for champ in CHAMPS_MATCH}


@dataclass(frozen=True)
class Refus:
    """Une ligne écartée, et pourquoi."""

    fichier: str
    numero: int
    motif: str

    def __str__(self) -> str:
        return f"{self.fichier} ligne {self.numero} : {self.motif}"


def convertir_ligne(
    ligne: dict[str, str],
    code_fd: str,
    code_saison: str,
    clubs_par_nom: dict[tuple[str, str], str],
) -> LigneMatch:
    """Une ligne de CSV en valeurs de colonnes. Lève `ValeurIllisible` si refusée."""
    nom_dom = (ligne.get("HomeTeam") or "").strip()
    nom_ext = (ligne.get("AwayTeam") or "").strip()
    dom = clubs_par_nom.get((code_fd, nom_dom))
    ext = clubs_par_nom.get((code_fd, nom_ext))
    if dom is None or ext is None:
        inconnus = [n for n, c in ((nom_dom, dom), (nom_ext, ext)) if c is None]
        raise ValeurIllisible(
            f"nom(s) absent(s) de clubs.nom_football_data pour {code_fd} : "
            + ", ".join(repr(n) for n in inconnus)
        )
    if dom == ext:
        raise ValeurIllisible(f"une équipe contre elle-même : {dom}")

    date_utc = convertir_date(ligne.get("Date", ""), ligne.get("Time"))
    buts_dom = _entier_ou_rien(ligne.get("FTHG"), "FTHG")
    buts_ext = _entier_ou_rien(ligne.get("FTAG"), "FTAG")
    mt_dom = _entier_ou_rien(ligne.get("HTHG"), "HTHG")
    mt_ext = _entier_ou_rien(ligne.get("HTAG"), "HTAG")

    # Le schéma refuse déjà ces deux cas ; les attraper ici nomme le fichier et
    # la ligne, au lieu de laisser remonter une contrainte SQLite.
    for cote, mi_temps, final in (("domicile", mt_dom, buts_dom),
                                  ("extérieur", mt_ext, buts_ext)):
        if mi_temps is not None and final is not None and mi_temps > final:
            raise ValeurIllisible(
                f"buts de mi-temps supérieurs au score final ({cote} : "
                f"{mi_temps} > {final})"
            )

    stats: dict[str, dict[str, int | float | None]] = {"dom": {}, "ext": {}}
    for champ, (colonne_dom, colonne_ext) in STATS_PAR_CAMP.items():
        stats["dom"][champ] = _entier_ou_rien(ligne.get(colonne_dom), colonne_dom)
        stats["ext"][champ] = _entier_ou_rien(ligne.get(colonne_ext), colonne_ext)
    stats["dom"]["xg"] = _flottant_ou_rien(ligne.get("HxG"), "HxG")
    stats["ext"]["xg"] = _flottant_ou_rien(ligne.get("AxG"), "AxG")

    # Plus de tirs cadrés que de tirs : la source se trompe. Le match, lui, est
    # bon — refuser la ligne entière pour deux statistiques coûterait un
    # résultat au moteur. Les deux valeurs passent donc à NULL : on ne sait pas
    # laquelle est fausse, et inventer serait pire que ne pas savoir. Le cas est
    # nommé dans le rapport, jamais avalé en silence. Un seul sur les 36 370
    # paires de `data/raw/` en septembre 2026 (Newcastle–West Ham, 2021-22) ;
    # si ce compte s'envolait, ce serait une inversion de colonnes chez la
    # source, et c'est précisément ce qu'il faut voir arriver.
    anomalies: list[str] = []
    for camp, nom_camp in (("dom", nom_dom), ("ext", nom_ext)):
        tirs, cadres = stats[camp]["tirs"], stats[camp]["tirs_cadres"]
        if tirs is not None and cadres is not None and cadres > tirs:
            stats[camp]["tirs"] = stats[camp]["tirs_cadres"] = None
            anomalies.append(
                f"{nom_dom}–{nom_ext} : {nom_camp} annoncé à {cadres} tirs cadrés "
                f"pour {tirs} tirs ; les deux valeurs sont écartées"
            )

    joue = buts_dom is not None and buts_ext is not None
    return LigneMatch(
        code_fd=code_fd,
        saison=libelle_saison(code_saison),
        code_saison=code_saison,
        date_utc=date_utc,
        club_id_dom=dom,
        club_id_ext=ext,
        statut="termine" if joue else "prevu",
        buts_dom=buts_dom,
        buts_ext=buts_ext,
        mt_dom=mt_dom,
        mt_ext=mt_ext,
        arbitre=_texte_ou_rien(ligne.get("Referee")),
        source_match_id=identifiant_source(code_saison, code_fd, dom, ext),
        stats_dom=stats["dom"],
        stats_ext=stats["ext"],
        anomalies=tuple(anomalies),
    )


# -- lecture d'un fichier ----------------------------------------------------


@dataclass
class Lecture:
    """Ce qu'un ou plusieurs fichiers ont donné."""

    lignes: list[LigneMatch] = field(default_factory=list)
    refus: list[Refus] = field(default_factory=list)
    # Lignes vides que football-data laisse en fin de fichier : ni une donnée,
    # ni une anomalie. Comptées pour que l'invariant de comptage retombe juste.
    ignorees: int = 0
    lues: int = 0
    # colonne surveillée → saisons où elle manque
    colonnes_absentes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # Valeurs écartées sans que la ligne le soit (voir `convertir_ligne`).
    anomalies: list[str] = field(default_factory=list)

    def etendre(self, autre: "Lecture") -> None:
        self.lignes.extend(autre.lignes)
        self.refus.extend(autre.refus)
        self.ignorees += autre.ignorees
        self.lues += autre.lues
        self.anomalies.extend(autre.anomalies)
        for colonne, saisons in autre.colonnes_absentes.items():
            self.colonnes_absentes[colonne].update(saisons)

    @property
    def comptage_juste(self) -> bool:
        return self.lues == len(self.lignes) + len(self.refus) + self.ignorees


def lire_fichier(
    chemin: Path,
    code_fd: str,
    code_saison: str,
    clubs_par_nom: dict[tuple[str, str], str],
) -> Lecture:
    """Lit un CSV football-data et convertit ses lignes.

    L'encodage est lu en `utf-8-sig` : les fichiers récents portent une marque
    d'ordre des octets qui, sinon, collerait à l'en-tête `Div` et ferait
    disparaître la colonne.
    """
    lecture = Lecture()
    nom_court = f"{code_saison}/{code_fd}"

    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        colonnes = set(lecteur.fieldnames or [])
        absentes = [c for c in COLONNES_OBLIGATOIRES if c not in colonnes]
        if absentes:
            raise TacheInterrompue(
                f"{nom_court} : colonne(s) obligatoire(s) absente(s) : "
                f"{', '.join(absentes)}"
            )
        for surveillee in COLONNES_SURVEILLEES:
            if surveillee not in colonnes:
                lecture.colonnes_absentes[surveillee].add(code_saison)

        for numero, ligne in enumerate(lecteur, start=2):
            lecture.lues += 1
            if not (ligne.get("HomeTeam") or "").strip():
                lecture.ignorees += 1
                continue
            try:
                convertie = convertir_ligne(ligne, code_fd, code_saison, clubs_par_nom)
            except ValeurIllisible as exc:
                lecture.refus.append(Refus(nom_court, numero, str(exc)))
                continue
            lecture.lignes.append(convertie)
            lecture.anomalies.extend(
                f"{nom_court} ligne {numero} : {anomalie}"
                for anomalie in convertie.anomalies
            )
    return lecture


def lire_tout(
    fichiers: list[tuple[str, str, Path]],
    clubs_par_nom: dict[tuple[str, str], str],
) -> Lecture:
    """Lit tous les fichiers retenus, sans rien écrire."""
    tout = Lecture()
    for code_saison, code_fd, chemin in fichiers:
        tout.etendre(lire_fichier(chemin, code_fd, code_saison, clubs_par_nom))
    return tout


# -- contrôles de cohérence --------------------------------------------------


def controles_coherence(lignes: list[LigneMatch], code_en_cours: str) -> list[str]:
    """Écarts de calendrier, saison par saison et ligue par ligue.

    Le nombre de matchs attendus est déduit du nombre d'équipes réellement
    observées, `N × (N−1)`, et non d'une valeur figée dans `ligues.csv` : la
    Ligue 1 est passée de 20 à 18 clubs en 2023-24, et une table de
    configuration aurait signalé six saisons parfaitement saines.

    Ce sont des **avertissements** : la saison en cours est forcément
    incomplète, et l'arrêt sanitaire de 2019-20 a bel et bien amputé la Ligue 1.
    Les taire reviendrait à ne plus voir le jour où un fichier est tronqué.
    """
    avertissements: list[str] = []
    par_groupe: dict[tuple[str, str], list[LigneMatch]] = defaultdict(list)
    for ligne in lignes:
        par_groupe[(ligne.code_saison, ligne.code_fd)].append(ligne)

    for (code_saison, code_fd), groupe in sorted(par_groupe.items()):
        equipes = {l.club_id_dom for l in groupe} | {l.club_id_ext for l in groupe}
        nombre = len(equipes)
        attendus = nombre * (nombre - 1)
        if len(groupe) != attendus:
            raison = " (saison en cours)" if code_saison == code_en_cours else ""
            avertissements.append(
                f"{code_saison}/{code_fd} : {len(groupe)} matchs pour {nombre} "
                f"équipes, {attendus} attendus{raison}"
            )
            continue
        dom = Counter(l.club_id_dom for l in groupe)
        ext = Counter(l.club_id_ext for l in groupe)
        irreguliers = sorted(
            club for club in equipes
            if dom[club] != nombre - 1 or ext[club] != nombre - 1
        )
        if irreguliers:
            avertissements.append(
                f"{code_saison}/{code_fd} : {len(irreguliers)} équipe(s) sans "
                f"{nombre - 1} matchs à domicile et autant à l'extérieur — "
                + ", ".join(irreguliers[:5])
            )
    return avertissements


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
    matchs: Comptes = field(default_factory=Comptes)
    stats: Comptes = field(default_factory=Comptes)
    lues: int = 0
    refusees: int = 0
    ignorees: int = 0
    absents_des_fichiers: int = 0
    avertissements: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    @property
    def comptage_juste(self) -> bool:
        """`lues == insérées + mises à jour + inchangées + refusées + ignorées`."""
        return self.lues == (
            self.matchs.inseres + self.matchs.majs + self.matchs.inchanges
            + self.refusees + self.ignorees
        )

    @property
    def rien_change(self) -> bool:
        return not (self.matchs.inseres or self.matchs.majs
                    or self.stats.inseres or self.stats.majs)


def _appliquer(objet: object, valeurs: dict[str, object]) -> bool:
    """Pose les valeurs qui diffèrent réellement. Dit si quelque chose a bougé.

    `maj_le` ne doit pas bouger sans raison : sinon l'horodatage ne dit plus
    rien et l'idempotence n'est plus vérifiable (leçon de T03).
    """
    differences = {
        champ: valeur
        for champ, valeur in valeurs.items()
        if getattr(objet, champ) != valeur
    }
    for champ, valeur in differences.items():
        setattr(objet, champ, valeur)
    return bool(differences)


def _matchs_du_perimetre(
    session: Session, lignes: list[LigneMatch]
) -> dict[tuple[str, str, str, str], Match]:
    """Matchs déjà en base sur les saisons et ligues lues, indexés par clé logique.

    Une seule requête plutôt qu'un `SELECT` par ligne : sur les 18 000 matchs de
    `data/raw/`, la différence est d'un ordre de grandeur, et l'idempotence se
    vérifie alors en secondes plutôt qu'en minutes.
    """
    saisons = {l.saison for l in lignes}
    codes = {l.code_fd for l in lignes}
    if not saisons:
        return {}
    existants = session.scalars(
        select(Match).where(Match.saison.in_(saisons), Match.code_fd.in_(codes))
    )
    return {
        (m.code_fd, m.saison, m.club_id_dom, m.club_id_ext): m for m in existants
    }


def _stats_du_perimetre(
    session: Session, lignes: list[LigneMatch]
) -> dict[tuple[int, str], StatsMatch]:
    """Lignes de `stats_match` déjà en base, indexées par (match, camp)."""
    saisons = {l.saison for l in lignes}
    codes = {l.code_fd for l in lignes}
    if not saisons:
        return {}
    existantes = session.scalars(
        select(StatsMatch)
        .join(Match, Match.id == StatsMatch.match_id)
        .where(Match.saison.in_(saisons), Match.code_fd.in_(codes))
    )
    return {(s.match_id, s.camp): s for s in existantes}


def _synchroniser_stats(
    session: Session,
    match: Match,
    ligne: LigneMatch,
    existantes: dict[tuple[int, str], StatsMatch],
    comptes: Comptes,
) -> None:
    for camp, club_id, valeurs in (
        ("dom", ligne.club_id_dom, ligne.stats_dom),
        ("ext", ligne.club_id_ext, ligne.stats_ext),
    ):
        existante = existantes.get((match.id, camp))
        if existante is None:
            session.add(
                StatsMatch(
                    match_id=match.id,
                    club_id=club_id,
                    camp=camp,
                    source=SOURCE,
                    **valeurs,
                )
            )
            comptes.inseres += 1
            continue
        # D03 : understat est la source des xG. Les colonnes `HxG`/`AxG` de
        # football-data ne servent que de **secours**, sur une ligne encore
        # vide. Protéger seulement les lignes qu'elle ne pourvoit pas ne
        # suffisait pas : une relance de T04 après T05 remplaçait les xG
        # understat par ceux de football-data — un autre modèle, écart moyen
        # 0,32 mesuré en T05 — et `source` continuait d'annoncer understat.
        a_poser = dict(valeurs)
        if existante.xg is not None:
            a_poser.pop("xg", None)
        a_poser["club_id"] = club_id
        if _appliquer(existante, a_poser):
            existante.maj_le = maintenant_utc()
            comptes.majs += 1
        else:
            comptes.inchanges += 1


def synchroniser(session: Session, lignes: list[LigneMatch]) -> Rapport:
    """Aligne `matchs` et `stats_match` sur les lignes lues. Ne supprime rien."""
    rapport = Rapport()
    attendus = {
        (l.code_fd, l.saison, l.club_id_dom, l.club_id_ext) for l in lignes
    }
    existants = _matchs_du_perimetre(session, lignes)
    apparies: list[tuple[LigneMatch, Match]] = []

    for ligne in lignes:
        cle = (ligne.code_fd, ligne.saison, ligne.club_id_dom, ligne.club_id_ext)
        existant = existants.get(cle)

        if existant is None:
            existant = Match(
                code_fd=ligne.code_fd,
                saison=ligne.saison,
                club_id_dom=ligne.club_id_dom,
                club_id_ext=ligne.club_id_ext,
                source=SOURCE,
                source_match_id=ligne.source_match_id,
                **ligne.champs_match(),
            )
            session.add(existant)
            rapport.matchs.inseres += 1
        else:
            valeurs = ligne.champs_match()
            # Un match créé par une autre source (le calendrier API-Football de
            # T07) garde son identité de source : football-data complète ses
            # résultats, il ne le réétiquette pas.
            if existant.source in (None, SOURCE):
                valeurs["source"] = SOURCE
                valeurs["source_match_id"] = ligne.source_match_id
            if _appliquer(existant, valeurs):
                existant.maj_le = maintenant_utc()
                rapport.matchs.majs += 1
            else:
                rapport.matchs.inchanges += 1
        apparies.append((ligne, existant))

    # Un seul envoi pour attribuer tous les identifiants techniques d'un coup :
    # `stats_match.match_id` en a besoin, et un `flush` par match coûterait
    # 18 000 allers-retours.
    session.flush()

    stats_existantes = _stats_du_perimetre(session, lignes)
    for ligne, match in apparies:
        _synchroniser_stats(session, match, ligne, stats_existantes, rapport.stats)

    # Comparaison limitée au périmètre réellement lu : avec `--saisons 2627`,
    # les dix autres saisons ne sont pas « absentes des fichiers », elles n'ont
    # simplement pas été demandées.
    perimetre = {(l.code_fd, l.saison) for l in lignes}
    rapport.absents_des_fichiers = sum(
        1
        for cle in session.execute(
            select(Match.code_fd, Match.saison, Match.club_id_dom, Match.club_id_ext)
        )
        if (cle.code_fd, cle.saison) in perimetre and tuple(cle) not in attendus
    )
    return rapport


# -- orchestration -----------------------------------------------------------


def _resume_colonnes_absentes(absentes: dict[str, set[str]]) -> list[str]:
    lignes = []
    for colonne, saisons in sorted(absentes.items()):
        explication = ABSENCES_CONNUES.get(colonne)
        marque = f" [connu : {explication}]" if explication else "  ← INATTENDU"
        lignes.append(
            f"  {colonne:<8} absente de {len(saisons)} saison(s) : "
            f"{', '.join(sorted(saisons))}{marque}"
        )
    return lignes


def executer(
    racine_depot: Path,
    dossier_source: Path | None = None,
    codes_ligues: list[str] | None = None,
    saisons: list[str] | None = None,
    url: str | None = None,
    ecrire: bool = True,
    tolerer: bool = False,
    aujourdhui: date | None = None,
    sortie=print,
) -> Rapport:
    """Déroule T04 : lit les CSV, contrôle tout, puis écrit — ou rien."""
    dossier = dossier_source or (racine_depot / DOSSIER_DEFAUT)
    racine = localiser_racine(dossier)

    machine = moteur(url)
    creer_tables(machine)
    session = fabrique_sessions(machine)()
    try:
        ligues = {
            ligue.code_fd: ligue for ligue in session.scalars(select(Ligue))
        }
        if not ligues:
            raise TacheInterrompue(
                "aucune ligue en base : lancer d'abord "
                "`python3 ingestion/charger_referentiel.py` (T03)."
            )
        if codes_ligues:
            inconnues = sorted(set(codes_ligues) - set(ligues))
            if inconnues:
                raise TacheInterrompue(
                    f"ligue(s) absente(s) de la base : {', '.join(inconnues)}"
                )
        else:
            codes_ligues = sorted(ligues)

        clubs_par_nom = {
            (club.code_fd, club.nom_football_data): club.club_id
            for club in session.scalars(select(Club))
        }

        fichiers = fichiers_a_lire(racine, codes_ligues, saisons)
        sortie(f"Source : {racine}")
        sortie(f"{len(fichiers)} fichier(s), "
               f"{len({s for s, _, _ in fichiers})} saison(s), "
               f"{len(codes_ligues)} ligue(s).")

        lecture = lire_tout(fichiers, clubs_par_nom)
        if not lecture.comptage_juste:
            raise TacheInterrompue(
                f"comptage de lecture faux : {lecture.lues} lues pour "
                f"{len(lecture.lignes)} retenues + {len(lecture.refus)} refusées "
                f"+ {lecture.ignorees} ignorées"
            )

        if lecture.colonnes_absentes:
            sortie("\nColonnes surveillées absentes :")
            for detail in _resume_colonnes_absentes(lecture.colonnes_absentes):
                sortie(detail)

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
        rapport.ignorees = lecture.ignorees
        rapport.anomalies = lecture.anomalies
        rapport.avertissements = controles_coherence(
            lecture.lignes, saison_en_cours(aujourdhui)
        )

        if not rapport.comptage_juste:
            raise TacheInterrompue(
                f"invariant de comptage faux : {rapport.lues} lues pour "
                f"{rapport.matchs.inseres} + {rapport.matchs.majs} + "
                f"{rapport.matchs.inchanges} + {rapport.refusees} + "
                f"{rapport.ignorees}"
            )

        if ecrire:
            session.commit()
        else:
            session.rollback()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
        machine.dispose()

    sortie(f"\nmatchs      : {rapport.matchs}")
    sortie(f"stats_match : {rapport.stats}")
    sortie(f"lignes      : {rapport.lues} lues = "
           f"{rapport.matchs.inseres} + {rapport.matchs.majs} + "
           f"{rapport.matchs.inchanges} + {rapport.refusees} refusées + "
           f"{rapport.ignorees} ignorées")
    if rapport.refusees:
        sortie(f"  {rapport.refusees} ligne(s) refusée(s) et écartées (--tolerer).")
    if rapport.absents_des_fichiers:
        sortie(f"  {rapport.absents_des_fichiers} match(s) en base et absent(s) "
               "des fichiers lus, conservés.")
    if rapport.anomalies:
        sortie(f"\nValeurs écartées ({len(rapport.anomalies)}) :")
        for anomalie in rapport.anomalies:
            sortie(f"  {anomalie}")
    if rapport.avertissements:
        sortie("\nÉcarts de calendrier :")
        for avertissement in rapport.avertissements:
            sortie(f"  {avertissement}")
    if not ecrire:
        sortie("\n[dry-run] aucune écriture.")
    return rapport


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    parseur.add_argument("--source", type=Path, metavar="DOSSIER",
                         help=f"dossier des CSV (défaut : {DOSSIER_DEFAUT})")
    parseur.add_argument("--ligues", nargs="+", metavar="CODE_FD", help="ex. E0 SP1")
    parseur.add_argument("--saisons", nargs="+", metavar="CODE", help="ex. 2526 2627")
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
