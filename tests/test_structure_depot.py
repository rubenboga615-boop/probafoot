"""Forme du dépôt : arborescence, dépendances, secrets hors Git.

Ces contrôles tiennent le dépôt conforme à docs/ARCHITECTURE.md et à la règle 8
(aucune clé secrète dans le code ni dans Git). Ils ne touchent ni au réseau ni à
une base de données.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

PAQUETS = [
    "ingestion",
    "moteur",
    "backtest",
    "publication",
    "api",
    "api/routes",
    "jobs",
]

DOSSIERS = PAQUETS + [
    "tests",
    "front",
    "front/css",
    "front/js",
    "data/reference",
    "reports",
    "docs",
    "tests/fixtures",
]

# Motifs que .gitignore doit contenir, avec ce qu'ils protègent.
IGNORES_OBLIGATOIRES = {
    ".env": "les secrets",
    "data/raw/": "les données brutes téléchargées",
    ".venv/": "l'environnement Python",
    "__pycache__/": "les fichiers compilés",
}

# Fichiers dont l'ignorance doit être vérifiée par Git lui-même.
CHEMINS_IGNORES = [".env", ".env.local", "data/raw/exemple.json", "data/local.db"]


def _lignes(nom: str) -> list[str]:
    chemin = RACINE / nom
    assert chemin.exists(), f"{nom} manquant à la racine du dépôt"
    return [l.strip() for l in chemin.read_text(encoding="utf-8").splitlines()]


def _git(*args: str) -> str:
    """Sortie d'une commande git, ou saut du test hors dépôt Git."""
    if not (RACINE / ".git").exists():
        pytest.skip("hors dépôt Git")
    return subprocess.run(
        ["git", "-C", str(RACINE), *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


# --- Arborescence (docs/ARCHITECTURE.md) ---------------------------------


@pytest.mark.parametrize("dossier", DOSSIERS)
def test_dossier_present(dossier: str) -> None:
    assert (RACINE / dossier).is_dir(), f"{dossier}/ absent de l'arborescence"


@pytest.mark.parametrize("paquet", PAQUETS)
def test_paquet_importable(paquet: str) -> None:
    """Sans __init__.py, Git ne versionne pas le dossier et l'import échoue."""
    assert (RACINE / paquet / "__init__.py").exists(), f"{paquet}/__init__.py absent"


# --- Dépendances ---------------------------------------------------------


@pytest.mark.parametrize("fichier", ["requirements.txt", "requirements-dev.txt"])
def test_dependances_epinglees(fichier: str) -> None:
    """Une version flottante casserait la reproductibilité (règle 9)."""
    utiles = [
        l for l in _lignes(fichier) if l and not l.startswith(("#", "-r ", "--"))
    ]
    assert utiles, f"{fichier} ne déclare aucune dépendance"
    for ligne in utiles:
        assert re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[\w.\-]+", ligne), (
            f"{fichier} : « {ligne} » n'épingle pas une version exacte avec =="
        )


def test_requirements_dev_inclut_requirements() -> None:
    assert "-r requirements.txt" in _lignes("requirements-dev.txt")


# --- Secrets (règle 8) ---------------------------------------------------


@pytest.mark.parametrize("motif", sorted(IGNORES_OBLIGATOIRES))
def test_gitignore_contient(motif: str) -> None:
    assert motif in _lignes(".gitignore"), (
        f".gitignore doit ignorer {motif} ({IGNORES_OBLIGATOIRES[motif]})"
    )


@pytest.mark.parametrize("chemin", CHEMINS_IGNORES)
def test_git_ignore_reellement(chemin: str) -> None:
    """Vérifié par git lui-même, pas par une lecture du fichier."""
    assert _git("check-ignore", "--", chemin).strip() == chemin, (
        f"{chemin} n'est pas ignoré par Git"
    )


def test_env_example_versionne() -> None:
    assert ".env.example" in _git("ls-files").splitlines()


def test_aucun_fichier_env_suivi_par_git() -> None:
    suivis = [
        f
        for f in _git("ls-files").splitlines()
        if Path(f).name.startswith(".env") and Path(f).name != ".env.example"
    ]
    assert not suivis, f"fichiers de secrets suivis par Git : {suivis}"


def test_env_example_sans_valeur_secrete() -> None:
    for ligne in _lignes(".env.example"):
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        if cle.strip().endswith(("_KEY", "_SECRET", "_TOKEN", "_PASSWORD")):
            assert not valeur.strip(), f"{cle.strip()} porte une valeur dans .env.example"


def test_env_example_declare_toutes_les_variables_lues() -> None:
    """Une clé ajoutée au code et oubliée du modèle bloquerait le déploiement."""
    declarees = {
        l.partition("=")[0].strip()
        for l in _lignes(".env.example")
        if l and not l.startswith("#") and "=" in l
    }
    lues: set[str] = set()
    for source in sorted(RACINE.rglob("*.py")):
        if {".venv", "__pycache__", "tests"} & set(source.parts):
            continue
        texte = source.read_text(encoding="utf-8")
        lues |= set(re.findall(r"os\.environ(?:\.get)?\(\s*[\"']([A-Z0-9_]+)[\"']", texte))
        lues |= set(re.findall(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']", texte))

    manquantes = lues - declarees
    assert not manquantes, f"variables lues par le code mais absentes de .env.example : {manquantes}"
