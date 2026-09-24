#!/usr/bin/env python3
"""
Client API-Football et parseurs des réponses
============================================

API-Football (v3.football.api-sports.io) sert uniquement au calendrier, aux
statuts et aux scores des matchs (décision D04).

Une particularité du fournisseur, apprise sur l'ancien dépôt et qui gouverne ce
module : **il répond HTTP 200 sur une erreur applicative**, en plaçant le
détail dans le champ ``errors`` de l'enveloppe JSON. Un client qui se fie au
seul code HTTP prend une clé refusée pour un succès et enregistre une liste
vide. L'enveloppe est donc inspectée à chaque réponse.

Deuxième règle : ne réessayer que ce qui peut réussir. Un réessai sur quota
épuisé ou clé refusée ne réussira jamais, et certains plans décomptent aussi
les requêtes refusées.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://v3.football.api-sports.io"
TIMEOUT = 30
TENTATIVES = 3
ATTENTE_INITIALE = 2.0  # secondes, doublée à chaque réessai

MOTIFS_QUOTA = ("limit", "quota", "rate")
MOTIFS_AUTH = ("token", "key", "subscription", "authoriz", "authent")


class ApiFootballError(Exception):
    """Erreur de base du client."""


class CleManquanteError(ApiFootballError):
    """API_FOOTBALL_KEY absente de l'environnement et de .env."""


class AuthentificationError(ApiFootballError):
    """Clé refusée ou abonnement inactif : inutile de réessayer."""


class QuotaEpuiseError(ApiFootballError):
    """Quota atteint : inutile de réessayer aujourd'hui."""


class ReponseInattendueError(ApiFootballError):
    """Enveloppe illisible ou erreur applicative non classée."""


class TransitoireError(ApiFootballError):
    """Panne passagère : réessayable."""


def charger_env(chemin: Path | None = None) -> None:
    """Charge les variables de .env dans l'environnement, sans les écraser.

    Aucun secret n'est écrit dans le code ni dans Git (règle 8).
    """
    chemin = chemin or Path(__file__).resolve().parent.parent / ".env"
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        os.environ.setdefault(cle.strip(), valeur.strip())


def _classer_erreurs(erreurs: Any) -> ApiFootballError:
    """Traduit le champ ``errors`` de l'enveloppe en exception typée."""
    if isinstance(erreurs, dict):
        texte = " ".join(f"{k}: {v}" for k, v in erreurs.items())
    elif isinstance(erreurs, list):
        texte = " ".join(str(e) for e in erreurs)
    else:
        texte = str(erreurs)
    minuscule = texte.lower()
    if any(m in minuscule for m in MOTIFS_QUOTA):
        return QuotaEpuiseError(texte)
    if any(m in minuscule for m in MOTIFS_AUTH):
        return AuthentificationError(texte)
    return ReponseInattendueError(texte)


