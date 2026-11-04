"""Mosaic file format 0.1: constants shared by every reader and writer.

The normative definitions live in the repository's ``spec/`` directory
(``format.sql`` and four JSON Schemas). This package holds the schema loader,
the hashes (``mosaic_format.hashes``), the sealed writer
(``mosaic_format.writer``), the reader (``mosaic_format.reader``), the pattern checker
(``mosaic_format.pattern``, imported on its own: it alone needs a YAML parser and a JSON Schema
validator) and, later, the file checker.
"""

__version__ = "0.0.0"

FORMAT_VERSION = "0.1"
"""Format version written in ``header.format_version``."""

APPLICATION_ID = 0x4D4F5341
"""``PRAGMA application_id`` of every tessera and mosaic ("MOSA")."""

USER_VERSION = 1
"""``PRAGMA user_version`` for format 0.1."""

KINDS = ("tessera", "mosaic")
"""The two profiles of the file format."""

NORMATIVE_FILES = (
    "format.sql",
    "pattern.schema.json",
    "proposals.schema.json",
    "build-report.schema.json",
    "answers.schema.json",
)
"""The five normative files of Specification 0.1, in ``spec/``."""

from mosaic_format.file import create  # noqa: E402
from mosaic_format.hashes import knowledge_hash, vector_hash  # noqa: E402
from mosaic_format.reader import open  # noqa: E402
from mosaic_format.writer import seal  # noqa: E402

__all__ = [
    "APPLICATION_ID",
    "FORMAT_VERSION",
    "KINDS",
    "NORMATIVE_FILES",
    "USER_VERSION",
    "create",
    "knowledge_hash",
    "open",
    "seal",
    "vector_hash",
]
