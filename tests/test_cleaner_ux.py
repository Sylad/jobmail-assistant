"""Revue UX du nettoyeur (L4) : garde-fous sur les écarts corrigés. Les mesures (contraste,
débordement, focus) ont été faites dans un navigateur ; ici, les règles qui les causaient ne
doivent pas revenir."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "jobmail" / "web" / "static" / "style.css").read_text(encoding="utf-8")
VUE = (ROOT / "frontend" / "src" / "cleaner" / "CleanerApp.vue").read_text(encoding="utf-8")
PANEL = (ROOT / "frontend" / "src" / "cleaner" / "ProgressPanel.vue").read_text(encoding="utf-8")
BUNDLE = (ROOT / "jobmail" / "web" / "static" / "assets" / "cleaner.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "jobmail" / "web" / "templates" / "cleaner.html").read_text(encoding="utf-8")


def _l4_block() -> str:
    return CSS[CSS.index("/* ── L4 : revue UX du nettoyeur ──"):]


def test_cleaner_secondary_text_uses_a_readable_token():
    # --fg-faint (#64748B) : 2,80 à 3,75:1 mesurés ; --fg-mute (#94A3B8) : plus de 6:1 (WCAG 1.4.3).
    block = _l4_block()
    rule = re.search(r"\.tool-head p,[^{]*\{([^}]*)\}", block)
    assert rule and "color: var(--fg-mute)" in rule.group(1)
    for selector in (".cleaner-app-shell .muted", ".label-title", ".compact-table th", ".phase-counts"):
        assert selector in block.split("{", 1)[0], selector


def test_filter_inputs_keep_a_visible_focus_ring():
    # `.filter-form input:focus { outline: none }` écrasait l'anneau (WCAG 2.4.7).
    assert re.search(r"\.filter-form input:focus-visible[^{]*\{[^}]*outline: 2px solid", _l4_block())


def test_indeterminate_animation_stops_on_reduced_motion():
    assert "@media (prefers-reduced-motion: reduce)" in _l4_block()


def test_candidate_checkboxes_and_phase_cards_are_named_for_screen_readers():
    assert ':aria-label="`Sélectionner : ' in VUE  # WCAG 4.1.2 : 48 cases sans nom mesurées
    assert ':aria-pressed="activePhase === phase.source"' in VUE
    assert "Regex expéditeur, ligne" in VUE and "Regex objet, ligne" in VUE
    # Le bundle commité est bien reconstruit depuis ces sources.
    assert "aria-pressed" in BUNDLE and "Regex expéditeur, ligne" in BUNDLE


def test_progress_bar_is_full_once_done_not_stuck_at_46():
    assert "props.progressValue ?? (props.active ? null : 100)" in PANEL


def test_long_tables_scroll_in_their_own_box_and_cards_have_labels():
    assert VUE.count('class="cleaner-table-scroll') == 2
    # Sous 900 px, seul le tableau des candidats (en cartes) sort de sa boîte de défilement.
    assert "  .cleaner-cards-scroll { overflow-x: visible; }" in _l4_block()
    assert "  .cleaner-table-scroll { overflow-x: visible; }" not in _l4_block()
    for label in ("Sélection", "Source", "Date", "Expéditeur", "Sujet", "Raison"):
        assert f'data-label="{label}"' in VUE, label


def test_cleaner_labels_are_written_with_their_accents():
    shown = "\n".join(
        line for line in (VUE + PANEL + TEMPLATE).splitlines()
        if "includes(" not in line  # messages du serveur comparés tels quels
    )
    for word in ("deplace", "Deplac", "selectionn", "scannes", "Regles", "Expediteur", "recents",
                 "Arret", "deja", "supprime(s)", "liberes", "scan only", "Jobs cleanup"):
        assert not re.search(rf"(?<![\w-]){re.escape(word)}", shown), word


def test_disabled_backup_button_says_why():
    assert 'aria-describedby="backup-none-eligible"' in TEMPLATE
