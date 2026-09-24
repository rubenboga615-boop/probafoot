"""
T05 — Ingestion understat (xG) et rattachement aux matchs
=========================================================

Même découpage qu'en T04 :

1. **Conversions pures** : libellés de saison, manifeste, localisation des
   fichiers. Aucune base, aucun fichier réel.
2. **Ingestion sur base temporaire**, à partir des CSV miniatures de
   `tests/fixtures/understat/`, qui décrivent exactement les mêmes matchs que
   les fixtures football-data de T04 — c'est ce qui permet de vérifier un
   rattachement de bout en bout. On y éprouve les trois propriétés : rien
   n'est écrit si quelque chose ne va pas, idempotence, rien n'est supprimé.
3. **Données réelles** de `data/raw/`, ignorées si le dossier est absent.

Le critère d'acceptation de T05 a son test dédié (`TestSeuilDeLiaison`) : sur
les saisons terminées, au moins 99 % des matchs de la base doivent porter un
xG. Il tourne sur les vraies données, parce qu'un seuil mesuré sur des
fixtures ne mesure que les fixtures.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from bdd.modeles import Club, Match, StatsMatch
from bdd.session import creer_tables, fabrique_sessions, moteur
from ingestion.charger_referentiel import executer as charger_referentiel
from ingestion.football_data import executer as importer_football_data
from ingestion.understat import (
    SEUIL_LIAISON,
    SOURCE,
    Lecture,
    TacheInterrompue,
    ValeurIllisible,
    _source_enrichie,
    est_joue,
    executer,
    fichiers_a_lire,
    libelle_saison,
    lire_manifeste,
    localiser_racine,
    nombre,
)
from ingestion.football_data import libelle_saison as libelle_saison_fd

RACINE = Path(__file__).resolve().parent.parent
FIXTURES = RACINE / "tests" / "fixtures" / "understat"
SAIN = FIXTURES / "sain"
CASSE = FIXTURES / "casse"
ANOMALIES = FIXTURES / "anomalies"
DOUBLONS = FIXTURES / "doublons"
ORPHELIN = FIXTURES / "orphelin"
SANS_EQUIPES = FIXTURES / "sans_equipes"
RETARD = FIXTURES / "retard"

FIXTURES_FD = RACINE / "tests" / "fixtures" / "football_data" / "sain"

# Lignes de `stats_match` que T04 pourvoit déjà d'un xG sur les fixtures : les
# 2 matchs de 2026-27 x 2 camps, football-data publiant `HxG`/`AxG` depuis
# cette saison. Tout ce que T05 ajoute vient en plus.
XG_DE_T04 = 4

DONNEES_REELLES = RACINE / "data" / "raw" / "understat"
DONNEES_FD = RACINE / "data" / "raw" / "football-data"

sans_donnees_reelles = pytest.mark.skipif(
    not DONNEES_REELLES.is_dir() or not DONNEES_FD.is_dir(),
    reason="data/raw/ est hors Git ; absent de cette machine",
)


# ─────────────────────────────────────────────────────────────────────
# 1) Conversions pures
# ─────────────────────────────────────────────────────────────────────


class TestLibelleSaison:
    @pytest.mark.parametrize(
        ("annee", "attendu"),
        [("2016", "2016-2017"), ("2024", "2024-2025"), ("2026", "2026-2027")],
    )
    def test_annee_en_libelle(self, annee, attendu):
        assert libelle_saison(annee) == attendu

    @pytest.mark.parametrize("annee", ["16", "20244", "abcd", ""])
    def test_annee_invalide_refusee(self, annee):
        with pytest.raises(TacheInterrompue):
            libelle_saison(annee)

    @pytest.mark.parametrize(
        ("annee_understat", "code_fd"),
        [("2016", "1617"), ("2019", "1920"), ("2025", "2526"), ("2026", "2627")],
    )
    def test_meme_libelle_que_t04(self, annee_understat, code_fd):
        """Les deux tâches doivent nommer la saison pareil, sinon rien ne lie.

        C'est le point de contact entre T04 et T05 : `Match.saison` est écrit
        par l'une et cherché par l'autre. Une divergence de format ne
        provoquerait aucune erreur, juste zéro rattachement.
        """
        assert libelle_saison(annee_understat) == libelle_saison_fd(code_fd)


class TestNombre:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [("1.88", 1.88), ("0", 0.0), ("  2.5  ", 2.5), ("", None), (None, None)],
    )
    def test_conversion(self, brut, attendu):
        assert nombre(brut, "xG") == attendu

    @pytest.mark.parametrize("brut", ["abc", "1,88", "--"])
    def test_illisible_refuse(self, brut):
        with pytest.raises(ValeurIllisible):
            nombre(brut, "xG")


class TestEstJoue:
    @pytest.mark.parametrize("brut", ["True", "true", "1", "VRAI"])
    def test_joue(self, brut):
        assert est_joue(brut)

    @pytest.mark.parametrize("brut", ["False", "false", "0", "", None, "peut-etre"])
    def test_pas_joue(self, brut):
        assert not est_joue(brut)


class TestSourceEnrichie:
    def test_ajoute_understat(self):
        assert _source_enrichie("football-data") == "football-data+understat"

    def test_pas_de_doublon(self):
        assert _source_enrichie("football-data+understat") == "football-data+understat"

    def test_source_vide(self):
        assert _source_enrichie(None) == "understat"
        assert _source_enrichie("") == "understat"

    def test_ordre_stable(self):
        """Même entrée, même sortie : l'ordre ne doit pas dépendre d'un set."""
        assert _source_enrichie("understat+football-data") == _source_enrichie(
            "football-data+understat"
        )


class TestManifeste:
    def test_lecture(self):
        assert lire_manifeste(SAIN) == {"EPL": "E0"}

    def test_manifeste_absent(self, tmp_path):
        with pytest.raises(TacheInterrompue, match="manifeste introuvable"):
            lire_manifeste(tmp_path)

    def test_colonne_absente(self, tmp_path):
        (tmp_path / "manifest.csv").write_text("ligue,url\nEPL,x\n", encoding="utf-8")
        with pytest.raises(TacheInterrompue, match="code_football_data"):
            lire_manifeste(tmp_path)

    def test_deux_codes_pour_un_slug(self, tmp_path):
        (tmp_path / "manifest.csv").write_text(
            "ligue,code_football_data\nEPL,E0\nEPL,SP1\n", encoding="utf-8"
        )
        with pytest.raises(TacheInterrompue, match="deux codes"):
            lire_manifeste(tmp_path)


class TestLocaliserRacine:
    def test_saisons_directement_sous_le_dossier(self):
        assert localiser_racine(SAIN) == SAIN

    def test_descend_une_arborescence_dupliquee(self, tmp_path):
        profond = tmp_path / "data" / "raw" / "understat"
        (profond / "2024" / "EPL").mkdir(parents=True)
        assert localiser_racine(tmp_path) == profond

    def test_dossier_absent(self, tmp_path):
        with pytest.raises(TacheInterrompue, match="introuvable"):
            localiser_racine(tmp_path / "nulle_part")

    def test_aucune_saison(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        with pytest.raises(TacheInterrompue, match="aucun dossier de saison"):
            localiser_racine(tmp_path)


class TestFichiersALire:
    def test_toutes_les_saisons(self):
        trouves = fichiers_a_lire(SAIN, {"E0": "EPL"}, ["E0"])
        assert [(a, c) for a, c, _ in trouves] == [
            ("2016", "E0"), ("2025", "E0"), ("2026", "E0")
        ]

    def test_saison_choisie(self):
        trouves = fichiers_a_lire(SAIN, {"E0": "EPL"}, ["E0"], saisons=["2026"])
        assert [a for a, _, _ in trouves] == ["2026"]

    def test_saison_absente_arrete(self):
        with pytest.raises(TacheInterrompue, match="1999"):
            fichiers_a_lire(SAIN, {"E0": "EPL"}, ["E0"], saisons=["1999"])

    def test_ligue_absente_arrete(self):
        with pytest.raises(TacheInterrompue, match="rien n'a été lu"):
            fichiers_a_lire(SAIN, {"SP1": "La_liga"}, ["SP1"])


class TestComptageDeLecture:
    def test_invariant_d_une_lecture_vide(self):
        assert Lecture().comptage_juste


# ─────────────────────────────────────────────────────────────────────
# 2) Ingestion sur base temporaire
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def url_base(tmp_path):
    """Base hors dépôt : référentiel (T03) puis matchs (T04), comme en vrai.

    T05 ne crée aucun match : sans T04 avant elle, il n'y a rien à enrichir.
    Monter la chaîne complète est aussi ce qui rend le rattachement vérifiable.
    """
    url = f"sqlite:///{tmp_path / 't05.db'}"
    charger_referentiel(RACINE, url=url, ecrire=True, sortie=lambda *_: None)
    importer_football_data(
        RACINE,
        dossier_source=FIXTURES_FD,
        codes_ligues=["E0"],
        url=url,
        ecrire=True,
        aujourdhui=date(2026, 9, 24),
        sortie=lambda *_: None,
    )
    return url


@pytest.fixture
def session_lecture(url_base):
    machine = moteur(url_base)
    creer_tables(machine)
    session = fabrique_sessions(machine)()
    yield session
    session.close()
    machine.dispose()


def lier(url, **kwargs):
    """Lance T05 sur les fixtures saines, silencieusement."""
    kwargs.setdefault("dossier_source", SAIN)
    kwargs.setdefault("codes_ligues", ["E0"])
    kwargs.setdefault("sortie", lambda *_: None)
    return executer(RACINE, url=url, **kwargs)


def xg_de(session, saison, dom, ext, camp):
    """xG et npxG d'un camp, retrouvés par la clé logique du match."""
    match = session.scalars(
        select(Match).where(
            Match.saison == saison, Match.club_id_dom == dom, Match.club_id_ext == ext
        )
    ).one()
    stat = session.scalars(
        select(StatsMatch).where(
            StatsMatch.match_id == match.id, StatsMatch.camp == camp
        )
    ).one()
    return stat.xg, stat.npxg


