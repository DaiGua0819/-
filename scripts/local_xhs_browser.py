from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4

from cloakbrowser import launch_persistent_context_async
from playwright.async_api import BrowserContext, Page

from xvi.adapters.source.xhs_web.adapter import XhsWebAdapter, extract_search_result_note_id
from xvi.browser.selector_registry import SelectorRegistry
from xvi.capture.frame_store import FrameStore
from xvi.capture.manifest import ArtifactWriter
from xvi.domain.enums import ErrorCode, SessionStatus
from xvi.domain.errors import CaptureIncompleteError
from xvi.domain.models import AssetMetadata, RunResult, SearchQuery, SearchResult

DEFAULT_HOME_URL = "https://www.xiaohongshu.com"
DEFAULT_SELECTOR_PATH = Path("configs/selectors/xhs_web.yaml")
DEFAULT_PROFILE_DIR = Path(".data/profiles/xhs-local")
DEFAULT_ASSET_ROOT = Path(".data/assets")
DEFAULT_ARTIFACT_ROOT = Path(".data/artifacts")
DAEMON_START_TIMEOUT_SECONDS = 30
MAX_IMAGE_NOTES = 40
MAX_EMPTY_RESULT_SCROLLS = 3
MAX_SEARCH_SCROLLS = 30
MAX_INSPECTED_CANDIDATES = 200


class DaemonEndpoint(TypedDict):
    host: str
    port: int
    token: str
    pid: int


