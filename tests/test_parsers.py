import json
from pathlib import Path

from lxml import etree

from harvester.config import Institution
from harvester import tier1_openaire
from harvester.tier2_oaipmh import OAI_NS, parse_oai_dc_record, pick_thesis_sets
from harvester.outputs import dedupe, drop_reviews

FIXTURES = Path(__file__).parent / "fixtures"

TALTECH = Institution(
    country="EE", institution_id="taltech",
    institution_en="Tallinn University of Technology",
    institution_native="Tallinna Tehnikaülikool", tier="A",
    repo_base_url="https://example-repo.invalid", repo_software_hint="dspace",
    openaire_org_name="Tallinn University of Technology",
    national_system="", yok_university_name="", pilot=True, notes="",
)

POLSL = Institution(
    country="PL", institution_id="polsl",
    institution_en="Silesian University of Technology",
    institution_native="Politechnika Śląska", tier="A",
    repo_base_url="https://example-repo.invalid", repo_software_hint="dlibra",
    openaire_org_name="Silesian University of Technology",
    national_system="", yok_university_name="", pilot=True, notes="",
)


def _fixture_records():
    root = etree.fromstring((FIXTURES / "oai_listrecords_dspace.xml").read_bytes())
    return root.findall(".//oai:record", OAI_NS)


def test_oai_dc_parse_verbatim():
    recs = [parse_oai_dc_record(r, TALTECH, "https://example-repo.invalid/oai/request")
            for r in _fixture_records()]
    recs = [r for r in recs if r]
    assert len(recs) == 2  # deleted record dropped, old record still parsed (year filter is downstream)

    r = recs[0]
    # Verbatim: diacritics intact, no transliteration.
    assert r["title_original"] == "Akusalvesti kasutamine sagedusreservi pakkumiseks Eesti elektrisüsteemis"
    assert r["authors"] == ["Tamm, Märt"]
    assert r["advisor"] == "Kask, Jaan"
    assert r["year"] == 2023
    assert r["level"] == "master"
    assert "masterThesis" in r["level_raw"]
    assert r["language"] == "et"
    assert r["url_landing"] == "https://example-repo.invalid/handle/123456789/1001"
    assert r["url_fulltext"].endswith(".pdf")
    assert r["keywords"] == ["sagedusreserv", "akusalvesti"]
    # Scoring ran: storage + frequency reserve + EE flags (Elering, sagedusreserv)
    assert "storage" in r["domain_flags"]
    assert "Elering" in r["national_flags"]
    assert r["relevance_score"] > 0


def test_openaire_parse_and_type_filter():
    payload = json.loads((FIXTURES / "openaire_page.json").read_text())
    recs = [tier1_openaire.parse_product(p, POLSL) for p in payload["results"]]
    kept = [r for r in recs if r]
    assert len(kept) == 1  # the journal article is dropped post-parse
    r = kept[0]
    assert r["level"] == "master"
    assert r["type_raw"] == "publication; Master thesis"
    assert r["year"] == 2022
    assert r["url_fulltext"].endswith(".pdf")
    assert "rynek mocy" in r["national_flags"]


def test_pick_thesis_sets():
    sets = [
        {"setSpec": "com_123", "setName": "Lõputööd"},
        {"setSpec": "com_456", "setName": "Journal articles"},
        {"setSpec": "col_789", "setName": "Master theses"},
    ]
    assert pick_thesis_sets(sets) == ["com_123", "col_789"]


def test_drop_reviews_filters_referee_reports():
    thesis = {"title_original": "Rozprawa doktorska o magazynach energii",
              "type_raw": "rozprawa doktorska"}
    review = {"title_original": "Recenzja rozprawy doktorskiej mgra inż. Jana Kowalskiego",
              "type_raw": None}
    posudek = {"title_original": "Posudek oponenta diplomové práce", "type_raw": "posudek"}
    kept, dropped = drop_reviews([thesis, review, posudek])
    assert kept == [thesis]
    assert dropped == 2


def test_dedupe_prefers_richer_source_and_merges():
    a = {"id": "1", "source": "openaire", "title_original": "Sama Töö", "year": 2022,
         "institution": "X", "advisor": None, "abstract": "abs from openaire"}
    b = {"id": "2", "source": "oai-pmh:https://x/oai", "title_original": "sama töö",
         "year": 2022, "institution": "X", "advisor": "Someone", "abstract": None}
    out = dedupe([a, b])
    assert len(out) == 1
    r = out[0]
    assert r["source"].startswith("oai-pmh")   # richer source wins
    assert r["advisor"] == "Someone"
    assert r["abstract"] == "abs from openaire"  # gap filled from the other source
