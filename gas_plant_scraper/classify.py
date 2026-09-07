"""Classification helpers: document type, MW size extraction and bucketing."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlparse

from .keywords import (
    DOC_TYPE_TERMS,
    DRAWING_EXTENSIONS,
    SEARCH_TERMS,
)

# Requested size classes (upper bounds, MW electrical).
MW_BUCKETS = [20, 50, 100, 200]

_MW_RE = re.compile(
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:MW[e]?|MVA|megavat\w*|megawat\w*)",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    """Lowercase, strip accents and normalise separators, so that
    'plynová' matches 'plynova' and 'plynova-elektrarna' matches
    'plynova elektrarna'."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[-_/+.]+", " ", text)


_FOLDED_DOC_TERMS = {
    doc_type: [_fold(t) for t in terms] for doc_type, terms in DOC_TYPE_TERMS.items()
}
_FOLDED_SEARCH_TERMS = sorted(
    {_fold(t) for terms in SEARCH_TERMS.values() for t in terms},
    key=len,
    reverse=True,
)


def classify_doc_types(text: str, url: str = "") -> list[str]:
    """Return matching document types for a link/file, e.g. ['drawing'].

    Matches against link text and the URL path; a file may belong to several
    categories (a site plan inside a safety report, for instance).
    """
    haystack = _fold(f"{text} {unquote(urlparse(url).path)}")
    types = [
        doc_type
        for doc_type, terms in _FOLDED_DOC_TERMS.items()
        if any(term in haystack for term in terms)
    ]
    ext = "." + url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
    if ext in DRAWING_EXTENSIONS and "drawing" not in types:
        types.insert(0, "drawing")
    return types


def relevance_score(text: str, url: str = "") -> int:
    """How many gas-plant search terms appear in the given text/URL."""
    haystack = _fold(f"{text} {unquote(urlparse(url).path)}")
    return sum(1 for term in _FOLDED_SEARCH_TERMS if term in haystack)


def extract_mw_values(text: str) -> list[float]:
    """All MW figures found in text, e.g. 'kaks 25 MW turbiini' -> [25.0]."""
    values = []
    for match in _MW_RE.finditer(text):
        try:
            values.append(float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
    return values


def mw_bucket(values: list[float]) -> str | None:
    """Bucket the largest plausible plant size into the requested classes.

    Returns '<=20 MW', '<=50 MW', '<=100 MW', '<=200 MW' or '>200 MW';
    None when no MW figure was found.
    """
    # Ignore obviously non-plant numbers (transformer kV misreads etc. are
    # filtered by the regex already; 0 values carry no information).
    plausible = [v for v in values if 0.1 <= v <= 5000]
    if not plausible:
        return None
    size = max(plausible)
    for bound in MW_BUCKETS:
        if size <= bound:
            return f"<={bound} MW"
    return ">200 MW"
