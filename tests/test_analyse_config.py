"""L23 : l'analyse statique déclarée à cadence (`analyse:` de cadence.yaml) et la parité CI / porte.

Ce que le test garde :
- ruff est déclaré au format `ruff-json`, avec un fichier de seuils à lui (`ruff-analyse.toml`)
  nommé dans la commande ET dans `configs:` (la doc de cadence interdit d'y mettre pyproject.toml :
  tout ajout de dépendance serait refusé) ;
- les seuils sont ceux de cadence : C901 à 15, PLR0913 à 5 arguments, PLR0912 / PLR0915 actifs ;
- la base figée existe (`.cadence/analyse/ruff.json`) ;
- la CI joue exactement les commandes de la porte (orchestrate.test et le ruff de orchestrate.build) ;
- L24 : ESLint et vue-tsc déclarés pour frontend/ (`dir: frontend`), outils en devDependencies, seuils de
  taille de cadence effectifs sur un .ts et un .vue (`eslint --print-config`, sauté sans node_modules).
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


# --- L24 : le frontend Vue/TS (ESLint aux seuils de cadence, vue-tsc), existant figé ---------------

FRONTEND = ROOT / "frontend"
ESLINT_THRESHOLDS = {
    "max-lines": 400,
    "max-lines-per-function": 80,
    "max-depth": 4,
    "max-params": 5,
    "complexity": 15,
    "sonarjs/cognitive-complexity": 15,
}


def _entry(name: str) -> dict:
    entries = _cadence().get("analyse") or []
    assert isinstance(entries, list), "analyse: est une liste directe (pas de sous-clé tools:)"
    found = [e for e in entries if e.get("name") == name]
    assert len(found) == 1, f"une entrée {name} attendue dans analyse:, trouvé {entries!r}"
    return found[0]


def test_frontend_tools_declared_in_frontend_dir():
    eslint = _entry("eslint")
    assert eslint["dir"] == "frontend"
    assert eslint["format"] == "eslint-json"
    assert eslint["configs"] == ["frontend/eslint.config.mjs"]
    assert "-f json" in eslint["command"]
    assert (FRONTEND / "eslint.config.mjs").is_file()

    vue_tsc = _entry("vue-tsc")
    assert vue_tsc["dir"] == "frontend"
    assert vue_tsc["format"] == "tsc"
    assert "vue-tsc --noEmit --pretty false" in vue_tsc["command"]
    for entry in (eslint, vue_tsc):
        # Un manifeste de dépendances ne va jamais dans configs (doc de cadence, analyse.md).
        assert not any(c.endswith("package.json") for c in entry.get("configs", [])), entry


def test_frontend_lint_dependencies_are_dev_only():
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    dev = pkg.get("devDependencies", {})
    for name in ("eslint", "typescript-eslint", "eslint-plugin-vue", "eslint-plugin-sonarjs"):
        assert name in dev, name
        assert name not in pkg.get("dependencies", {}), name


def _resolved_rules(file: str) -> dict:
    """Règles effectives d'ESLint pour un fichier (sauté sans node_modules : la CI n'installe pas le frontend)."""
    import shutil
    import subprocess

    import pytest

    eslint = FRONTEND / "node_modules" / ".bin" / "eslint"
    if not eslint.exists() or shutil.which("node") is None:
        pytest.skip("frontend/node_modules absent : npm --prefix frontend ci")
    out = subprocess.run(
        [str(eslint), "--print-config", file],
        cwd=FRONTEND, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["rules"]


def _max_option(rule) -> object:
    option = rule[1] if isinstance(rule, list) and len(rule) > 1 else None
    return option.get("max") if isinstance(option, dict) else option


def test_eslint_thresholds_are_cadence_ones_for_ts_and_vue():
    for file in ("src/cleaner/cleaner-core.ts", "src/cleaner/CleanerApp.vue"):
        rules = _resolved_rules(file)
        for name, expected in ESLINT_THRESHOLDS.items():
            assert name in rules, f"{name} absent pour {file}"
            level = rules[name][0] if isinstance(rules[name], list) else rules[name]
            assert level not in (0, "off"), f"{name} éteint pour {file}"
            assert _max_option(rules[name]) == expected, f"{name} pour {file} : {rules[name]!r}"


def test_frontend_baselines_are_frozen():
    for name in ("eslint", "vue-tsc"):
        baseline = ROOT / ".cadence" / "analyse" / f"{name}.json"
        assert baseline.is_file(), baseline
        json.loads(baseline.read_text(encoding="utf-8"))
