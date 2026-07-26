from harvester.scoring import NATIONAL_FLAG_WEIGHT, score_text


def test_domain_terms_multilingual():
    domain, national, score = score_text(
        "Akusalvesti kasutamine sagedusreservi pakkumiseks", country="EE")
    assert "storage" in domain
    # sagedusreserv is both a domain term (frequency_reserve) and an EE flag
    assert "frequency_reserve" in domain
    assert "sagedusreserv" in national


def test_national_flags_weighted():
    domain, national, score = score_text(
        "Analiza rynku mocy dla magazynu energii w KSE", country="PL")
    assert "rynek mocy" in national
    assert "KSE" in national
    assert score == len(domain) + NATIONAL_FLAG_WEIGHT * len(national)


def test_short_acronyms_need_word_boundary_and_case():
    # 'AST' (Latvian TSO) must not fire inside ordinary words or lowercase text.
    _, national, _ = score_text("fastest broadcast forecast", country="LV")
    assert national == []
    _, national, _ = score_text("The Latvian TSO AST operates the grid", country="LV")
    assert national == ["AST"]


def test_country_scoping_avoids_cross_language_noise():
    # PGE is a Polish flag; a Latvian record mentioning "page" must not hit it.
    _, national, _ = score_text("front page of the report", country="LV")
    assert national == []


def test_no_relevance_thresholding():
    domain, national, score = score_text("A thesis about medieval literature", country="EE")
    assert score == 0  # scored zero, still a valid record — filtering happens later
