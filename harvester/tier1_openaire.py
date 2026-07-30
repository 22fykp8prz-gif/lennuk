"""Tier 1 — OpenAIRE Graph API (broadest first pass).

Every query is partitioned by institution × year so no single query
approaches the 10,000-result paging cap; numFound is asserted per partition
and truncation is logged, never silent. Cursor paging is used throughout.

Type vocabularies are inconsistent across providers, so the raw instance
type strings are collected into `type_raw` and normalised afterwards —
records are NOT hard-filtered by type at query time. A record is kept if
its normalised level is known OR its raw type looks thesis-like.
"""
from __future__ import annotations

import json

from .config import OPENAIRE_BASE, YEAR_FROM, YEAR_TO, Institution
from .http import HarvestError, PoliteClient
from .log import HarvestLog
from .normalize import extract_year, normalize_level
from .schema import new_record
from .scoring import apply_scoring

PAGE_SIZE = 100
HARD_CAP = 10_000

# The organizations lookup lives at a different base than researchProducts
# on some deployments (api.openaire.eu/graph/v2 answered 405 in the field);
# try the known variants in order until one answers.
ORG_ENDPOINT_CANDIDATES = [
    ("https://api.openaire.eu/graph/v2/organizations", "search"),
    ("https://api.openaire.eu/graph/v2/organizations", "legalName"),
    ("https://api.graph.openaire.eu/v2/organizations", "search"),
    ("https://api.graph.openaire.eu/v1/organizations", "search"),
    ("https://api.openaire.eu/graph/v1/organizations", "search"),
]


def resolve_org_id(names: list[str], client: PoliteClient, log: HarvestLog, institution: str) -> str | None:
    """Resolve an organisation to an OpenAIRE org id so researchProducts can
    be filtered with relOrganizationId instead of a free-text search (free
    text matches a fraction of the org's actual output).

    Tries each candidate name in turn — the registry often knows an
    institution only by its native legal name (Univerza v Ljubljani, not
    University of Ljubljana)."""
    attempts = []
    for name in names:
        name_cf = name.casefold()
        for base, param in ORG_ENDPOINT_CANDIDATES:
            try:
                res = client.get(base, params={param: name, "pageSize": 10})
                data = json.loads(res.text)
            except HarvestError as e:
                attempts.append(f"{param}={name!r} @ {base} -> {e.status or e.kind}")
                continue
            except json.JSONDecodeError as e:
                attempts.append(f"{param}={name!r} @ {base} -> not JSON ({e})")
                continue
            results = data.get("results") or []
            if not results:
                attempts.append(f"{param}={name!r} @ {base} -> 200 but 0 matches")
                continue
            best = next((o for o in results
                         if name_cf in ((o.get("legalName") or "").casefold(),
                                        (o.get("legalShortName") or "").casefold())),
                        results[0])
            org_id = best.get("id")
            log.add("openaire", f"{base} {param}={name}", "ok",
                    institution=institution, records_returned=len(results),
                    note=f"resolved org id {org_id} (legalName: {best.get('legalName')})")
            return org_id
    log.add("openaire", "organizations lookup", "failed", institution=institution,
            error="org id could not be resolved; free-text fallback in use "
                  "(coverage will be poor)",
            note="; ".join(attempts))
    return None

_THESIS_TYPE_HINTS = ["thes", "diplom", "disert", "dissert", "praca", "práce",
                      "darbs", "darbas", "töö", "tez", "delo", "лицензиат"]


def _looks_like_thesis(type_raw: str) -> bool:
    t = type_raw.casefold()
    return any(h in t for h in _THESIS_TYPE_HINTS)