class TestRattachement:
    def test_tous_les_matchs_joues_sont_rattaches(self, url_base):
        rapport = lier(url_base)
        # 12 (2016) + 12 (2025) + 2 (2026 joués) = 26 ; 2 matchs à venir.
        assert rapport.rattachees == 26
        assert rapport.a_venir == 2
        assert rapport.sans_match == []

    def test_invariant_de_comptage(self, url_base):
        """lues == rattachées + sans match + refusées + à venir."""
        rapport = lier(url_base)
        assert rapport.lues == 28
        assert rapport.comptage_juste

    def test_xg_pose_sur_les_deux_camps(self, url_base, session_lecture):
        lier(url_base)
        assert xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "dom"
        ) == (1.84, 1.84)
        assert xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "ext"
        ) == (1.12, 0.41)

    def test_aucun_camp_inverse(self, url_base, session_lecture):
        """Le camp domicile doit recevoir le xG domicile, sur tous les matchs.

        Une inversion serait invisible à l'œil : les deux valeurs existent, les
        comptes tombent juste, et seul le modèle s'en apercevrait six mois plus
        tard. On rejoue donc la fixture ligne à ligne.
        """
        lier(url_base)
        clubs = {
            nom: club_id
            for club_id, nom in session_lecture.execute(
                select(Club.club_id, Club.nom_understat)
            )
        }
        with (SAIN / "2016" / "EPL" / "matches.csv").open(encoding="utf-8") as flux:
            attendus = [ligne for ligne in csv.DictReader(flux)
                        if ligne["is_result"] == "True"]
        assert attendus
        for ligne in attendus:
            dom, ext = clubs[ligne["home_team"]], clubs[ligne["away_team"]]
            assert xg_de(session_lecture, "2016-2017", dom, ext, "dom")[0] == pytest.approx(
                float(ligne["home_xg"])
            )
            assert xg_de(session_lecture, "2016-2017", dom, ext, "ext")[0] == pytest.approx(
                float(ligne["away_xg"])
            )

    def test_npxg_repris_de_team_matches(self, url_base, session_lecture):
        lier(url_base)
        xg, npxg = xg_de(
            session_lecture, "2026-2027", "E0-arsenal", "E0-chelsea", "dom"
        )
        assert (xg, npxg) == (1.88, 1.51)  # un penalty dans le xG, pas dans le npxG

    def test_matchs_a_venir_sans_xg(self, url_base, session_lecture):
        """Les matchs non joués d'understat portent des zéros : ne rien écrire.

        Sans ce filtre, un match futur poserait `xg = 0`, valeur parfaitement
        plausible qu'aucune contrainte ne rattraperait.
        """
        lier(url_base)
        assert (
            session_lecture.scalars(
                select(Match).where(
                    Match.saison == "2026-2027", Match.club_id_dom == "E0-chelsea"
                )
            ).one_or_none()
            is None
        )
        pourvus = session_lecture.scalar(
            select(func.count()).select_from(StatsMatch).where(StatsMatch.xg.is_not(None))
        )
        assert pourvus == 2 * 26

    def test_source_enrichie_sans_perdre_la_precedente(self, url_base, session_lecture):
        """T04 a posé `football-data` ; T05 ajoute sans effacer."""
        lier(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        stat = session_lecture.scalars(
            select(StatsMatch).where(
                StatsMatch.match_id == match.id, StatsMatch.camp == "dom"
            )
        ).one()
        assert stat.source == "football-data+understat"
        assert SOURCE in stat.source

    def test_aucun_match_cree(self, url_base, session_lecture):
        """T05 enrichit, elle n'ingère pas : le compte de matchs ne bouge pas."""
        avant = session_lecture.scalar(select(func.count()).select_from(Match))
        lier(url_base)
        session_lecture.expire_all()
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == avant

    def test_les_stats_de_t04_sont_preservees(self, url_base, session_lecture):
        """Tirs, corners et cartons ne doivent pas bouger d'un iota."""
        lier(url_base)
        stat = session_lecture.scalars(
            select(StatsMatch)
            .join(Match, Match.id == StatsMatch.match_id)
            .where(
                Match.saison == "2026-2027",
                Match.club_id_dom == "E0-arsenal",
                StatsMatch.camp == "dom",
            )
        ).one()
        assert (stat.tirs, stat.tirs_cadres, stat.corners) == (20, 6, 8)
        assert (stat.cartons_jaunes, stat.cartons_rouges) == (1, 0)


class TestIdempotence:
    def test_deuxieme_passage_n_ecrit_rien(self, url_base):
        lier(url_base)
        second = lier(url_base)
        assert (second.stats.majs, second.stats.inseres) == (0, 0)
        assert second.stats.inchanges == 2 * 26

    def test_maj_le_ne_bouge_pas_sans_raison(self, url_base, session_lecture):
        lier(url_base)
        avant = {
            (s.match_id, s.camp): s.maj_le
            for s in session_lecture.scalars(select(StatsMatch))
        }
        lier(url_base)
        session_lecture.expire_all()
        apres = {
            (s.match_id, s.camp): s.maj_le
            for s in session_lecture.scalars(select(StatsMatch))
        }
        assert avant == apres

    def test_source_non_dupliquee_au_second_passage(self, url_base, session_lecture):
        lier(url_base)
        lier(url_base)
        session_lecture.expire_all()
        sources = set(session_lecture.scalars(select(StatsMatch.source)))
        assert sources == {"football-data+understat"}

    def test_xg_corrige_est_repris(self, url_base, session_lecture, tmp_path):
        """Un xG révisé chez la source doit être mis à jour, une seule fois."""
        lier(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2016-2017", Match.club_id_dom == "E0-arsenal",
                Match.club_id_ext == "E0-chelsea",
            )
        ).one()
        stat = session_lecture.scalars(
            select(StatsMatch).where(
                StatsMatch.match_id == match.id, StatsMatch.camp == "dom"
            )
        ).one()
        # `npxg` part avec lui : le laisser à 1.84 violerait `npxg <= xg`, et
        # le test tomberait sur la contrainte au lieu de mesurer l'idempotence.
        stat.xg = 1.11
        stat.npxg = None
        session_lecture.commit()

        rapport = lier(url_base)
        assert rapport.stats.majs == 1
        session_lecture.expire_all()
        assert xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "dom"
        )[0] == 1.84


