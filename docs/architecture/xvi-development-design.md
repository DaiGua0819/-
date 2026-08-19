# XVI 技术架构与开发设计

- **文档状态**：Phase 1 设计基线
- **基线日期**：2026-08-11
- **关联需求**：`docs/requirements/xvi-requirements.md`
- **原始规格**：`C:\Users\xinli.wang\Downloads\XHS_VISUAL_INTELLIGENCE_MVP_DEVELOPMENT_SPEC.md`

## 1. 设计目标

第一阶段优先构建稳定、可审计、可暂停的授权浏览器采集链路。浏览器采集与视觉分析、业务决策、飞书同步必须解耦，使未来更换视觉模型不会影响来源适配器。

## 2. 总体架构

```text
┌──────────────────────────────────────────────┐
│ API / CLI                                    │
│ Profile · SearchTask · Run · Audit           │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ Policy Gate + Orchestration                  │
│ access mode · approval · lease · state       │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ Browser Worker                               │
│ Session · Search · Candidate · Note · Carousel│
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ Temporary Frame Store                        │
│ rendered frame · hash · manifest · TTL       │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ VisionProvider                               │
│ Mock · Local · Approved External              │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ PostgreSQL / Audit / Optional Projection      │
└──────────────────────────────────────────────┘
```

## 3. 组件边界

### 3.1 API / CLI

负责创建 Profile 元数据、创建检索任务、启动一次运行、查询运行状态、取消运行和查看脱敏 Artifact。API 不返回 Profile 路径、Cookie、内部对象存储凭据或完整浏览器上下文信息。

### 3.2 Policy Gate

在任何真实来源访问前校验：

- `SOURCE_ACCESS_MODE`；
- 数据库审批记录；
- 审批有效期；
- Profile 状态；
- 当前用户权限；
- 运行预算和并发限制。

Policy Gate 不允许仅凭请求参数绕过全局禁用。

### 3.3 Browser Worker

Browser Worker 是唯一可以持有 Playwright `BrowserContext` 和 `Page` 的组件。视觉、数据库和飞书模块不能直接调用 Playwright 对象。

每个 Profile 绑定一个专属队列，默认并发为 1。第一阶段可以使用进程内任务执行器，后续再接入 Celery/Redis。

### 3.4 SourceAdapter

平台相关代码只放在：

```text
src/xvi/adapters/source/xhs_web/
```

通用接口：

```python
class SourceAdapter(Protocol):
    async def ensure_session(self) -> SessionStatus: ...
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...
    async def open_note(self, result: SearchResult) -> NoteSnapshot: ...
    async def iter_rendered_frames(
        self,
        note: NoteSnapshot,
    ) -> AsyncIterator[RenderedFrame]: ...
    async def close_note(self) -> None: ...
```

接口不得包含评论、点赞、收藏、关注、私信或发布方法。

### 3.5 Selector Registry

选择器放在版本化 YAML 文件中：

```text
configs/selectors/xhs_web.yaml
```

定位优先级：

1. `get_by_role` 和可访问性名称；
2. `get_by_label`、`get_by_placeholder`；
3. 可见文本或公开属性；
4. 稳定 CSS fallback。

选择器不存在、数量异常或核心区域不可见时，必须产生 `SELECTOR_DRIFT`，不能返回空结果。

### 3.6 Capture Pipeline

```text
Locate carousel viewport
→ Wait stable
→ Detect visible download control
→ Visible download if available
→ Otherwise screenshot rendered region
→ Validate bytes
→ Compute SHA-256 / pHash
→ Detect repeated frame
→ Advance carousel
→ Wait visual change
→ Repeat or complete
```

图片保存优先使用页面上用户可见的下载入口，并通过 Playwright `expect_download()` 捕获浏览器下载结果；如果页面没有可见下载入口，则使用 `locator.screenshot()` 保存浏览器渲染区域。禁止读取 `src`、`srcset`、隐藏状态、网络响应、签名参数或直接请求图片地址。下载文件和渲染截图都进入受控临时资产目录，并按 TTL 清理。

### 3.7 VisionProvider

```python
class VisionProvider(Protocol):
    async def analyze_note(
        self,
        images: list[VisionImage],
        context: VisionContext,
    ) -> VisionAnalysis: ...
```

