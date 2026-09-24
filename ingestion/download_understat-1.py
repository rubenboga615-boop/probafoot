#!/usr/bin/env python3
"""
Téléchargement des données xG de understat.com  (v2 — endpoint JSON)
====================================================================

Understat a déplacé ses données du HTML vers un endpoint AJAX :
    https://understat.com/getLeagueData/<LIGUE>/<ANNEE>
qui renvoie directement du JSON (gzip/deflate, décompressé par requests).

Deux fichiers par championnat/saison :
  matches.csv       — un match par ligne (xG domicile/extérieur)
  team_matches.csv  — une ligne par équipe et par match (xG, npxG, PPDA, deep, xPTS)

Usage :
    python3 download_understat.py --inspect          # voir la structure brute
    python3 download_understat.py --dry-run
    python3 download_understat.py                    # 10 saisons + saison en cours
    python3 download_understat.py --resume           # ne retente que ce qui manque
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Module manquant : pip install requests")


BASE_URL = "https://understat.com/getLeagueData"

LEAGUES: dict[str, tuple[str, str]] = {
    "EPL": ("Angleterre - Premier League", "E0"),
    "La_liga": ("Espagne - La Liga", "SP1"),
    "Serie_A": ("Italie - Serie A", "I1"),
    "Bundesliga": ("Allemagne - Bundesliga", "D1"),
    "Ligue_1": ("France - Ligue 1", "F1"),
}

FIRST_SEASON = 2014

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Encoding": "gzip, deflate",
}

TIMEOUT = 60
MAX_RETRIES = 5       # réseau instable : on insiste
RETRY_DELAY = 2
PAUSE = 2.0


# --------------------------------------------------------------------------
def current_season_start(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def build_seasons(n: int, include_current: bool, today: date | None = None) -> list[int]:
    cur = current_season_start(today)
    years = [cur - i for i in range(n, 0, -1)]
    if include_current:
        years.append(cur)
    return [y for y in years if y >= FIRST_SEASON]


def season_label(year: int) -> str:
    return f"{year}/{(year + 1) % 100:02d}"


# --------------------------------------------------------------------------
def fetch_json(session: requests.Session, url: str, referer: str):
    """GET avec retries. Renvoie (data, erreur)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, headers={"Referer": referer})
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                return None, f"reseau:{exc.__class__.__name__}"
            time.sleep(RETRY_DELAY * attempt)
            continue

        if r.status_code == 404:
            return None, "404"
        if r.status_code == 200:
            try:
                return r.json(), None
            except ValueError:
                head = r.text[:60].replace("\n", " ")
                return None, f"json_invalide:{head!r}"
        if attempt == MAX_RETRIES:
            return None, f"http_{r.status_code}"
        time.sleep(RETRY_DELAY * attempt)
    return None, "echec"


# --------------------------------------------------------------------------
# Détection des clés : Understat a déjà renommé une fois, on ne code pas en dur
# --------------------------------------------------------------------------
def find_teams(data):
    """Dict {id: {..., 'history': [...]}} — quel que soit le nom de la clé."""
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, dict) and value:
            first = next(iter(value.values()), None)
            if isinstance(first, dict) and "history" in first:
                return value
    return None


def find_matches(data):
    """Liste de matchs : chaque entrée a une équipe 'h' et une équipe 'a'."""
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and "h" in first and "a" in first:
                return value
    return None


# --------------------------------------------------------------------------
MATCH_FIELDS = [
    "match_id", "date", "is_result", "home_team", "away_team",
    "home_goals", "away_goals", "home_xg", "away_xg",
    "forecast_w", "forecast_d", "forecast_l", "source",
]


def _team_name(node):
    if isinstance(node, dict):
        return node.get("title") or node.get("short_title")
    return node


def flatten_matches(matches: list) -> list[dict]:
    rows = []
    for m in matches:
        fc = m.get("forecast") or {}
        goals = m.get("goals") or {}
        xg = m.get("xG") or {}
        rows.append({
            "match_id": m.get("id"),
            "date": m.get("datetime") or m.get("date"),
            "is_result": m.get("isResult"),
            "home_team": _team_name(m.get("h")),
            "away_team": _team_name(m.get("a")),
            "home_goals": goals.get("h"),
            "away_goals": goals.get("a"),
            "home_xg": xg.get("h"),
            "away_xg": xg.get("a"),
            "forecast_w": fc.get("w"),
            "forecast_d": fc.get("d"),
            "forecast_l": fc.get("l"),
            "source": "endpoint",
        })
    return rows


