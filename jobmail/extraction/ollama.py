from __future__ import annotations

import json
import logging

import httpx

from ..config import Settings
from ..models import ContractType, OfferExtraction, RawEmail, WorkMode
from .base import LocalLLMProvider

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Tu es un assistant carrière local spécialisé dans l'analyse de mails de recrutement.

Tu dois analyser UNIQUEMENT le mail fourni.
Tu dois répondre UNIQUEMENT avec un objet JSON valide.
Aucun markdown. Aucun commentaire. Aucun texte autour.

Profil cible pour le scoring:
{profile}

Règles de scoring (NE PAS être conservateur — utilise toute l'échelle 0→10):
- 10  : offre quasi-parfaite (Java senior + GeoServer/PostGIS + remote ou Toulouse).
- 9   : forte correspondance — Java senior + au moins 1 critère majeur (SIG/GIS,
       GeoServer, PostGIS, Kubernetes, AWS cloud).
- 8   : très bonne offre Java/Spring senior ou architecte SIG, même sans match
       parfait. Une vraie offre chez une boîte sérieuse = 8 minimum si Java
       senior est mentionné.
- 7   : offre Java/Spring ou DevOps/Cloud compatible, sans GIS.
- 5-6 : techno intéressante mais éloignée (front pur, data, etc.).
- 3-4 : alerte/newsletter listant plusieurs offres sans focus.
- 1-2 : confirmation de compte, alerte créée, communication service.
- 0   : hors sujet (e-commerce, gaming, transport).

N'hésite PAS à donner 8, 9 ou 10. Une vraie offre Java senior + GeoServer doit
TOUJOURS être ≥ 9. Une vraie offre Java/Spring senior chez une vraie société
doit être ≥ 8.

Pondération:
- GeoServer / GeoTools / GeoNetwork : +3
- OpenLayers / MapLibre / Leaflet / Mapbox : +3
- PostGIS / PostgreSQL spatial : +3
- Java senior / Spring / Spring Boot : +3
- SIG / GIS / cartographie / géomatique / météo / aviation : +3
- Kubernetes / K8s / Docker / ArgoCD / Helm : +2
- AWS / Azure / GCP cloud : +2
- Remote / télétravail / hybride : +1
- Toulouse / Sud-Ouest : +1
- Stack ESRI uniquement (pas Java, pas open-source) : −2
- Anglais oral courant obligatoire (daily meetings EN) : −1
- Newsletter générique listant des offres sans focus : −2 (cap à 3-4 max)
- Alerte de compte / confirmation / bienvenue : score 0-2

Détection work_mode (cherche dans le BODY) :
- "remote", "télétravail total", "full remote", "100% remote" → "remote"
- "hybride", "X jours sur site", "2-3 jours bureau" → "hybrid"
- "présentiel", "sur site uniquement", "onsite only" → "onsite"
- Si rien trouvé : "unknown" (mais cherche AVANT de répondre).

Schéma JSON attendu:
{{
  "title": "string",
  "company": "string",
  "recruiter": "string",
  "location": "string",
  "work_mode": "remote|hybrid|onsite|unknown",
  "technos": ["string"],
  "english_required": true,
  "contract_type": "cdi|cdd|freelance|mission|unknown",
  "summary": "string <= 400 caractères",
  "relevance_score": 0
}}

Contraintes:
- relevance_score doit être un entier entre 0 et 10.
- technos doit contenir uniquement des noms de technologies ou domaines détectés.
- Si une information est absente, utilise "" ou "unknown".
- Ne devine pas une société si elle n'est pas indiquée.
- Ne mets pas de texte hors JSON.

Mail:
De: {sender}
Sujet: {subject}
---
{body}

/no_think
"""


class OllamaProvider(LocalLLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    def extract(self, email: RawEmail, target_profile: str) -> OfferExtraction:
        prompt = PROMPT_TEMPLATE.format(
            profile=target_profile,
            sender=email.sender,
            subject=email.subject,
            body=email.body_text[:4000],
        )

        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "think": False,           # qwen3 native disable-thinking
                    "keep_alive": "10m",      # keep model hot between calls
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 512,   # cap output, JSON is short
                    },
                },
                timeout=180,
            )
            resp.raise_for_status()

            data = resp.json()
            payload = json.loads(data.get("response", "{}"))

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("Ollama extraction failed: %s", e)
            return OfferExtraction()

        score = _safe_score(payload.get("relevance_score", 0))

        return OfferExtraction(
            title=str(payload.get("title", "") or ""),
            company=str(payload.get("company", "") or ""),
            recruiter=str(payload.get("recruiter", "") or ""),
            location=str(payload.get("location", "") or ""),
            work_mode=_safe_enum(WorkMode, payload.get("work_mode")),
            technos=_safe_technos(payload.get("technos", [])),
            english_required=bool(payload.get("english_required", False)),
            contract_type=_safe_enum(ContractType, payload.get("contract_type")),
            summary=str(payload.get("summary", "") or "")[:400],
            relevance_score=score,
        )


def _safe_score(value) -> int:
    try:
        score = int(value or 0)
    except (ValueError, TypeError):
        score = 0

    return max(0, min(10, score))


def _safe_technos(value) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip().lower() for item in value if str(item).strip()]


def _safe_enum(enum_cls, value):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return enum_cls("unknown")


OllamaExtractor = OllamaProvider
