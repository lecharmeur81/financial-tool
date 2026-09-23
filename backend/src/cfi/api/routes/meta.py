"""Service metadata (``/api/v1/meta``)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from cfi.core.time import utc_now
from cfi.domain.enums import EvidenceCategory

router = APIRouter(prefix="/api/v1", tags=["meta"])


class MetaResponse(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str
    server_time_utc: datetime
    evidence_categories: list[EvidenceCategory]
    data_sources_connected: int


@router.get("/meta", response_model=MetaResponse)
async def meta(request: Request) -> MetaResponse:
    settings = request.app.state.settings
    return MetaResponse(
        name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        api_version="v1",
        server_time_utc=utc_now(),
        evidence_categories=list(EvidenceCategory),
        # Phase 3: provider interfaces exist, but no real data source is connected.
        data_sources_connected=0,
    )
