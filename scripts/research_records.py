"""Validation helpers for versioned claim-level research records.

The JSON Schema is the normative contract; these helpers keep validation consistent
across migration scripts and tests. Source metadata alone is never an evidence passage.
"""
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "research-records.schema.json"


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_record(record):
    """Return human-readable schema errors; an empty list means the record is valid."""
    errors = sorted(_validator().iter_errors(record), key=lambda error: list(map(str, error.absolute_path)))
    messages = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{path}: {error.message}")
    return messages


def require_valid_record(record):
    """Raise ValueError when a record does not satisfy the research schema."""
    errors = validate_record(record)
    if errors:
        raise ValueError("Invalid research record:\n- " + "\n- ".join(errors))
    return record
