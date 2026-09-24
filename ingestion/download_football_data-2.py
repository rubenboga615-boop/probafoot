#!/usr/bin/env python3
"""
Téléchargement des CSV historiques de football-data.co.uk
=========================================================

Récupère les statistiques de match des N dernières saisons pour les
5 grands championnats européens (Angleterre, Espagne, Italie, Allemagne, France).

Source  : https://www.football-data.co.uk/mmz4281/<SAISON>/<DIV>.csv
Sortie  : <out>/<SAISON>/<DIV>.csv  + un manifest.csv récapitulatif

Usage :
    python3 download_football_data.py                      # 10 saisons + saison en cours
    python3 download_football_data.py --seasons 15
    python3 download_football_data.py --leagues E0 SP1
    python3 download_football_data.py --dry-run            # liste les URL sans télécharger
    python3 download_football_data.py --force              # re-télécharge tout
    python3 download_football_data.py --out data/raw/football-data
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Module manquant : pip install requests")


BASE_URL = "https://football-data.co.uk/mmz4281"  # sans www : le www redirige en 302

# Codes division utilisés par football-data.co.uk
LEAGUES: dict[str, str] = {
    "E0": "Angleterre - Premier League",
    "SP1": "Espagne - La Liga",
    "I1": "Italie - Serie A",
    "D1": "Allemagne - Bundesliga",
    "F1": "France - Ligue 1",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}

TIMEOUT = 30
MAX_RETRIES = 5
PAUSE = 1.0  # secondes entre deux requêtes (on reste poli avec le serveur)


# --------------------------------------------------------------------------
# Calcul des saisons
# --------------------------------------------------------------------------
def season_code(start_year: int) -> str:
    """2025 -> '2526' (format football-data.co.uk)."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def current_season_start(today: date | None = None) -> int:
    """Année de début de la saison en cours. Une saison démarre en juillet."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def build_seasons(n: int, include_current: bool, today: date | None = None) -> list[str]:
    """
    Renvoie les codes des N dernières saisons TERMINÉES,
    plus la saison en cours si include_current.
    Ordre chronologique (la plus ancienne d'abord).
    """
    cur = current_season_start(today)
    starts = [cur - i for i in range(n, 0, -1)]  # n saisons terminées
    if include_current:
        starts.append(cur)
    return [season_code(y) for y in starts]


# --------------------------------------------------------------------------
# Téléchargement
# --------------------------------------------------------------------------
def looks_like_csv(content: bytes) -> bool:
    """Le serveur renvoie parfois une page HTML 404 avec un code 200."""
    head = content[:200].lstrip().lower()
    if head.startswith(b"<"):
        return False
    return head.startswith(b"div,") or b"hometeam" in content[:500].lower()


def fetch(session: requests.Session, url: str) -> bytes | None:
    """Télécharge une URL avec retries. Renvoie None si 404 ou échec définitif."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                print(f"      réseau KO ({exc.__class__.__name__})")
                return None
            time.sleep(2 * attempt)
            continue

        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.content
        if attempt == MAX_RETRIES:
            print(f"      HTTP {r.status_code}")
            return None
        time.sleep(2 * attempt)
    return None


def download_all(
    seasons: list[str],
    leagues: list[str],
    out_dir: Path,
    force: bool,
    dry_run: bool,
) -> list[dict]:
    manifest: list[dict] = []
    current = season_code(current_season_start())
    session = requests.Session()
    session.headers.update(HEADERS)

    for season in seasons:
        season_dir = out_dir / season
        print(f"\n=== Saison 20{season[:2]}/20{season[2:]} ===")

        for div in leagues:
            url = f"{BASE_URL}/{season}/{div}.csv"
            dest = season_dir / f"{div}.csv"
            label = LEAGUES.get(div, div)

            if dry_run:
                print(f"  [dry-run] {div:4s} {url}")
                manifest.append(
                    {"saison": season, "division": div, "championnat": label,
                     "statut": "dry-run", "lignes": 0, "octets": 0, "url": url}
                )
                continue

            # La saison en cours évolue : on la rafraîchit toujours.
            if dest.exists() and not force and season != current:
                rows = max(sum(1 for _ in dest.open("rb")) - 1, 0)
                print(f"  {div:4s} déjà présent ({rows} matchs) — ignoré")
                manifest.append(
                    {"saison": season, "division": div, "championnat": label,
                     "statut": "cache", "lignes": rows,
                     "octets": dest.stat().st_size, "url": url}
                )
                continue

            print(f"  {div:4s} {label} …", end=" ", flush=True)
            content = fetch(session, url)
            time.sleep(PAUSE)

            if content is None:
                print("indisponible")
                manifest.append(
                    {"saison": season, "division": div, "championnat": label,
                     "statut": "absent", "lignes": 0, "octets": 0, "url": url}
                )
                continue

            if not looks_like_csv(content):
                print("réponse invalide (HTML ?)")
                manifest.append(
                    {"saison": season, "division": div, "championnat": label,
                     "statut": "invalide", "lignes": 0,
                     "octets": len(content), "url": url}
                )
                continue

            season_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            rows = max(content.count(b"\n") - 1, 0)
            print(f"OK ({rows} matchs, {len(content) // 1024} Ko)")
            manifest.append(
                {"saison": season, "division": div, "championnat": label,
                 "statut": "telecharge", "lignes": rows,
                 "octets": len(content), "url": url}
            )

    return manifest


def write_manifest(manifest: list[dict], out_dir: Path) -> Path:
    path = out_dir / "manifest.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["saison", "division", "championnat", "statut",
                        "lignes", "octets", "url"],
        )
        w.writeheader()
        w.writerows(manifest)
    return path