Provider 类型：

- `MockVisionProvider`：本地测试和端到端测试；
- `LocalVisionProvider`：企业内部部署的视觉模型；
- `ApprovedExternalVisionProvider`：经过数据出域审批的外部模型。

VisionProvider 不允许访问浏览器页面，只读取受控的临时图片数据。

### 3.8 Artifact Writer

每次运行输出：

```text
artifacts/browser-runs/<run_id>/
├── manifest.json
├── steps.jsonl
├── result.json
├── diagnostics.json
├── failure.jpg              # 仅失败或阻断时
└── frames-manifest.json
```

Artifact 中只保存脱敏 URL、Hash、索引、尺寸、状态和错误码，不保存 Cookie、Authorization、验证码、二维码或完整页面 HTML。

## 4. 端到端时序

```text
Create SearchRun
  → Policy Gate
  → Acquire Profile Lease
  → Launch Persistent Context
  → Ensure Session
  → Open Search Page
  → Submit Query
  → Collect Visible Results
  → Open Candidate Note
  → Iterate Carousel
  → Store Temporary Frames
  → Compute Hash / Basic Quality
  → Optional VisionProvider
  → Persist Results
  → Cleanup Temporary Frames
  → Release Lease
  → Complete Artifact
```

视觉模型不可用时，流程可以停在 `VISION_PENDING` 或 `MODEL_UNAVAILABLE`，不得重新访问来源。

## 5. 状态机

```text
QUEUED
→ POLICY_CHECKED
→ ACQUIRING_PROFILE
→ CHECKING_SESSION
→ SEARCHING
→ COLLECTING_RESULTS
→ OPENING_NOTE
→ CAPTURING
→ CAPTURED
→ VISION_PENDING
→ VISION_PROCESSING
→ COMPLETED
```

终止状态：

```text
AUTH_REQUIRED
BLOCKED
SELECTOR_DRIFT
CAPTURE_INCOMPLETE
PAGE_TIMEOUT
SESSION_CLOSED
MODEL_UNAVAILABLE
CANCELLED
FAILED_PERMANENT
```

所有迁移集中定义，非法迁移必须失败。

## 6. Profile 与租约

同时使用：

- 本机文件锁，防止同一宿主机重复打开 Profile；
- PostgreSQL 租约，防止不同节点并发使用 Profile。

租约字段：

```text
lease_owner
lease_expires_at
lease_heartbeat_at
```

建议租约 60 秒失效，心跳每 15 秒刷新。接管过期租约前必须确认旧浏览器进程已退出，不能通过删除 Chromium lock 文件强行恢复。

## 7. 数据与文件生命周期

默认 `CAPTURE_MODE=visible_download_or_rendered`：

```text
Visible Download or RenderedFrame
→ 受控临时文件
→ Validate / Hash / Basic Quality
→ 保存结构化资产记录
→ 按 TTL 清理
```

可见下载得到的文件仍然只能通过页面可见动作产生；系统不保存原始 CDN URL，不解析下载请求，也不自行重放请求。渲染截图作为没有可见下载入口时的兜底方式。下载文件和截图均需记录 `capture_method`，并按审批的保留期限清理。允许内部缩略图时，缩略图必须单独生成、脱除 EXIF、设置 TTL，并保留处理记录。

## 8. Docker 部署边界

第一阶段所有运行组件进入 Docker：

- `api`：控制 API 和 CLI 服务；
- `browser-worker`：包含 Chromium 和 Playwright 的授权浏览器工作节点；
- `postgres`：事实数据和租约；
- `redis`：第一阶段可选，后续用于队列；
- `fixture-web`：本地浏览器 Contract Test 页面。

浏览器 Profile、下载目录、Artifact 和临时资产使用受控 Docker volume。Profile 不挂载到普通共享目录，不进入镜像和 Git。headed 人工登录需要通过受控图形转发或一次性登录容器完成，不能把 Profile 导出到宿主机。

## 9. 后续扩展边界

第二阶段可增加：

- Celery/Redis 调度；
- PostgreSQL/pgvector；
- 图片质量和重复候选服务；
- 飞书投影；
- Label Studio 反馈；
- 模型版本管理；
- 主动学习和自训练模型。

这些扩展不能反向破坏第一阶段的访问安全边界。
