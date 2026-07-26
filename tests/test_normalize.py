from harvester.normalize import extract_year, normalize_level


def test_eu_repo_semantics():
    assert normalize_level("info:eu-repo/semantics/masterThesis") == "master"
    assert normalize_level("info:eu-repo/semantics/bachelorThesis") == "bachelor"
    assert normalize_level("info:eu-repo/semantics/doctoralThesis") == "doctoral"


def test_local_languages():
    assert normalize_level("Magistritöö") == "master"
    assert normalize_level("bakalaura darbs") == "bachelor"
    assert normalize_level("Daktaro disertacija") == "doctoral"
    assert normalize_level("магистърска теза") == "master"
    assert normalize_level("Yüksek Lisans Tezi") == "master"


def test_first_cycle_traps():
    # Polish praca inżynierska and Czech bakalářská práce are first-cycle;
    # Czech/Slovak diplomová práce is the MASTER'S thesis.
    assert normalize_level("praca inżynierska") == "bachelor"
    assert normalize_level("bakalářská práce") == "bachelor"
    assert normalize_level("diplomová práce") == "master"


def test_unmatched_goes_to_unknown_not_guessed():
    assert normalize_level("konferenčný príspevok") == "unknown"
    assert normalize_level("") == "unknown"
    assert normalize_level(None) == "unknown"


def test_extract_year():
    assert extract_year("2023-06-15T08:00:00Z") == 2023
    assert extract_year("defended in 2021") == 2021
    assert extract_year("no year here") is None
