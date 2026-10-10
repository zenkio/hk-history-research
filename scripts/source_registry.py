"""Pluggable source registry for claim-focused historical research.

Registry metadata describes discovery capabilities and provenance; it is not evidence
that a source supports a claim. Adapters must return candidate dictionaries and must
distinguish inspectable passages from catalogue-only metadata.
"""
from dataclasses import dataclass
from typing import Callable, Iterable


INSPECTABLE_STATUSES = frozenset({
    "inspectable_text", "inspectable_abstract", "inspectable_record",
})
ALLOWED_PASSAGE_STATUSES = INSPECTABLE_STATUSES | frozenset({
    "metadata_only", "retrieval_failed",
})

RIGHTS_POLICIES = frozenset({
    "metadata_only", "cc0_dataset", "item_rights_gate", "open_government_licence", "review_required",
})


@dataclass(frozen=True)
class SourceDefinition:
    """Stable source-family metadata plus a callable search adapter."""

    source_id: str
    name: str
    institution: str
    source_type: str
    authority_level: str
    language: str
    coverage: str
    stable_url: str
    retrieval_method: str
    search: Callable[[str], Iterable[dict]]
    rights_notes: str = "Review source-specific rights and terms before reuse or AI processing."
    rights_policy: str = "review_required"


class SourceRegistry:
    """Register source adapters and search them through one consistent interface."""

    def __init__(self, sources=()):
        self._sources = {}
        for source in sources:
            self.register(source)

    def register(self, source):
        if not isinstance(source, SourceDefinition):
            raise TypeError("source must be a SourceDefinition")
        if not source.source_id or source.source_id.strip() != source.source_id:
            raise ValueError("source_id must be a non-empty stable identifier")
        if source.source_id in self._sources:
            raise ValueError(f"duplicate source_id: {source.source_id}")
        if not callable(source.search):
            raise TypeError("source search adapter must be callable")
        if source.rights_policy not in RIGHTS_POLICIES:
            raise ValueError(f"unsupported rights_policy: {source.rights_policy}")
        self._sources[source.source_id] = source
        return source

    def get(self, source_id):
        return self._sources[source_id]

    def list_sources(self):
        """Return stable metadata only; callable adapters are deliberately excluded."""
        fields = (
            "source_id", "name", "institution", "source_type", "authority_level",
            "language", "coverage", "stable_url", "retrieval_method", "rights_notes", "rights_policy",
        )
        return [
            {field: getattr(source, field) for field in fields}
            for source in self._sources.values()
        ]

    def adapters(self):
        """Return the legacy (name, callable) pairs used by evidence.py and existing tests."""
        return [(source.name, source.search) for source in self._sources.values()]

    def definition_for_name(self, name):
        """Return a registered adapter by its display name, or None if it is not registered."""
        return next((source for source in self._sources.values() if source.name == name), None)

    def search(self, query, source_ids=None):
        """Search selected adapters, returning candidates and explicit adapter failures.

        Failures are returned instead of silently becoming zero-result searches. A
        candidate's passage status is preserved; metadata-only results never become
        inspectable evidence merely because they passed through this registry.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        selected = list(self._sources) if source_ids is None else list(source_ids)
        candidates, failures, successful_source_ids = [], [], []
        for source_id in selected:
            source = self.get(source_id)  # unknown IDs are programmer/configuration errors
            try:
                rows = source.search(query)
                for row in rows or ():
                    if not isinstance(row, dict):
                        raise TypeError("adapter candidates must be dictionaries")
                    candidate = dict(row)
                    status = candidate.get("passage_status", "metadata_only")
                    if status not in ALLOWED_PASSAGE_STATUSES:
                        raise ValueError(f"unsupported passage_status: {status}")
                    passage = candidate.get("passage")
                    if status not in INSPECTABLE_STATUSES and passage:
                        candidate["passage"] = ""
                        candidate["registry_note"] = (
                            "Non-inspectable passage status; passage cleared before AI judgement."
                        )
                        passage = ""
                    if status in INSPECTABLE_STATUSES and not (
                        isinstance(passage, str) and passage.strip()
                    ):
                        candidate["passage_status"] = "metadata_only"
                        candidate["passage"] = ""
                        candidate["registry_note"] = (
                            "Adapter labelled this inspectable, but supplied no passage; "
                            "downgraded to metadata_only."
                        )
                        status = "metadata_only"
                    rights_policy = source.rights_policy
                    rights_allowed = (
                        (rights_policy == "cc0_dataset" and status == "inspectable_abstract")
                        or (
                            rights_policy == "item_rights_gate"
                            and candidate.get("rights_status") == "public_domain_or_cc0"
                        )
                        or (
                            rights_policy == "open_government_licence"
                            and status == "inspectable_text"
                            and candidate.get("rights_status") == "open_government_licence"
                        )
                    )
                    if status in INSPECTABLE_STATUSES and not rights_allowed:
                        candidate["passage_status"] = "metadata_only"
                        candidate["passage"] = ""
                        prior_note = candidate.get("registry_note", "")
                        rights_note = (
                            f"Source rights policy '{rights_policy}' does not permit this passage "
                            "to be sent for AI judgement; downgraded to metadata_only."
                        )
                        candidate["registry_note"] = f"{prior_note} {rights_note}".strip()
                    candidate.update({
                        "registry_source_id": source.source_id,
                        "source_name": source.name,
                        "institution": source.institution,
                        "source_type": source.source_type,
                        "authority_level": source.authority_level,
                        "language": source.language,
                        "retrieval_method": source.retrieval_method,
                        "source_coverage": source.coverage,
                        "rights_notes": source.rights_notes,
                        "rights_policy": source.rights_policy,
                    })
                    candidates.append(candidate)
                successful_source_ids.append(source.source_id)
            except Exception as exc:
                failures.append({
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:240],
                })
        return {
            "query": query,
            "candidates": candidates,
            "failures": failures,
            "successful_source_ids": successful_source_ids,
        }


def build_default_registry():
    """Wrap the existing, tested discovery adapters without changing pipeline wiring."""
    # Import lazily to avoid a module cycle: evidence.py remains the owner of adapters.
    import evidence
    from uk_legislation import search as search_uk_legislation

    return SourceRegistry([
        SourceDefinition(
            source_id="hk-government-records-service",
            name="Hong Kong Government Records Service",
            institution="Government Records Service, Public Records Office",
            source_type="archive_record",
            authority_level="primary",
            language="en",
            coverage="Online catalogue of Hong Kong government archival records; this adapter retrieves catalogue metadata only",
            stable_url="https://search.grs.gov.hk/en/index.xhtml",
            retrieval_method="web",
            search=evidence.grs_catalogue,
            rights_notes="Catalogue metadata only. Record detail pages are not treated as inspectable historical passages; access conditions may apply.",
            rights_policy="metadata_only",
        ),
        SourceDefinition(
            source_id="uk-national-archives-discovery",
            name="UK National Archives Discovery",
            institution="The National Archives (UK)",
            source_type="archive_record",
            authority_level="primary",
            language="en",
            coverage="UK-held archival catalogue records, including records relating to Hong Kong",
            stable_url="https://discovery.nationalarchives.gov.uk/",
            retrieval_method="api",
            search=evidence.national_archives,
            rights_notes="Catalogue metadata only unless an inspectable record passage is separately retrieved.",
            rights_policy="metadata_only",
        ),
        SourceDefinition(
            source_id="uk-legislation-gov",
            name="Legislation.gov.uk",
            institution="The National Archives (UK)",
            source_type="government_record",
            authority_level="primary",
            language="en",
            coverage="Official UK legislation; title search and inspectable statutory text relevant to Hong Kong history",
            stable_url="https://www.legislation.gov.uk/search",
            retrieval_method="web",
            search=search_uk_legislation,
            rights_notes="Legislation text is reusable under the Open Government Licence with attribution; preserve item-specific contributor notices and follow the site's 5-second crawl delay and robots.txt.",
            rights_policy="open_government_licence",
        ),
        SourceDefinition(
            source_id="internet-archive",
            name="Internet Archive",
            institution="Internet Archive",
            source_type="contemporary_publication",
            authority_level="unknown",
            language="en",
            coverage="Digitised publications; OCR retrieval is restricted by the existing explicit public-domain/CC0 gate",
            stable_url="https://archive.org/",
            retrieval_method="api",
            search=evidence.internet_archive,
            rights_notes="OCR processing remains default-deny unless item metadata explicitly signals public domain or CC0.",
            rights_policy="item_rights_gate",
        ),
        SourceDefinition(
            source_id="openalex",
            name="OpenAlex",
            institution="OpenAlex",
            source_type="academic_work",
            authority_level="scholarly",
            language="en",
            coverage="Scholarly-work discovery and abstracts where supplied; abstract is not a substitute for full text",
            stable_url="https://openalex.org/",
            retrieval_method="api",
            search=evidence.openalex,
            rights_notes="OpenAlex states its dataset is CC0; this covers supplied dataset/abstract content, not underlying publisher full text or separate copies.",
            rights_policy="cc0_dataset",
        ),
    ])
