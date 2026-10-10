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
        self._sources[source.source_id] = source
        return source

    def get(self, source_id):
        return self._sources[source_id]

    def list_sources(self):
        """Return stable metadata only; callable adapters are deliberately excluded."""
        fields = (
            "source_id", "name", "institution", "source_type", "authority_level",
            "language", "coverage", "stable_url", "retrieval_method", "rights_notes",
        )
        return [
            {field: getattr(source, field) for field in fields}
            for source in self._sources.values()
        ]

    def adapters(self):
        """Return the legacy (name, callable) pairs used by evidence.py and existing tests."""
        return [(source.name, source.search) for source in self._sources.values()]

    def search(self, query, source_ids=None):
        """Search selected adapters, returning candidates and explicit adapter failures.

        Failures are returned instead of silently becoming zero-result searches. A
        candidate's passage status is preserved; metadata-only results never become
        inspectable evidence merely because they passed through this registry.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        selected = list(self._sources) if source_ids is None else list(source_ids)
        candidates, failures = [], []
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
                    if status in INSPECTABLE_STATUSES and not (
                        isinstance(passage, str) and passage.strip()
                    ):
                        candidate["passage_status"] = "metadata_only"
                        candidate["passage"] = ""
                        candidate["registry_note"] = (
                            "Adapter labelled this inspectable, but supplied no passage; "
                            "downgraded to metadata_only."
                        )
                    candidate.update({
                        "source_id": source.source_id,
                        "institution": source.institution,
                        "source_type": source.source_type,
                        "authority_level": source.authority_level,
                        "language": source.language,
                        "retrieval_method": source.retrieval_method,
                        "source_coverage": source.coverage,
                        "rights_notes": source.rights_notes,
                    })
                    candidates.append(candidate)
            except Exception as exc:
                failures.append({
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:240],
                })
        return {"query": query, "candidates": candidates, "failures": failures}


def build_default_registry():
    """Wrap the existing, tested discovery adapters without changing pipeline wiring."""
    # Import lazily to avoid a module cycle: evidence.py remains the owner of adapters.
    import evidence

    return SourceRegistry([
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
            rights_notes="Use discovery metadata and abstracts within source terms; inspect the cited work for stronger claims.",
        ),
    ])