class TestRienNEstEcrasePourRien:
    def test_xg_existant_non_efface_par_un_vide(self, url_base, session_lecture):
        """Cas réel : football-data a fourni un xG qu'understat n'a pas encore.

        `_appliquer` ignore les `None`. Sans cela, un passage de T05 effacerait
        les xG de la saison en cours chaque fois qu'understat est en retard.
        """
        lier(url_base, dossier_source=SANS_EQUIPES)
        xg, npxg = xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "dom"
        )
        assert xg == 1.84       # posé par matches.csv
        assert npxg is None     # team_matches.csv absent : rien d'inventé

    def test_xg_de_t04_survit_au_retard_d_understat(self, url_base, session_lecture):
        """Le cas réel des 44 matchs de la dernière journée.

        football-data publie `HxG`/`AxG` depuis 2026-27 et va plus vite
        qu'understat. Sur ces matchs, understat n'a encore rien : ses colonnes
        d'xG valent 0 et `is_result` est faux. Si T05 écrivait quand même,
        elle remplacerait une vraie valeur par un zéro — une perte silencieuse,
        que rien en aval ne distinguerait d'un match sans occasion.
        """
        avant = xg_de(session_lecture, "2026-2027", "E0-arsenal", "E0-chelsea", "dom")
        assert avant[0] == 1.88, "T04 doit avoir posé ce xG"

        lier(url_base, dossier_source=RETARD)
        session_lecture.expire_all()
        apres = xg_de(session_lecture, "2026-2027", "E0-arsenal", "E0-chelsea", "dom")
        assert apres[0] == 1.88, "understat en retard ne doit rien effacer"

    def test_npxg_de_t05_ne_regresse_pas(self, url_base, session_lecture):
        """Un npxG déjà posé n'est pas remis à vide par un passage plus pauvre.

        Cas discriminant : le match est **joué** — il traverse donc tout le
        chemin d'écriture — mais `team_matches.csv` a disparu, si bien
        qu'understat ne donne plus que le xG. Seul le refus d'écrire les
        `None` protège ici le npxG déjà en base ; `est_joue` ne filtre rien
        sur un match joué.
        """
        lier(url_base)
        assert xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "dom"
        )[1] == 1.84

        lier(url_base, dossier_source=SANS_EQUIPES)
        session_lecture.expire_all()
        assert xg_de(
            session_lecture, "2016-2017", "E0-arsenal", "E0-chelsea", "dom"
        )[1] == 1.84, "un passage sans team_matches.csv ne doit pas effacer le npxG"

    def test_npxg_absent_signale(self, url_base):
        rapport = lier(url_base, dossier_source=SANS_EQUIPES)
        assert any("team_matches.csv absent" in a for a in rapport.anomalies)


