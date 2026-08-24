from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_QUALIFICATION_SQL = """
    CASE
        WHEN COUNT(a.asset_id) = 0 THEN 'needs_review'
        WHEN SUM(
            CASE WHEN COALESCE(a.human_review_status, a.ai_requirement_status)
                IN ('accepted', 'rejected') THEN 1 ELSE 0 END
        ) < COUNT(a.asset_id) THEN 'needs_review'
        WHEN CAST(SUM(
            CASE WHEN COALESCE(a.human_review_status, a.ai_requirement_status) = 'accepted'
                THEN 1 ELSE 0 END
        ) AS REAL) / COUNT(a.asset_id) >= ? THEN 'eligible'
        ELSE 'below_threshold'
    END
"""


class LibraryRepository:
    """SQLite 事实索引。原始 Artifact 和图片仍保留在既有 .data 目录。"""

    def __init__(self, database_path: Path, *, qualification_threshold: float = 0.6) -> None:
        self.database_path = database_path
        self.qualification_threshold = qualification_threshold

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    query_text TEXT,
                    source_access_mode TEXT,
                    capture_complete INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    started_at TEXT,
                    artifact_path TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notes (
                    note_key TEXT PRIMARY KEY,
                    source_note_id TEXT,
                    platform_note_id TEXT,
                    source_url TEXT,
                    canonical_url TEXT,
                    normalized_url TEXT,
                    title TEXT,
                    body_text TEXT,
                    search_keyword TEXT,
                    author_id TEXT,
                    author_name TEXT,
                    published_at TEXT,
                    published_at_raw TEXT,
                    published_at_utc TEXT,
                    edited_at_raw TEXT,
                    note_type TEXT,
                    expected_image_count INTEGER,
                    expected_media_count INTEGER,
                    captured_media_count INTEGER,
                    note_capture_status TEXT,
                    capture_error_code TEXT,
                    capture_error_reason TEXT,
                    capture_complete INTEGER NOT NULL DEFAULT 0,
                    first_captured_at TEXT,
                    last_captured_at TEXT,
                    first_seen_at TEXT,
                    last_verified_at TEXT,
                    delivery_status TEXT NOT NULL DEFAULT 'new'
                        CHECK(delivery_status IN ('new', 'delivered')),
                    delivered_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_notes_delivery ON notes(delivery_status);
                CREATE INDEX IF NOT EXISTS idx_notes_search_keyword ON notes(search_keyword);
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    note_key TEXT NOT NULL REFERENCES notes(note_key) ON DELETE CASCADE,
                    source_index INTEGER NOT NULL,
                    local_path TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    mime_type TEXT,
                    sha256 TEXT,
                    phash TEXT,
                    capture_method TEXT,
                    ai_requirement_status TEXT
                        CHECK(
                            ai_requirement_status IN ('accepted', 'rejected')
                            OR ai_requirement_status IS NULL
                        ),
                    ai_requirement_reason TEXT,
                    human_review_status TEXT
                        CHECK(
                            human_review_status IN ('accepted', 'rejected', 'needs_review')
                            OR human_review_status IS NULL
                        ),
                    human_review_reason TEXT,
                    review_source TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_assets_note ON assets(note_key, source_index);
                CREATE INDEX IF NOT EXISTS idx_assets_path ON assets(local_path);

                CREATE TABLE IF NOT EXISTS note_tags (
                    note_key TEXT NOT NULL REFERENCES notes(note_key) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    PRIMARY KEY(note_key, tag, origin)
                );

                CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);

                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    reason TEXT,
                    reviewer TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidate_observations (
                    observation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    platform_note_id TEXT,
                    source_url TEXT,
                    canonical_url TEXT,
                    query_text TEXT,
                    author_id TEXT,
                    author_name TEXT,
                    published_at_raw TEXT,
                    result_rank INTEGER,
                    status TEXT NOT NULL,
                    reason_code TEXT,
                    observed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_candidate_platform_id
                    ON candidate_observations(platform_note_id);
                CREATE INDEX IF NOT EXISTS idx_candidate_run
                    ON candidate_observations(run_id);

                CREATE TABLE IF NOT EXISTS capture_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    platform_note_id TEXT,
                    stage TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    expected_value TEXT,
                    actual_value TEXT,
                    selector_key TEXT,
                    page_url TEXT,
                    artifact_path TEXT,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    occurred_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_capture_failures_run
                    ON capture_failures(run_id);
                CREATE INDEX IF NOT EXISTS idx_capture_failures_code
                    ON capture_failures(error_code);
                """
            )
            self._ensure_schema_columns(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_platform_id ON notes(platform_note_id)"
            )

    @staticmethod
    def _ensure_schema_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(notes)").fetchall()
        }
        definitions = {
            "platform_note_id": "TEXT",
            "canonical_url": "TEXT",
            "body_text": "TEXT",
            "published_at_raw": "TEXT",
            "published_at_utc": "TEXT",
            "edited_at_raw": "TEXT",
            "note_type": "TEXT",
            "expected_media_count": "INTEGER",
            "captured_media_count": "INTEGER",
            "note_capture_status": "TEXT",
            "capture_error_code": "TEXT",
            "capture_error_reason": "TEXT",
            "first_seen_at": "TEXT",
            "last_verified_at": "TEXT",
        }
        for name, definition in definitions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE notes ADD COLUMN {name} {definition}")

    def upsert_run(
        self,
        *,
        run_id: str,
        query_text: str | None,
        source_access_mode: str | None,
        capture_complete: bool,
        error_code: str | None,
        started_at: str | None,
        artifact_path: str,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs(
                    run_id, query_text, source_access_mode, capture_complete, error_code,
                    started_at, artifact_path, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    query_text=excluded.query_text,
                    source_access_mode=excluded.source_access_mode,
                    capture_complete=excluded.capture_complete,
                    error_code=excluded.error_code,
                    started_at=excluded.started_at,
                    artifact_path=excluded.artifact_path,
                    indexed_at=excluded.indexed_at
                """,
                (
                    run_id,
                    query_text,
                    source_access_mode,
                    int(capture_complete),
                    error_code,
                    started_at,
                    artifact_path,
                    _utc_now(),
                ),
            )

    def upsert_note(self, values: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "note_key": None,
            "source_note_id": None,
            "platform_note_id": None,
            "source_url": None,
            "canonical_url": None,
            "normalized_url": None,
            "title": None,
            "body_text": None,
            "search_keyword": None,
            "author_id": None,
            "author_name": None,
            "published_at": None,
            "published_at_raw": None,
            "published_at_utc": None,
            "edited_at_raw": None,
            "note_type": None,
            "expected_image_count": None,
            "expected_media_count": None,
            "captured_media_count": None,
            "note_capture_status": None,
            "capture_error_code": None,
            "capture_error_reason": None,
            "capture_complete": 0,
            "captured_at": None,
            "first_seen_at": None,
            "last_verified_at": None,
        }
        payload.update(values)
        payload["captured_at"] = payload.get("captured_at") or _utc_now()
        payload["first_seen_at"] = payload.get("first_seen_at") or payload["captured_at"]
        payload["last_verified_at"] = payload.get("last_verified_at") or payload["captured_at"]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO notes(
                    note_key, source_note_id, platform_note_id, source_url, canonical_url,
                    normalized_url, title, body_text, search_keyword, author_id, author_name,
                    published_at, published_at_raw, published_at_utc, edited_at_raw, note_type,
                    expected_image_count, expected_media_count, captured_media_count,
                    note_capture_status, capture_error_code, capture_error_reason,
                    capture_complete, first_captured_at, last_captured_at, first_seen_at,
                    last_verified_at
                ) VALUES(
                    :note_key, :source_note_id, :platform_note_id, :source_url, :canonical_url,
                    :normalized_url, :title, :body_text, :search_keyword, :author_id, :author_name,
                    :published_at, :published_at_raw, :published_at_utc, :edited_at_raw, :note_type,
                    :expected_image_count, :expected_media_count, :captured_media_count,
                    :note_capture_status, :capture_error_code, :capture_error_reason,
                    :capture_complete, :captured_at, :captured_at, :first_seen_at,
                    :last_verified_at
                )
                ON CONFLICT(note_key) DO UPDATE SET
                    source_note_id=COALESCE(excluded.source_note_id, notes.source_note_id),
                    platform_note_id=COALESCE(excluded.platform_note_id, notes.platform_note_id),
                    source_url=COALESCE(excluded.source_url, notes.source_url),
                    canonical_url=COALESCE(excluded.canonical_url, notes.canonical_url),
                    normalized_url=COALESCE(excluded.normalized_url, notes.normalized_url),
                    title=COALESCE(excluded.title, notes.title),
                    body_text=COALESCE(excluded.body_text, notes.body_text),
                    search_keyword=COALESCE(excluded.search_keyword, notes.search_keyword),
                    author_id=COALESCE(excluded.author_id, notes.author_id),
                    author_name=COALESCE(excluded.author_name, notes.author_name),
                    published_at=COALESCE(excluded.published_at, notes.published_at),
                    published_at_raw=COALESCE(excluded.published_at_raw, notes.published_at_raw),
                    published_at_utc=COALESCE(excluded.published_at_utc, notes.published_at_utc),
                    edited_at_raw=COALESCE(excluded.edited_at_raw, notes.edited_at_raw),
                    note_type=COALESCE(excluded.note_type, notes.note_type),
                    expected_image_count=COALESCE(
                        excluded.expected_image_count, notes.expected_image_count
                    ),
                    expected_media_count=COALESCE(
                        excluded.expected_media_count, notes.expected_media_count
                    ),
                    captured_media_count=COALESCE(
                        excluded.captured_media_count, notes.captured_media_count
                    ),
                    note_capture_status=COALESCE(
                        excluded.note_capture_status, notes.note_capture_status
                    ),
                    capture_error_code=COALESCE(
                        excluded.capture_error_code, notes.capture_error_code
                    ),
                    capture_error_reason=COALESCE(
                        excluded.capture_error_reason, notes.capture_error_reason
                    ),
                    capture_complete=excluded.capture_complete,
                    last_captured_at=excluded.last_captured_at,
                    last_verified_at=COALESCE(excluded.last_verified_at, notes.last_verified_at)
                """,
                payload,
            )


    def upsert_candidate(self, values: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "observation_id": None,
            "run_id": None,
            "platform_note_id": None,
            "source_url": None,
            "canonical_url": None,
            "query_text": None,
            "author_id": None,
            "author_name": None,
            "published_at_raw": None,
            "result_rank": None,
            "status": "discovered",
            "reason_code": None,
            "observed_at": _utc_now(),
        }
        payload.update(values)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO candidate_observations(
                    observation_id, run_id, platform_note_id, source_url, canonical_url,
                    query_text, author_id, author_name, published_at_raw, result_rank,
                    status, reason_code, observed_at
                ) VALUES(
                    :observation_id, :run_id, :platform_note_id, :source_url, :canonical_url,
                    :query_text, :author_id, :author_name, :published_at_raw, :result_rank,
                    :status, :reason_code, :observed_at
                )
                ON CONFLICT(observation_id) DO UPDATE SET
                    platform_note_id=excluded.platform_note_id,
                    source_url=excluded.source_url,
                    canonical_url=excluded.canonical_url,
                    query_text=excluded.query_text,
                    author_id=excluded.author_id,
                    author_name=excluded.author_name,
                    published_at_raw=excluded.published_at_raw,
                    result_rank=excluded.result_rank,
                    status=excluded.status,
                    reason_code=excluded.reason_code,
                    observed_at=excluded.observed_at
                """,
                payload,
            )

    def record_capture_failure(self, values: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "run_id": None,
            "platform_note_id": None,
            "stage": "capture_note",
            "error_code": "capture_incomplete",
            "error_message": "未提供失败原因",
            "expected_value": None,
            "actual_value": None,
            "selector_key": None,
            "page_url": None,
            "artifact_path": None,
            "retryable": 1,
            "occurred_at": _utc_now(),
        }
        payload.update(values)
        with self.connection() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM capture_failures
                WHERE run_id=? AND COALESCE(platform_note_id, '')=COALESCE(?, '')
                  AND stage=? AND error_code=? AND error_message=?
                  AND COALESCE(page_url, '')=COALESCE(?, '')
                  AND occurred_at=?
                LIMIT 1
                """,
                (
                    payload["run_id"],
                    payload["platform_note_id"],
                    payload["stage"],
                    payload["error_code"],
                    payload["error_message"],
                    payload["page_url"],
                    payload["occurred_at"],
                ),
            ).fetchone()
            if existing is not None:
                return
            connection.execute(
                """
                INSERT INTO capture_failures(
                    run_id, platform_note_id, stage, error_code, error_message,
                    expected_value, actual_value, selector_key, page_url, artifact_path,
                    retryable, occurred_at
                ) VALUES(
                    :run_id, :platform_note_id, :stage, :error_code, :error_message,
                    :expected_value, :actual_value, :selector_key, :page_url, :artifact_path,
                    :retryable, :occurred_at
                )
                """,
                payload,
            )

    def list_capture_failures(
        self,
        *,
        run_id: str | None,
        error_code: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if error_code:
            where.append("error_code=?")
            params.append(error_code)
        where_sql = " AND ".join(where)
        with self.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM capture_failures WHERE {where_sql}",
                params,
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT id, run_id, platform_note_id, stage, error_code, error_message,
                       expected_value, actual_value, selector_key, page_url, artifact_path,
                       retryable, occurred_at
                FROM capture_failures
                WHERE {where_sql}
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {"total": int(total), "items": [dict(row) for row in rows]}

    def upsert_asset(self, values: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO assets(
                    asset_id, note_key, source_index, local_path, width, height, mime_type,
                    sha256, phash, capture_method, ai_requirement_status, ai_requirement_reason
                ) VALUES(
                    :asset_id, :note_key, :source_index, :local_path, :width, :height, :mime_type,
                    :sha256, :phash, :capture_method, :ai_requirement_status, :ai_requirement_reason
                )
                ON CONFLICT(asset_id) DO UPDATE SET
                    note_key=excluded.note_key,
                    source_index=excluded.source_index,
                    local_path=excluded.local_path,
                    width=excluded.width,
                    height=excluded.height,
                    mime_type=excluded.mime_type,
                    sha256=excluded.sha256,
                    phash=excluded.phash,
                    capture_method=excluded.capture_method,
                    ai_requirement_status=COALESCE(
                        excluded.ai_requirement_status, assets.ai_requirement_status
                    ),
                    ai_requirement_reason=COALESCE(
                        excluded.ai_requirement_reason, assets.ai_requirement_reason
                    )
                """,
                values,
            )

    def add_tags(self, note_key: str, tags: Sequence[str], *, origin: str) -> None:
        if not tags:
            return
        with self.connection() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO note_tags(note_key, tag, origin) VALUES (?, ?, ?)",
                [(note_key, tag, origin) for tag in tags],
            )

    def import_legacy_review(
        self, *, local_path_suffix: str, status: str, reason: str | None
    ) -> int:
        """仅回填尚未被网页人工修改过的旧画廊结果。"""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT asset_id, human_review_status, human_review_reason, review_source
                FROM assets
                WHERE REPLACE(local_path, '\\', '/') LIKE ?
                """,
                (f"%/{local_path_suffix.lstrip('/')}",),
            ).fetchall()
            changed = 0
            for row in rows:
                if row["review_source"] not in {None, "legacy_gallery"}:
                    continue
                if row["human_review_status"] == status and row["human_review_reason"] == reason:
                    continue
                connection.execute(
                    """
                    UPDATE assets
                    SET human_review_status=?, human_review_reason=?, review_source='legacy_gallery'
                    WHERE asset_id=?
                    """,
                    (status, reason, row["asset_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO review_events(
                        asset_id, status, reason, reviewer, source, created_at
                    )
                    VALUES (?, ?, ?, '历史画廊迁移', 'legacy_gallery', ?)
                    """,
                    (row["asset_id"], status, reason, _utc_now()),
                )
                changed += 1
            return changed

    def update_asset_review(
        self, *, asset_id: str, status: str, reviewer: str, reason: str | None
    ) -> bool:
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                """
                UPDATE assets
                SET human_review_status=?, human_review_reason=?, review_source='web_review'
                WHERE asset_id=?
                """,
                (status, reason, asset_id),
            )
            connection.execute(
                """
                INSERT INTO review_events(asset_id, status, reason, reviewer, source, created_at)
                VALUES (?, ?, ?, ?, 'web_review', ?)
                """,
                (asset_id, status, reason, reviewer, _utc_now()),
            )
            return True

    def update_delivery(self, *, note_key: str, status: str) -> bool:
        delivered_at = _utc_now() if status == "delivered" else None
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE notes SET delivery_status=?, delivered_at=? WHERE note_key=?",
                (status, delivered_at, note_key),
            )
            return cursor.rowcount > 0

    def list_tags(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT tag, COUNT(DISTINCT note_key) AS note_count
                FROM note_tags GROUP BY tag ORDER BY note_count DESC, tag COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_notes(
        self,
        *,
        query: str | None,
        tag: str | None,
        status: str | None,
        only_new: bool,
        limit: int,
        offset: int,
        sort: str = "recent",
    ) -> dict[str, Any]:
        where, params = self._note_filters(query=query, tag=tag, status=status, only_new=only_new)
        scored_sql = self._scored_notes_sql()
        where_sql = " AND ".join(where)
        order_by = self._note_sort(sort)
        with self.connection() as connection:
            count = connection.execute(
                f"SELECT COUNT(*) AS total FROM ({scored_sql}) AS scored WHERE {where_sql}",
                [self.qualification_threshold, *params],
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT * FROM ({scored_sql}) AS scored
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                [self.qualification_threshold, *params, limit, offset],
            ).fetchall()
        return {"total": count, "items": [self._note_payload(row) for row in rows]}

    def get_note(self, note_key: str) -> dict[str, Any] | None:
        scored_sql = self._scored_notes_sql()
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT * FROM ({scored_sql}) AS scored WHERE note_key=?",
                (self.qualification_threshold, note_key),
            ).fetchone()
            if row is None:
                return None
            asset_rows = connection.execute(
                """
                SELECT asset_id, source_index, width, height, capture_method,
                       ai_requirement_status, ai_requirement_reason,
                       human_review_status, human_review_reason, review_source
                FROM assets WHERE note_key=? ORDER BY source_index, asset_id
                """,
                (note_key,),
            ).fetchall()
        payload = self._note_payload(row)
        payload["assets"] = [
            {
                **dict(asset),
                "media_url": f"/api/v1/library/assets/{asset['asset_id']}/media",
                "effective_review_status": asset["human_review_status"]
                or asset["ai_requirement_status"]
                or "needs_review",
            }
            for asset in asset_rows
        ]
        return payload

    def get_asset_path(self, asset_id: str, *, asset_root: Path) -> Path | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT local_path FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        candidate = Path(row["local_path"])
        try:
            resolved_root = asset_root.resolve()
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_root)
        except (OSError, ValueError):
            return None
        return resolved_candidate if resolved_candidate.is_file() else None

    def summary(self) -> dict[str, int]:
        scored_sql = self._scored_notes_sql()
        with self.connection() as connection:
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS note_count,
                    COALESCE(SUM(asset_count), 0) AS asset_count,
                    COALESCE(
                        SUM(CASE WHEN eligibility='eligible' THEN 1 ELSE 0 END), 0
                    ) AS eligible_count,
                    COALESCE(
                        SUM(CASE WHEN eligibility='needs_review' THEN 1 ELSE 0 END), 0
                    ) AS needs_review_count,
                    COALESCE(SUM(CASE WHEN delivery_status='new' THEN 1 ELSE 0 END), 0) AS new_count
                FROM ({scored_sql}) AS scored
                """,
                (self.qualification_threshold,),
            ).fetchone()
        return {key: int(row[key]) for key in row.keys()}

    def _scored_notes_sql(self) -> str:
        return f"""
            SELECT
                n.note_key, n.source_note_id, n.platform_note_id, n.source_url,
                n.canonical_url, n.normalized_url, n.title, n.body_text, n.search_keyword,
                n.author_id, n.author_name, n.published_at, n.published_at_raw,
                n.published_at_utc, n.edited_at_raw, n.note_type, n.expected_image_count,
                n.expected_media_count, n.captured_media_count, n.note_capture_status,
                n.capture_error_code, n.capture_error_reason, n.capture_complete,
                n.first_captured_at, n.last_captured_at, n.first_seen_at, n.last_verified_at,
                n.delivery_status, n.delivered_at,
                COUNT(a.asset_id) AS asset_count,
                SUM(
                    CASE WHEN COALESCE(a.human_review_status, a.ai_requirement_status)='accepted'
                    THEN 1 ELSE 0 END
                ) AS accepted_count,
                SUM(
                    CASE WHEN COALESCE(a.human_review_status, a.ai_requirement_status)='rejected'
                    THEN 1 ELSE 0 END
                ) AS rejected_count,
                SUM(
                    CASE WHEN COALESCE(a.human_review_status, a.ai_requirement_status)
                    IN ('accepted', 'rejected') THEN 1 ELSE 0 END
                ) AS reviewed_count,
                {_QUALIFICATION_SQL} AS eligibility,
                (
                    SELECT GROUP_CONCAT(tag, char(31)) FROM note_tags
                    WHERE note_key=n.note_key
                ) AS tag_list,
                (
                    SELECT asset_id FROM assets preview
                    WHERE preview.note_key=n.note_key
                    ORDER BY preview.source_index, preview.asset_id LIMIT 1
                ) AS preview_asset_id
            FROM notes n
            LEFT JOIN assets a ON a.note_key=n.note_key
            GROUP BY n.note_key
        """

    @staticmethod
    def _note_sort(sort: str) -> str:
        order_by = {
            "recent": "last_captured_at DESC, note_key DESC",
            "oldest": "last_captured_at ASC, note_key ASC",
            "most_images": "asset_count DESC, last_captured_at DESC, note_key DESC",
            "review_priority": (
                "CASE WHEN eligibility='needs_review' THEN 0 "
                "WHEN eligibility='below_threshold' THEN 1 ELSE 2 END, "
                "(asset_count - reviewed_count) DESC, last_captured_at DESC, note_key DESC"
            ),
        }
        return order_by.get(sort, order_by["recent"])

    @staticmethod
    def _note_filters(
        *, query: str | None, tag: str | None, status: str | None, only_new: bool
    ) -> tuple[list[str], list[Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if query:
            like = f"%{query.strip()}%"
            where.append(
                "(COALESCE(title, '') LIKE ? OR COALESCE(search_keyword, '') LIKE ? "
                "OR COALESCE(author_name, '') LIKE ?)"
            )
            params.extend([like, like, like])
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM note_tags filter_tag "
                "WHERE filter_tag.note_key=scored.note_key AND filter_tag.tag=?)"
            )
            params.append(tag)
        if status:
            where.append("eligibility=?")
            params.append(status)
        if only_new:
            where.append("delivery_status='new'")
        return where, params

    @staticmethod
    def _note_payload(row: sqlite3.Row) -> dict[str, Any]:
        asset_count = int(row["asset_count"] or 0)
        accepted_count = int(row["accepted_count"] or 0)
        rejected_count = int(row["rejected_count"] or 0)
        reviewed_count = int(row["reviewed_count"] or 0)
        tags = [tag for tag in (row["tag_list"] or "").split(chr(31)) if tag]
        return {
            "note_key": row["note_key"],
            "source_note_id": row["source_note_id"],
            "platform_note_id": row["platform_note_id"],
            "source_url": row["source_url"],
            "canonical_url": row["canonical_url"],
            "normalized_url": row["normalized_url"],
            "title": row["title"],
            "body_text": row["body_text"],
            "search_keyword": row["search_keyword"],
            "author_id": row["author_id"],
            "author_name": row["author_name"],
            "published_at": row["published_at"],
            "published_at_raw": row["published_at_raw"],
            "published_at_utc": row["published_at_utc"],
            "edited_at_raw": row["edited_at_raw"],
            "note_type": row["note_type"],
            "expected_image_count": row["expected_image_count"],
            "expected_media_count": row["expected_media_count"],
            "captured_media_count": row["captured_media_count"],
            "note_capture_status": row["note_capture_status"],
            "capture_error_code": row["capture_error_code"],
            "capture_error_reason": row["capture_error_reason"],
            "capture_complete": bool(row["capture_complete"]),
            "last_captured_at": row["last_captured_at"],
            "delivery_status": row["delivery_status"],
            "delivered_at": row["delivered_at"],
            "asset_count": asset_count,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "needs_review_count": max(asset_count - reviewed_count, 0),
            "qualifying_ratio": round(accepted_count / asset_count, 3) if asset_count else None,
            "eligibility": row["eligibility"],
            "tags": tags,
            "preview_asset_id": row["preview_asset_id"],
            "preview_url": (
                f"/api/v1/library/assets/{row['preview_asset_id']}/media"
                if row["preview_asset_id"]
                else None
            ),
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
