from jobmail.esn import detect_esn


def test_detect_esn_known_companies():
    assert detect_esn("CGI") == "CGI"
    assert detect_esn("Sopra Steria") == "Sopra Steria"
    assert detect_esn("Capgemini Engineering") == "Capgemini"
    assert detect_esn("Randstad Digital") == "Randstad Digital"


def test_detect_esn_avoids_generic_open_word():
    assert detect_esn("Open source GIS role") == ""
    assert detect_esn("Groupe Open") == "Open"