class TestColonnesSurveillees:
    """Les colonnes surveillées vivent dans `team_matches.csv`, pas ailleurs.

    Les chercher dans `matches.csv` — qui n'a jamais porté `npxG` ni `deep` —
    faisait signaler onze saisons comme amputées à chaque exécution. Un rapport
    qui crie tout le temps ne se lit plus, et la vraie disparition passerait
    inaperçue le jour où elle arrive.
    """

    def test_aucune_absence_sur_des_fichiers_complets(self, url_base, capsys):
        executer(
            RACINE, url=url_base, dossier_source=SAIN, codes_ligues=["E0"],
            ecrire=False,
        )
        assert "Colonnes surveillées absentes" not in capsys.readouterr().out

    def test_absence_reelle_signalee(self, url_base, capsys):
        executer(
            RACINE, url=url_base, dossier_source=SANS_EQUIPES, codes_ligues=["E0"],
            ecrire=False,
        )
        sortie = capsys.readouterr().out
        assert "Colonnes surveillées absentes" in sortie
        assert "npxG" in sortie


class TestRienNEstEcritSiQuelqueChoseNeVaPas:
    def test_dry_run_n_ecrit_rien(self, url_base, session_lecture):
        rapport = lier(url_base, ecrire=False)
        assert rapport.rattachees == 26
        session_lecture.expire_all()
        pourvus = session_lecture.scalar(
            select(func.count()).select_from(StatsMatch).where(StatsMatch.xg.is_not(None))
        )
        # 4 = les 2 matchs de 2026-27 x 2 camps, dont T04 a lu les colonnes
        # `HxG`/`AxG` de football-data. T05 n'a rien ajouté.
        assert pourvus == XG_DE_T04

    def test_nom_inconnu_arrete_tout(self, url_base, session_lecture):
        with pytest.raises(TacheInterrompue, match="nom understat inconnu"):
            lier(url_base, dossier_source=CASSE)
        session_lecture.expire_all()
        pourvus = session_lecture.scalar(
            select(func.count()).select_from(StatsMatch).where(StatsMatch.xg.is_not(None))
        )
        assert pourvus == XG_DE_T04, "un fichier fautif ne doit rien laisser passer"

    def test_tolerer_importe_le_reste(self, url_base, session_lecture):
        rapport = lier(url_base, dossier_source=CASSE, tolerer=True)
        assert rapport.refusees == 1
        assert rapport.comptage_juste
        session_lecture.expire_all()
        pourvus = session_lecture.scalar(
            select(func.count()).select_from(StatsMatch).where(StatsMatch.xg.is_not(None))
        )
        assert pourvus == 2 * 25  # les 26 moins le match refusé

    def test_doublon_dans_les_fichiers_arrete_tout(self, url_base):
        with pytest.raises(TacheInterrompue, match="en double"):
            lier(url_base, dossier_source=DOUBLONS)

    def test_stats_match_disparue_arrete(self, url_base, session_lecture):
        """`matchs` et `stats_match` ont divergé : le dire, ne pas combler.

        T04 crée toujours deux lignes de stats par match. S'il en manque une,
        quelque chose d'anormal s'est produit en amont, et une ligne recréée
        ici n'aurait que des xG — ni tirs, ni corners, ni cartons. Mieux vaut
        s'arrêter et renvoyer vers T04.
        """
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2016-2017", Match.club_id_dom == "E0-arsenal",
                Match.club_id_ext == "E0-chelsea",
            )
        ).one()
        stat = session_lecture.scalars(
            select(StatsMatch).where(
                StatsMatch.match_id == match.id, StatsMatch.camp == "dom"
            )
        ).one()
        session_lecture.delete(stat)
        session_lecture.commit()

        with pytest.raises(TacheInterrompue, match="ont\\s+divergé"):
            lier(url_base)

        session_lecture.expire_all()
        pourvus = session_lecture.scalar(
            select(func.count()).select_from(StatsMatch).where(StatsMatch.xg.is_not(None))
        )
        assert pourvus == XG_DE_T04, "rien ne doit avoir été écrit"

    def test_base_sans_match_arrete(self, tmp_path):
        """Sans T04, il n'y a rien à enrichir : le dire, pas écrire à vide."""
        url = f"sqlite:///{tmp_path / 'vide.db'}"
        charger_referentiel(RACINE, url=url, ecrire=True, sortie=lambda *_: None)
        with pytest.raises(TacheInterrompue, match="aucun match en base"):
            lier(url)


