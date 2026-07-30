"""Tier 2 — direct OAI-PMH harvesting per repository.

Endpoints are discovered, not hardcoded: conventional DSpace/dLibra/EPrints
paths are probed with ?verb=Identify. Sets and metadata formats are listed
and logged in full so a human can pick the right sets for ambiguous cases.
ListRecords follows resumptionToken to exhaustion; every raw page is cached
to disk by PoliteClient before parsing.
"""
from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from .config import YEAR_FROM, YEAR_TO, Institution
from .http import HarvestError, PoliteClient
from .log import HarvestLog
from .normalize import extract_year, normalize_level
from .schema import new_record
from .scoring import apply_scoring

OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

# Conventional endpoint paths, most common first. DSpace 6/7, dLibra,
# EPrints, OMEGA-PSIR.
CANDIDATE_PATHS = [
    "/oai/request",
    "/server/oai/request",
    "/oai/driver",
    "/oai/openaire",
    "/dlibra/oai-pmh-repository.xml",
    "/oai-pmh-repository.xml",
    "/cgi/oai2",
    "/oai",
]

THESIS_SET_HINTS = [
    "thes", "lõputö", "loputo", "magistr", "diplom", "dyplom", "prace",
    "práce", "zaverecne", "závěrečné", "graduation", "etd", "disert",
    "dissert", "doktor", "rozpraw", "baigiam",
]


def discover_endpoint(base_url: str, client: PoliteClient, log: HarvestLog, institution: str) -> dict | None:
    """Probe candidate OAI paths; return {'endpoint', 'repository_name', ...}
    for the first that answers Identify, logging every failed probe."""
    base = base_url.rstrip("/")
    probe_summary = []
    for path in CANDIDATE_PATHS:
        url = f"{base}{path}"
        try:
            res = client.get(url, params={"verb": "Identify"}, allow_error_status=True)
        except HarvestError as e:
            probe_summary.append(f"{path}={e.kind}")
            log.add("oai-pmh", f"{url}?verb=Identify", "failed", institution=institution,
                    http_status=e.status, error=f"{e.kind}: {e}")
            if e.kind == "egress_blocked":
                # Same host for every candidate path — no point probing the rest.
                return None
            continue
        if res.status != 200:
            probe_summary.append(f"{path}=HTTP {res.status}")
            continue
        try:
            root = etree.fromstring(res.body)
        except etree.XMLSyntaxError:
            probe_summary.append(f"{path}=200 but not XML")
            continue
        ident = root.find(".//oai:Identify", OAI_NS)
        if ident is None:
            probe_summary.append(f"{path}=XML but no Identify")
            continue
        name = ident.findtext("oai:repositoryName", default="", namespaces=OAI_NS)
        info = {"endpoint": url, "repository_name": name}
        log.add("oai-pmh", f"{url}?verb=Identify", "ok", institution=institution,
                http_status=200, note=f"Identify OK: {name}")
        return info
    log.add("oai-pmh", base_url, "failed", institution=institution,
            error="no OAI-PMH endpoint discovered",
            note="probe results: " + "; ".join(probe_summary))
    return None


def _list_verb(endpoint: str, client: PoliteClient, verb: str, item_xpath: str, **params):
    """Generic OAI list verb with resumptionToken paging. Yields elements."""
    query: dict = {"verb": verb, **params}
    while True:
        res = client.get(endpoint, params=query)
        root = etree.fromstring(res.body)
        err = root.find("oai:error", OAI_NS)
        if err is not None:
            code = err.get("code", "")
            if code in ("noRecordsMatch", "noSetHierarchy"):
                return
            raise HarvestError("http_error", f"OAI error {code}: {err.text}")
        yield from root.findall(item_xpath, OAI_NS)
        token_el = root.find(f".//oai:{verb}/oai:resumptionToken", OAI_NS)
        token = (token_el.text or "").strip() if token_el is not None else ""
        if not token:
            return
        query = {"verb": verb, "resumptionToken": token}


def list_sets(endpoint: str, client: PoliteClient) -> list[dict]:
    return [
        {"setSpec": s.findtext("oai:setSpec", default="", namespaces=OAI_NS),
         "setName": s.findtext("oai:setName", default="", namespaces=OAI_NS)}
        for s in _list_verb(endpoint, client, "ListSets", ".//oai:set")
    ]


def list_metadata_formats(endpoint: str, client: PoliteClient) -> list[str]:
    return [
        f.findtext("oai:metadataPrefix", default="", namespaces=OAI_NS)
        for f in _list_verb(endpoint, client, "ListMetadataFormats", ".//oai:metadataFormat")
    ]


def pick_thesis_sets(sets: list[dict]) -> list[str]:
    """Heuristic pick of thesis-looking sets; ambiguous cases stay for a
    human (the full list is persisted next to the raw cache)."""
    picked = []
    for s in sets:
        # dLibra advertises ":criteria" pseudo-sets that reject ListRecords.
        if s["setSpec"].endswith(":criteria"):
            continue
        blob = f"{s['setSpec']} {s['setName']}".casefold()
        if any(h in blob for h in THESIS_SET_HINTS):
            picked.append(s["setSpec"])
    return picked


