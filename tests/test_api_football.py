"""Client API-Football et parseurs — aucun appel réseau réel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from ingestion import api_football
from ingestion.api_football import (
    AuthentificationError,
    ClientApiFootball,
    QuotaEpuiseError,
    ReponseInattendueError,
    TransitoireError,
    charger_env,
    parser_equipes,
    parser_matchs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "api_football"


def _charger(nom: str):
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


class FausseReponse:
    def __init__(self, corps, status_code: int = 200) -> None:
        self._corps = corps
        self.status_code = status_code

    def json(self):
        if isinstance(self._corps, str):
            raise ValueError("corps non JSON")
        return self._corps


@pytest.fixture
def client() -> ClientApiFootball:
    return ClientApiFootball(cle="cle-de-test")


@pytest.fixture(autouse=True)
def _pas_d_attente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les réessais ne doivent pas ralentir la suite de tests."""
    monkeypatch.setattr(api_football.time, "sleep", lambda _: None)


def _repondre(monkeypatch: pytest.MonkeyPatch, reponses: list) -> list[dict]:
    """Remplace requests.get ; retourne la liste des appels observés."""
    appels: list[dict] = []
    file = list(reponses)

    def faux_get(url, headers=None, params=None, timeout=None):
        appels.append({"url": url, "params": dict(params or {})})
        suivante = file.pop(0)
        if isinstance(suivante, Exception):
            raise suivante
        return suivante

    monkeypatch.setattr(api_football.requests, "get", faux_get)
    return appels


# -- enveloppe -------------------------------------------------------------


def test_erreur_applicative_malgre_un_http_200(client, monkeypatch) -> None:
    """Le fournisseur répond 200 sur une clé refusée : l'enveloppe fait foi."""
    _repondre(monkeypatch, [FausseReponse(_charger("erreur_token.json"))])

    with pytest.raises(AuthentificationError):
        client.appeler("teams", league=39, season=2026)


def test_quota_epuise_signale_dans_l_enveloppe(client, monkeypatch) -> None:
    corps = {"errors": {"rateLimit": "Too many requests"}, "response": []}
    _repondre(monkeypatch, [FausseReponse(corps)])

    with pytest.raises(QuotaEpuiseError):
        client.appeler("teams", league=39)


def test_pas_de_reessai_sur_quota_ou_authentification(client, monkeypatch) -> None:
    """Un réessai sur quota épuisé ne réussira jamais et peut être décompté."""
    appels = _repondre(monkeypatch, [FausseReponse({}, status_code=429)])

    with pytest.raises(QuotaEpuiseError):
        client.appeler("teams", league=39)

    assert len(appels) == 1


def test_reessai_des_seules_pannes_passageres(client, monkeypatch) -> None:
    appels = _repondre(
        monkeypatch,
        [
            FausseReponse({}, status_code=503),
            requests.RequestException("coupure"),
            FausseReponse({"errors": [], "response": [1], "paging": {"current": 1, "total": 1}}),
        ],
    )

    enveloppe = client.appeler("teams", league=39)

    assert enveloppe["response"] == [1]
    assert len(appels) == 3


def test_abandon_apres_trois_pannes(client, monkeypatch) -> None:
    _repondre(monkeypatch, [FausseReponse({}, status_code=502)] * 3)

    with pytest.raises(TransitoireError):
        client.appeler("teams", league=39)


def test_corps_non_json(client, monkeypatch) -> None:
    _repondre(monkeypatch, [FausseReponse("<html>", status_code=200)])

    with pytest.raises(ReponseInattendueError):
        client.appeler("teams", league=39)


# -- pagination ------------------------------------------------------------


def test_pagination_concatenee(client, monkeypatch) -> None:
    appels = _repondre(
        monkeypatch,
        [
            FausseReponse({"errors": [], "response": ["a"], "paging": {"current": 1, "total": 2}}),
            FausseReponse({"errors": [], "response": ["b"], "paging": {"current": 2, "total": 2}}),
        ],
    )

    assert client.appeler_tout("fixtures", league=39) == ["a", "b"]
    # `/teams` refuse un `page` explicite : il n'apparaît qu'à partir de la 2e page.
    assert "page" not in appels[0]["params"]
    assert appels[1]["params"]["page"] == 2


def test_quota_ne_compte_pas_les_appels_status(client, monkeypatch) -> None:
    _repondre(monkeypatch, [FausseReponse(_charger("status.json"))])

    assert client.quota() == (4970, 7500)
    assert client.requetes_emises == 0


# -- clé ------------------------------------------------------------------


def test_cle_manquante(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    monkeypatch.setattr(api_football, "charger_env", lambda: None)

    with pytest.raises(api_football.CleManquanteError):
        ClientApiFootball()


def test_charger_env_n_ecrase_pas_l_environnement(monkeypatch, tmp_path) -> None:
    fichier = tmp_path / ".env"
    fichier.write_text("# commentaire\nAPI_FOOTBALL_KEY=depuis-le-fichier\nVIDE\n", encoding="utf-8")
    monkeypatch.setenv("API_FOOTBALL_KEY", "deja-en-place")

    charger_env(fichier)

    assert api_football.os.environ["API_FOOTBALL_KEY"] == "deja-en-place"


# -- parseurs --------------------------------------------------------------


def test_parser_equipes() -> None:
    equipes = parser_equipes(_charger("teams_extrait.json"))

    assert equipes == [
        {"api_team_id": 157, "nom_api": "Bayern München"},
        {"api_team_id": 165, "nom_api": "Borussia Dortmund"},
    ]


def test_parser_equipes_refuse_une_equipe_sans_id() -> None:
    with pytest.raises(ReponseInattendueError):
        parser_equipes([{"team": {"name": "Sans identifiant"}}])


def test_parser_matchs_convertit_en_utc() -> None:
    matchs = parser_matchs(_charger("fixtures_extrait.json"))

    assert [m["date_utc"] for m in matchs] == [
        "2026-08-21T18:30:00Z",  # 20:30+02:00 dans la réponse brute
        "2026-08-22T13:30:00Z",
    ]
    assert matchs[0]["fixture_id"] == 1390331
    assert matchs[0]["api_team_id_dom"] == 157
    assert matchs[0]["statut_court"] == "NS"
    assert matchs[0]["buts_dom"] is None
    assert matchs[1]["buts_dom"] == 2 and matchs[1]["mt_ext"] == 1


def test_parser_matchs_trie_par_date() -> None:
    matchs = parser_matchs(list(reversed(_charger("fixtures_extrait.json"))))

    assert [m["date_utc"] for m in matchs] == sorted(m["date_utc"] for m in matchs)


def test_parser_matchs_refuse_un_match_incomplet() -> None:
    with pytest.raises(ReponseInattendueError):
        parser_matchs([{"fixture": {"id": 1}, "teams": {}}])
