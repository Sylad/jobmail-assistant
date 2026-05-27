from jobmail.web.links import build_preferred_offer_terms, extract_offer_links


def test_extract_offer_links_from_html_href():
    links = extract_offer_links(
        body_html='<p><a href="https://jobs.example.com/offers/42">Voir le poste</a></p>',
    )

    assert len(links) == 1
    assert links[0].url == "https://jobs.example.com/offers/42"
    assert links[0].label == "Voir le poste"


def test_extract_offer_links_from_plain_text_and_dedupes():
    links = extract_offer_links(
        body_text="Details: https://jobs.example.com/offers/42. Again https://jobs.example.com/offers/42",
    )

    assert len(links) == 1
    assert links[0].url == "https://jobs.example.com/offers/42"


def test_extract_offer_links_unwraps_common_tracking_url():
    links = extract_offer_links(
        body_html=(
            '<a href="https://tracker.example/click?url=https%3A%2F%2Fjobs.example.com%2Foffer">'
            "Consulter</a>"
        ),
    )

    assert len(links) == 1
    assert links[0].url == "https://jobs.example.com/offer"


def test_extract_offer_links_prefers_linkedin_job_view_over_nav_links():
    links = extract_offer_links(
        body_html=(
            '<a href="https://www.linkedin.com/comm/feed/?trk=header"></a>'
            '<a href="https://www.linkedin.com/comm/messaging/?trk=header"></a>'
            '<a href="https://www.linkedin.com/comm/jobs/search?keywords=Java">Votre alerte Emploi</a>'
            '<a href="https://www.linkedin.com/comm/jobs/view/4388799424/?trackingId=abc">'
            "Full Stack Engineer - VP (Java)</a>"
        ),
    )

    assert links[0].url == "https://www.linkedin.com/jobs/view/4388799424/"
    assert links[0].label == "Full Stack Engineer - VP (Java)"


def test_extract_offer_links_prefers_matching_linkedin_job_when_digest_has_many_jobs():
    links = extract_offer_links(
        body_html=(
            '<a href="https://www.linkedin.com/comm/jobs/view/4329264165/?trackingId=abc"></a>'
            '<a href="https://www.linkedin.com/comm/jobs/view/4329264165/?trackingId=abc">'
            "Développeur Java F/H</a>"
            '<a href="https://www.linkedin.com/comm/jobs/view/4388799424/?trackingId=def"></a>'
            '<a href="https://www.linkedin.com/comm/jobs/view/4388799424/?trackingId=def">'
            "Full Stack Engineer - VP (Java) BlackRock · Paris</a>"
        ),
        preferred_terms=["Full Stack Engineer - VP (Java)", "BlackRock"],
    )

    assert links[0].url == "https://www.linkedin.com/jobs/view/4388799424/"
    assert links[0].label == "Full Stack Engineer - VP (Java) BlackRock · Paris"


def test_extract_offer_links_uses_subject_terms_for_linkedin_alerts():
    links = extract_offer_links(
        body_html=(
            '<a href="https://www.linkedin.com/comm/jobs/view/4329264165/?trackingId=abc">'
            "Développeur Java F/H Onepoint · Paris</a>"
            '<a href="https://www.linkedin.com/comm/jobs/view/4388799424/?trackingId=def">'
            "Full Stack Engineer - VP (Java) BlackRock · Paris</a>"
        ),
        preferred_terms=build_preferred_offer_terms("Full Stack Engineer - VP (Java) chez BlackRock"),
    )

    assert links[0].url == "https://www.linkedin.com/jobs/view/4388799424/"


def test_extract_offer_links_prefers_valid_model_url_present_in_mail():
    links = extract_offer_links(
        body_html=(
            '<a href="https://jobs.example.com/offers/one">Offre Java</a>'
            '<a href="https://jobs.example.com/offers/two">Offre GeoServer</a>'
        ),
        preferred_url="https://jobs.example.com/offers/two",
    )

    assert links[0].url == "https://jobs.example.com/offers/two"


def test_extract_offer_links_ignores_model_url_absent_from_mail():
    links = extract_offer_links(
        body_html='<a href="https://jobs.example.com/offers/one">Offre Java</a>',
        preferred_url="https://evil.example.com/fake",
    )

    assert links[0].url == "https://jobs.example.com/offers/one"
