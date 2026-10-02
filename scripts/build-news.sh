#!/usr/bin/env bash
# L6 — compile les Nouveautés (docs/nouveautes/*.md + captures) avec `cadence news build`
# dans jobmail/web/static/nouveautes-data/, servi par l'application sous /static/.
# Le résultat est VERSIONNÉ : l'application tourne sans cadence après un `git clone`.
# À relancer (puis commiter le dossier) après tout ajout ou modification d'une entrée ;
# tests/test_news_web.py échoue si le JSON versionné n'est plus à jour.
set -euo pipefail
cd "$(dirname "$0")/.."
out=jobmail/web/static/nouveautes-data
rm -rf "$out"
cadence news build -o "$out"
# cadence écrit aussi une page index.html autonome : doublon non habillé de /nouveautes.
rm -f "$out/index.html"
echo "Nouveautés compilées dans $out"