def parse_product(product: dict, inst: Institution) -> dict | None:
    """Map one Graph API researchProduct to the output schema."""
    pid = product.get("id") or ""
    if not pid:
        return None

    title = (product.get("mainTitle") or "").strip() or None
    authors = [a.get("fullName", "").strip() for a in product.get("authors") or [] if a.get("fullName")]

    # Collect every type string the record carries, verbatim.
    type_strings = []
    if product.get("type"):
        type_strings.append(str(product["type"]))
    for ins in product.get("instances") or []:
        if ins.get("type"):
            type_strings.append(str(ins["type"]))
    type_raw = "; ".join(dict.fromkeys(type_strings))

    level = normalize_level(type_raw)
    if level == "unknown" and not _looks_like_thesis(type_raw):
        return None  # post-parse filter, not a query-time filter

    year = extract_year(product.get("publicationDate") or "")

    descriptions = product.get("descriptions") or []
    abstract = descriptions[0].strip() if descriptions and isinstance(descriptions[0], str) else None

    keywords = []
    for s in product.get("subjects") or []:
        v = s.get("subject", {}).get("value") if isinstance(s, dict) else None
        if v:
            keywords.append(v)

    url_landing, url_fulltext = None, None
    for ins in product.get("instances") or []:
        for u in ins.get("urls") or []:
            if url_landing is None:
                url_landing = u
            if u.lower().endswith(".pdf") and url_fulltext is None:
                url_fulltext = u

    lang = (product.get("language") or {}).get("code")

    rec = new_record(
        source="openaire",
        native_id=pid,
        title_original=title,
        authors=authors,
        year=year,
        level=level,
        level_raw=type_raw or None,
        type_raw=type_raw or None,
        institution=inst.institution_en,
        country=inst.country,
        language=lang,
        abstract=abstract,
        keywords=keywords,
        url_landing=url_landing,
        url_fulltext=url_fulltext,
    )
    return apply_scoring(rec)


def harvest_institution(
    inst: Institution,
    client: PoliteClient,
    log: HarvestLog,
    year_from: int = YEAR_FROM,
    year_to: int = YEAR_TO,
) -> list[dict]:
    """Tier-1 harvest for one institution, partitioned by year."""
    if not inst.openaire_org_name:
        log.add("openaire", OPENAIRE_BASE, "skipped", institution=inst.institution_en,
                note="no OpenAIRE organisation name configured")
        return []

    lookup_names = [n for n in (inst.openaire_org_name, inst.institution_native) if n]
    org_id = resolve_org_id(lookup_names, client, log, inst.institution_en)

    records: list[dict] = []
    for year in range(year_from, year_to + 1):
        # Prefer the org-id filter; if the API rejects it (HTTP 400), fall
        # back to free-text search for this and subsequent years.
        modes = ["org", "search"] if org_id else ["search"]
        for mode in modes:
            cursor = "*"
            endpoint_desc = f"{OPENAIRE_BASE} org={inst.openaire_org_name} year={year}" + (
                f" relOrganizationId={org_id}" if mode == "org" else " (free-text)")
            n_year = 0
            num_found = None
            try:
                while True:
                    params = {
                        "type": "publication",
                        "fromPublicationDate": f"{year}-01-01",
                        "toPublicationDate": f"{year}-12-31",
                        "pageSize": PAGE_SIZE,
                        "cursor": cursor,
                    }
                    if mode == "org":
                        params["relOrganizationId"] = org_id
                    else:
                        params["search"] = inst.openaire_org_name
                    res = client.get(OPENAIRE_BASE, params=params)
                    payload = json.loads(res.text)
                    header = payload.get("header", {})
                    num_found = int(header.get("numFound", 0))
                    for product in payload.get("results") or []:
                        rec = parse_product(product, inst)
                        if rec is not None:
                            records.append(rec)
                            n_year += 1
                    cursor = header.get("nextCursor")
                    if not cursor:
                        break
            except HarvestError as e:
                if mode == "org" and e.status == 400:
                    log.add("openaire", endpoint_desc, "failed", institution=inst.institution_en,
                            http_status=400,
                            error="relOrganizationId rejected; retrying with free-text search")
                    continue  # next mode
                log.add("openaire", endpoint_desc, "failed", institution=inst.institution_en,
                        http_status=e.status, error=f"{e.kind}: {e}")
                break
            except (json.JSONDecodeError, ValueError) as e:
                log.add("openaire", endpoint_desc, "failed", institution=inst.institution_en,
                        error=f"parse_error: {e}")
                break

            note = f"numFound={num_found}, kept {n_year} thesis-like"
            if num_found is not None and num_found >= HARD_CAP:
                note += f"; WARNING partition at/over {HARD_CAP} cap — REPARTITION (results may be truncated)"
            log.add("openaire", endpoint_desc, "ok" if n_year else "ok_empty",
                    institution=inst.institution_en, records_returned=n_year,
                    http_status=200, note=note)
            break  # this year done, no fallback needed
    return records