class LocalBrowserDaemon:
    def __init__(self, args: argparse.Namespace, endpoint_path: Path) -> None:
        self.args = args
        self.endpoint_path = endpoint_path
        self.registry = SelectorRegistry(args.selector_path.resolve())
        self.frame_store = FrameStore(args.asset_root.resolve())
        self.adapter = XhsWebAdapter(
            self.registry,
            self.frame_store,
            max_frames=args.max_frames,
            timeout_ms=args.timeout_ms,
        )
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.server: asyncio.Server | None = None
        self.stop_event = asyncio.Event()
        self.command_lock = asyncio.Lock()
        self.endpoint_token = secrets.token_urlsafe(32)

    async def start(self) -> None:
        profile_dir = self.args.profile_dir.resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.context = await launch_persistent_context_async(
            str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            timezone="Asia/Shanghai",
            accept_downloads=True,
            stealth_args=False,
            humanize=False,
        )
        self.context.set_default_timeout(self.args.timeout_ms)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto(
            DEFAULT_HOME_URL,
            wait_until="domcontentloaded",
            timeout=self.args.timeout_ms,
        )

        self.server = await asyncio.start_server(self._handle_client, "127.0.0.1", 0)
        socket = self.server.sockets[0] if self.server.sockets else None
        if socket is None:
            raise RuntimeError("无法创建本地浏览器控制端口")
        port = int(socket.getsockname()[1])
        self._write_endpoint(
            {
                "host": "127.0.0.1",
                "port": port,
                "token": self.endpoint_token,
                "pid": os.getpid(),
            }
        )

    async def wait_until_closed(self) -> None:
        await self.stop_event.wait()

    async def shutdown(self) -> None:
        self.stop_event.set()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self.endpoint_path.exists():
            try:
                endpoint = _load_endpoint(self.endpoint_path)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                endpoint = None
            if endpoint is None or endpoint["pid"] == os.getpid():
                self.endpoint_path.unlink(missing_ok=True)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        close_requested = False
        try:
            raw_request = await asyncio.wait_for(reader.readline(), timeout=10)
            request = json.loads(raw_request)
            if not isinstance(request, dict):
                raise ValueError("控制请求格式无效")
            if request.get("token") != self.endpoint_token:
                raise PermissionError("本地浏览器控制令牌无效")

            action = request.get("action")
            if action == "status":
                response: dict[str, object] = {
                    "ok": True,
                    "status": "running",
                    "pid": os.getpid(),
                    "page_url": self.page.url if self.page is not None else None,
                }
            elif action == "probe":
                response = {"ok": True, "probe": await self._probe_selectors()}
            elif action == "run":
                query = request.get("query")
                authorization_reference = request.get("authorization_reference")
                if not isinstance(query, str) or not query.strip():
                    raise ValueError("控制请求缺少 query")
                if not isinstance(authorization_reference, str):
                    authorization_reference = None
                async with self.command_lock:
                    exit_code, result = await self._run_query(
                        query.strip(),
                        authorization_reference,
                    )
                response = {
                    "ok": True,
                    "exit_code": exit_code,
                    "result": result.model_dump(mode="json"),
                }
            elif action == "close":
                response = {"ok": True, "exit_code": 0, "status": "closing"}
                close_requested = True
            else:
                raise ValueError("不支持的浏览器控制操作")
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}

        writer.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        if close_requested:
            self.stop_event.set()

    async def _run_query(
        self,
        query_text: str,
        authorization_reference: str | None,
    ) -> tuple[int, RunResult]:
        if self.page is None:
            raise RuntimeError("本地浏览器页面尚未就绪")
        await self.page.goto(
            DEFAULT_HOME_URL,
            wait_until="domcontentloaded",
            timeout=self.args.timeout_ms,
        )
        return await execute_query(
            args=self.args,
            page=self.page,
            adapter=self.adapter,
            registry=self.registry,
            query_text=query_text,
            authorization_reference=authorization_reference,
            browser_backend="cloakbrowser_local_reused",
        )

    async def _probe_selectors(self) -> dict[str, object]:
        if self.page is None:
            raise RuntimeError("本地浏览器页面尚未就绪")

        selector_report: dict[str, object] = {}
        for key, config in self.registry.selectors.items():
            candidates: list[dict[str, object]] = []
            for candidate in config["candidates"]:
                try:
                    locator = self.registry._candidate_locator(self.page, candidate)
                    count = await locator.count()
                    visible_count = 0
                    samples: list[dict[str, str | None]] = []
                    for index in range(min(count, 30)):
                        current = locator.nth(index)
                        if not await current.is_visible():
                            continue
                        visible_count += 1
                        if len(samples) < 5:
                            samples.append(
                                {
                                    "href": await current.get_attribute("href"),
                                    "text": (await current.inner_text()).strip()[:200],
                                }
                            )
                    candidates.append(
                        {
                            "candidate": candidate,
                            "count": count,
                            "visible_count": visible_count,
                            "samples": samples,
                        }
                    )
                except Exception as exc:
                    candidates.append({"candidate": candidate, "error": str(exc)})
            selector_report[key] = candidates

        visible_anchors = await self.page.locator("a").evaluate_all(
            """
            elements => elements.filter(element => {
              const rect = element.getBoundingClientRect();
              const style = window.getComputedStyle(element);
              return rect.width > 0 && rect.height > 0 &&
                style.visibility !== 'hidden' && style.display !== 'none';
            }).slice(0, 50).map(element => ({
              href: element.getAttribute('href'),
              text: (element.innerText || '').trim().slice(0, 200)
            }))
            """
        )
        return {
            "url": self.page.url,
            "title": await self.page.title(),
            "selector_report": selector_report,
            "visible_anchors": visible_anchors,
        }

    def _write_endpoint(self, endpoint: DaemonEndpoint) -> None:
        self.endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.endpoint_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(endpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.endpoint_path)


