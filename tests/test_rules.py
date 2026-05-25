from jobmail.filtering.rules import classify


def test_strong_intent_alone_is_job():
    r = classify("Suite à votre candidature", "Nous recrutons un dev senior.")
    assert r.is_job_related
    assert any("recrut" in m for m in r.matched_strong)


def test_two_technos_alone_count_as_job():
    r = classify("Update produit", "On utilise Java et GeoServer en interne.")
    assert r.is_job_related
    assert {"java", "geoserver"}.issubset({t.lower() for t in r.matched_technos})


def test_single_techno_alone_is_not_job():
    r = classify("OpenLayers tip", "OpenLayers est génial.")
    assert not r.is_job_related


def test_weak_intent_alone_is_not_enough():
    """'opportunité' seul (sans techno) ne suffit plus — fix faux positifs Xbox."""
    r = classify("Opportunité incroyable", "Une opportunité de soldes.")
    assert not r.is_job_related


def test_weak_intent_plus_techno_is_job():
    r = classify("Position ouverte", "On cherche un dev Java.")
    assert r.is_job_related
    assert "position" in r.matched_weak
    assert "java" in r.matched_technos


def test_noise_sender_zero_chance():
    """Xbox / Stardock / Atari ne peuvent JAMAIS être classés job, peu importe le body."""
    r = classify(
        subject="Nouvelle mission java spring kubernetes recrutement candidature",
        body="Toutes les techs du monde.",
        sender='"Xbox" <xboxreps@engage.xbox.com>',
    )
    assert not r.is_job_related
    assert r.sender_is_noise


def test_recruiter_sender_auto_positive():
    """Jooble / LinkedIn / Welcome to the Jungle override toute logique body."""
    r = classify(
        subject="Random subject",
        body="Random body without any keyword.",
        sender="alerts@fr.jooble.org",
    )
    assert r.is_job_related
    assert r.sender_is_recruiter


def test_linkedin_recruiter_inmail():
    r = classify(
        subject="Sylvain, here's a new role for you",
        body="A recruiter from XYZ wants to connect.",
        sender="messaging-digest-noreply@linkedin.com",
    )
    assert r.is_job_related
    assert r.sender_is_recruiter


def test_welcometothejungle_recruiter():
    r = classify(
        subject="5 nouvelles offres",
        body="Backend Java...",
        sender="alerts@welcometothejungle.com",
    )
    assert r.is_job_related
    assert r.sender_is_recruiter


def test_application_word_alone_no_longer_triggers():
    """'application' (en anglais = app) ne doit plus classer job-related."""
    r = classify(
        subject="Téléchargez l'application Xbox",
        body="Abonne-toi via l'application.",
        sender='"Some Random" <hello@neutral.com>',
    )
    assert not r.is_job_related


def test_accent_and_case_insensitive():
    r = classify("OPPORTUNITÉ", "candidature pour ce poste")
    # candidature is strong, so this should be true
    assert r.is_job_related


def test_partial_word_no_match():
    r = classify("Cours de javanais", "Apprendre le javanais.")
    assert not r.is_job_related


def test_noise_ecommerce_rejected():
    r = classify("Votre commande Amazon", "Livraison demain.", sender="service@amazon.fr")
    assert not r.is_job_related
    assert r.sender_is_noise
