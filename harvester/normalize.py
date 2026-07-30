"""Degree-level normalisation.

Everything unmatched goes to `unknown` — never guessed. The raw string is
always preserved in `level_raw` so mappings can be re-derived later.

Known traps encoded below:
- Polish `praca inżynierska` and `praca licencjacka` are first-cycle.
- Czech/Slovak `diplomová práce` is the *master's* thesis.
- Slovenian `diplomsko delo` can be first or second cycle depending on era
  and programme; it maps to bachelor here (post-Bologna majority) but the
  raw string is kept precisely so this can be revisited.
"""
from __future__ import annotations

import re

# Ordered: first match wins. Patterns are matched case-insensitively as
# substrings of the raw type/level string.
_LEVEL_PATTERNS: list[tuple[str, str]] = [
    # eu-repo semantics / English (common in DSpace oai_dc dc:type)
    ("info:eu-repo/semantics/bachelorthesis", "bachelor"),
    ("info:eu-repo/semantics/masterthesis", "master"),
    ("info:eu-repo/semantics/doctoralthesis", "doctoral"),
    ("bachelor's thesis", "bachelor"),
    ("bachelor thesis", "bachelor"),
    ("bachelorthesis", "bachelor"),
    ("master's thesis", "master"),
    ("master thesis", "master"),
    ("masterthesis", "master"),
    ("doctoral thesis", "doctoral"),
    ("doctoralthesis", "doctoral"),
    ("phd thesis", "doctoral"),
    ("dissertation", "doctoral"),
    # Estonian
    ("bakalaureusetöö", "bachelor"),
    ("magistritöö", "master"),
    ("doktoritöö", "doctoral"),
    # Latvian
    ("bakalaura darbs", "bachelor"),
    ("maģistra darbs", "master"),
    ("magistra darbs", "master"),
    ("promocijas darbs", "doctoral"),
    # Lithuanian
    ("bakalauro darbas", "bachelor"),
    ("magistro darbas", "master"),
    ("magistro baigiamasis darbas", "master"),
    ("daktaro disertacija", "doctoral"),
    # Polish (nominative + genitive, which appears in type/degree phrases)
    ("praca licencjacka", "bachelor"),
    ("pracy licencjackiej", "bachelor"),
    ("praca inżynierska", "bachelor"),
    ("praca inzynierska", "bachelor"),
    ("pracy inżynierskiej", "bachelor"),
    ("praca magisterska", "master"),
    ("pracy magisterskiej", "master"),
    ("rozprawa doktorska", "doctoral"),
    ("rozprawy doktorskiej", "doctoral"),
    ("praca doktorska", "doctoral"),
    ("pracy doktorskiej", "doctoral"),
    # Czech / Slovak
    ("bakalářská práce", "bachelor"),
    ("bakalarska praca", "bachelor"),
    ("bakalárska práca", "bachelor"),
    ("diplomová práce", "master"),
    ("diplomová práca", "master"),
    ("diplomova praca", "master"),
    ("dizertační práce", "doctoral"),
    ("dizertačná práca", "doctoral"),
    # Slovenian (see module docstring for the diplomsko delo caveat)
    ("magistrsko delo", "master"),
    ("magistrska naloga", "master"),
    ("diplomsko delo", "bachelor"),
    ("diplomska naloga", "bachelor"),
    ("doktorska disertacija", "doctoral"),
    # Romanian
    ("lucrare de licență", "bachelor"),
    ("lucrare de licenta", "bachelor"),
    ("lucrare de disertație", "master"),
    ("disertație", "master"),
    ("disertatie", "master"),
    ("teză de doctorat", "doctoral"),
    ("teza de doctorat", "doctoral"),
    # Bulgarian
    ("дипломна работа", "bachelor"),
    ("магистърска теза", "master"),
    ("дисертация", "doctoral"),
    # Turkish (YÖK "Tez Türü" values)
    ("yüksek lisans", "master"),
    ("yuksek lisans", "master"),
    ("doktora", "doctoral"),
]


def normalize_level(raw: str | None) -> str:
    """Map a raw degree-level/type string to bachelor/master/doctoral/unknown."""
    if not raw:
        return "unknown"
    text = raw.casefold()
    for pattern, level in _LEVEL_PATTERNS:
        if pattern in text:
            return level
    return "unknown"


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def extract_year(raw: str | None) -> int | None:
    """Pull a plausible defence/publication year out of a date string."""
    if not raw:
        return None
    m = _YEAR_RE.search(raw)
    return int(m.group(0)) if m else None