class TestAnomalies:
    def test_desaccord_entre_les_deux_fichiers_signale(self, url_base):
        """`matches.csv` et `team_matches.csv` doivent donner le même xG.

        Un désaccord veut dire que le rattachement a apparié deux matchs
        différents : c'est le seul risque sérieux de cette tâche, et il est
        parfaitement silencieux sans ce contrôle croisé.
        """
        rapport = lier(url_base, dossier_source=ANOMALIES)
        assert any("team_matches.csv" in a and "9.99" in a for a in rapport.anomalies)

    def test_npxg_superieur_au_xg_ecarte(self, url_base, session_lecture):
        rapport = lier(url_base, dossier_source=ANOMALIES)
        assert any("npxG pour" in a for a in rapport.anomalies)
        _, npxg = xg_de(
            session_lecture, "2016-2017", "E0-chelsea", "E0-arsenal", "dom"
        )
        assert npxg is None, "une valeur invraisemblable ne doit pas entrer"

    def test_le_match_est_importe_quand_meme(self, url_base, session_lecture):
        """Une anomalie sur une colonne n'invalide pas le xG du match."""
        lier(url_base, dossier_source=ANOMALIES)
        xg, _ = xg_de(session_lecture, "2016-2017", "E0-chelsea", "E0-arsenal", "dom")
        assert xg == 2.41


