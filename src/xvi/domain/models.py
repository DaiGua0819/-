from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from xvi.domain.enums import CaptureMethod, SessionStatus


class SearchQuery(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)
    direction_tags: list[str] = Field(default_factory=list)
    market: str | None = None
    priority: str | None = None
    source_record_id: str | None = None


class SearchResult(BaseModel):
    source_url: str
    normalized_url: str
    visible_title: str | None = None
    visible_publish_hint: str | None = None
    search_keyword: str | None = None
    result_rank: int


class NoteSnapshot(BaseModel):
    note_id: UUID = Field(default_factory=uuid4)
    source_url: str
    title: str | None = None
    search_keyword: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    published_at: str | None = None
    expected_image_count: int | None = None


@dataclass(slots=True)
class RenderedFrame:
    source_index: int
    data: bytes
    width: int
    height: int
    capture_method: CaptureMethod
    file_name: str
    sha256: str
    phash: str | None


class SessionProbe(BaseModel):
    status: SessionStatus
    current_url: str
    page_title: str | None = None


class QueryRule(BaseModel):
    record_id: str
    query_text: str
    target: str | None = None
    entity_type: str | None = None
    market: str | None = None
    priority: str | None = None
    event_types: list[str] = Field(default_factory=list)
    location_terms: str | None = None
    inclusion_criteria: str | None = None
    exclusion_criteria: str | None = None
    status: str | None = None
    notes: str | None = None


class AssetMetadata(BaseModel):
    asset_id: UUID
    note_id: UUID
    source_index: int
    capture_method: CaptureMethod
    path: Path
    width: int
    height: int
    mime_type: str
    sha256: str
    phash: str | None
    search_keyword: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    published_at: str | None = None
    is_duplicate: bool = False
    duplicate_of_asset_id: UUID | None = None
    is_requirement_met: bool | None = None
    requirement_reason: str | None = None


class RunResult(BaseModel):
    run_id: UUID
    query: SearchQuery
    candidates: list[SearchResult] = Field(default_factory=list)
    assets: list[AssetMetadata] = Field(default_factory=list)
    capture_complete: bool = False
    error_code: str | None = None