def matches_from_teams(team_rows: list[dict]) -> list[dict]:
    """
    Repli si l'endpoint ne renvoie pas la liste des matchs : on reconstruit
    les affiches en appariant, pour chaque horodatage, l'équipe à domicile
    et l'équipe à l'extérieur. Les dates Understat sont des heures de coup
    d'envoi exactes, l'appariement est donc fiable.
    """
    par_date: dict[str, dict[str, dict]] = {}
    for r in team_rows:
        par_date.setdefault(str(r["date"]), {})[r["h_a"]] = r

    rows = []
    for d, cote in sorted(par_date.items()):
        dom, ext = cote.get("h"), cote.get("a")
        if not dom or not ext:
            continue
        rows.append({
            "match_id": None,
            "date": d,
            "is_result": True,
            "home_team": dom["team"],
            "away_team": ext["team"],
            "home_goals": dom["scored"],
            "away_goals": dom["missed"],
            "home_xg": dom["xG"],
            "away_xg": dom["xGA"],
            "forecast_w": None, "forecast_d": None, "forecast_l": None,
            "source": "reconstruit",
        })
    return rows


TEAM_FIELDS = [
    "team_id", "team", "date", "h_a", "result",
    "scored", "missed", "xG", "xGA", "npxG", "npxGA", "npxGD",
    "ppda_att", "ppda_def", "ppda_allowed_att", "ppda_allowed_def",
    "deep", "deep_allowed", "xpts", "pts", "wins", "draws", "loses",
]


def flatten_team_matches(teams: dict) -> list[dict]:
    rows = []
    for team in teams.values():
        title, tid = team.get("title"), team.get("id")
        for h in team.get("history", []):
            ppda = h.get("ppda") or {}
            ppda_a = h.get("ppda_allowed") or {}
            rows.append({
                "team_id": tid, "team": title,
                "date": h.get("date"), "h_a": h.get("h_a"),
                "result": h.get("result"),
                "scored": h.get("scored"), "missed": h.get("missed"),
                "xG": h.get("xG"), "xGA": h.get("xGA"),
                "npxG": h.get("npxG"), "npxGA": h.get("npxGA"),
                "npxGD": h.get("npxGD"),
                "ppda_att": ppda.get("att"), "ppda_def": ppda.get("def"),
                "ppda_allowed_att": ppda_a.get("att"),
                "ppda_allowed_def": ppda_a.get("def"),
                "deep": h.get("deep"), "deep_allowed": h.get("deep_allowed"),
                "xpts": h.get("xpts"), "pts": h.get("pts"),
                "wins": h.get("wins"), "draws": h.get("draws"),
                "loses": h.get("loses"),
            })
    rows.sort(key=lambda r: (str(r["date"]), str(r["team"])))
    return rows


