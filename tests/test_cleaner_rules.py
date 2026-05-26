from jobmail.cleaner.rules import classify_cleaner_candidate


def test_newsletter_is_candidate():
    result = classify_cleaner_candidate(
        subject="Newsletter: offres speciales du week-end",
        body="Cliquez ici pour vous desabonner.",
        sender="newsletter@shop.example",
    )

    assert result.is_candidate
    assert result.reason


def test_invoice_keyword_without_attachment_does_not_exclude_candidate():
    result = classify_cleaner_candidate(
        subject="Newsletter facture",
        body="Promotion et unsubscribe",
        sender="newsletter@shop.example",
    )

    assert result.is_candidate
    assert not result.safety_hit


def test_invoice_keyword_with_attachment_excludes_candidate():
    result = classify_cleaner_candidate(
        subject="Newsletter facture",
        body="Promotion et unsubscribe",
        sender="newsletter@shop.example",
        has_attachment=True,
    )

    assert not result.is_candidate
    assert result.safety_hit == "facture"


def test_job_related_terms_can_be_cleaner_candidates_when_sender_matches():
    result = classify_cleaner_candidate(
        subject="Recrutement Java",
        body="Votre candidature pour un emploi RH.",
        sender="promo@example.com",
    )

    assert result.is_candidate
    assert not result.safety_hit