async def execute_query(
    *,
    args: argparse.Namespace,
    page: Page,
    adapter: XhsWebAdapter,
    registry: SelectorRegistry,
    query_text: str,
    authorization_reference: str | None,
    browser_backend: str,
) -> tuple[int, RunResult]:
    if not authorization_reference:
        raise ValueError("真实搜索必须提供 --authorization-reference")

    run_id = uuid4()
    artifact = ArtifactWriter(args.artifact_root.resolve(), run_id)
    query = SearchQuery(text=query_text)
    artifact.write_manifest(
        {
            "run_id": str(run_id),
            "operation": "local_xhs_search",
            "selector_version": registry.version,
            "started_at": datetime.now(UTC).isoformat(),
            "source_access_mode": "authorized_browser",
            "authorization_reference": authorization_reference,
            "profile_dir": str(args.profile_dir.resolve()),
            "browser_backend": browser_backend,
            "stealth_args": False,
            "humanize": False,
            "max_image_notes": MAX_IMAGE_NOTES,
            "skip_video_notes": True,
        }
    )
    artifact.append_step("launch_local_browser", "done", url=page.url)

    session = await adapter.ensure_session(page)
    artifact.append_step("ensure_session", "done", session_status=session.status.value)
    if session.status != SessionStatus.AUTHENTICATED:
        error_code = (
            ErrorCode.AUTH_REQUIRED
            if session.status == SessionStatus.AUTH_REQUIRED
            else ErrorCode.SESSION_UNKNOWN
        )
        result = RunResult(run_id=run_id, query=query, error_code=error_code.value)
        artifact.write_result(result.model_dump(mode="json"))
        artifact.append_step(
            "complete",
            "failed",
            error_code=error_code.value,
            session_status=session.status.value,
        )
        return 2, result

    is_live_adapter = isinstance(adapter, XhsWebAdapter)
    artifact.append_step("open_search", "started", query=query_text, method="visible_search_input")
    pending_candidates = await adapter.search(page, query)
    search_results_url = page.url if is_live_adapter else None
    artifact.append_step(
        "open_search",
        "done",
        query=query_text,
        method="visible_search_input",
        search_results_url=search_results_url,
    )
    artifact.append_step("collect_results", "done", count=len(pending_candidates))

    assets: list[AssetMetadata] = []
    processed_candidates: list[SearchResult] = []
    seen_note_ids = {
        note_id
        for candidate in pending_candidates
        if (note_id := extract_search_result_note_id(candidate.normalized_url)) is not None
    }
    pending_index = 0
    failed_candidates = 0
    image_note_count = 0
    skipped_video_count = 0
    empty_scroll_count = 0
    scroll_count = 0
    run_incomplete = False
    search_context_failed = False
    stop_reason = "all_candidates_processed"

    while True:
        if is_live_adapter and image_note_count >= MAX_IMAGE_NOTES:
            stop_reason = "image_note_limit_reached"
            break
        if is_live_adapter and pending_index >= MAX_INSPECTED_CANDIDATES:
            run_incomplete = True
            stop_reason = "candidate_safety_limit_reached"
            break

        if pending_index >= len(pending_candidates):
            if not is_live_adapter:
                break
            if empty_scroll_count >= MAX_EMPTY_RESULT_SCROLLS:
                stop_reason = "no_more_search_results"
                break
            if scroll_count >= MAX_SEARCH_SCROLLS:
                run_incomplete = True
                stop_reason = "scroll_safety_limit_reached"
                break
            scroll_count += 1
            try:
                assert search_results_url is not None
                new_candidates = await adapter.load_more_results(
                    page,
                    query,
                    seen_note_ids,
                    rank_start=len(seen_note_ids) + 1,
                    expected_url=search_results_url,
                )
            except Exception as exc:
                run_incomplete = True
                search_context_failed = True
                stop_reason = "search_context_lost"
                artifact.append_step(
                    "scroll_search_results",
                    "failed",
                    error_code=ErrorCode.CAPTURE_INCOMPLETE.value,
                    error=str(exc),
                    search_results_url=page.url,
                )
                break

            if new_candidates:
                pending_candidates.extend(new_candidates)
                empty_scroll_count = 0
            else:
                empty_scroll_count += 1
            artifact.append_step(
                "scroll_search_results",
                "done",
                new_candidate_count=len(new_candidates),
                discovered_candidate_count=len(pending_candidates),
                empty_scroll_count=empty_scroll_count,
                scroll_count=scroll_count,
                search_results_url=page.url,
            )
            continue

        candidate = pending_candidates[pending_index]
        pending_index += 1
        processed_candidates.append(candidate)
        note_page = page
        child_page_created = False
        note_opened = False
        candidate_failed = False
        candidate_asset_count = 0
        skipped_video = False

        artifact.append_step(
            "open_note",
            "started",
            source_url=candidate.normalized_url,
            result_rank=candidate.result_rank,
        )
        try:
            if is_live_adapter:
                assert search_results_url is not None
                await adapter.ensure_search_context(
                    page,
                    query,
                    expected_url=search_results_url,
                )
                note_page = await page.context.new_page()
                child_page_created = True

            note = await adapter.open_note(note_page, candidate)
            note_opened = True
            artifact.append_step(
                "open_note",
                "done",
                title=note.title,
                source_url=candidate.normalized_url,
                final_url=note_page.url,
                result_rank=candidate.result_rank,
                expected_image_count=note.expected_image_count,
            )

            if is_live_adapter:
                media_type = await adapter.detect_note_media(note_page)
                if media_type == "video":
                    skipped_video = True
                    skipped_video_count += 1
                    artifact.append_step(
                        "skip_note",
                        "done",
                        reason="pure_video",
                        source_url=candidate.normalized_url,
                        final_url=note_page.url,
                        result_rank=candidate.result_rank,
                    )

            if not skipped_video:
                async for asset in adapter.iter_rendered_frames(note_page, note):
                    assets.append(asset)
                    candidate_asset_count += 1
                    artifact.append_step(
                        "capture_frame",
                        "done",
                        asset_id=str(asset.asset_id),
                        source_index=asset.source_index,
                        capture_method=asset.capture_method.value,
                        sha256=asset.sha256,
                        phash=asset.phash,
                        search_keyword=asset.search_keyword,
                        author_id=asset.author_id,
                        author_name=asset.author_name,
                        published_at=asset.published_at,
                        is_requirement_met=asset.is_requirement_met,
                        requirement_reason=asset.requirement_reason,
                        is_duplicate=asset.is_duplicate,
                        duplicate_of_asset_id=asset.duplicate_of_asset_id,
                        result_rank=candidate.result_rank,
                    )
                if candidate_asset_count == 0:
                    raise CaptureIncompleteError("图片笔记没有采集到任何图片")
                image_note_count += 1
                artifact.append_step(
                    "capture_note",
                    "done",
                    source_url=candidate.normalized_url,
                    result_rank=candidate.result_rank,
                    asset_count=candidate_asset_count,
                    expected_image_count=note.expected_image_count,
                    completed_image_note_count=image_note_count,
                )
        except Exception as exc:
            candidate_failed = True
            artifact.append_step(
                "capture_note",
                "failed",
                source_url=candidate.normalized_url,
                result_rank=candidate.result_rank,
                error_code=ErrorCode.CAPTURE_INCOMPLETE.value,
                error=str(exc),
            )
        finally:
            try:
                close_method = None
                if child_page_created:
                    await note_page.close()
                    close_method = "close_child_page"
                elif note_opened:
                    await adapter.close_note(note_page)
                    close_method = "adapter_close"
                if close_method is not None:
                    artifact.append_step(
                        "close_note",
                        "done",
                        source_url=candidate.normalized_url,
                        result_rank=candidate.result_rank,
                        method=close_method,
                    )
            except Exception as exc:
                candidate_failed = True
                artifact.append_step(
                    "close_note",
                    "failed",
                    source_url=candidate.normalized_url,
                    result_rank=candidate.result_rank,
                    error_code=ErrorCode.CAPTURE_INCOMPLETE.value,
                    error=str(exc),
                )

            if is_live_adapter:
                try:
                    assert search_results_url is not None
                    await adapter.ensure_search_context(
                        page,
                        query,
                        expected_url=search_results_url,
                    )
                except Exception as exc:
                    candidate_failed = True
                    search_context_failed = True
                    stop_reason = "search_context_lost"
                    artifact.append_step(
                        "verify_search_context",
                        "failed",
                        source_url=candidate.normalized_url,
                        result_rank=candidate.result_rank,
                        error_code=ErrorCode.CAPTURE_INCOMPLETE.value,
                        error=str(exc),
                        current_url=page.url,
                    )

        if candidate_failed:
            failed_candidates += 1
        if search_context_failed:
            break

    capture_complete = failed_candidates == 0 and not run_incomplete
    result_error_code = (
        ErrorCode.CAPTURE_INCOMPLETE.value if failed_candidates or run_incomplete else None
    )
    result = RunResult(
        run_id=run_id,
        query=query,
        candidates=processed_candidates,
        assets=assets,
        capture_complete=capture_complete,
        error_code=result_error_code,
    )
    artifact.write_result(result.model_dump(mode="json"))
    artifact.append_step(
        "complete",
        "done" if capture_complete else "partial",
        asset_count=len(assets),
        candidate_count=len(processed_candidates),
        discovered_candidate_count=len(pending_candidates),
        image_note_count=image_note_count,
        skipped_video_count=skipped_video_count,
        failed_candidate_count=failed_candidates,
        scroll_count=scroll_count,
        run_incomplete=run_incomplete,
        stop_reason=stop_reason,
        search_results_url=search_results_url,
    )
    return (0 if capture_complete else 1), result


