"""Dates en français pour les pages rendues au serveur (Nouveautés, Plan de travail).

« 1er octobre 2026 » : le premier du mois s'écrit « 1er », et les trois parties sont
liées par des espaces insécables pour qu'une date ne se coupe jamais en fin de ligne.
Le séparateur « Déjà vu … » du navigateur utilise le même format (static/news-core.js) ;
les deux formateurs sont testés sur les mêmes cas (tests/fixtures/date-format-cases.json).
"""
from __future__ import annotations

from datetime import date, datetime

NBSP = " "

MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def format_day(value: object) -> str:
    """« 1er octobre 2026 » ; chaîne vide si la valeur n'est pas une date lisible."""
    d = _as_date(value)
    if d is None:
        return ""
    day = "1er" if d.day == 1 else str(d.day)
    return NBSP.join((day, MONTHS[d.month - 1], str(d.year)))
