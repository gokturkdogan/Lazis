"""Documents the user chooses (Phase 11, first version): read locally, summarized and answered
from. Nothing here is learned or stored: see :mod:`lazis.documents.library`."""

from lazis.documents.extract import Extracted, Kind, extract
from lazis.documents.library import Document, Library, note

__all__ = ["Document", "Extracted", "Kind", "Library", "extract", "note"]