class TestMatchSansCorrespondance:
    def test_signale_et_jamais_cree(self, url_base, session_lecture):
        """understat en avance sur football-data : signaler, ne rien inventer."""
        avant = session_lecture.scalar(select(func.count()).select_from(Match))
        rapport = lier(url_base, dossier_source=ORPHELIN)
        assert len(rapport.sans_match) == 1
        assert "E0-mancity" in rapport.sans_match[0]
        session_lecture.expire_all()
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == avant

    def test_comptage_reste_juste(self, url_base):
        rapport = lier(url_base, dossier_source=ORPHELIN)
        assert rapport.comptage_juste
        assert rapport.lues == 29  # 28 + le match orphelin


class TestContraintesDuSchema:
    def test_npxg_superieur_au_xg_refuse(self, url_base, session_lecture):
        lier(url_base)
        stat = session_lecture.scalars(
            select(StatsMatch).where(StatsMatch.xg.is_not(None))
        ).first()
        stat.npxg = stat.xg + 1
        with pytest.raises(Exception, match="ck_stats_match_npxg"):
            session_lecture.commit()
        session_lecture.rollback()

    def test_xg_negatif_refuse(self, url_base, session_lecture):
        lier(url_base)
        stat = session_lecture.scalars(
            select(StatsMatch).where(StatsMatch.xg.is_not(None))
        ).first()
        # `npxg` d'abord vidé, pour que ce test-ci ne bute pas sur
        # `ck_stats_match_npxg` : c'est le signe du xG négatif qu'il éprouve.
        stat.npxg = None
        stat.xg = -0.5
        with pytest.raises(Exception, match="ck_stats_match_xg_positif"):
            session_lecture.commit()
        session_lecture.rollback()


