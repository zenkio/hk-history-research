"""Persist claim-level evidence and judgements as validated, auditable JSONL records."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from research_records import require_valid_record
from state import atomic_write

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS_DIR = PROJECT_ROOT / "research" / "records"
INSPECTABLE_STATUSES = {"inspectable_text", "inspectable_abstract", "inspectable_record"}


def slug(value):
    value = value.lower().replace("\\", "-").replace("/", "-")
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


def event_id_for_relative_path(relative_path):
    return "event:" + slug(Path(relative_path).with_suffix("").as_posix())


def normalize_claim_text(text):
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text))
    value = re.sub(r"[*_~]", "", value)
    value = re.sub(r"^(?:❔|\[[ xX]\])\s*", "", value)
    return re.sub(r"\s+", " ", value).strip()


def claim_id_for(event_id, text):
    normalized = normalize_claim_text(text).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return f"claim:{event_id.removeprefix('event:')}-{digest}"


def source_id_for(url):
    return "source:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
    return rows


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write(str(path), content)


def _upsert(path, rows, key):
    current = _read_jsonl(path)
    positions = {row[key]: index for index, row in enumerate(current) if key in row}
    for row in rows:
        row = require_valid_record(row)
        identity = row[key]
        if identity in positions:
            index = positions[identity]
            previous = current[index]
            if row.get("record_type") == "source":
                row["event_ids"] = sorted(set(previous.get("event_ids", []) + row.get("event_ids", [])))
            current[index] = {**previous, **row}
        else:
            positions[identity] = len(current)
            current.append(row)
    _write_jsonl(path, current)


def _source_metadata(candidate, event_id, timestamp):
    url = str(candidate.get("url") or "").strip()
    if not url:
        return None
    source_name = str(candidate.get("source") or "Unknown source")
    allowed_types = {
        "government_record", "archive_record", "contemporary_publication", "academic_work",
        "institutional_collection", "specialist_collection", "community_source", "reference", "other",
    }
    allowed_authorities = {"primary", "scholarly", "institutional", "specialist", "discovery_only", "unknown"}
    allowed_methods = {"api", "web", "ocr", "manual", "metadata_only", "imported", "other"}

    # Prefer the registry's explicit source-family metadata. Fall back to the legacy
    # mapping for old candidates and test fixtures that predate registry provenance.
    source_type = candidate.get("source_type")
    authority = candidate.get("authority_level")
    method = candidate.get("retrieval_method")
    institution = candidate.get("institution") or source_name
    coverage = candidate.get("source_coverage")
    language = candidate.get("language") or "und"
    rights = candidate.get("rights_notes")
    if source_type not in allowed_types or authority not in allowed_authorities:
        if source_name == "OpenAlex":
            source_type, authority, method = "academic_work", "scholarly", "api"
            rights = rights or "OpenAlex metadata is released under CC0; abstract text is used only as supplied in metadata."
        elif source_name in {"National Archives", "UK National Archives Discovery"}:
            source_type, authority = "archive_record", "institutional"
            method = method or "metadata_only"
            rights = rights or "Catalogue metadata only; the description is not an inspected source passage."
        elif source_name == "Internet Archive":
            source_type, authority = "contemporary_publication", "unknown"
            method = method or ("ocr" if candidate.get("passage_status") == "inspectable_text" else "metadata_only")
            rights = rights or "OCR is processed only when item metadata explicitly signals public-domain/CC0; verify item-specific rights before reuse."
        else:
            source_type, authority, method = "other", "unknown", method or "other"
            rights = rights or "Source authority and rights require manual review."
    if method not in allowed_methods:
        method = "other"
    if source_name == "Internet Archive" and candidate.get("passage_status") == "inspectable_text":
        method = "ocr"
    return require_valid_record({
        "record_type": "source",
        "schema_version": 1,
        "source_id": source_id_for(url),
        "title": str(candidate.get("title") or urlparse(url).netloc or source_name)[:500],
        "institution": institution,
        "event_ids": [event_id],
        "source_type": source_type,
        "authority_level": authority,
        "coverage": coverage,
        "language": language,
        "stable_url": url,
        "catalogue_reference": str(candidate.get("catalogue_reference") or "")[:500] or None,
        "retrieval_method": method,
        "publication_date": str(candidate.get("year")) if candidate.get("year") else None,
        "discovered_at": timestamp,
        "rights_notes": rights or "Source-specific rights and terms require manual review.",
    })


def persist_page_judgement(path, timeline_root, title, date, claims, kept, model, prompt_version, records_dir=None):
    """Upsert claim/source/evidence records and append a versioned judgement per claim."""
    records_dir = Path(records_dir or DEFAULT_RECORDS_DIR)
    relative_path = Path(path).resolve().relative_to(Path(timeline_root).resolve()).as_posix()
    event_id = event_id_for_relative_path(relative_path)
    timestamp_dt = datetime.now(timezone.utc)
    timestamp = timestamp_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    timestamp_slug = timestamp_dt.strftime("%Y%m%dt%H%M%S%fZ").lower()
    claim_texts = [f"{title} occurred in {date}." if date else f"{title} occurred.", *[normalize_claim_text(item) for item in claims]]
    claim_rows = []
    for index, text in enumerate(claim_texts):
        claim_id = claim_id_for(event_id, text)
        claim_rows.append({
            "record_type": "claim",
            "schema_version": 1,
            "id": claim_id,
            "event_id": event_id,
            "text": text,
            "claim_type": "date" if index == 0 else "other",
            "status": "unverified",
            "is_current": True,
            "superseded_at": None,
            "importance": "core",
            "created_from": "migration",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": {
                "source_page": f"content/01_Timeline/{relative_path}",
                "extraction": "event title/date" if index == 0 else "explicit Claims to verify bullet",
            },
        })

    source_rows, evidence_rows, claim_relations = [], [], {}
    for candidate in kept:
        url = str(candidate.get("url") or "").strip()
        if not url:
            continue
        source = _source_metadata(candidate, event_id, timestamp)
        if source:
            source_rows.append(source)
        candidate_status = candidate.get("passage_status", "metadata_only")
        passage = str(candidate.get("passage") or "").strip()
        passage_status = "inspectable" if candidate_status in INSPECTABLE_STATUSES and len(passage) >= 30 else (
            "retrieval_failed" if candidate_status == "retrieval_failed" else "metadata_only"
        )
        for claim_number in candidate.get("claims") or []:
            if not isinstance(claim_number, int) or claim_number < 1 or claim_number > len(claim_texts):
                continue
            claim_text = claim_texts[claim_number - 1]
            claim_id = claim_id_for(event_id, claim_text)
            source_id = source_id_for(url)
            evidence_digest = hashlib.sha256(
                f"{source_id}|{claim_id}|{url}|{passage}".encode("utf-8")
            ).hexdigest()[:16]
            relation = candidate.get("relation", "background")
            relation = relation if relation in {"supports", "contradicts", "partial", "background", "undetermined"} else "undetermined"
            evidence = require_valid_record({
                "record_type": "evidence",
                "schema_version": 1,
                "evidence_id": f"evidence:{evidence_digest}",
                "source_id": source_id,
                "claim_id": claim_id,
                "relation": relation,
                "passage_status": passage_status,
                "is_current": True,
                "superseded_at": None,
                "passage": passage if passage_status == "inspectable" else None,
                "locator": candidate.get("locator"),
                "source_date": str(candidate.get("year")) if candidate.get("year") else None,
                "url": url,
                "retrieved_at": timestamp,
                "retrieval_notes": str(candidate.get("why") or candidate.get("note") or "")[:1000] or None,
            })
            evidence_rows.append(evidence)
            claim_relations.setdefault(claim_id, []).append(evidence)

    # Keep current inspectable evidence referenced by a manual judgement when the exact
    # claim is unchanged. Scheduled AI passes must not erase a human's source audit just
    # because their own retrieval found nothing. If the claim text changes, normal
    # supersession below still retires the old evidence.
    evidence_path = records_dir / "evidence.jsonl"
    existing_evidence = _read_jsonl(evidence_path)
    existing_judgements = _read_jsonl(records_dir / "judgements.jsonl")
    current_claim_ids = {row["id"] for row in claim_rows}
    manual_evidence_ids = {
        evidence_id
        for judgement in existing_judgements
        if str(judgement.get("prompt_version") or "").startswith("manual-")
        for evidence_id in judgement.get("evidence_ids", [])
    }
    for item in existing_evidence:
        if (
            item.get("is_current", True)
            and item.get("evidence_id") in manual_evidence_ids
            and item.get("claim_id") in current_claim_ids
        ):
            related = claim_relations.setdefault(item["claim_id"], [])
            if all(row.get("evidence_id") != item.get("evidence_id") for row in related):
                related.append(item)

    claim_statuses = {}
    judgement_rows = []
    for claim_text in claim_texts:
        claim_id = claim_id_for(event_id, claim_text)
        claim_evidence = claim_relations.get(claim_id, [])
        inspected = [item for item in claim_evidence if item["passage_status"] == "inspectable"]
        relations = {item["relation"] for item in inspected}
        if "supports" in relations and "contradicts" in relations:
            verdict, uncertainty = "partial", "Inspected evidence conflicts; resolve the disagreement before treating the claim as settled."
        elif "supports" in relations:
            verdict, uncertainty = "supported", "At least one inspectable passage directly supports the claim; continue checking for contrary evidence."
        elif "contradicts" in relations:
            verdict, uncertainty = "contradicted", "At least one inspectable passage directly contradicts the claim; review before publication."
        elif "partial" in relations:
            verdict, uncertainty = "partial", "Inspectable evidence only partly addresses the claim."
        else:
            verdict, uncertainty = "unverified", "No inspectable passage directly establishes or contradicts this claim."
        claim_statuses[claim_id] = verdict
        evidence_ids = sorted({item["evidence_id"] for item in claim_evidence})
        rationale = " ".join(
            str(item.get("retrieval_notes") or "").strip()
            for item in claim_evidence if item.get("retrieval_notes")
        )[:2000] or uncertainty
        judgement_rows.append(require_valid_record({
            "record_type": "judgement",
            "schema_version": 1,
            "judgement_id": f"judgement:{claim_id.removeprefix('claim:')}-v{prompt_version}-{timestamp_slug}",
            "claim_id": claim_id,
            "evidence_ids": evidence_ids,
            "verdict": verdict,
            "rationale": rationale,
            "uncertainty": uncertainty,
            "model": model,
            "prompt_version": str(prompt_version),
            "judged_at": timestamp,
        }))

    claim_path = records_dir / "claims.jsonl"
    existing_claim_rows = _read_jsonl(claim_path)
    existing_claims = {row["id"]: row for row in existing_claim_rows}
    for existing in existing_claim_rows:
        if existing.get("event_id") == event_id and existing.get("id") not in current_claim_ids:
            if existing.get("is_current", True):
                existing["is_current"] = False
                existing["superseded_at"] = timestamp
    _write_jsonl(claim_path, existing_claim_rows)
    for row in claim_rows:
        existing = existing_claims.get(row["id"])
        verdict = claim_statuses.get(row["id"], "unverified")
        row["status"] = verdict
        if existing:
            if verdict != existing.get("status"):
                row["updated_at"] = timestamp
            else:
                row["updated_at"] = existing.get("updated_at", row["updated_at"])
            row["created_at"] = existing.get("created_at", row["created_at"])
            row["created_from"] = existing.get("created_from", row["created_from"])
            row["provenance"] = existing.get("provenance", row["provenance"])
    _upsert(claim_path, claim_rows, "id")

    affected_claim_ids = {
        row["id"] for row in existing_claim_rows if row.get("event_id") == event_id
    } | current_claim_ids
    for item in existing_evidence:
        if item.get("claim_id") in affected_claim_ids and item.get("is_current", True):
            if item.get("evidence_id") in manual_evidence_ids and item.get("claim_id") in current_claim_ids:
                continue
            item["is_current"] = False
            item["superseded_at"] = timestamp
    if existing_evidence:
        _write_jsonl(evidence_path, existing_evidence)
    if source_rows:
        _upsert(records_dir / "sources.jsonl", source_rows, "source_id")
    if evidence_rows:
        _upsert(evidence_path, evidence_rows, "evidence_id")
    if judgement_rows:
        _upsert(records_dir / "judgements.jsonl", judgement_rows, "judgement_id")
    return {"event_id": event_id, "claims": len(claim_rows), "sources": len(source_rows), "evidence": len(evidence_rows), "judgements": len(judgement_rows)}
