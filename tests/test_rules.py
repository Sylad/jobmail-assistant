from jobmail.filtering.rules import classify


def test_keyword_recrutement_detected():
    r = classify("Opportunité de recrutement", "Bonjour, nous avons une mission.")
    assert r.is_job_related
    assert "recrutement" in r.matched_intent


def test_two_technos_alone_count_as_job():
    r = classify("Update produit", "On utilise Java et GeoServer.")
    assert r.is_job_related
    assert {"java", "geoserver"}.issubset({t.lower() for t in r.matched_technos})


def test_single_techno_alone_is_not_job():
    r = classify("OpenLayers tip", "OpenLayers est génial.")
    assert not r.is_job_related


def test_newsletter_ecommerce_is_not_job():
    r = classify("Votre commande Amazon", "Livraison demain.")
    assert not r.is_job_related


def test_accent_and_case_insensitive():
    r = classify("OPPORTUNITÉ", "candidature pour ce poste")
    assert r.is_job_related


def test_english_keywords():
    r = classify("Senior Java Engineer position", "Hello, we have a position open in our hiring team.")
    assert r.is_job_related


def test_partial_word_no_match():
    # "java" should not match "javanais" — checking word boundary.
    r = classify("Cours de javanais", "Apprendre le javanais.")
    assert not r.is_job_related, "should not match substring inside another word"
