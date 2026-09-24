"""
T04 — Ingestion football-data.co.uk
===================================

Trois familles de tests :

1. **Conversions pures** : dates, heures, codes de saison, localisation des
   fichiers. Aucune base, aucun fichier réel.
2. **Ingestion sur base temporaire**, à partir des CSV miniatures de
   `tests/fixtures/football_data/`. C'est là que se vérifient les trois
   propriétés annoncées : rien n'est écrit si quelque chose ne va pas,
   l'ingestion est idempotente, rien n'est supprimé.
3. **Données réelles** de `data/raw/`, ignorées si le dossier est absent : il
   est hors Git, et la suite doit rester verte sur une machine neuve.

La conversion de fuseau a une preuve dédiée : les coups d'envoi lus dans les
CSV de la saison en cours doivent tomber **à la seconde près** sur les
`date_utc` du calendrier API-Football récupéré en T00. Deux sources
indépendantes, une seule vérité.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from bdd.modeles import Club, Match, StatsMatch
from bdd.session import creer_tables, fabrique_sessions, moteur
from ingestion.charger_referentiel import executer as charger_referentiel
from ingestion.football_data import (
    SOURCE,
    Lecture,
    TacheInterrompue,
    ValeurIllisible,
    controles_coherence,
    convertir_date,
    executer,
    fichiers_a_lire,
    identifiant_source,
    libelle_saison,
    localiser_racine,
    saison_en_cours,
)

RACINE = Path(__file__).resolve().parent.parent
FIXTURES = RACINE / "tests" / "fixtures" / "football_data"
SAIN = FIXTURES / "sain"
CASSE = FIXTURES / "casse"
ANOMALIES = FIXTURES / "anomalies"

DONNEES_REELLES = RACINE / "data" / "raw" / "football-data"
CALENDRIER_API = RACINE / "data" / "raw" / "api-football" / "fixtures" / "2026"

sans_donnees_reelles = pytest.mark.skipif(
    not DONNEES_REELLES.is_dir(),
    reason="data/raw/football-data/ est hors Git ; absent de cette machine",
)


# ─────────────────────────────────────────────────────────────────────
# 1) Conversions pures
# ─────────────────────────────────────────────────────────────────────


class TestLibelleSaison:
    @pytest.mark.parametrize(
        ("code", "attendu"),
        [("1617", "2016-2017"), ("2526", "2025-2026"), ("2627", "2026-2027"),
         ("9900", "1999-2000"), ("0001", "2000-2001")],
    )
    def test_code_en_libelle(self, code, attendu):
        assert libelle_saison(code) == attendu

    @pytest.mark.parametrize("code", ["26", "202627", "abcd", ""])
    def test_code_invalide_refuse(self, code):
        with pytest.raises(TacheInterrompue):
            libelle_saison(code)


class TestSaisonEnCours:
    def test_une_saison_demarre_en_juillet(self):
        assert saison_en_cours(date(2026, 6, 30)) == "2526"
        assert saison_en_cours(date(2026, 7, 1)) == "2627"

    def test_aujourdhui_dans_la_saison_2026_27(self):
        assert saison_en_cours(date(2026, 9, 24)) == "2627"


class TestConvertirDate:
    def test_format_a_deux_chiffres_sans_heure(self):
        """Saisons 2016-17 à 2018-19 : la source ne publiait pas l'heure."""
        assert convertir_date("13/08/16", None) == datetime(2016, 8, 13, 0, 0)

    def test_heure_vide_traitee_comme_absente(self):
        assert convertir_date("13/08/2016", "") == datetime(2016, 8, 13, 0, 0)

    def test_minuit_sans_conversion_de_fuseau(self):
        """Convertir minuit depuis Londres reculerait la date d'un jour l'été."""
        assert convertir_date("15/08/2025", None).date() == date(2025, 8, 15)

    def test_heure_d_ete_britannique_retiree(self):
        """Août : Londres est à UTC+1, le coup d'envoi recule d'une heure."""
        assert convertir_date("15/08/2025", "20:00") == datetime(2025, 8, 15, 19, 0)

    def test_heure_d_hiver_identique_a_l_utc(self):
        """Décembre : Londres est à UTC+0, rien ne bouge."""
        assert convertir_date("20/12/2025", "15:00") == datetime(2025, 12, 20, 15, 0)

    def test_conversion_peut_changer_le_jour(self):
        """Une heure d'été très matinale bascule la veille en UTC."""
        assert convertir_date("15/08/2025", "00:30") == datetime(2025, 8, 14, 23, 30)

    def test_bascule_de_l_heure_d_ete(self):
        """Le 30 mars 2025, Londres passe à UTC+1 à 01:00 : avant, rien ne bouge."""
        assert convertir_date("30/03/2025", "00:30") == datetime(2025, 3, 30, 0, 30)
        assert convertir_date("30/03/2025", "15:00") == datetime(2025, 3, 30, 14, 0)

    def test_resultat_sans_fuseau(self):
        """La base stocke des datetimes naïfs (règle 11, bdd/session.py)."""
        assert convertir_date("15/08/2025", "20:00").tzinfo is None

    @pytest.mark.parametrize("brut", ["32/13/2019", "2019-08-13", "", "demain"])
    def test_date_illisible_refusee(self, brut):
        with pytest.raises(ValeurIllisible):
            convertir_date(brut, "15:00")

    def test_heure_illisible_refusee(self):
        with pytest.raises(ValeurIllisible):
            convertir_date("13/08/2016", "midi")


