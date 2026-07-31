from harvester.flags import FlagMatcher, normalize


def matcher():
    return FlagMatcher()


def test_normalize_latin_diacritics_stripped_cyrillic_untouched():
    assert normalize("Balansēšanas tirgus õÕ ąŞč") == "balansesanas tirgus oo asc"
    assert normalize("студен резерв НЕБАЛАНС") == "студен резерв небаланс"


def test_normalize_turkish_casefold():
    # İ casefolds to i + combining dot; the dot is stripped after a Latin base.
    assert normalize("GÜN İÇİ PİYASA") == "gun ici piyasa"


def test_strong_stems_survive_inflection():
    m = matcher()
    fired = m.match("Analiza rynku mocy w Polsce")
    assert "capacity_market" in fired
    fired = m.match("Balansēšanas tirgus attīstība Latvijā")
    assert "frequency_reserves" in fired
    fired = m.match("Оценка на студен резерв в българската електроенергийна система")
    assert "capacity_market" in fired


def test_acronyms_case_sensitive_with_boundaries():
    m = matcher()
    assert "frequency_reserves" in m.match("Participation in aFRR markets")
    assert "frequency_reserves" in m.match("AFRR product design")     # uppercased variant
    assert m.match("Pablo Picasso and modern art") == {}              # not PICASSO
    assert "frequency_reserves" in m.match("The PICASSO platform for aFRR")
    assert m.match("terre des hommes") == {}                          # not TERRE
    assert m.match("a cone-shaped structure") == {}                   # not CONE


def test_weak_stems_require_energy_context():
    m = matcher()
    # dengeleme alone (generic Turkish "balancing") must not fire...
    assert m.match("Örgütlerde iş ve yaşam dengeleme stratejileri") == {}
    # ...but fires alongside an energy-context stem
    fired = m.match("Elektrik piyasasında dengeleme mekanizmaları")
    assert "frequency_reserves" in fired
    # CZ 'přiměřenost' (also legal 'reasonableness') gated the same way
    assert m.match("Přiměřenost trestní sankce") == {}
    assert "adequacy_selfsufficiency" in m.match(
        "Přiměřenost výrobních kapacit v energetice")


def test_flags_are_independent_and_overlap():
    m = matcher()
    fired = m.match(
        "Design of the balancing market and aFRR procurement in the energy sector")
    assert "frequency_reserves" in fired
    # audit trail names the triggering terms
    assert any("aFRR" in t for t in fired["frequency_reserves"])


def test_record_uses_both_languages():
    m = matcher()
    rec = {
        "title_original": "Elektrienergia varustuskindlus Eestis",
        "title_en": "Security of supply of electricity in Estonia",
        "abstract": None,
        "keywords": [],
    }
    fired = m.flag_record(rec)
    assert "adequacy_selfsufficiency" in fired
