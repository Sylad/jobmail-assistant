from __future__ import annotations

import re
import unicodedata

ESN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Accenture", r"\baccenture\b"),
    ("Agap2", r"\bagap2\b"),
    ("Akkodis", r"\b(akka|akkodis|modis)\b"),
    ("Alten", r"\b(alten|altran)\b"),
    ("Astek", r"\bastek\b"),
    ("Atos", r"\b(atos|eviden)\b"),
    ("Aubay", r"\baubay\b"),
    ("Axians", r"\baxians\b"),
    ("Business & Decision", r"\bbusiness\s*&\s*decision\b"),
    ("Capgemini", r"\b(capgemini|sogeti)\b"),
    ("CGI", r"\bcgi\b"),
    ("Consort", r"\bconsort\b"),
    ("Davidson", r"\bdavidson\b"),
    ("Devoteam", r"\bdevoteam\b"),
    ("Econocom", r"\beconocom\b"),
    ("Expleo", r"\bexpleo\b"),
    ("Extia", r"\bextia\b"),
    ("Hardis", r"\bhardis\b"),
    ("Inetum", r"\b(inetum|gfi)\b"),
    ("Infotel", r"\binfotel\b"),
    ("Keyrus", r"\bkeyrus\b"),
    ("Meritis", r"\bmeritis\b"),
    ("mc2i", r"\bmc2i\b"),
    ("Niji", r"\bniji\b"),
    ("Neurones", r"\bneurones\b"),
    ("Octo", r"\bocto\s+technology\b|\bocto\b"),
    ("Onepoint", r"\bonepoint\b"),
    ("Orange Business", r"\borange\s+business\b"),
    ("Open", r"\bgroupe\s+open\b|\bopen\s+digital\b"),
    ("Proxiad", r"\bproxiad\b"),
    ("Randstad Digital", r"\brandstad\s+digital\b"),
    ("Scalian", r"\bscalian\b"),
    ("SCC", r"\bscc\b"),
    ("SII", r"\bsii\b"),
    ("Sopra Steria", r"\b(sopra\s*steria|soprasteria)\b"),
    ("SQLI", r"\bsqli\b"),
    ("Talan", r"\btalan\b"),
    ("UTiGroup", r"\butigroup\b"),
    ("Wavestone", r"\bwavestone\b"),
    ("Webnet", r"\bwebnet\b"),
    ("Worldline", r"\bworldline\b"),
    ("Zenika", r"\bzenika\b"),
)


def detect_esn(*values: str) -> str:
    text = _normalize(" ".join(value or "" for value in values))
    if not text.strip():
        return ""
    for label, pattern in ESN_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return ""


def _normalize(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    return " ".join(without_accents.replace("\xa0", " ").split()).lower()