class TestIdentifiantSource:
    def test_construit_sur_la_cle_logique(self):
        assert (
            identifiant_source("2526", "E0", "E0-arsenal", "E0-chelsea")
            == "2526:E0:E0-arsenal:E0-chelsea"
        )

    def test_stable_si_le_match_est_reporte(self):
        """L'identité ne dépend ni de la date ni du numéro de ligne."""
        premier = identifiant_source("2526", "E0", "E0-arsenal", "E0-chelsea")
        second = identifiant_source("2526", "E0", "E0-arsenal", "E0-chelsea")
        assert premier == second

    def test_le_match_retour_a_une_autre_identite(self):
        assert identifiant_source("2526", "E0", "E0-arsenal", "E0-chelsea") != (
            identifiant_source("2526", "E0", "E0-chelsea", "E0-arsenal")
        )


class TestLocaliserRacine:
    def test_dossier_contenant_deja_les_saisons(self):
        assert localiser_racine(SAIN) == SAIN

    def test_descend_dans_une_arborescence_dupliquee(self, tmp_path):
        """Cas réel : data/raw/football-data/data/raw/football-data/<saison>/."""
        profond = tmp_path / "data" / "raw" / "football-data"
        (profond / "2526").mkdir(parents=True)
        assert localiser_racine(tmp_path) == profond

    def test_s_arrete_si_plusieurs_pistes(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        with pytest.raises(TacheInterrompue, match="aucun dossier de saison"):
            localiser_racine(tmp_path)

    def test_dossier_absent(self, tmp_path):
        with pytest.raises(TacheInterrompue, match="introuvable"):
            localiser_racine(tmp_path / "nulle-part")


class TestFichiersALire:
    def test_ordre_chronologique(self):
        trouves = fichiers_a_lire(SAIN, ["E0"])
        assert [saison for saison, _, _ in trouves] == ["1617", "2526", "2627"]

    def test_filtre_par_saison(self):
        trouves = fichiers_a_lire(SAIN, ["E0"], saisons=["2627"])
        assert [saison for saison, _, _ in trouves] == ["2627"]

    def test_saison_demandee_absente(self):
        with pytest.raises(TacheInterrompue, match="1819"):
            fichiers_a_lire(SAIN, ["E0"], saisons=["1819"])

    def test_ligue_sans_fichier(self):
        """Un fichier manquant arrête la tâche : il ne s'agit pas de deviner."""
        with pytest.raises(TacheInterrompue, match="absent"):
            fichiers_a_lire(SAIN, ["E0", "SP1"])


class TestComptageDeLecture:
    def test_invariant_d_une_lecture_vide(self):
        assert Lecture().comptage_juste


# ─────────────────────────────────────────────────────────────────────
# 2) Ingestion sur base temporaire
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def url_base(tmp_path):
    """Base temporaire hors du dépôt, chargée du référentiel réel (T03)."""
    url = f"sqlite:///{tmp_path / 't04.db'}"
    charger_referentiel(RACINE, url=url, ecrire=True, sortie=lambda *_: None)
    return url


@pytest.fixture
def session_lecture(url_base):
    """Session de lecture seule sur la base du test."""
    machine = moteur(url_base)
    creer_tables(machine)
    session = fabrique_sessions(machine)()
    yield session
    session.close()
    machine.dispose()


def importer(url, **kwargs):
    """Lance T04 sur les fixtures saines, silencieusement."""
    kwargs.setdefault("dossier_source", SAIN)
    kwargs.setdefault("codes_ligues", ["E0"])
    kwargs.setdefault("aujourdhui", date(2026, 9, 24))
    kwargs.setdefault("sortie", lambda *_: None)
    return executer(RACINE, url=url, **kwargs)


class TestImportInitial:
    def test_les_trois_fichiers_sont_importes(self, url_base, session_lecture):
        rapport = importer(url_base)
        assert rapport.matchs.inseres == 26  # 12 + 12 + 2
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 26

    def test_invariant_de_comptage(self, url_base):
        """lues == insérées + mises à jour + inchangées + refusées + ignorées."""
        rapport = importer(url_base)
        assert rapport.lues == 26
        assert rapport.comptage_juste

    def test_aucun_nom_brut_en_base(self, url_base, session_lecture):
        """Règle 10 : les matchs désignent les clubs par `club_id`."""
        importer(url_base)
        connus = set(session_lecture.scalars(select(Club.club_id)))
        cotes = session_lecture.execute(
            select(Match.club_id_dom, Match.club_id_ext)
        ).all()
        assert cotes
        for dom, ext in cotes:
            assert dom in connus and ext in connus

    def test_scores_et_mi_temps(self, url_base, session_lecture):
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027",
                Match.club_id_dom == "E0-arsenal",
            )
        ).one()
        assert (match.buts_dom, match.buts_ext) == (3, 0)
        assert (match.mt_dom, match.mt_ext) == (2, 0)
        assert match.statut == "termine"
        assert match.arbitre == "T Bramall"

    def test_saison_au_format_du_referentiel(self, url_base, session_lecture):
        importer(url_base)
        saisons = set(session_lecture.scalars(select(Match.saison).distinct()))
        assert saisons == {"2016-2017", "2025-2026", "2026-2027"}

    def test_identite_de_source(self, url_base, session_lecture):
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        assert match.source == SOURCE
        assert match.source_match_id == "2627:E0:E0-arsenal:E0-chelsea"

    def test_heure_convertie_depuis_londres(self, url_base, session_lecture):
        """20:00 BST le 21/08/2026 → 19:00 UTC."""
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        assert match.date_utc == datetime(2026, 8, 21, 19, 0)

    def test_saison_sans_heure_stockee_a_minuit(self, url_base, session_lecture):
        importer(url_base)
        dates = session_lecture.scalars(
            select(Match.date_utc).where(Match.saison == "2016-2017")
        ).all()
        assert dates
        assert all(d.hour == 0 and d.minute == 0 for d in dates)


