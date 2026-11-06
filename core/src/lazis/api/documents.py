"""Documents API (Phase 11, first version): open a document the user chose, list, close.

The app reads the file the user picked and sends its bytes; the backend never opens a path. The
text is extracted locally and kept in memory for this session only (:mod:`lazis.documents`):
nothing is written to disk or to the database, and nothing is learned from it. Summaries and
answers are ordinary turns that name the document (``document_id`` on ``POST /turns``).
Responses carry the name the user gave and sizes, never document content; logs carry neither.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from lazis.conversation import ConversationEngine
from lazis.documents import Document, extract
from lazis.documents.extract import MAX_BYTES
from lazis.errors import DocumentNotFoundError, DocumentRefusedError, LazisError
from lazis.observability.logging import get_logger, log_event

UPLOAD_PATH = "/documents"
MAX_CONTENT_BASE64 = (MAX_BYTES + 2) // 3 * 4
MAX_UPLOAD_BODY = MAX_CONTENT_BASE64 + 4096  # the JSON around it
_ID = r"^[0-9A-HJKMNP-TV-Z]{26}$"
_log = get_logger("documents")


class _EngineUnavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


class DocumentAddRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=MAX_CONTENT_BASE64)


class DocumentModel(BaseModel):
    id: str
    name: str
    kind: Literal["txt", "pdf", "docx"]
    pages: int | None
    chars: int
    parts: int
    truncated: bool
    added_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentModel]


class DocumentRemoveResponse(BaseModel):
    removed: bool


def _view(doc: Document) -> DocumentModel:
    return DocumentModel(
        id=doc.id,
        name=doc.name,
        kind=doc.kind,
        pages=doc.pages,
        chars=doc.chars,
        parts=len(doc.parts),
        truncated=doc.truncated,
        added_at=doc.added_at,
    )


def build_documents_router(
    prefix: str, get_engine: Callable[[], ConversationEngine | None]
) -> APIRouter:
    router = APIRouter(prefix=prefix)

    def engine() -> ConversationEngine:
        e = get_engine()
        if e is None:
            raise _EngineUnavailable("conversation engine not available")
        return e

    @router.get(UPLOAD_PATH, response_model=DocumentListResponse)
    async def list_documents() -> DocumentListResponse:  # pyright: ignore[reportUnusedFunction]
        return DocumentListResponse(documents=[_view(d) for d in engine().documents.list()])

    @router.post(UPLOAD_PATH, response_model=DocumentModel)
    async def add_document(  # pyright: ignore[reportUnusedFunction]
        body: DocumentAddRequest,
    ) -> DocumentModel:
        library = engine().documents
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise DocumentRefusedError("invalid") from None
        started = time.monotonic()
        extracted = await asyncio.to_thread(extract, body.file_name, data)
        doc = library.add(body.file_name, extracted)
        ms = round((time.monotonic() - started) * 1000)
        log_event(_log, logging.INFO, "documents.added", kind=doc.kind, size_bytes=len(data),
                  pages=doc.pages, chars=doc.chars, parts=len(doc.parts),
                  truncated=doc.truncated, ms=ms)  # fmt: skip
        return _view(doc)

    @router.delete(f"{UPLOAD_PATH}/{{document_id}}", response_model=DocumentRemoveResponse)
    async def remove_document(  # pyright: ignore[reportUnusedFunction]
        document_id: Annotated[str, Path(pattern=_ID)],
    ) -> DocumentRemoveResponse:
        if not engine().documents.remove(document_id):
            raise DocumentNotFoundError("the document is not open")
        log_event(_log, logging.INFO, "documents.removed")
        return DocumentRemoveResponse(removed=True)

    return router