def _texts(md, tag: str) -> list[str]:
    return [e.text.strip() for e in md.findall(f"dc:{tag}", OAI_NS) if e.text and e.text.strip()]


def parse_oai_dc_record(rec_el, inst: Institution, endpoint: str) -> dict | None:
    """Map one <record> (oai_dc) to the output schema. Verbatim metadata."""
    header = rec_el.find("oai:header", OAI_NS)
    if header is None or header.get("status") == "deleted":
        return None
    identifier = header.findtext("oai:identifier", default="", namespaces=OAI_NS)
    md = rec_el.find(".//oai_dc:dc", OAI_NS)
    if md is None:
        return None

    titles = _texts(md, "title")
    creators = _texts(md, "creator")
    contributors = _texts(md, "contributor")
    types = _texts(md, "type")
    dates = _texts(md, "date")
    identifiers = _texts(md, "identifier")
    descriptions = _texts(md, "description")
    languages = _texts(md, "language")

    year = None
    for d in dates:
        y = extract_year(d)
        if y and (year is None or y < year):
            year = y  # earliest plausible year ~ defence year, not embargo lift

    url_landing = next((i for i in identifiers if i.startswith("http")), None)
    url_fulltext = next((i for i in identifiers if i.startswith("http") and i.lower().endswith(".pdf")), None)

    type_raw = "; ".join(types)
    level = normalize_level(type_raw)

    rec = new_record(
        source=f"oai-pmh:{endpoint}",
        native_id=identifier,
        title_original=titles[0] if titles else None,
        title_en=titles[1] if len(titles) > 1 else None,  # second dc:title is usually the parallel title; verify per repo
        authors=creators,
        advisor="; ".join(contributors) if contributors else None,
        year=year,
        level=level,
        level_raw=type_raw or None,
        type_raw=type_raw or None,
        institution=inst.institution_en,
        country=inst.country,
        language=languages[0] if languages else None,
        abstract=descriptions[0] if descriptions else None,
        keywords=_texts(md, "subject"),
        url_landing=url_landing or (identifier if identifier.startswith("http") else None),
        url_fulltext=url_fulltext,
    )
    return apply_scoring(rec)


def harvest_institution(
    inst: Institution,
    client: PoliteClient,
    log: HarvestLog,
    meta_dir: Path,
    year_from: int = YEAR_FROM,
    year_to: int = YEAR_TO,
) -> list[dict]:
    """Full tier-2 harvest for one institution. Returns schema records.

    Every failure is logged; an unreachable repository yields zero rows and
    an explicit failure line, never silence.
    """
    if not inst.repo_base_url:
        log.add("oai-pmh", "", "skipped", institution=inst.institution_en,
                note="no repository base URL configured")
        return []

    info = discover_endpoint(inst.repo_base_url, client, log, inst.institution_en)
    if info is None:
        return []  # discover_endpoint already logged the per-path probe results
    endpoint = info["endpoint"]

    meta_dir.mkdir(parents=True, exist_ok=True)
    try:
        formats = list_metadata_formats(endpoint, client)
        sets = list_sets(endpoint, client)
    except HarvestError as e:
        log.add("oai-pmh", endpoint, "failed", institution=inst.institution_en,
                http_status=e.status, error=f"{e.kind}: {e}")
        return []
    # Persist the full set list — a human picks the right sets for ambiguous cases.
    (meta_dir / f"{inst.institution_id}_oai_meta.json").write_text(
        json.dumps({"identify": info, "metadata_formats": formats, "sets": sets},
                   ensure_ascii=False, indent=2)
    )

    prefix = "oai_dc" if "oai_dc" in formats or not formats else formats[0]
    thesis_sets = pick_thesis_sets(sets) or [None]  # None = harvest whole repo

    records: list[dict] = []
    for set_spec in thesis_sets:
        params = {"metadataPrefix": prefix}
        if set_spec:
            params["set"] = set_spec
        n_before = len(records)
        try:
            for rec_el in _list_verb(endpoint, client, "ListRecords", ".//oai:record", **params):
                rec = parse_oai_dc_record(rec_el, inst, endpoint)
                if rec is None:
                    continue
                if rec["year"] is not None and not (year_from <= rec["year"] <= year_to):
                    continue
                records.append(rec)
        except HarvestError as e:
            log.add("oai-pmh", f"{endpoint} set={set_spec}", "failed",
                    institution=inst.institution_en, http_status=e.status,
                    error=f"{e.kind}: {e}")
            continue
        n = len(records) - n_before
        log.add("oai-pmh", f"{endpoint} set={set_spec}", "ok" if n else "ok_empty",
                institution=inst.institution_en, records_returned=n,
                http_status=200, note=f"metadataPrefix={prefix}, years {year_from}-{year_to}")

    # De-dup identical OAI identifiers across overlapping sets.
    seen: set[str] = set()
    deduped = []
    for r in records:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        deduped.append(r)
    return deduped