class TestStatsMatch:
    def test_deux_lignes_par_match(self, url_base, session_lecture):
        importer(url_base)
        matchs = session_lecture.scalar(select(func.count()).select_from(Match))
        stats = session_lecture.scalar(select(func.count()).select_from(StatsMatch))
        assert stats == 2 * matchs

    def test_camps_et_clubs_corrects(self, url_base, session_lecture):
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        lignes = {
            stats.camp: stats
            for stats in session_lecture.scalars(
                select(StatsMatch).where(StatsMatch.match_id == match.id)
            )
        }
        assert set(lignes) == {"dom", "ext"}
        assert lignes["dom"].club_id == match.club_id_dom
        assert lignes["ext"].club_id == match.club_id_ext
        assert (lignes["dom"].tirs, lignes["dom"].tirs_cadres) == (20, 6)
        assert lignes["ext"].corners == 2

    def test_xg_de_la_saison_en_cours(self, url_base, session_lecture):
        """La source publie HxG/AxG depuis 2026-27 ; T05 fera le reste."""
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        valeurs = {
            stats.camp: stats.xg
            for stats in session_lecture.scalars(
                select(StatsMatch).where(StatsMatch.match_id == match.id)
            )
        }
        assert valeurs == {"dom": pytest.approx(1.88), "ext": pytest.approx(0.20)}

    def test_xg_absent_des_saisons_anciennes(self, url_base, session_lecture):
        importer(url_base)
        anciens = session_lecture.scalars(
            select(StatsMatch.xg)
            .join(Match, Match.id == StatsMatch.match_id)
            .where(Match.saison == "2016-2017")
        ).all()
        assert anciens and all(valeur is None for valeur in anciens)

    def test_xg_understat_non_ecrase_par_une_colonne_vide(
        self, url_base, session_lecture
    ):
        """T05 écrira les xG de l'historique ; une relance ne doit pas les effacer."""
        importer(url_base)
        ligne = session_lecture.scalars(
            select(StatsMatch)
            .join(Match, Match.id == StatsMatch.match_id)
            .where(Match.saison == "2016-2017")
            .limit(1)
        ).one()
        identifiant = ligne.id
        ligne.xg = 1.23
        session_lecture.commit()

        importer(url_base)
        session_lecture.expire_all()
        assert session_lecture.get(StatsMatch, identifiant).xg == pytest.approx(1.23)


