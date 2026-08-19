from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from xvi import __version__
from xvi.config import settings
from xvi.library import ArtifactIndexer, LibraryRepository
from xvi.library.schemas import AssetReviewUpdate, DeliveryUpdate

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    *,
    database_path: Path | None = None,
    artifact_root: Path | None = None,
    gallery_root: Path | None = None,
    asset_root: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = LibraryRepository(
            database_path or settings.resolved_library_db_path,
            qualification_threshold=settings.library_qualification_threshold,
        )
        repository.ensure_schema()
        indexer = ArtifactIndexer(
            repository,
            artifact_root=artifact_root or settings.resolved_browser_artifact_root,
            gallery_root=gallery_root or Path.cwd(),
        )
        app.state.library_repository = repository
        app.state.library_indexer = indexer
        app.state.library_asset_root = asset_root or settings.resolved_browser_asset_root
        app.state.library_index_report = indexer.index_all()
        yield

    app = FastAPI(title="XVI 素材库", version=__version__, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def material_library() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    def ready(request: Request) -> dict[str, str | int]:
        report = request.app.state.library_index_report
        return {
            "status": "ready",
            "source_access_mode": settings.source_access_mode.value,
            "indexed_runs": report.run_count,
            "indexed_assets": report.asset_count,
        }

    @app.get("/api/v1/library/summary")
    def library_summary(request: Request) -> dict[str, int]:
        return _repository(request).summary()

    @app.get("/api/v1/library/tags")
    def library_tags(request: Request) -> dict[str, list[dict[str, object]]]:
        return {"items": _repository(request).list_tags()}

    @app.get("/api/v1/library/notes")
    def library_notes(
        request: Request,
        q: str | None = Query(default=None, max_length=160),
        tag: str | None = Query(default=None, max_length=120),
        status: Literal["eligible", "below_threshold", "needs_review"] | None = None,
        only_new: bool = False,
        limit: int | None = Query(default=None, ge=1),
        offset: int = Query(default=0, ge=0),
        sort: Literal["recent", "oldest", "most_images", "review_priority"] = "recent",
    ) -> dict[str, object]:
        page_size = min(
            limit or settings.library_default_page_size,
            settings.library_max_page_size,
        )
        return _repository(request).list_notes(
            query=q,
            tag=tag,
            status=status,
            only_new=only_new,
            limit=page_size,
            offset=offset,
            sort=sort,
        )

    @app.get("/api/v1/library/notes/{note_key}")
    def library_note(request: Request, note_key: str) -> dict[str, object]:
        note = _repository(request).get_note(note_key)
        if note is None:
            raise HTTPException(status_code=404, detail="未找到该笔记")
        return note

    @app.patch("/api/v1/library/assets/{asset_id}/review")
    def review_asset(request: Request, asset_id: str, update: AssetReviewUpdate) -> dict[str, str]:
        updated = _repository(request).update_asset_review(
            asset_id=asset_id,
            status=update.status,
            reviewer=update.reviewer,
            reason=update.reason,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="未找到该图片")
        return {"status": "ok", "asset_id": asset_id, "review_status": update.status}

    @app.patch("/api/v1/library/notes/{note_key}/delivery")
    def update_note_delivery(
        request: Request, note_key: str, update: DeliveryUpdate
    ) -> dict[str, str]:
        updated = _repository(request).update_delivery(note_key=note_key, status=update.status)
        if not updated:
            raise HTTPException(status_code=404, detail="未找到该笔记")
        return {"status": "ok", "note_key": note_key, "delivery_status": update.status}

    @app.post("/api/v1/library/reindex")
    def reindex_library(request: Request) -> dict[str, int | list[str]]:
        report = request.app.state.library_indexer.index_all()
        request.app.state.library_index_report = report
        return {
            "run_count": report.run_count,
            "note_count": report.note_count,
            "asset_count": report.asset_count,
            "legacy_review_count": report.legacy_review_count,
            "warnings": report.warnings,
        }

    @app.get("/api/v1/library/assets/{asset_id}/media")
    def asset_media(request: Request, asset_id: str) -> FileResponse:
        path = _repository(request).get_asset_path(
            asset_id,
            asset_root=request.app.state.library_asset_root,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="图片不存在或不在受控素材目录内")
        return FileResponse(path)

    return app


def _repository(request: Request) -> LibraryRepository:
    return cast(LibraryRepository, request.app.state.library_repository)


app = create_app()