class TestCouverture:
    def test_mesuree_par_saison(self, url_base):
        rapport = lier(url_base)
        assert rapport.couverture["2016-2017"] == (12, 12)
        assert rapport.couverture["2025-2026"] == (12, 12)
        assert rapport.couverture["2026-2027"] == (2, 2)

    def test_saison_en_cours_exclue_du_seuil(self, url_base):
        """Un retard d'understat sur la journée en cours ne doit rien faire tomber."""
        rapport = lier(url_base, dossier_source=SANS_EQUIPES)
        assert rapport.avertissements == []


# ─────────────────────────────────────────────────────────────────────
# 3) Données réelles
# ─────────────────────────────────────────────────────────────────────


@sans_donnees_reelles
class TestDonneesReelles:
    def test_onze_saisons_cinq_ligues(self):
        racine = localiser_racine(DONNEES_REELLES)
        manifeste = lire_manifeste(racine)
        assert set(manifeste.values()) == {"E0", "SP1", "I1", "D1", "F1"}
        slugs = {code: slug for slug, code in manifeste.items()}
        fichiers = fichiers_a_lire(racine, slugs, sorted(slugs))
        assert len({a for a, _, _ in fichiers}) == 11
        assert len(fichiers) == 55

    def test_tous_les_noms_understat_sont_au_referentiel(self):
        """Règle 10 : aucun nom brut ne doit rester sans `club_id`.

        Un nom non résolu ferait tomber toute la tâche (`nom understat
        inconnu`) : ce test dit *lequel*, ce qui est la seule chose utile
        quand understat renomme un club en cours de saison.
        """
        racine = localiser_racine(DONNEES_REELLES)
        connus = set()
        with (RACINE / "data" / "reference" / "clubs.csv").open(
            encoding="utf-8-sig"
        ) as flux:
            for ligne in csv.DictReader(flux):
                if ligne["nom_understat"]:
                    connus.add((ligne["code_fd"], ligne["nom_understat"]))
        manifeste = lire_manifeste(racine)
        inconnus = set()
        for chemin in sorted(racine.glob("20*/*/matches.csv")):
            code_fd = manifeste.get(chemin.parent.name)
            with chemin.open(encoding="utf-8-sig") as flux:
                for ligne in csv.DictReader(flux):
                    for nom in (ligne["home_team"], ligne["away_team"]):
                        if (code_fd, nom.strip()) not in connus:
                            inconnus.add((code_fd, nom.strip()))
        assert not inconnus, f"noms understat sans club_id : {sorted(inconnus)[:10]}"