class TestValeursInvraisemblables:
    """Plus de tirs cadrés que de tirs : la source se trompe, le match est bon.

    Cas réel, trouvé à la première exécution de T04 sur `data/raw/` :
    Newcastle–West Ham du 15/08/2021, 8 tirs et 9 cadrés pour West Ham. Un seul
    sur 36 370 paires.
    """

    def test_le_match_est_importe_quand_meme(self, url_base, session_lecture):
        rapport = importer(url_base, dossier_source=ANOMALIES)
        assert rapport.matchs.inseres == 2
        assert rapport.refusees == 0
        match = session_lecture.scalars(
            select(Match).where(Match.club_id_dom == "E0-newcastle")
        ).one()
        assert (match.buts_dom, match.buts_ext) == (2, 4)

    def test_les_deux_valeurs_sont_ecartees(self, url_base, session_lecture):
        """On ne sait pas laquelle est fausse : inventer serait pire."""
        importer(url_base, dossier_source=ANOMALIES)
        match = session_lecture.scalars(
            select(Match).where(Match.club_id_dom == "E0-newcastle")
        ).one()
        lignes = {
            stats.camp: stats
            for stats in session_lecture.scalars(
                select(StatsMatch).where(StatsMatch.match_id == match.id)
            )
        }
        assert (lignes["ext"].tirs, lignes["ext"].tirs_cadres) == (None, None)
        # Le reste de la ligne est conservé, et le camp sain n'est pas touché.
        assert lignes["ext"].corners == 4
        assert (lignes["dom"].tirs, lignes["dom"].tirs_cadres) == (12, 4)

    def test_le_cas_est_nomme_dans_le_rapport(self, url_base):
        rapport = importer(url_base, dossier_source=ANOMALIES)
        assert len(rapport.anomalies) == 1
        assert "West Ham" in rapport.anomalies[0]
        assert "2122/E0" in rapport.anomalies[0]

    def test_les_fixtures_saines_n_en_produisent_aucune(self, url_base):
        assert importer(url_base).anomalies == []


