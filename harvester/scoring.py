"""Relevance scoring: domain terms + national-context flags.

Two independent signals, both stored. No thresholding at harvest time — a
low score is a filtering decision for later, not a harvesting decision now.

relevance_score = (# distinct domain-term tags matched)
                + 2 * (# distinct national flags matched)

National flags are weighted because a thesis naming its own TSO / market
instrument / asset is almost always modelling something real.

Matching: terms of <=4 characters (acronyms like FCR, PSE, AST) match only
on word boundaries; longer terms match as casefolded substrings so
inflected forms in the source languages still hit.
"""
from __future__ import annotations

import re

# tag -> list of multilingual surface forms (seed list from the brief;
# extend per language as coverage grows).
DOMAIN_TERMS: dict[str, list[str]] = {
    "storage": [
        "energy storage", "battery", "BESS", "akusalvesti", "salvestustehnoloogia",
        "akumulācija", "kaupimo įrenginys", "magazyn energii", "magazynu energii",
        "magazyny energii", "magazynów energii", "magazynem energii", "akumulace energie",
        "akumulácia energie", "hranilnik energije", "stocare energie",
        "съхранение на енергия", "enerji depolama", "battery energy storage",
    ],
    "frequency_reserve": [
        "frequency reserve", "ancillary service", "FCR", "aFRR", "mFRR",
        "sagedusreserv", "jaudas rezerve", "dažnio rezervas", "usługi systemowe",
        "usług systemowych", "usługami systemowymi",
        "podpůrné služby", "podpůrných služeb", "podporné služby", "sistemske storitve",
        "servicii de sistem", "primary reserve", "balancing reserve",
    ],
    "grid_connection": [
        "grid connection", "liitumine", "przyłączenie do sieci", "przyłączenia do sieci",
        "przyłączeniem do sieci", "připojení do sítě",
        "pripojenie do siete", "priključitev", "racordare la rețea",
        "присъединяване", "bağlantı", "interconnection request",
    ],
    "stability": [
        "power system stability", "voltage stability", "frequency stability",
        "transient stability", "elektrisüsteem", "elektros sistema",
        "inertia", "grid stability",
    ],
    "power_electronics": [
        "inverter", "converter", "power conversion system", "PCS",
        "grid-forming", "grid following", "muundur",
    ],
    "capacity_market": [
        "capacity market", "rynek mocy", "rynku mocy", "rynkiem mocy", "capacity mechanism",
        "kapasite mekanizması", "capacity remuneration",
    ],
    "electricity_market": [
        "day-ahead", "intraday", "balancing market", "electricity market",
        "elektrituru", "elektriturg", "elektroenerģijas tirgus",
        "elektros rinka", "trh s elektřinou", "trh s elektrinou",
        "trg z električno energijo", "piața de echilibrare", "piata de echilibrare",
        "балансиращ пазар", "dengeleme", "bilansihaldus", "bilansowanie",
        "elektrik piyasası", "PPA", "power purchase agreement",
    ],
    "wind": ["wind power", "wind energy", "wind farm", "tuulepark", "tuuleenergia",
             "vēja", "vėjo", "energetyka wiatrowa", "farma wiatrowa",
             "větrná", "veterná", "vetrna", "eoliană", "eoliana",
             "вятърна", "rüzgar", "offshore wind"],
    "solar": ["photovoltaic", "solar power", "päikeseenergia", "päikesepark",
              "saules", "saulės", "fotowoltai", "fotovoltai", "fotovolta",
              "фотоволта", "güneş enerjisi", "PV system", "PV plant"],
    "hydrogen": ["hydrogen", "electrolyser", "electrolyzer", "vesinik",
                 "ūdeņradis", "vandenilis", "wodór", "wodor", "vodík", "vodik",
                 "hidrogen", "водород", "hidrojen", "power-to-gas"],
    "thermal_gen": ["gas turbine", "gas engine", "combined cycle", "CHP",
                    "cogeneration", "koostootmis", "kogeneracja", "kogenerace"],
    "load": ["data centre", "data center", "demand response", "demand side",
             "talep tarafı", "andmekeskus", "load forecasting"],
    "congestion": ["congestion", "curtailment", "redispatch", "ülekandevõimsus"],
    "substation": ["substation", "HV substation", "alajaam", "apakšstacija",
                   "pastotė", "stacja elektroenergetyczna", "rozdzielnia",
                   "transformovna", "rozvodňa", "trafo merkezi"],
}