def write_csv(rows: list[dict], fields: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------
def inspect(session: requests.Session, slug: str, year: int) -> int:
    url = f"{BASE_URL}/{slug}/{year}"
    ref = f"https://understat.com/league/{slug}/{year}"
    print(f"GET {url}")
    data, err = fetch_json(session, url, ref)
    if err:
        print(f"Échec : {err}")
        return 1

    print(f"\nClés de premier niveau : {list(data)}")
    for k, v in data.items():
        kind = type(v).__name__
        taille = len(v) if isinstance(v, (list, dict)) else "-"
        print(f"  {k:20s} {kind:6s} {taille}")
        sample = None
        if isinstance(v, list) and v:
            sample = v[0]
        elif isinstance(v, dict) and v:
            sample = next(iter(v.values()))
        if isinstance(sample, dict):
            print(f"      champs : {list(sample)[:14]}")

    print(f"\nDétection — équipes : {'OK' if find_teams(data) else 'NON'}"
          f"   |   matchs : {'OK' if find_matches(data) else 'NON'}")
    Path("/tmp/understat_sample.json").write_text(
        json.dumps(data, ensure_ascii=False)[:4000], encoding="utf-8"
    )
    print("Extrait écrit dans /tmp/understat_sample.json")
    return 0


# --------------------------------------------------------------------------
def download_all(seasons, leagues, out_dir: Path, force, dry_run, resume) -> list[dict]:
    manifest: list[dict] = []
    current = current_season_start()
    session = requests.Session()
    session.headers.update(HEADERS)

    for year in seasons:
        print(f"\n=== Saison {season_label(year)} ===")
        for slug in leagues:
            label, fd_code = LEAGUES[slug]
            url = f"{BASE_URL}/{slug}/{year}"
            ref = f"https://understat.com/league/{slug}/{year}"
            dest_dir = out_dir / str(year) / slug
            matches_csv = dest_dir / "matches.csv"

            entry = {"saison": year, "ligue": slug, "championnat": label,
                     "code_football_data": fd_code, "statut": "", "matchs": 0,
                     "lignes_equipes": 0, "origine_matchs": "", "url": url}

            if dry_run:
                print(f"  [dry-run] {slug:12s} {url}")
                entry["statut"] = "dry-run"
                manifest.append(entry)
                continue

            deja = matches_csv.exists()
            if deja and not force and (resume or year != current):
                n = max(sum(1 for _ in matches_csv.open("rb")) - 1, 0)
                print(f"  {slug:12s} déjà présent ({n} matchs) — ignoré")
                entry.update(statut="cache", matchs=n)
                manifest.append(entry)
                continue

            print(f"  {slug:12s} {label} …", end=" ", flush=True)
            data, err = fetch_json(session, url, ref)
            time.sleep(PAUSE)

            if err:
                print(err)
                entry["statut"] = err.split(":")[0]
                manifest.append(entry)
                continue

            teams = find_teams(data)
            if not teams:
                print(f"structure inattendue (clés : {list(data)[:6]})")
                entry["statut"] = "parse_ko"
                manifest.append(entry)
                continue

            team_rows = flatten_team_matches(teams)
            write_csv(team_rows, TEAM_FIELDS, dest_dir / "team_matches.csv")

            brut = find_matches(data)
            if brut:
                matches, origine = flatten_matches(brut), "endpoint"
            else:
                matches, origine = matches_from_teams(team_rows), "reconstruit"
            write_csv(matches, MATCH_FIELDS, matches_csv)

            noms = sorted({r["team"] for r in team_rows if r["team"]})
            (dest_dir / "teams.txt").write_text("\n".join(noms) + "\n", encoding="utf-8")

            print(f"OK ({len(matches)} matchs [{origine}], "
                  f"{len(team_rows)} lignes équipes, {len(noms)} équipes)")
            entry.update(statut="telecharge", matchs=len(matches),
                         lignes_equipes=len(team_rows), origine_matchs=origine)
            manifest.append(entry)

    return manifest


def write_manifest(manifest: list[dict], out_dir: Path) -> Path:
    path = out_dir / "manifest.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]) if manifest else ["saison"])
        w.writeheader()
        w.writerows(manifest)
    return path


def main() -> int:
    p = argparse.ArgumentParser(description="Télécharge les données xG de understat.com")
    p.add_argument("--seasons", type=int, default=10)
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), metavar="LIGUE")
    p.add_argument("--out", type=Path, default=Path("data/raw/understat"))
    p.add_argument("--no-current", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="re-télécharger même si le fichier existe")
    p.add_argument("--resume", action="store_true",
                   help="ne retenter que les fichiers manquants (réseau instable)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--inspect", action="store_true",
                   help="afficher la structure JSON renvoyée et sortir")
    args = p.parse_args()

    unknown = [l for l in args.leagues if l not in LEAGUES]
    if unknown:
        print(f"Ligues inconnues : {', '.join(unknown)}")
        print(f"Disponibles : {', '.join(LEAGUES)}")
        return 2

    if args.inspect:
        s = requests.Session()
        s.headers.update(HEADERS)
        return inspect(s, args.leagues[0], current_season_start())

    seasons = build_seasons(args.seasons, include_current=not args.no_current)
    if not seasons:
        print(f"Aucune saison valide (Understat commence en {FIRST_SEASON}/15).")
        return 2

    print(f"Championnats : {', '.join(args.leagues)}")
    print(f"Saisons ({len(seasons)}) : "
          f"{season_label(seasons[0])} → {season_label(seasons[-1])}")
    print(f"Destination  : {args.out.resolve()}")

    manifest = download_all(seasons, args.leagues, args.out,
                            args.force, args.dry_run, args.resume)

    if args.dry_run:
        print(f"\n{len(manifest)} requêtes seraient envoyées.")
        return 0

    ok = sum(1 for m in manifest if m["statut"] == "telecharge")
    cached = sum(1 for m in manifest if m["statut"] == "cache")
    ko = [m for m in manifest if m["statut"] not in ("telecharge", "cache")]
    total = sum(m["matchs"] for m in manifest)

    path = write_manifest(manifest, args.out)
    print("\n" + "=" * 52)
    print(f"Téléchargés : {ok}   |   en cache : {cached}   |   échecs : {len(ko)}")
    print(f"Total matchs : {total}")
    print(f"Manifest : {path}")
    for m in ko:
        print(f"  ! {m['saison']} {m['ligue']} : {m['statut']}")
    if ko:
        print("\nRelance avec --resume pour ne retenter que ces fichiers.")
    return 0 if (ok or cached) else 1


if __name__ == "__main__":
    raise SystemExit(main())