class TestIdempotence:
    def test_deuxieme_passage_n_ecrit_rien(self, url_base, session_lecture):
        importer(url_base)
        rapport = importer(url_base)
        assert (rapport.matchs.inseres, rapport.matchs.majs) == (0, 0)
        assert rapport.matchs.inchanges == 26
        assert (rapport.stats.inseres, rapport.stats.majs) == (0, 0)
        assert rapport.stats.inchanges == 52
        assert rapport.rien_change
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 26

    def test_maj_le_ne_bouge_pas_sans_raison(self, url_base, session_lecture):
        importer(url_base)
        avant = dict(session_lecture.execute(select(Match.id, Match.maj_le)).all())
        importer(url_base)
        session_lecture.expire_all()
        apres = dict(session_lecture.execute(select(Match.id, Match.maj_le)).all())
        assert avant == apres

    def test_score_corrige_met_a_jour_sans_doubler(self, url_base, session_lecture):
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        identifiant = match.id
        match.buts_dom = 9
        session_lecture.commit()

        rapport = importer(url_base)
        session_lecture.expire_all()
        assert (rapport.matchs.inseres, rapport.matchs.majs) == (0, 1)
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 26
        assert session_lecture.get(Match, identifiant).buts_dom == 3

    def test_match_reporte_ne_cree_pas_de_doublon(self, url_base, session_lecture):
        """Ce que protège la clé logique de T03 : la date n'identifie pas le match."""
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        match.date_utc = datetime(2026, 12, 1, 19, 0)
        session_lecture.commit()

        rapport = importer(url_base)
        session_lecture.expire_all()
        assert (rapport.matchs.inseres, rapport.matchs.majs) == (0, 1)
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 26
        assert session_lecture.get(Match, match.id).date_utc == datetime(
            2026, 8, 21, 19, 0
        )

    def test_une_source_etrangere_n_est_pas_reetiquetee(
        self, url_base, session_lecture
    ):
        """T07 créera des matchs depuis API-Football ; T04 complète, ne renomme pas."""
        importer(url_base)
        match = session_lecture.scalars(
            select(Match).where(
                Match.saison == "2026-2027", Match.club_id_dom == "E0-arsenal"
            )
        ).one()
        match.source = "api-football"
        match.source_match_id = "1557367"
        match.buts_dom = None
        session_lecture.commit()

        importer(url_base)
        session_lecture.expire_all()
        rafraichi = session_lecture.get(Match, match.id)
        assert rafraichi.source == "api-football"
        assert rafraichi.source_match_id == "1557367"
        assert rafraichi.buts_dom == 3  # le score, lui, est bien complété


class TestRienNEstEcritSiQuelqueChoseNeVaPas:
    def test_dry_run_laisse_la_base_vide(self, url_base, session_lecture):
        rapport = importer(url_base, ecrire=False)
        assert rapport.matchs.inseres == 26
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 0

    def test_fichier_abime_refuse_en_bloc(self, url_base, session_lecture):
        with pytest.raises(TacheInterrompue, match="refusée"):
            importer(url_base, dossier_source=CASSE)
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 0
        assert session_lecture.scalar(select(func.count()).select_from(StatsMatch)) == 0

    def test_toutes_les_anomalies_sont_nommees(self, url_base):
        """Une relance par anomalie serait une perte de temps : on les voit d'un coup."""
        with pytest.raises(TacheInterrompue) as erreur:
            importer(url_base, dossier_source=CASSE)
        message = str(erreur.value)
        assert "Real Madrid" in message          # nom absent du référentiel
        assert "mi-temps" in message             # 3 buts à la pause pour 1 au final
        assert "date illisible" in message       # 32/13/2019
        assert "elle-même" in message            # Everton contre Everton
        assert "4 ligne(s) refusée(s)" in message

    def test_tolerer_importe_les_lignes_saines(self, url_base, session_lecture):
        rapport = importer(url_base, dossier_source=CASSE, tolerer=True)
        assert rapport.refusees == 4
        assert rapport.ignorees == 1  # la ligne vide de fin de fichier
        assert rapport.matchs.inseres == 1
        assert rapport.comptage_juste
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 1

    def test_base_sans_referentiel_refusee(self, tmp_path):
        """T04 suit T03 : sans ligues en base, rien à quoi rattacher un match."""
        url = f"sqlite:///{tmp_path / 'vide.db'}"
        with pytest.raises(TacheInterrompue, match="charger_referentiel"):
            importer(url)

    def test_ligue_inconnue_refusee(self, url_base):
        with pytest.raises(TacheInterrompue, match="XX"):
            importer(url_base, codes_ligues=["XX"])