async def run_browser_daemon(args: argparse.Namespace) -> int:
    daemon = LocalBrowserDaemon(args, endpoint_path(args))
    try:
        await daemon.start()
        print(
            f"CloakBrowser 已启动并保持运行，Profile: {args.profile_dir.resolve()}",
            flush=True,
        )
        print("后续查询将复用当前浏览器；执行 --close-browser 才会关闭。", flush=True)
        await daemon.wait_until_closed()
        return 0
    finally:
        await daemon.shutdown()


async def run_standalone_browser(args: argparse.Namespace) -> int:
    profile_dir = args.profile_dir.resolve()
    registry = SelectorRegistry(args.selector_path.resolve())
    frame_store = FrameStore(args.asset_root.resolve())
    adapter = XhsWebAdapter(
        registry,
        frame_store,
        max_frames=args.max_frames,
        timeout_ms=args.timeout_ms,
    )
    context = await launch_persistent_context_async(
        str(profile_dir),
        headless=False,
        viewport={"width": 1440, "height": 1000},
        locale="zh-CN",
        timezone="Asia/Shanghai",
        accept_downloads=True,
        stealth_args=False,
        humanize=False,
    )
    context.set_default_timeout(args.timeout_ms)
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(DEFAULT_HOME_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)
        print(f"本地浏览器已启动，Profile: {profile_dir}")
        print(f"当前页面: {page.url}")

        if args.login_wait_seconds > 0:
            print(f"请在浏览器窗口中手动登录，等待 {args.login_wait_seconds} 秒后继续。")
            await asyncio.sleep(args.login_wait_seconds)

        if not args.query:
            await asyncio.sleep(args.stay_open_seconds)
            return 0

        exit_code, result = await execute_query(
            args=args,
            page=page,
            adapter=adapter,
            registry=registry,
            query_text=args.query,
            authorization_reference=args.authorization_reference,
            browser_backend="cloakbrowser_local",
        )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str))
        await asyncio.sleep(args.stay_open_seconds)
        return exit_code
    finally:
        await context.close()


