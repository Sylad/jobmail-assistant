from jobmail.web.links import extract_offer_links


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
