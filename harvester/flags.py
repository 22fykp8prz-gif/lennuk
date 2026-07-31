"""Market-domain flags: frequency_reserves, capacity_market,
adequacy_selfsufficiency, market_design.

Implements the matching rules from the domain-flags reference notes,
exactly:

- stems are substrings, matched after Unicode casefold + diacritic
  stripping applied to LATIN letters only (Cyrillic untouched; Turkish
  İ/ı behave because casefold runs first);
- acronyms match with word boundaries on the original, non-normalized
  text, case-sensitive as listed plus a fully-uppercased variant
  (aFRR also matches AFRR; PICASSO must not match the painter);
- weak stems only count when an energy_context stem also appears;
- every fired flag records which terms triggered it (the audit trail);
- the YAML version is logged with each flagged thesis so re-runs are
  comparable.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

FLAGS_PATH = PROJECT_ROOT / "thesis_domain_flags.yaml"

FLAG_NAMES = [
    "frequency_reserves",
    "capacity_market",
    "adequacy_selfsufficiency",
    "market_design",
]


def normalize(text: str) -> str:
    """Casefold, then strip diacritics from Latin letters only.

    õ→o, ą→a, ş→s, č→c ... while Cyrillic (студен, небаланс) is left
    untouched. Characters like ł/đ have no combining decomposition and
    stay as-is on both sides of the comparison, which is symmetric and
    therefore safe.
    """
    text = text.casefold()
    out: list[str] = []
    last_base_is_latin = False
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch):
            if last_base_is_latin:
                continue  # strip the diacritic
            out.append(ch)
        else:
            try:
                last_base_is_latin = unicodedata.name(ch).startswith("LATIN")
            except ValueError:
                last_base_is_latin = False
            out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


class FlagMatcher:
    def __init__(self, spec_path: Path = FLAGS_PATH):
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        self.version = str(spec.get("version", "unversioned"))
        self.context_stems = [normalize(s) for s in spec["energy_context"]["stems"]]
        self.flags: dict[str, dict] = {}
        for name, groups in spec["flags"].items():
            strong = [(s, normalize(s)) for s in groups.get("strong") or []]
            weak = [(s, normalize(s)) for s in groups.get("weak") or []]
            acronyms = []
            for a in groups.get("acronyms") or []:
                variants = {a, a.upper()}
                pattern = re.compile(
                    "|".join(rf"(?<!\w){re.escape(v)}(?!\w)" for v in sorted(variants))
                )
                acronyms.append((a, pattern))
            self.flags[name] = {"strong": strong, "weak": weak, "acronyms": acronyms}

    def match(self, text: str) -> dict[str, list[str]]:
        """Return {flag_name: [triggering terms]} for a text blob
        (title + abstract + keywords, original + English when present)."""
        if not text:
            return {}
        norm = normalize(text)
        has_context = any(c in norm for c in self.context_stems)

        fired: dict[str, list[str]] = {}
        for name, groups in self.flags.items():
            hits: list[str] = []
            for natural, stem in groups["strong"]:
                if stem in norm:
                    hits.append(natural)
            if has_context:
                for natural, stem in groups["weak"]:
                    if stem in norm:
                        hits.append(f"{natural} (weak)")
            for acr, pattern in groups["acronyms"]:
                if pattern.search(text):
                    hits.append(acr)
            if hits:
                fired[name] = hits
        return fired

    def flag_record(self, rec: dict) -> dict[str, list[str]]:
        """Match against a schema record's title/abstract/keywords in both
        the original language and the English translation when present.
        Tolerates NaN/None/array values from parquet round-trips."""
        def as_str(v) -> str:
            return v if isinstance(v, str) else ""

        keywords = rec.get("keywords")
        if keywords is None or isinstance(keywords, float):
            keywords = []
        parts = [
            as_str(rec.get("title_original")),
            as_str(rec.get("title_en")),
            as_str(rec.get("abstract")),
            " ".join(as_str(k) for k in keywords),
        ]
        return self.match("\n".join(p for p in parts if p))
