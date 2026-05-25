from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from jobmail.config import Settings, get_settings
from jobmail.models import RawEmail
from jobmail.pipeline import run as run_pipeline

MOCK_EMAILS: list[dict] = [
    {
        "subject": "Java Senior GeoServer / OpenLayers — Mission longue Paris hybride",
        "sender": '"Marie Dupont" <marie.dupont@geocompany.fr>',
        "body": (
            "Bonjour,\n\nNous recherchons un développeur Java senior maîtrisant "
            "GeoServer, OpenLayers et PostGIS pour une mission freelance de 12 mois, "
            "TJM 650€, basée à Paris en hybride (2 jours sur site). Stack: Spring Boot, "
            "Docker, Kubernetes, Maven. Anglais professionnel requis pour échanges avec "
            "l'équipe de Berlin. Disponible début juin.\n\nCordialement,\nMarie — Recruteuse"
        ),
    },
    {
        "subject": "Opportunité : Tech Lead Backend Java/Spring CDI Lyon",
        "sender": '"Talent Acquisition" <jobs@bigcorp.com>',
        "body": (
            "Hello,\n\nWe have a Tech Lead Backend position open at our Lyon office. "
            "CDI, salary 75-85k€. Java 21, Spring Boot, Kafka, Kubernetes, PostgreSQL. "
            "Full remote possible. English required as our team is distributed across Europe."
        ),
    },
    {
        "subject": "Mission freelance — GIS / PostGIS / Python Toulouse",
        "sender": "recruiter@freelance-platform.io",
        "body": (
            "Mission de 6 mois renouvelable pour un consultant freelance en SIG. "
            "Stack: PostGIS, Python, FastAPI, OpenLayers. Hybride Toulouse, TJM 600€. "
            "Pas d'anglais requis."
        ),
    },
    {
        "subject": "Newsletter LinkedIn — Vos offres du jour",
        "sender": "jobs-noreply@linkedin.com",
        "body": (
            "Voici une sélection d'opportunités correspondant à votre profil : "
            "DevOps Engineer, SRE, Platform Engineer, Java Backend Developer. "
            "Postulez en un clic depuis l'application LinkedIn."
        ),
    },
    {
        "subject": "Confirmation de votre commande Amazon #112-4823",
        "sender": "auto-confirm@amazon.fr",
        "body": "Votre commande a bien été enregistrée. Livraison prévue mardi.",
    },
    {
        "subject": "Newsletter Le Monde — édition du jour",
        "sender": "newsletter@lemonde.fr",
        "body": "Tous les articles de la rédaction, climat, politique, économie...",
    },
    {
        "subject": "Re: Candidature poste DevOps Platform Engineer chez Maritime SaaS",
        "sender": '"Jean Martin" <j.martin@maritime-saas.eu>',
        "body": (
            "Bonjour Sylvain,\n\nSuite à votre candidature, nous aimerions vous "
            "proposer un entretien pour le poste de Platform Engineer. Stack: "
            "Kubernetes, ArgoCD, Helm, Docker, Prometheus, GeoServer. CDI, Nantes, "
            "package 70k€, full remote possible 4 jours/semaine.\n\nDisponibilités ?"
        ),
    },
    {
        "subject": "Freelance opportunity — Senior Backend Engineer Kafka/Java",
        "sender": '"ESN-Recrut" <hello@esn-recrut.com>',
        "body": (
            "Mission urgente Paris La Défense, démarrage ASAP. Java 17, Spring Boot 3, "
            "Kafka, Cassandra, Kubernetes, ArgoCD. TJM 700€, 100% onsite. "
            "Durée 9 mois. Anglais courant."
        ),
    },
    {
        "subject": "OpenLayers v10 release notes",
        "sender": "news@openlayers.org",
        "body": "OpenLayers v10 is out with WebGL improvements...",
    },
    {
        "subject": "Welcome to the Jungle — 5 nouvelles offres",
        "sender": "alerts@welcometothejungle.com",
        "body": (
            "5 nouvelles offres en CDI correspondent à votre recherche : "
            "Backend Java, Tech Lead Spring, Cloud Engineer K8s, SRE, Data Engineer."
        ),
    },
]


def seed(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    base_time = datetime.now()
    emails = [
        RawEmail(
            uid=f"mock-{i}",
            message_id=f"<mock-{i}@local>",
            subject=item["subject"],
            sender=item["sender"],
            received_at=base_time - timedelta(hours=i * 6),
            body_text=item["body"],
        )
        for i, item in enumerate(MOCK_EMAILS)
    ]
    stats = run_pipeline(source=iter(emails), settings=settings)
    return stats.extracted


if __name__ == "__main__":  # pragma: no cover
    n = seed()
    print(f"Seeded {n} offers.")