def endpoint_path(args: argparse.Namespace) -> Path:
    configured_path = cast(Path | None, args.endpoint_path)
    profile_dir = cast(Path, args.profile_dir)
    if configured_path is not None:
        return configured_path.resolve()
    return profile_dir.resolve() / ".cloakedbrowser-endpoint.json"


def _load_endpoint(path: Path) -> DaemonEndpoint:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("浏览器端点文件格式无效")
    return {
        "host": str(raw["host"]),
        "port": int(raw["port"]),
        "token": str(raw["token"]),
        "pid": int(raw["pid"]),
    }


async def send_browser_command(
    path: Path,
    command: dict[str, object],
) -> dict[str, object]:
    endpoint = _load_endpoint(path)
    reader, writer = await asyncio.open_connection(endpoint["host"], endpoint["port"])
    payload = {"token": endpoint["token"], **command}
    writer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
    await writer.drain()
    raw_response = await asyncio.wait_for(reader.readline(), timeout=300)
    writer.close()
    await writer.wait_closed()
    response = json.loads(raw_response)
    if not isinstance(response, dict):
        raise ValueError("浏览器控制响应格式无效")
    response = cast(dict[str, object], response)
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error", "浏览器控制请求失败")))
    return response


async def ensure_browser_daemon(args: argparse.Namespace) -> Path:
    path = endpoint_path(args)
    try:
        await send_browser_command(path, {"action": "status"})
        return path
    except (OSError, RuntimeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        path.unlink(missing_ok=True)

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--browser-daemon",
        "--profile-dir",
        str(args.profile_dir.resolve()),
        "--selector-path",
        str(args.selector_path.resolve()),
        "--asset-root",
        str(args.asset_root.resolve()),
        "--artifact-root",
        str(args.artifact_root.resolve()),
        "--max-frames",
        str(args.max_frames),
        "--timeout-ms",
        str(args.timeout_ms),
    ]
    if args.endpoint_path is not None:
        command.extend(["--endpoint-path", str(path)])
    if args.login_wait_seconds:
        command.extend(["--login-wait-seconds", str(args.login_wait_seconds)])

    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess,
        "DETACHED_PROCESS",
        0,
    )
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )

    deadline = asyncio.get_running_loop().time() + DAEMON_START_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        try:
            await send_browser_command(path, {"action": "status"})
            return path
        except (OSError, RuntimeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            await asyncio.sleep(0.2)
    raise RuntimeError("CloakBrowser 常驻会话启动超时，请检查 Profile 是否被其他浏览器占用")


async def run_reused_browser(args: argparse.Namespace) -> int:
    path = await ensure_browser_daemon(args)
    if args.probe_selectors:
        response = await send_browser_command(path, {"action": "probe"})
        print(json.dumps(response.get("probe"), ensure_ascii=False, indent=2, default=str))
        return 0
    if not args.query:
        response = await send_browser_command(path, {"action": "status"})
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    response = await send_browser_command(
        path,
        {
            "action": "run",
            "query": args.query,
            "authorization_reference": args.authorization_reference,
        },
    )
    result = response.get("result")
    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    exit_code = response.get("exit_code", 1)
    return exit_code if isinstance(exit_code, int) else 1


async def close_browser(args: argparse.Namespace) -> int:
    path = endpoint_path(args)
    try:
        await send_browser_command(path, {"action": "close"})
        print("CloakBrowser 已关闭，常驻会话和控制端点已释放。")
    except (OSError, RuntimeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        print("未发现正在运行的 CloakBrowser 常驻会话。")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地可见运行 CloakBrowser 小红书网页适配器")
    parser.add_argument("--query", help="固定搜索关键词；不填写时只启动或查看浏览器")
    parser.add_argument(
        "--probe-selectors",
        action="store_true",
        help="只读检查当前常驻浏览器中的可见选择器",
    )
    parser.add_argument(
        "--authorization-reference",
        help="人工授权记录，例如 local-manual-test",
    )
    parser.add_argument("--login-wait-seconds", type=int, default=0)
    parser.add_argument(
        "--stay-open-seconds",
        type=int,
        default=0,
        help="仅用于 --no-reuse-browser 的任务结束等待时间",
    )
    reuse_group = parser.add_mutually_exclusive_group()
    reuse_group.add_argument(
        "--reuse-browser",
        dest="reuse_browser",
        action="store_true",
        help="复用常驻 CloakBrowser（默认）",
    )
    reuse_group.add_argument(
        "--no-reuse-browser",
        dest="reuse_browser",
        action="store_false",
        help="禁用复用，执行一次性浏览器任务并在结束后关闭",
    )
    parser.set_defaults(reuse_browser=True)
    parser.add_argument("--close-browser", action="store_true", help="关闭当前常驻 CloakBrowser")
    parser.add_argument("--max-frames", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--selector-path", type=Path, default=DEFAULT_SELECTOR_PATH)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--endpoint-path", type=Path, default=None)
    parser.add_argument("--browser-daemon", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.login_wait_seconds < 0 or args.stay_open_seconds < 0:
        parser.error("等待时间不能小于 0")
    if not 1 <= args.max_frames <= 100:
        parser.error("--max-frames 必须在 1 到 100 之间")
    if not 1_000 <= args.timeout_ms <= 300_000:
        parser.error("--timeout-ms 必须在 1000 到 300000 之间")
    if args.close_browser and not args.reuse_browser:
        parser.error("--close-browser 不能与 --no-reuse-browser 同时使用")
    if args.browser_daemon and (args.close_browser or args.query):
        parser.error("--browser-daemon 只能由脚本内部启动")
    return args


async def run_local_browser(args: argparse.Namespace) -> int:
    if args.browser_daemon:
        return await run_browser_daemon(args)
    if args.close_browser:
        return await close_browser(args)
    if args.reuse_browser:
        return await run_reused_browser(args)
    return await run_standalone_browser(args)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_local_browser(parse_args())))
