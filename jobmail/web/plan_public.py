"""L7 — ce que la page « Plan de travail » publie du plan (docs/plan/raf.yaml, tenu par raf).

Règles alignées sur les apps sœurs (finance-tracker frontend/scripts/plan-data.mjs,
evatosorus frontend/src/lib/plan-public.ts) :

1. seuls les lots `visible: true` (changements pour l'utilisateur) et non abandonnés ;
2. TITRE PUBLIC seulement, jamais le titre brut du plan : le champ `public:` du lot (une
   chaîne d'une ligne), sinon — pour un lot livré seulement — le titre de son entrée
   Nouveautés, sinon le lot est masqué ; les lots de processus (« Revue … », « Audit … »,
   « Campagne … ») exigent un `public:` ;
3. liste blanche : id (jamais affiché, seulement en id d'élément), titre public, état,
   date de livraison, décompte des sous-tâches non abandonnées — jamais les notes,
   verdicts UX, raisons d'abandon, titres bruts ni titres de sous-tâches ;
4. un titre public non conforme (pas du texte, plusieurs lignes, > 80 caractères, « / »,
   fichier, nom de technique, identifiant de lot, sujet de sécurité) masque le lot ; un
   test sur le vrai plan échoue alors (tests/test_plan_web.py) : on corrige le plan.

Plan absent ou illisible : état d'erreur honnête sur la page (jamais une erreur 500 ni une
page vide qui laisserait croire qu'il n'y a rien de prévu).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

PLAN_PATH = Path(__file__).resolve().parents[2] / "docs" / "plan" / "raf.yaml"

RECENT_DONE = 8
PUBLIC_TITLE_MAX = 80
STATUSES = ("doing", "todo", "done")

MISSING = "Le plan de travail est introuvable pour le moment."
UNREADABLE = "Le plan de travail est illisible pour le moment."

# Même liste noire que finance-tracker (comparaison sans casse ni accents).
_DENY = [
    r"securit", r"faille", r"spoof", r"injection", r"\btoken", r"\bjeton", r"secret",
    r"mot de passe", r"password", r"\bpin\b", r"\bcve\b", r"vulnerab", r"\bxss\b",
    r"\bcsrf\b", r"x-forwarded", r"forgeable", r"\bauth", r"bypass",
]
_PROCESS = [r"^revue\b", r"^audit\b", r"^campagne\b"]


def _fold(text: object) -> str:
    s = unicodedata.normalize("NFD", str(text if text is not None else ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def is_denied(title: object) -> bool:
    folded = _fold(title)
    return any(re.search(p, folded) for p in _DENY)


def is_process_lot(title: object) -> bool:
    folded = _fold(title).strip()
    return any(re.search(p, folded) for p in _PROCESS)


def public_title_problem(title: object) -> str | None:
    """Raison pour laquelle un titre ne peut pas être montré au visiteur, sinon None."""
    if not isinstance(title, str):
        return "pas du texte"
    t = title.strip()
    if not t:
        return "vide"
    if re.search(r"[\r\n  ]", t):
        return "retour à la ligne"
    if len(t) > PUBLIC_TITLE_MAX:
        return f"{len(t)} caractères (> {PUBLIC_TITLE_MAX})"
    if "/" in t:
        return "contient « / »"
    if re.search(r"\.ya?ml\b", t, re.I):
        return "cite un fichier"
    if re.search(r"localstorage", t, re.I):
        return "nom de technique"
    if re.search(r"\bL\d+\b", t):
        return "cite un identifiant de lot"
    if is_denied(t):
        return "liste noire sécurité"
    return None


def _day(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    return None


@dataclass
class PublicLot:
    id: str
    title: str
    status: str
    finished: str | None = None
    tasks_done: int = 0
    tasks_total: int = 0
    also: list[str] = field(default_factory=list)
    sort_key: str = ""

    @property
    def ready(self) -> bool:
        """Toutes les étapes faites, pas encore livré."""
        return self.status != "done" and self.tasks_total > 0 and self.tasks_done == self.tasks_total


@dataclass
class PublicPlan:
    doing: list[PublicLot] = field(default_factory=list)
    todo: list[PublicLot] = field(default_factory=list)
    done: list[PublicLot] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"doing": 0, "todo": 0, "done": 0})
    error: str = ""
    # Lots visibles masqués : (id, raison). Jamais rendu ; sert aux tests et au rapport.
    hidden: list[tuple[str, str]] = field(default_factory=list)


def _to_public(raw: object, news_titles: dict[str, str], hidden: list) -> PublicLot | None:
    if not isinstance(raw, dict):
        return None
    lot_id = raw.get("id")
    if raw.get("visible") is not True or not isinstance(lot_id, str):
        return None
    status = raw.get("status")
    if status not in STATUSES:
        return None
    if is_denied(raw.get("title")):
        hidden.append((lot_id, "sujet de sécurité"))
        return None
    title = raw.get("public")
    if title is None:
        if status != "done":
            hidden.append((lot_id, "pas de titre public (public:)"))
            return None
        if is_process_lot(raw.get("title")):
            hidden.append((lot_id, "lot de processus sans public:"))
            return None
        title = news_titles.get(lot_id)
        if title is None:
            hidden.append((lot_id, "livré sans public: ni entrée Nouveautés"))
            return None
    problem = public_title_problem(title)
    if problem:
        hidden.append((lot_id, f"titre public non conforme ({problem})"))
        return None
    lot = PublicLot(
        id=lot_id,
        title=title.strip(),
        status=status,
        sort_key=_day(raw.get("finished")) or _day(raw.get("started")) or _day(raw.get("created")) or "",
    )
    if status == "done":
        lot.finished = _day(raw.get("finished"))
    tasks = raw.get("tasks")
    if isinstance(tasks, list):
        states = [
            t.get("status")
            for t in tasks
            if isinstance(t, dict) and t.get("status") != "dropped" and not is_denied(t.get("title"))
        ]
        lot.tasks_total = len(states)
        lot.tasks_done = sum(1 for s in states if s == "done")
    return lot


def _merge_same_title(group: list[PublicLot]) -> list[PublicLot]:
    """Deux lots au même titre public ne font qu'une ligne (la première), étapes additionnées."""
    kept: dict[str, PublicLot] = {}
    for lot in group:
        first = kept.get(lot.title)
        if first is None:
            kept[lot.title] = lot
            continue
        first.also.append(lot.id)
        first.tasks_done += lot.tasks_done
        first.tasks_total += lot.tasks_total
    return list(kept.values())