class TestRienNEstSupprime:
    def test_match_absent_des_fichiers_conserve_et_signale(
        self, url_base, session_lecture
    ):
        importer(url_base)
        session_lecture.add(
            Match(
                code_fd="E0",
                saison="2026-2027",
                date_utc=datetime(2026, 9, 1, 14, 0),
                club_id_dom="E0-fulham",
                club_id_ext="E0-brentford",
                statut="prevu",
                source="api-football",
                source_match_id="9999",
            )
        )
        session_lecture.commit()

        rapport = importer(url_base)
        assert rapport.absents_des_fichiers == 1
        assert session_lecture.scalar(select(func.count()).select_from(Match)) == 27

    def test_saison_hors_perimetre_non_signalee(self, url_base):
        """Avec --saisons 2627, les autres saisons ne sont pas « absentes »."""
        importer(url_base)
        rapport = importer(url_base, saisons=["2627"])
        assert rapport.absents_des_fichiers == 0


class TestContraintesDuSchema:
    def test_mi_temps_superieure_au_score_refusee_par_la_base(self, session_lecture):
        from sqlalchemy.exc import IntegrityError

        session_lecture.add(
            Match(
                code_fd="E0",
                saison="2025-2026",
                date_utc=datetime(2025, 8, 15, 19, 0),
                club_id_dom="E0-arsenal",
                club_id_ext="E0-chelsea",
                statut="termine",
                buts_dom=1,
                buts_ext=0,
                mt_dom=3,
                mt_ext=0,
            )
        )
        with pytest.raises(IntegrityError):
            session_lecture.commit()

    def test_camp_inconnu_refuse_par_la_base(self, url_base, session_lecture):
        from sqlalchemy.exc import IntegrityError

        importer(url_base)
        match = session_lecture.scalars(select(Match).limit(1)).one()
        session_lecture.add(
            StatsMatch(match_id=match.id, club_id=match.club_id_dom, camp="neutre")
        )
        with pytest.raises(IntegrityError):
            session_lecture.commit()

    def test_tirs_cadres_superieurs_aux_tirs_refuses(self, url_base, session_lecture):
        from sqlalchemy.exc import IntegrityError

        importer(url_base)
        ligne = session_lecture.scalars(select(StatsMatch).limit(1)).one()
        ligne.tirs, ligne.tirs_cadres = 3, 9
        with pytest.raises(IntegrityError):
            session_lecture.commit()


class TestControlesDeCoherence:
    def test_saison_complete_sans_avertissement(self, url_base):
        """12 matchs pour 4 équipes : 4 × 3, chacune 3 fois à domicile."""
        rapport = importer(url_base, saisons=["2526"])
        assert rapport.avertissements == []

    def test_saison_en_cours_signalee_comme_telle(self, url_base):
        rapport = importer(url_base, saisons=["2627"])
        assert len(rapport.avertissements) == 1
        assert "saison en cours" in rapport.avertissements[0]

    def test_calendrier_tronque_signale(self):
        """Un fichier amputé doit se voir, comme la Ligue 1 arrêtée en 2019-20."""
        lignes = _lignes_factices(nombre_equipes=4)
        assert controles_coherence(lignes, "2627") == []
        assert controles_coherence(lignes[:-1], "2627") != []

    def test_desequilibre_domicile_exterieur_signale(self):
        lignes = _lignes_factices(nombre_equipes=4)
        # Le dernier match devient un doublon du premier : toujours 12 matchs
        # et 4 équipes, mais une affiche jouée deux fois et une jamais.
        from dataclasses import replace

        lignes[-1] = replace(
            lignes[-1],
            club_id_dom=lignes[0].club_id_dom,
            club_id_ext=lignes[0].club_id_ext,
        )
        avertissements = controles_coherence(lignes, "2627")
        assert avertissements and "domicile" in avertissements[0]


def _lignes_factices(nombre_equipes: int):
    """Une mini-saison complète : toutes les paires ordonnées, une fois chacune."""
    from ingestion.football_data import LigneMatch

    clubs = [f"E0-club{numero}" for numero in range(nombre_equipes)]
    lignes = []
    for dom in clubs:
        for ext in clubs:
            if dom == ext:
                continue
            lignes.append(
                LigneMatch(
                    code_fd="E0",
                    saison="2025-2026",
                    code_saison="2526",
                    date_utc=datetime(2025, 8, 15, 19, 0),
                    club_id_dom=dom,
                    club_id_ext=ext,
                    statut="termine",
                    buts_dom=1,
                    buts_ext=0,
                    mt_dom=0,
                    mt_ext=0,
                    arbitre=None,
                    source_match_id=identifiant_source("2526", "E0", dom, ext),
                    stats_dom={},
                    stats_ext={},
                )
            )
    return lignes