class ClientApiFootball:
    """Appels HTTP, inspection de l'enveloppe, pagination et comptage."""

    def __init__(self, cle: str | None = None, base_url: str = BASE_URL) -> None:
        if cle is None:
            charger_env()
            cle = os.environ.get("API_FOOTBALL_KEY", "").strip()
        if not cle:
            raise CleManquanteError(
                "API_FOOTBALL_KEY absente : renseigner .env (modèle : .env.example)"
            )
        self._cle = cle
        self.base_url = base_url.rstrip("/")
        self.requetes_emises = 0

    # -- appel unitaire ----------------------------------------------------
    def _appel_brut(self, chemin: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{chemin.lstrip('/')}"
        entetes = {"x-apisports-key": self._cle, "Accept": "application/json"}
        try:
            reponse = requests.get(url, headers=entetes, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise TransitoireError(f"réseau : {exc}") from exc

        self.requetes_emises += 1

        if reponse.status_code in (429,):
            raise QuotaEpuiseError(f"HTTP {reponse.status_code}")
        if reponse.status_code in (401, 403):
            raise AuthentificationError(f"HTTP {reponse.status_code}")
        if reponse.status_code >= 500:
            raise TransitoireError(f"HTTP {reponse.status_code}")
        if reponse.status_code != 200:
            raise ReponseInattendueError(f"HTTP {reponse.status_code}")

        try:
            enveloppe = reponse.json()
        except ValueError as exc:
            raise ReponseInattendueError("corps non JSON") from exc
        if not isinstance(enveloppe, dict):
            raise ReponseInattendueError("enveloppe inattendue")

        # HTTP 200 ne veut pas dire succès : le détail est dans `errors`.
        erreurs = enveloppe.get("errors")
        if erreurs:
            raise _classer_erreurs(erreurs)
        return enveloppe

    def appeler(self, chemin: str, **params: Any) -> dict[str, Any]:
        """Un appel, avec réessai des seules pannes passagères."""
        attente = ATTENTE_INITIALE
        derniere: TransitoireError | None = None
        for _ in range(TENTATIVES):
            try:
                return self._appel_brut(chemin, params)
            except TransitoireError as exc:
                derniere = exc
                time.sleep(attente)
                attente *= 2
        raise derniere if derniere else ReponseInattendueError("échec inconnu")

    def appeler_tout(self, chemin: str, **params: Any) -> list[Any]:
        """Un appel paginé : concatène les `response` de toutes les pages.

        Le paramètre `page` n'est ajouté qu'à partir de la deuxième page :
        certains endpoints (`/teams`) refusent un `page` explicite.
        """
        page = 1
        elements: list[Any] = []
        while True:
            supplement = {"page": page} if page > 1 else {}
            enveloppe = self.appeler(chemin, **params, **supplement)
            elements.extend(enveloppe.get("response") or [])
            paging = enveloppe.get("paging") or {}
            total = int(paging.get("total") or 1)
            if page >= total:
                return elements
            page += 1

    # -- quota -------------------------------------------------------------
    def quota(self) -> tuple[int, int]:
        """(requêtes déjà consommées aujourd'hui, plafond). `/status` est gratuit."""
        enveloppe = self.appeler("status")
        self.requetes_emises -= 1  # /status n'est pas décompté par le fournisseur
        requetes = (enveloppe.get("response") or {}).get("requests") or {}
        return int(requetes.get("current", 0)), int(requetes.get("limit_day", 0))

    def abonnement_actif(self) -> bool:
        enveloppe = self.appeler("status")
        self.requetes_emises -= 1
        abonnement = (enveloppe.get("response") or {}).get("subscription") or {}
        return bool(abonnement.get("active"))


# -- parseurs (purs, testables hors ligne) --------------------------------


def parser_equipes(reponse: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`/teams` → [{api_team_id, nom_api}], trié par nom."""
    equipes = []
    for element in reponse:
        equipe = element.get("team") or {}
        identifiant, nom = equipe.get("id"), equipe.get("name")
        if identifiant is None or not nom:
            raise ReponseInattendueError(f"équipe sans id ou sans nom : {element!r}")
        equipes.append({"api_team_id": int(identifiant), "nom_api": str(nom).strip()})
    return sorted(equipes, key=lambda e: e["nom_api"])


def _en_utc(date_iso: str) -> str:
    """Convertit la date d'un match en UTC (règle 11), format ISO en Z."""
    moment = datetime.fromisoformat(date_iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parser_matchs(reponse: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`/fixtures` → matchs normalisés, dates en UTC, trié par date puis id."""
    matchs = []
    for element in reponse:
        match = element.get("fixture") or {}
        ligue = element.get("league") or {}
        equipes = element.get("teams") or {}
        buts = element.get("goals") or {}
        score = element.get("score") or {}
        mi_temps = score.get("halftime") or {}
        lieu = match.get("venue") or {}
        statut = match.get("status") or {}

        identifiant = match.get("id")
        date_iso = match.get("date")
        dom = (equipes.get("home") or {}).get("id")
        ext = (equipes.get("away") or {}).get("id")
        if identifiant is None or not date_iso or dom is None or ext is None:
            raise ReponseInattendueError(f"match incomplet : {element!r}")

        matchs.append(
            {
                "fixture_id": int(identifiant),
                "saison": ligue.get("season"),
                "journee": ligue.get("round") or "",
                "date_utc": _en_utc(str(date_iso)),
                "statut_court": statut.get("short") or "",
                "api_team_id_dom": int(dom),
                "api_team_id_ext": int(ext),
                "buts_dom": buts.get("home"),
                "buts_ext": buts.get("away"),
                "mt_dom": mi_temps.get("home"),
                "mt_ext": mi_temps.get("away"),
                "stade": lieu.get("name") or "",
                "ville": lieu.get("city") or "",
            }
        )
    return sorted(matchs, key=lambda m: (m["date_utc"], m["fixture_id"]))