def build_public_plan(raw: object, news_titles: dict[str, str] | None = None) -> PublicPlan:
    if not isinstance(raw, dict) or not isinstance(raw.get("lots"), list):
        return PublicPlan(error=UNREADABLE)
    hidden: list[tuple[str, str]] = []
    lots = [
        lot for lot in (_to_public(r, news_titles or {}, hidden) for r in raw["lots"]) if lot
    ]
    doing = _merge_same_title([lot for lot in lots if lot.status == "doing"])
    todo = _merge_same_title([lot for lot in lots if lot.status == "todo"])
    # Tri stable : à date égale, le lot le plus loin dans le plan (le plus récent) d'abord.
    indexed = [(i, lot) for i, lot in enumerate(lots) if lot.status == "done"]
    indexed.sort(key=lambda p: (p[1].sort_key, p[0]), reverse=True)
    done = _merge_same_title([lot for _, lot in indexed])
    return PublicPlan(
        doing=doing,
        todo=todo,
        done=done[:RECENT_DONE],
        counts={"doing": len(doing), "todo": len(todo), "done": len(done)},
        hidden=hidden,
    )


def load_raw_plan(path: Path | None = None) -> object:
    with (path or PLAN_PATH).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_public_plan(path: Path | None = None, news_titles: dict[str, str] | None = None) -> PublicPlan:
    try:
        raw = load_raw_plan(path)
    except FileNotFoundError:
        return PublicPlan(error=MISSING)
    except Exception:  # noqa: BLE001 — YAML invalide, date impossible, imbrication sans fin…
        # Tout plan illisible donne l'état d'erreur de la page, jamais une erreur 500.
        return PublicPlan(error=UNREADABLE)
    try:
        return build_public_plan(raw, news_titles)
    except Exception:  # noqa: BLE001 — structure inattendue malgré les contrôles
        return PublicPlan(error=UNREADABLE)


# ── Libellés ─────────────────────────────────────────────────────────────────────

NBSP = " "


def _count(n: int, one: str, many: str) -> str:
    return f"{n}{NBSP}{many if n > 1 else one}"


def plan_summary(counts: dict[str, int]) -> list[str]:
    """Bandeau de décomptes : groupes vides omis (pas de « 0 prévu »)."""
    parts = [
        _count(counts["doing"], "travail en cours", "travaux en cours") if counts["doing"] else "",
        _count(counts["todo"], "travail prévu", "travaux prévus") if counts["todo"] else "",
        _count(counts["done"], "travail livré", "travaux livrés") if counts["done"] else "",
    ]
    return [p for p in parts if p]


def steps_label(done: int, total: int) -> str:
    """« 1 étape faite sur 2 », « 2 étapes faites sur 3 » (0 et 1 au singulier)."""
    word = "étapes faites" if done > 1 else "étape faite"
    return f"{done} {word} sur {total}".replace(" ", NBSP)


# ── Textes privés (preuve de non-fuite) ──────────────────────────────────────────

MIN_PRIVATE = 12
MIN_TITLE = 20


def private_texts(raw: object, plan: PublicPlan) -> list[str]:
    """Textes du plan qui ne doivent JAMAIS être rendus : notes, verdicts UX, raisons
    (dès 12 caractères), titres bruts de lots et de sous-tâches, `public:` de lots masqués
    (dès 20) — sauf un texte contenu dans un titre publié (public par définition)."""
    published = [lot.title for lot in plan.doing + plan.todo + plan.done]
    out: set[str] = set()

    def add(value: object, minimum: int) -> None:
        if value is None:
            return
        s = str(value).strip()
        if len(s) >= minimum and not any(s in p for p in published):
            out.add(s)

    def walk(item: object, is_task: bool) -> None:
        if not isinstance(item, dict):
            return
        add(item.get("title"), MIN_TITLE)
        add(item.get("public"), MIN_TITLE)
        add(item.get("reason"), MIN_PRIVATE)
        ux = item.get("ux")
        if isinstance(ux, dict):
            add(ux.get("verdict"), MIN_PRIVATE)
        for note in item.get("notes") or []:
            add(note.get("text") if isinstance(note, dict) else note, MIN_PRIVATE)
        for task in item.get("tasks") or []:
            walk(task, True)

    lots = raw.get("lots") if isinstance(raw, dict) else None
    for lot in lots or []:
        walk(lot, False)
    return sorted(out)
