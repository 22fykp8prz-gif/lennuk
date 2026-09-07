"""Unit tests for classification, MW extraction and bucketing."""

from gas_plant_scraper.classify import (
    classify_doc_types,
    extract_mw_values,
    mw_bucket,
    relevance_score,
)


def test_drawing_detected_from_estonian_text():
    types = classify_doc_types("Lisa 3. Asendiplaan", "https://x.ee/lisa3.pdf")
    assert "drawing" in types


def test_drawing_detected_from_dwg_extension():
    types = classify_doc_types("Lisa 7", "https://x.ee/failid/lisa7.dwg")
    assert "drawing" in types


def test_safety_detected_czech_accent_insensitive():
    # 'Analýza rizik' should match even without accents in the vocabulary.
    types = classify_doc_types("Analyza rizik zamer", "https://cz.example/doc.pdf")
    assert "safety" in types


def test_description_detected_finnish():
    types = classify_doc_types(
        "YVA arviointiselostus, kaasuvoimalaitos", "https://fi.example/selostus.pdf"
    )
    assert "description" in types


def test_infrastructure_detected_polish():
    types = classify_doc_types("Przyłącze gazowe i gazociąg", "")
    assert "infrastructure" in types


def test_multiple_types_possible():
    types = classify_doc_types("Riskianalüüs ja asendiplaan", "")
    assert "safety" in types and "drawing" in types


def test_relevance_score_counts_terms():
    assert relevance_score("Uus gaasiturbiin elektrijaamas", "") >= 1
    assert relevance_score("kohalik lasteaed", "") == 0


def test_relevance_from_url_path():
    assert relevance_score("", "https://x.cz/plynova-elektrarna/dokumentace") >= 1


def test_extract_mw_values():
    text = "Jaama võimsus on 49,9 MW (kaks 25 MW gaasiturbiini), lisaks 10 MWe."
    values = extract_mw_values(text)
    assert 49.9 in values and 25.0 in values and 10.0 in values


def test_mw_bucket_boundaries():
    assert mw_bucket([15.0]) == "<=20 MW"
    assert mw_bucket([20.0]) == "<=20 MW"
    assert mw_bucket([49.9]) == "<=50 MW"
    assert mw_bucket([75.0]) == "<=100 MW"
    assert mw_bucket([200.0]) == "<=200 MW"
    assert mw_bucket([450.0]) == ">200 MW"
    assert mw_bucket([]) is None
    # Largest figure wins when several are present.
    assert mw_bucket([25.0, 49.9]) == "<=50 MW"
