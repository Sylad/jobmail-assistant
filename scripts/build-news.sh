#!/usr/bin/env bash
# L6 — compile les Nouveautés (docs/nouveautes/*.md + captures) avec `cadence news build`
# dans jobmail/web/static/nouveautes-data/, servi par l'application sous /static/.
# Le résultat est VERSIONNÉ : l'application tourne sans cadence après un `git clone`.
# À relancer (puis commiter le dossier) après tout ajout ou modification d'une entrée ;
# tests/test_news_web.py échoue si le JSON versionné n'est plus à jour.
#
# Compilation dans un dossier temporaire, remplacé seulement en cas de succès : cadence
# absent ou une entrée en erreur laisse le dossier versionné intact.
set -euo pipefail
cd "$(dirname "$0")/.."
out=jobmail/web/static/nouveautes-data
parent=$(dirname "$out")

if ! command -v cadence >/dev/null 2>&1; then
  echo "cadence introuvable dans le PATH : rien n'est modifié" >&2
  exit 1
fi

work=$(mktemp -d "$parent/.nouveautes-build.XXXXXX")
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

cadence news build -o "$work/new"
# cadence écrit aussi une page index.html autonome : doublon non habillé de /nouveautes.
rm -f "$work/new/index.html"

if [ -e "$out" ]; then mv "$out" "$work/old"; fi
mv "$work/new" "$out"
echo "Nouveautés compilées dans $out"
