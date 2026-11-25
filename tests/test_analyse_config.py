"""L23 : l'analyse statique déclarée à cadence (`analyse:` de cadence.yaml) et la parité CI / porte.

Ce que le test garde :
- ruff est déclaré au format `ruff-json`, avec un fichier de seuils à lui (`ruff-analyse.toml`)
  nommé dans la commande ET dans `configs:` (la doc de cadence interdit d'y mettre pyproject.toml :
  tout ajout de dépendance serait refusé) ;
- les seuils sont ceux de cadence : C901 à 15, PLR0913 à 5 arguments, PLR0912 / PLR0915 actifs ;
- la base figée existe (`.cadence/analyse/ruff.json`) ;
- la CI joue exactement les commandes de la porte (orchestrate.test et le ruff de orchestrate.build).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _cadence() -> dict:
    return yaml.safe_load((ROOT / "cadence.yaml").read_text(encoding="utf-8"))


def _ruff_entry() -> dict:
    entries = _cadence().get("analyse") or []
    found = [e for e in entries if e.get("name") == "ruff"]
    assert len(found) == 1, f"une entrée ruff attendue dans analyse:, trouvé {entries!r}"
    return found[0]


def test_ruff_declared_with_its_own_config_file():
    entry = _ruff_entry()
    assert entry["format"] == "ruff-json"
    assert entry["configs"] == ["ruff-analyse.toml"]
    assert "pyproject.toml" not in entry["configs"]
    command = entry["command"]
    assert "--config ruff-analyse.toml" in command
    assert "--output-format json" in command
    assert "--exit-zero" in command
    assert (ROOT / "ruff-analyse.toml").is_file()


def test_ruff_thresholds_are_cadence_ones():
    conf = tomllib.loads((ROOT / "ruff-analyse.toml").read_text(encoding="utf-8"))
    lint = conf["lint"]
    for code in ("C901", "PLR0912", "PLR0913", "PLR0915"):
        assert code in lint["select"], code
    # Les règles du lint ordinaire (pyproject) restent mesurées aussi.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for code in pyproject["tool"]["ruff"]["lint"]["select"]:
        assert code in lint["select"], code
    assert lint["mccabe"]["max-complexity"] == 15
    assert lint["pylint"]["max-args"] == 5
    # PLR0912 / PLR0915 à leur défaut : aucun seuil réécrit.
    assert "max-branches" not in lint["pylint"]
    assert "max-statements" not in lint["pylint"]


def test_ruff_baseline_is_frozen():
    baseline = ROOT / ".cadence" / "analyse" / "ruff.json"
    assert baseline.is_file()
    json.loads(baseline.read_text(encoding="utf-8"))


def _ci_run_steps() -> list[str]:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return [step["run"].strip() for step in ci["jobs"]["test"]["steps"] if "run" in step]


def test_ci_plays_the_gate_commands():
    orch = _cadence()["orchestrate"]
    runs = _ci_run_steps()
    assert orch["test"] in runs, f"la CI doit jouer {orch['test']!r}, elle joue {runs!r}"
    ruff_gate = orch["build"].split("&&")[0].strip()
    assert ruff_gate in runs, f"la CI doit jouer {ruff_gate!r}, elle joue {runs!r}"
    # Plus de commande de test ou de lint que la porte ne jouerait pas.
    assert "pytest -q" not in runs
    assert "ruff check ." not in runs