# ─────────────────────────────────────────────────────────────────────
# 3) Données réelles (hors Git : ignorées si absentes)
# ─────────────────────────────────────────────────────────────────────


@sans_donnees_reelles
class TestDonneesReelles:
    def test_tous_les_noms_se_resolvent(self, url_base):
        """Aucun nom de `data/raw/` ne manque à `clubs.nom_football_data`."""
        rapport = executer(
            RACINE, url=url_base, ecrire=False, aujourdhui=date(2026, 9, 24),
            sortie=lambda *_: None,
        )
        assert rapport.refusees == 0
        assert rapport.comptage_juste
        assert rapport.matchs.inseres == rapport.lues - rapport.ignorees

    def test_onze_saisons_cinq_ligues(self, url_base):
        rapport = executer(
            RACINE, url=url_base, ecrire=True, aujourdhui=date(2026, 9, 24),
            sortie=lambda *_: None,
        )
        machine = moteur(url_base)
        session = fabrique_sessions(machine)()
        try:
            saisons = set(session.scalars(select(Match.saison).distinct()))
            ligues = set(session.scalars(select(Match.code_fd).distinct()))
        finally:
            session.close()
            machine.dispose()
        assert len(saisons) == 11
        assert ligues == {"E0", "SP1", "I1", "D1", "F1"}
        assert rapport.matchs.inseres > 18_000

    def test_saisons_terminees_completes(self, url_base):
        """Critère d'ACCEPTATION.md : 380 ou 306 matchs, sauf la saison en cours."""
        rapport = executer(
            RACINE, url=url_base, ecrire=False, aujourdhui=date(2026, 9, 24),
            sortie=lambda *_: None,
        )
        inattendus = [
            avertissement
            for avertissement in rapport.avertissements
            # Saison en cours : incomplète par nature. Ligue 1 2019-20 : la
            # saison a réellement été arrêtée au 28ᵉ match par la pandémie.
            if "saison en cours" not in avertissement
            and not avertissement.startswith("1920/F1")
        ]
        assert inattendus == []

    @pytest.mark.skipif(
        not CALENDRIER_API.is_dir(), reason="calendrier API-Football de T00 absent"
    )
    def test_fuseau_confirme_par_api_football(self, url_base):
        """Preuve de la conversion : deux sources indépendantes, mêmes instants.

        Les coups d'envoi lus dans les CSV de la saison en cours doivent tomber
        à la seconde près sur les `date_utc` du calendrier API-Football, qui les
        publie déjà en UTC.
        """
        executer(
            RACINE, url=url_base, ecrire=True, saisons=["2627"],
            aujourdhui=date(2026, 9, 24), sortie=lambda *_: None,
        )
        attendus: dict[tuple[str, str, str], datetime] = {}
        for fichier in sorted(CALENDRIER_API.glob("*.csv")):
            if fichier.name == "manifest.csv":
                continue
            with fichier.open(encoding="utf-8", newline="") as flux:
                for ligne in csv.DictReader(flux):
                    attendus[
                        (ligne["code_fd"], ligne["club_id_dom"], ligne["club_id_ext"])
                    ] = datetime.strptime(ligne["date_utc"], "%Y-%m-%dT%H:%M:%SZ")

        machine = moteur(url_base)
        session = fabrique_sessions(machine)()
        try:
            matchs = session.execute(
                select(
                    Match.code_fd, Match.club_id_dom, Match.club_id_ext, Match.date_utc
                ).where(Match.saison == "2026-2027")
            ).all()
        finally:
            session.close()
            machine.dispose()

        compares = 0
        for code_fd, dom, ext, date_utc in matchs:
            attendu = attendus.get((code_fd, dom, ext))
            if attendu is None:
                continue
            assert date_utc == attendu, f"{code_fd} {dom}-{ext}"
            compares += 1
        assert compares >= 200
