"""Search keywords and classification vocabularies per language.

Two roles:
- SEARCH_TERMS: fed into portal search forms / used to decide which links to
  follow while crawling.
- DOC_TYPE_TERMS: used to classify a found document (drawing / description /
  safety / infrastructure / permit).
"""

# Terms used to search portals and to score link relevance.
SEARCH_TERMS = {
    "et": [
        "gaasiturbiin", "gaasimootor", "gaasielektrijaam", "gaasijaam",
        "koostootmisjaam", "elektrijaam maagaas", "tipukoormusjaam",
    ],
    "lv": [
        "gāzes turbīna", "gāzes dzinējs", "gāzes elektrostacija",
        "koģenerācijas stacija", "termoelektrostacija",
    ],
    "lt": [
        "dujų turbina", "dujų variklis", "dujų elektrinė",
        "kogeneracinė jėgainė", "termofikacinė elektrinė",
    ],
    "fi": [
        "kaasuturbiini", "kaasumoottori", "kaasuvoimalaitos",
        "kaasumoottorivoimalaitos", "huippuvoimalaitos",
        "voimalaitos maakaasu",
    ],
    "sv": [
        "gasturbin", "gasmotor", "gaskraftverk",
        "kraftvärmeverk naturgas", "topplastverk",
    ],
    "pl": [
        "turbina gazowa", "silnik gazowy", "elektrownia gazowa",
        "elektrociepłownia gazowa", "blok gazowo-parowy",
        "jednostka kogeneracji",
    ],
    "cs": [
        "plynová turbína", "plynový motor", "plynová elektrárna",
        "paroplynová elektrárna", "kogenerační jednotka",
        "špičkový zdroj",
    ],
    "en": [
        "gas turbine", "gas engine", "gas-fired power plant",
        "OCGT", "CCGT", "peaking plant", "combined cycle",
    ],
}

# Vocabulary for classifying documents by type. Matched (lowercased,
# accent-insensitively) against link text, URL and, when possible, PDF text.
DOC_TYPE_TERMS = {
    # Joonised
    "drawing": [
        # et
        "joonis", "asendiplaan", "situatsiooniskeem", "põhijoonis",
        "tehnovõrkude joonis", "asendiskeem", "generaalplaan",
        # fi
        "asemapiirustus", "piirustus", "asemakaavakartta", "kartta",
        # sv
        "ritning", "situationsplan", "plankarta",
        # lv / lt
        "rasējums", "situācijas plāns", "brėžinys", "planas",
        # pl
        "rysunek", "plan zagospodarowania", "mapa",
        # cs
        "výkres", "situace", "situační", "koordinační",
        # en
        "drawing", "site plan", "layout", "general arrangement",
        "single line diagram", "plot plan",
    ],
    # Kirjeldused / seletuskirjad / aruanded
    "description": [
        "seletuskiri", "eskiis", "kmh aruanne", "keskkonnamõju",
        "selostus", "arviointiselostus", "arviointiohjelma",
        "beskrivning", "miljökonsekvensbeskrivning", "mkb",
        "paskaidrojuma raksts", "ietekmes uz vidi",
        "aiškinamasis raštas", "pav ataskaita", "poveikio aplinkai",
        "opis techniczny", "raport oddziaływania", "karta informacyjna",
        "technická zpráva", "dokumentace", "oznámení záměru", "posudek",
        "explanatory", "description", "eia report", "environmental impact",
        "technical report",
    ],
    # Ohutus
    "safety": [
        "ohutus", "riskianalüüs", "riskihinnang", "õnnetus", "kemikaali",
        "turvallisuus", "riskinarviointi", "onnettomuus",
        "säkerhet", "riskanalys", "riskbedömning",
        "drošība", "risku novērtējums",
        "sauga", "rizikos vertinimas", "avarij",
        "bezpieczeństwo", "analiza ryzyka", "awari",
        "bezpečnost", "analýza rizik", "havarijní",
        "seveso", "safety", "risk assessment", "hazard", "hazop", "atex",
    ],
    # Taristu / võrguühendused
    "infrastructure": [
        "taristu", "liitumine", "võrguühendus", "gaasitrass", "torustik",
        "alajaam", "ülekandeliin",
        "liityntä", "kaasuputki", "sähköasema", "voimajohto",
        "anslutning", "gasledning", "ställverk", "kraftledning",
        "pieslēgums", "gāzesvads", "apakšstacija",
        "prijungimas", "dujotiekis", "pastotė",
        "przyłącze", "gazociąg", "stacja elektroenergetyczna",
        "přípojka", "plynovod", "rozvodna",
        "grid connection", "pipeline", "substation", "interconnection",
        "transmission line",
    ],
    # Load / otsused
    "permit": [
        "luba", "keskkonnaluba", "kompleksluba", "otsus", "korraldus",
        "lupa", "päätös", "ympäristölupa",
        "tillstånd", "beslut", "miljötillstånd",
        "atļauja", "lēmums",
        "leidimas", "sprendimas", "tirpi",
        "pozwolenie", "decyzja", "decyzja środowiskowa",
        "povolení", "rozhodnutí", "závazné stanovisko", "stanovisko",
        "permit", "decision", "consent",
    ],
}

# File extensions treated as downloadable documents. DWG/DXF are CAD drawings.
DOCUMENT_EXTENSIONS = {
    ".pdf", ".dwg", ".dxf", ".zip", ".doc", ".docx", ".xls", ".xlsx",
    ".asice", ".bdoc", ".ddoc",
}

# Extensions that are drawings by definition, regardless of filename wording.
DRAWING_EXTENSIONS = {".dwg", ".dxf"}
