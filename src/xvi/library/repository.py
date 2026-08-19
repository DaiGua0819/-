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
                    source_url TEXT,
                    normalized_url TEXT,
                    title TEXT,
                    search_keyword TEXT,
                    author_id TEXT,
                    author_name TEXT,
                    published_at TEXT,
                    expected_image_count INTEGER,
                    capture_complete INTEGER NOT NULL DEFAULT 0,
                    first_captured_at TEXT,
                    last_captured_at TEXT,
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
                """
            )

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
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO notes(
                    note_key, source_note_id, source_url, normalized_url, title,
                    search_keyword, author_id, author_name, published_at,
                    expected_image_count, capture_complete,
                    first_captured_at, last_captured_at
                ) VALUES(
                    :note_key, :source_note_id, :source_url, :normalized_url, :title,
                    :search_keyword, :author_id, :author_name, :published_at,
                    :expected_image_count, :capture_complete,
                    :captured_at, :captured_at
                )
                ON CONFLICT(note_key) DO UPDATE SET
                    source_note_id=COALESCE(excluded.source_note_id, notes.source_note_id),
                    source_url=COALESCE(excluded.source_url, notes.source_url),
                    normalized_url=COALESCE(excluded.normalized_url, notes.normalized_url),
                    title=COALESCE(excluded.title, notes.title),
                    search_keyword=COALESCE(excluded.search_keyword, notes.search_keyword),
                    author_id=COALESCE(excluded.author_id, notes.author_id),
                    author_name=COALESCE(excluded.author_name, notes.author_name),
                    published_at=COALESCE(excluded.published_at, notes.published_at),
                    expected_image_count=COALESCE(
                        excluded.expected_image_count, notes.expected_image_count
                    ),
                    capture_complete=excluded.capture_complete,
                    last_captured_at=excluded.last_captured_at
                """,
                values,
            )

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
                n.note_key, n.source_url, n.normalized_url, n.title, n.search_keyword,
                n.author_id, n.author_name, n.published_at, n.expected_image_count,
                n.capture_complete, n.first_captured_at, n.last_captured_at,
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
            "source_url": row["source_url"],
            "normalized_url": row["normalized_url"],
            "title": row["title"],
            "search_keyword": row["search_keyword"],
            "author_name": row["author_name"],
            "published_at": row["published_at"],
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
