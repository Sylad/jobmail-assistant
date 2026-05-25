from jobmail.mail.parser import html_to_text, normalize_body


def test_html_to_text_strips_tags_and_scripts():
    html = """
    <html><head><script>alert(1)</script></head>
    <body><p>Hello <b>world</b></p><p>Stack: Java, GeoServer</p></body></html>
    """
    txt = html_to_text(html)
    assert "Hello" in txt
    assert "world" in txt
    assert "alert" not in txt
    assert "<" not in txt


def test_normalize_strips_quoted_lines():
    body = "Réponse rapide:\n> Vieux texte cité\n> Encore\n\nMerci"
    out = normalize_body(body)
    assert "Vieux texte cité" not in out
    assert "Merci" in out
    assert "Réponse rapide" in out


def test_normalize_compacts_whitespace():
    body = "Hello   world\n\n\n\nNext"
    out = normalize_body(body)
    assert "Hello world" in out
    assert "\n\n\n" not in out


def test_empty_html_returns_empty():
    assert html_to_text("") == ""
