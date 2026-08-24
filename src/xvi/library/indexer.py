from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from xvi.library.repository import LibraryRepository

_CARD_RE = re.compile(r"<article\b(?P<card>.*?)</article>", re.DOTALL | re.IGNORECASE)
_STATUS_RE = re.compile(r'data-status=["\'](?P<status>yes|no|unknown)["\']', re.IGNORECASE)
_ASSET_RE = re.compile(
    r"(?:src|href)=[\"']file:///[^\"']*/assets/(?P<directory>[^/\"']+)/(?P<file>[^\"']+)[\"']",
    re.IGNORECASE,
)
_REASON_RE = re.compile(r"<p>(?P<reason>.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_SPLIT_RE = re.compile(r"[+，,、/\s]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class IndexReport:
    run_count: int = 0
    note_count: int = 0
    asset_count: int = 0
    legacy_review_count: int = 0
    warnings: list[str] = field(default_factory=list)


class ArtifactIndexer:
    """读取既有 Artifact，不重新访问小红书来源。"""

    def __init__(
        self,
        repository: LibraryRepository,
        *,
        artifact_root: Path,
        gallery_root: Path,
    ) -> None:
        self.repository = repository
        self.artifact_root = artifact_root
        self.gallery_root = gallery_root

    def index_all(self) -> IndexReport:
        report = IndexReport()
        if self.artifact_root.is_dir():
            for result_path in sorted(self.artifact_root.glob("*/result.json")):
                self._index_result(result_path, report)
        else:
            report.warnings.append(f"Artifact 目录不存在：{self.artifact_root}")
        report.legacy_review_count = self._import_legacy_gallery_reviews(report)
        return report

    def _index_result(self, result_path: Path, report: IndexReport) -> None:
        try:
            result = _read_json(result_path)
        except (OSError, json.JSONDecodeError) as exc:
            report.warnings.append(f"无法解析 {result_path}: {exc}")
            return
        if not isinstance(result, dict):
            report.warnings.append(f"结果格式无效：{result_path}")
            return
        run_id = _text(result.get("run_id")) or result_path.parent.name
        manifest = _read_optional_json(result_path.with_name("manifest.json"))
        query_text = _text(_mapping(result.get("query")).get("text"))
        self.repository.upsert_run(
            run_id=run_id,
            query_text=query_text,
            source_access_mode=_text(manifest.get("source_access_mode")),
            capture_complete=bool(result.get("capture_complete")),
            error_code=_text(result.get("error_code")),
            started_at=_text(manifest.get("started_at")),
            artifact_path=str(result_path.parent),
        )
        report.run_count += 1

        candidates = [item for item in _list(result.get("candidates")) if isinstance(item, dict)]
        for index, candidate in enumerate(candidates):
            platform_id = _text(candidate.get("platform_note_id")) or _platform_note_id(
                _text(candidate.get("canonical_url")) or _text(candidate.get("normalized_url"))
                or _text(candidate.get("source_url"))
            )
            rank = _number(candidate.get("result_rank")) or index + 1
            observation_id = f"{run_id}:{platform_id or 'rank'}:{rank}"
            self.repository.upsert_candidate(
                {
                    "observation_id": observation_id,
                    "run_id": run_id,
                    "platform_note_id": platform_id,
                    "source_url": _text(candidate.get("source_url")),
                    "canonical_url": _text(candidate.get("canonical_url"))
                    or _canonical_url(platform_id),
                    "query_text": _text(candidate.get("search_keyword")) or query_text,
                    "author_id": _text(candidate.get("author_id")),
                    "author_name": _text(candidate.get("author_name")),
                    "published_at_raw": _text(candidate.get("visible_publish_hint")),
                    "result_rank": rank,
                    "status": "discovered",
                }
            )

        self._index_failures(
            run_id=run_id,
            steps_path=result_path.with_name("steps.jsonl"),
            artifact_path=str(result_path.parent),
        )

        assets = [item for item in _list(result.get("assets")) if isinstance(item, dict)]
        if not assets:
            return
        explicit_notes = {
            _text(note.get("note_id")): note
            for note in _list(result.get("notes"))
            if isinstance(note, dict) and _text(note.get("note_id"))
        }
        legacy_notes = _legacy_notes_by_capture_group(result_path.with_name("steps.jsonl"))
        groups = _asset_groups(assets)
        for index, (source_note_id, note_assets) in enumerate(groups):
            note = explicit_notes.get(source_note_id, {})
            fallback = legacy_notes[index] if index < len(legacy_notes) else {}
            source_url = _text(note.get("source_url")) or _text(fallback.get("source_url"))
            normalized_url = _text(note.get("normalized_url")) or source_url
            platform_id = _text(note.get("platform_note_id")) or _platform_note_id(
                _text(note.get("canonical_url")) or normalized_url or source_url
            )
            canonical_url = _text(note.get("canonical_url")) or _canonical_url(platform_id)
            note_key = _note_key(source_url, source_note_id)
            first_asset = note_assets[0]
            search_keyword = (
                _text(note.get("search_keyword"))
                or _text(first_asset.get("search_keyword"))
                or query_text
            )
            captured_at = _text(manifest.get("started_at"))
            self.repository.upsert_note(
                {
                    "note_key": note_key,
                    "source_note_id": source_note_id,
                    "platform_note_id": platform_id,
                    "source_url": source_url,
                    "canonical_url": canonical_url,
                    "normalized_url": normalized_url,
                    "title": _display_title(
                        _text(note.get("title")) or _text(fallback.get("title"))
                    ),
                    "body_text": _text(note.get("body_text")),
                    "search_keyword": search_keyword,
                    "author_id": _text(note.get("author_id"))
                    or _text(first_asset.get("author_id")),
                    "author_name": _text(note.get("author_name"))
                    or _text(first_asset.get("author_name")),
                    "published_at": _text(note.get("published_at"))
                    or _text(first_asset.get("published_at")),
                    "published_at_raw": _text(note.get("published_at_raw"))
                    or _text(note.get("published_at")),
                    "published_at_utc": _text(note.get("published_at_utc")),
                    "edited_at_raw": _text(note.get("edited_at_raw")),
                    "note_type": _text(note.get("note_type")) or "image",
                    "expected_image_count": _number(note.get("expected_image_count"))
                    or _number(fallback.get("expected_image_count")),
                    "expected_media_count": _number(note.get("expected_image_count")),
                    "captured_media_count": len(note_assets),
                    "note_capture_status": "captured",
                    "capture_error_code": None,
                    "capture_error_reason": None,
                    "capture_complete": int(bool(result.get("capture_complete"))),
                    "captured_at": captured_at,
                    "first_seen_at": captured_at,
                    "last_verified_at": captured_at,
                }
            )
            self.repository.add_tags(note_key, _derive_tags(search_keyword), origin="capture_query")
            native_tags = [
                tag.strip()
                for tag in (_list(note.get("native_tags")))
                if isinstance(tag, str) and tag.strip()
            ]
            self.repository.add_tags(note_key, native_tags, origin="xhs_detail_dom")
            report.note_count += 1
            for asset in note_assets:
                self.repository.upsert_asset(
                    {
                        "asset_id": _text(asset.get("asset_id")),
                        "note_key": note_key,
                        "source_index": _number(asset.get("source_index")) or 0,
                        "local_path": _normalise_path(_text(asset.get("path")) or ""),
                        "width": _number(asset.get("width")),
                        "height": _number(asset.get("height")),
                        "mime_type": _text(asset.get("mime_type")),
                        "sha256": _text(asset.get("sha256")),
                        "phash": _text(asset.get("phash")),
                        "capture_method": _text(asset.get("capture_method")),
                        "ai_requirement_status": _ai_status(asset.get("is_requirement_met")),
                        "ai_requirement_reason": _text(asset.get("requirement_reason")),
                    }
                )
                report.asset_count += 1

    def _index_failures(
        self,
        *,
        run_id: str,
        steps_path: Path,
        artifact_path: str,
    ) -> None:
        if not steps_path.is_file():
            return
        try:
            lines = steps_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            step = _text(event.get("step")) or "unknown"
            status = _text(event.get("status"))
            if status != "failed" and step != "skip_note":
                continue
            metadata = _mapping(event.get("metadata"))
            error_code = _text(metadata.get("error_code")) or (
                "VIDEO_PRESENT" if step == "skip_note" else "capture_incomplete"
            )
            self.repository.record_capture_failure(
                {
                    "run_id": run_id,
                    "platform_note_id": _text(metadata.get("platform_note_id")),
                    "stage": _text(metadata.get("stage")) or step,
                    "error_code": error_code,
                    "error_message": _text(metadata.get("error"))
                    or _text(metadata.get("reason"))
                    or f"{step} 未完成",
                    "expected_value": _text(metadata.get("expected_value")),
                    "actual_value": _text(metadata.get("actual_value")),
                    "selector_key": _text(metadata.get("selector_key")),
                    "page_url": _text(metadata.get("final_url"))
                    or _text(metadata.get("current_url"))
                    or _text(metadata.get("source_url")),
                    "artifact_path": artifact_path,
                    "retryable": int(
                        bool(metadata.get("retryable", False if step == "skip_note" else True))
                    ),
                    "occurred_at": _text(event.get("timestamp")) or _utc_now(),
                }
            )

    def _import_legacy_gallery_reviews(self, report: IndexReport) -> int:
        imported = 0
        for gallery_path in self.gallery_root.glob("*gallery.html"):
            try:
                content = gallery_path.read_text(encoding="utf-8")
            except OSError as exc:
                report.warnings.append(f"无法读取历史画廊 {gallery_path.name}: {exc}")
                continue
            for card_match in _CARD_RE.finditer(content):
                card = card_match.group("card")
                status_match = _STATUS_RE.search(card)
                asset_match = _ASSET_RE.search(card)
                if status_match is None or asset_match is None:
                    continue
                review_status = {"yes": "accepted", "no": "rejected", "unknown": "needs_review"}[
                    status_match.group("status").lower()
                ]
                reason_match = _REASON_RE.search(card)
                reason = _clean_html(reason_match.group("reason")) if reason_match else None
                imported += self.repository.import_legacy_review(
                    local_path_suffix=f"{asset_match.group('directory')}/{asset_match.group('file')}",
                    status=review_status,
                    reason=reason,
                )
        return imported


def _asset_groups(assets: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for asset in assets:
        source_note_id = _text(asset.get("note_id"))
        if not source_note_id:
            continue
        if source_note_id not in grouped:
            order.append(source_note_id)
        grouped[source_note_id].append(asset)
    return [(note_id, grouped[note_id]) for note_id in order]


def _legacy_notes_by_capture_group(steps_path: Path) -> list[dict[str, Any]]:
    if not steps_path.is_file():
        return []
    opened_by_rank: dict[int, dict[str, Any]] = {}
    captured: list[dict[str, Any]] = []
    try:
        lines = steps_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        metadata = _mapping(event.get("metadata"))
        rank = _number(metadata.get("result_rank"))
        if event.get("step") == "open_note" and event.get("status") == "done" and rank is not None:
            opened_by_rank[rank] = metadata
        if event.get("step") == "capture_note" and event.get("status") == "done":
            if rank is not None and rank in opened_by_rank:
                captured.append({**opened_by_rank[rank], **metadata})
            else:
                captured.append(metadata)
    return captured


def _note_key(source_url: str | None, source_note_id: str) -> str:
    if source_url:
        parsed = urlsplit(source_url)
        if parsed.scheme and parsed.netloc and parsed.path:
            identity = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
            return sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"capture-{source_note_id}"


def _platform_note_id(url: str | None) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-2] in {"explore", "search_result"}:
        return parts[-1]
    return None


def _canonical_url(platform_id: str | None) -> str | None:
    return f"https://www.xiaohongshu.com/explore/{platform_id}" if platform_id else None


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _derive_tags(search_keyword: str | None) -> list[str]:
    if not search_keyword:
        return []
    tags = [search_keyword.strip()]
    tags.extend(
        part.strip() for part in _TAG_SPLIT_RE.split(search_keyword) if len(part.strip()) >= 2
    )
    return list(dict.fromkeys(tags))


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(raw)


def _read_optional_json(path: Path) -> dict[str, Any]:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ai_status(value: Any) -> str | None:
    if value is True:
        return "accepted"
    if value is False:
        return "rejected"
    return None


def _normalise_path(path: str) -> str:
    return path.replace("\\", "/")


def _display_title(value: str | None) -> str | None:
    """将浏览器详情全文压缩为卡片可读标题，避免在素材库保存整篇正文。"""
    if not value:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if lines and re.fullmatch(r"\d+\s*/\s*\d+", lines[0]):
        lines.pop(0)
    try:
        follow_index = lines.index("关注")
    except ValueError:
        follow_index = -1
    if 0 <= follow_index < 4 and len(lines) > follow_index + 1:
        lines = lines[follow_index + 1 :]
    title = " ".join(lines).strip()
    if not title:
        return None
    return title if len(title) <= 100 else f"{title[:97].rstrip()}…"


def _clean_html(value: str) -> str | None:
    text = _HTML_TAG_RE.sub("", value).strip()
    return text or None