@sans_donnees_reelles
class TestSeuilDeLiaison:
    """Le critère d'acceptation de T05 (ROADMAP) : ≥ 99 % de liaison.

    Mesuré sur la base réelle, qui doit avoir été remplie par T04 puis T05.
    Le test est ignoré si la base n'existe pas encore : il mesure un résultat,
    il ne le fabrique pas.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def session_reelle(cls):
        chemin = RACINE / "data" / "local.db"
        if not chemin.exists():
            pytest.skip("data/local.db absente : lancer T04 puis T05")
        machine = moteur(f"sqlite:///{chemin}")
        session = fabrique_sessions(machine)()
        yield session
        session.close()
        machine.dispose()

    def test_saisons_terminees_au_dessus_du_seuil(self, session_reelle):
        en_cours = session_reelle.scalar(select(func.max(Match.saison)))
        totaux: dict[str, int] = {}
        pourvus: dict[str, int] = {}
        for saison, total in session_reelle.execute(
            select(Match.saison, func.count()).group_by(Match.saison)
        ):
            totaux[saison] = total
        for saison, total in session_reelle.execute(
            select(Match.saison, func.count(func.distinct(StatsMatch.match_id)))
            .join(StatsMatch, StatsMatch.match_id == Match.id)
            .where(StatsMatch.xg.is_not(None))
            .group_by(Match.saison)
        ):
            pourvus[saison] = total

        sous_le_seuil = {
            saison: (pourvus.get(saison, 0), total)
            for saison, total in totaux.items()
            if saison != en_cours
            and pourvus.get(saison, 0) / total < SEUIL_LIAISON
        }
        assert not sous_le_seuil, f"saisons sous 99 % : {sous_le_seuil}"

    def test_ensemble_au_dessus_du_seuil(self, session_reelle):
        total = session_reelle.scalar(select(func.count()).select_from(Match))
        pourvus = session_reelle.scalar(
            select(func.count(func.distinct(StatsMatch.match_id)))
            .where(StatsMatch.xg.is_not(None))
        )
        assert pourvus / total >= SEUIL_LIAISON, (
            f"{pourvus}/{total} = {100 * pourvus / total:.2f} %"
        )

    def test_aucun_xg_sans_npxg_coherent(self, session_reelle):
        """npxg ≤ xg partout : la contrainte le garantit, on le vérifie en vrai."""
        fautifs = session_reelle.scalar(
            select(func.count())
            .select_from(StatsMatch)
            .where(StatsMatch.npxg.is_not(None), StatsMatch.xg.is_not(None))
            .where(StatsMatch.npxg > StatsMatch.xg + 1e-6)
        )
        assert fautifs == 0
