"""En-têtes de mail : RFC 2047, UTF-8 brut, latin-1 brut, mélange (L4/t2).

Tous les en-têtes sont fictifs : aucun vrai mail, expéditeur ni offre.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jobmail.mail.mbox_reader import _parse
from jobmail.mail.thunderbird import _decode_hdr, read_mbox

REPLACEMENT = "�"


def _message(subject: bytes, content_type: bytes = b"text/plain; charset=utf-8", sender: bytes = b"Demo <demo@example.org>") -> bytes:
    return (
        b"From - Mon Jan 05 10:00:00 2026\n"
        b"Message-Id: <fictif-1@example.org>\n"
        b"Date: Mon, 05 Jan 2026 10:00:00 +0000\n"
        b"From: " + sender + b"\n"
        b"Subject: " + subject + b"\n"
        b"Content-Type: " + content_type + b"\n"
        b"\n"
        b"Corps fictif.\n"
    )


def _subject(raw: bytes, charset: str | None = None) -> str:
    """Passe par le vrai analyseur (politique compat32), comme le lecteur MBOX."""
    return _decode_hdr(_parse(_message(raw)).get("Subject", ""), charset)


@pytest.mark.parametrize(
    ("raw", "charset", "expected"),
    [
        # RFC 2047, encodage Q et B, UTF-8 et latin-1
        (b"=?UTF-8?Q?R=C3=A9union_d=27=C3=A9quipe?=", None, "Réunion d'équipe"),
        (b"=?utf-8?B?w4l0w6kgaW5kaWVu?=", None, "Été indien"),
        (b"=?ISO-8859-1?Q?Caf=E9_cr=E8me?=", None, "Café crème"),
        # deux mots encodés qui se suivent : l'espace entre eux ne s'affiche pas
        (b"=?UTF-8?Q?Pr=C3=A9?= =?UTF-8?Q?sentation?=", None, "Présentation"),
        # UTF-8 brut, sans RFC 2047
        ("Réunion d'équipe à 14 h — rappel".encode(), None, "Réunion d'équipe à 14 h — rappel"),
        ("Œuvre complète €".encode(), "iso-8859-1", "Œuvre complète €"),
        # latin-1 brut : dernier recours sans jeu déclaré
        ("Café crème à emporter".encode("latin-1"), None, "Café crème à emporter"),
        # 8 bits brut dans le jeu déclaré par le message, essayé avant latin-1
        ("Prix : 12 € l'œuvre".encode("cp1252"), "windows-1252", "Prix : 12 € l'œuvre"),
        ("Prix réduit".encode("latin-1"), "jeu-inconnu", "Prix réduit"),
        # mélanges : mot encodé + 8 bits brut dans le même en-tête
        (b"=?UTF-8?Q?R=C3=A9ponse?= : " + "café".encode(), None, "Réponse : café"),
        (b"=?ISO-8859-1?Q?Caf=E9?= et " + "thé".encode("latin-1"), None, "Café et thé"),
        ("Déjà vu : ".encode() + b"=?UTF-8?B?w4l0w6k=?=", None, "Déjà vu : Été"),
        # ASCII simple, inchangé
        (b"Plain subject", None, "Plain subject"),
    ],
)
def test_decode_hdr(raw: bytes, charset: str | None, expected: str):
    out = _subject(raw, charset)
    assert out == expected
    assert REPLACEMENT not in out


def test_decode_hdr_valeurs_limites():
    assert _decode_hdr(None) == ""
    assert _decode_hdr("") == ""
    assert _decode_hdr("Sujet déjà en str") == "Sujet déjà en str"
    # jeu de caractères inconnu dans un mot encodé : pas d'exception, pas de U+FFFD
    assert _decode_hdr("=?x-inconnu?Q?Caf=E9?=") == "Café"
    # mot encodé invalide : rendu tel quel
    assert _decode_hdr("=?UTF-8?B?!!!?= fin").endswith("fin")


def test_read_mbox_sujet_et_expediteur_8_bits(tmp_path: Path):
    """De bout en bout : le jeu déclaré par le message sert aux en-têtes bruts."""
    mbox = tmp_path / "Inbox"
    mbox.write_bytes(
        _message("Réunion d'équipe".encode())
        + _message(
            "Prix : 12 € l'œuvre".encode("cp1252"),
            content_type=b"text/plain; charset=windows-1252",
            sender="Société Démo <demo@example.org>".encode("cp1252"),
        )
        + _message("Café crème".encode("latin-1"), content_type=b"text/plain")
    )
    mails = list(read_mbox(mbox))
    assert [m.subject for m in mails] == ["Réunion d'équipe", "Prix : 12 € l'œuvre", "Café crème"]
    assert mails[1].sender == "Société Démo <demo@example.org>"
    assert all(REPLACEMENT not in m.subject + m.sender for m in mails)