# --------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description="Télécharge les CSV historiques de football-data.co.uk"
    )
    p.add_argument("--seasons", type=int, default=10,
                   help="nombre de saisons terminées à récupérer (défaut : 10)")
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES),
                   metavar="DIV",
                   help=f"codes division (défaut : {' '.join(LEAGUES)})")
    p.add_argument("--out", type=Path, default=Path("data/raw/football-data"),
                   help="dossier de sortie (défaut : data/raw/football-data)")
    p.add_argument("--no-current", action="store_true",
                   help="ne pas inclure la saison en cours")
    p.add_argument("--force", action="store_true",
                   help="re-télécharger même si le fichier existe déjà")
    p.add_argument("--dry-run", action="store_true",
                   help="afficher les URL sans rien télécharger")
    args = p.parse_args()

    unknown = [d for d in args.leagues if d not in LEAGUES]
    if unknown:
        print(f"Codes division inconnus : {', '.join(unknown)}")
        print(f"Codes disponibles : {', '.join(LEAGUES)}")
        return 2

    seasons = build_seasons(args.seasons, include_current=not args.no_current)

    print(f"Championnats : {', '.join(args.leagues)}")
    print(f"Saisons ({len(seasons)}) : {seasons[0]} → {seasons[-1]}")
    print(f"Destination  : {args.out.resolve()}")

    manifest = download_all(
        seasons, args.leagues, args.out, args.force, args.dry_run
    )

    if args.dry_run:
        print(f"\n{len(manifest)} fichiers seraient téléchargés.")
        return 0

    ok = sum(1 for m in manifest if m["statut"] == "telecharge")
    cached = sum(1 for m in manifest if m["statut"] == "cache")
    ko = [m for m in manifest if m["statut"] in ("absent", "invalide")]
    matchs = sum(m["lignes"] for m in manifest)

    path = write_manifest(manifest, args.out)
    print("\n" + "=" * 46)
    print(f"Téléchargés : {ok}   |   déjà en cache : {cached}   |   échecs : {len(ko)}")
    print(f"Total matchs disponibles : {matchs}")
    print(f"Manifest : {path}")
    for m in ko:
        print(f"  ! {m['saison']} {m['division']} : {m['statut']}")
    return 1 if ok == 0 and cached == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