# country -> {canonical flag: [surface forms]}. The canonical name is what
# lands in `national_flags`; surface forms cover inflection and
# diacritic-stripped spellings.
NATIONAL_FLAGS: dict[str, dict[str, list[str]]] = {
    "EE": {"Elering": ["Elering"], "Kiisa": ["Kiisa"], "Estlink": ["Estlink"],
           "sagedusreserv": ["sagedusreserv"], "Narva": ["Narva"],
           "Auvere": ["Auvere"], "Tsirguliina": ["Tsirguliina"]},
    "LV": {"AST": ["AST"], "Latvenergo": ["Latvenergo"],
           "Inčukalns": ["Inčukalns", "Incukalns", "Inčukalna"],
           "Daugava HPP": ["Daugava HPP", "Daugavas HES"],
           "Kurzeme Ring": ["Kurzeme Ring", "Kurzemes loks", "Kurzemes loka"]},
    "LT": {"Litgrid": ["Litgrid"], "NordBalt": ["NordBalt"], "LitPol": ["LitPol"],
           "Kruonis": ["Kruonis", "Kruonio"], "Ignalina": ["Ignalina", "Ignalinos"],
           "Ignitis": ["Ignitis"]},
    "PL": {"PSE": ["PSE"], "rynek mocy": ["rynek mocy", "rynku mocy", "rynkiem mocy"],
           "KSE": ["KSE"], "Żarnowiec": ["Żarnowiec", "Zarnowiec", "Żarnowcu"],
           "Kozienice": ["Kozienice", "Kozienicach"],
           "Bełchatów": ["Bełchatów", "Belchatow", "Bełchatowie"],
           "Enea": ["Enea"], "Tauron": ["Tauron"], "PGE": ["PGE"],
           "Baltic Power": ["Baltic Power"]},
    "CZ": {"ČEPS": ["ČEPS", "CEPS"], "ČEZ": ["ČEZ"],
           "Dukovany": ["Dukovany", "Dukovan"], "Temelín": ["Temelín", "Temelin"],
           "Dlouhé Stráně": ["Dlouhé Stráně", "Dlouhe Strane", "Dlouhých Strání"],
           "EGD": ["EGD"]},
    "SK": {"SEPS": ["SEPS"],
           "Slovenské elektrárne": ["Slovenské elektrárne", "Slovenske elektrarne", "Slovenských elektrární"],
           "Mochovce": ["Mochovce", "Mochoviec"],
           "Gabčíkovo": ["Gabčíkovo", "Gabcikovo", "Gabčíkova"],
           "Čierny Váh": ["Čierny Váh", "Cierny Vah", "Čierneho Váhu"]},
    "SI": {"ELES": ["ELES"], "GEN-I": ["GEN-I"], "Krško": ["Krško", "Krsko", "Krškem"],
           "Šoštanj": ["Šoštanj", "Sostanj", "Šoštanju"], "Avče": ["Avče", "Avce"],
           "Borzen": ["Borzen"]},
    "RO": {"Transelectrica": ["Transelectrica"], "Hidroelectrica": ["Hidroelectrica"],
           "Cernavodă": ["Cernavodă", "Cernavoda"], "Oltenia": ["Oltenia"],
           "Porțile de Fier": ["Porțile de Fier", "Portile de Fier"],
           "Dobrogea": ["Dobrogea"]},
    "BG": {"ESO EAD": ["ESO EAD"], "NEK": ["NEK", "НЕК"],
           "Kozloduy": ["Kozloduy", "Козлодуй"],
           "Maritsa East": ["Maritsa East", "Марица изток", "Марица-изток"],
           "Chaira": ["Chaira", "Чаира"], "Belene": ["Belene", "Белене"]},
    "TR": {"TEİAŞ": ["TEİAŞ", "TEIAS"], "EPİAŞ": ["EPİAŞ", "EPIAS"],
           "EÜAŞ": ["EÜAŞ", "EUAS"], "YEKA": ["YEKA"], "YEKDEM": ["YEKDEM"],
           "kapasite mekanizması": ["kapasite mekanizması", "kapasite mekanizmasi"],
           "Akkuyu": ["Akkuyu"], "Karapınar": ["Karapınar", "Karapinar"],
           "Keban": ["Keban"]},
}

NATIONAL_FLAG_WEIGHT = 2


def _matches(term: str, text_cf: str, text_orig: str) -> bool:
    if len(term) <= 4:
        # Short terms / acronyms: word-boundary, case-sensitive for
        # all-caps acronyms (AST/PSE/NEK would otherwise fire on ordinary
        # words), case-insensitive otherwise.
        flags = 0 if term.isupper() else re.IGNORECASE
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text_orig, flags) is not None
    return term.casefold() in text_cf


def score_text(text: str, country: str | None = None) -> tuple[list[str], list[str], int]:
    """Return (domain_flags, national_flags, relevance_score) for a blob of
    title + abstract + keywords. If `country` is given, only that country's
    national flags are checked (avoids cross-language acronym noise)."""
    text = text or ""
    text_cf = text.casefold()

    domain = [
        tag
        for tag, terms in DOMAIN_TERMS.items()
        if any(_matches(t, text_cf, text) for t in terms)
    ]

    countries = [country] if country and country in NATIONAL_FLAGS else list(NATIONAL_FLAGS)
    national = []
    for c in countries:
        for canonical, variants in NATIONAL_FLAGS[c].items():
            if canonical not in national and any(_matches(v, text_cf, text) for v in variants):
                national.append(canonical)

    score = len(domain) + NATIONAL_FLAG_WEIGHT * len(national)
    return domain, national, score


def apply_scoring(rec: dict) -> dict:
    """Score a schema record in place from title/abstract/keywords."""
    parts = [
        rec.get("title_original") or "",
        rec.get("title_en") or "",
        rec.get("abstract") or "",
        " ".join(rec.get("keywords") or []),
    ]
    domain, national, s = score_text("\n".join(parts), rec.get("country"))
    rec["domain_flags"] = domain
    rec["national_flags"] = national
    rec["relevance_score"] = s
    return rec
