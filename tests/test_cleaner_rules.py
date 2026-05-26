from jobmail.cleaner.rules import classify_cleaner_candidate


def test_newsletter_is_candidate():
    result = classify_cleaner_candidate(
        subject="Newsletter: offres speciales du week-end",
        body="Cliquez ici pour vous desabonner.",
        sender="newsletter@shop.example",
    )

    assert result.is_candidate
    assert result.reason


def test_safety_keywords_always_exclude_candidate():
    result = classify_cleaner_candidate(
        subject="Newsletter contrat assurance",
        body="Promotion et unsubscribe",
        sender="newsletter@shop.example",
    )

    assert not result.is_candidate
    assert result.safety_hit in {"contrat", "assurance"}


def test_job_related_terms_are_not_cleaner_candidates():
    result = classify_cleaner_candidate(
        subject="Recrutement Java",
        body="Votre candidature pour un emploi RH.",
        sender="promo@example.com",
    )

    assert not result.is_candidate
    assert result.safety_hit
