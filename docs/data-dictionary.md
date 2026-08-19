# XVI 数据字典

- **文档状态**：Phase 1 初版
- **更新时间**：2026-08-11
- **数据源原则**：PostgreSQL/内部存储是事实源；飞书若接入，只是可重建投影

## 1. 命名和通用约定

- 主键使用 UUID。
- 时间统一使用 UTC 存储和 ISO 8601 表示。
- API 字段使用 `snake_case`。
- 数据库表名使用小写下划线和复数形式。
- 业务删除优先使用软删除或 Suppression Key。
- 不存 Cookie、Authorization、验证码、二维码、密码和原始 CDN URL。
- 所有来源访问数据必须带 `source_platform`、`source_url`、`captured_at` 或明确为空的原因。
- 所有模型输出必须带 Provider、Model、Prompt 版本。

## 2. Phase 1 核心实体

### 2.1 `browser_profiles`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | Profile 内部 ID |
| `name` | text | 显示名称 |
| `profile_path` | text | 宿主机专用路径，API 不直接返回 |
| `enabled` | boolean | 是否允许调度 |
| `session_status` | enum | `unknown/authenticated/auth_required/blocked` |
| `approval_id` | text nullable | 授权审批编号 |
| `approval_expires_at` | timestamptz nullable | 审批到期时间 |
| `lease_owner` | text nullable | 当前租约持有者 |
| `lease_expires_at` | timestamptz nullable | 租约到期时间 |
| `lease_heartbeat_at` | timestamptz nullable | 最近心跳时间 |
| `paused_reason` | text nullable | 暂停原因 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

明确禁止字段：`cookie`、`cookies`、`storage_state`、`access_token`、`refresh_token`。

### 2.2 `search_tasks`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 检索任务 ID |
| `query_text` | text | 最终检索词 |
| `profile_id` | UUID | 绑定 Profile |
| `max_results` | integer | 最大候选数 |
| `max_scrolls` | integer | 最大滚动次数 |
| `max_frames_per_note` | integer | 单笔记最大图片数 |
| `enabled` | boolean | 是否启用 |
| `priority` | smallint | 优先级 |
| `config_version` | text | 配置版本 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

### 2.3 `browser_runs`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 运行 ID |
| `search_task_id` | UUID nullable | 来源任务 |
| `profile_id` | UUID | 使用的 Profile |
| `query_text` | text | 本次查询 |
| `status` | enum | 运行状态 |
| `current_step` | text | 当前步骤 |
| `selector_version` | text | 选择器版本 |
| `capture_policy_version` | text | 采集策略版本 |
| `started_at` | timestamptz | 开始时间 |
| `finished_at` | timestamptz nullable | 结束时间 |
| `error_code` | text nullable | 错误码 |
| `artifact_uri` | text nullable | Artifact 目录或对象引用 |
| `created_at` | timestamptz | 创建时间 |

### 2.4 `candidates`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 候选 ID |
| `browser_run_id` | UUID | 来源运行 |
| `source_platform` | text | 例如 `xhs_web` |
| `source_url` | text | 业务来源链接 |
| `normalized_url` | text | 规范化链接 |
| `visible_title` | text nullable | 页面可见标题 |
| `visible_publish_hint` | text nullable | 页面可见发布时间提示 |
| `result_rank` | integer | 搜索结果排名 |
| `dedup_key` | text | 候选幂等键 |
| `status` | enum | `discovered/opened/failed/skipped` |
| `discovered_at` | timestamptz | 发现时间 |

唯一约束建议：`(source_platform, dedup_key)`。

### 2.5 `notes`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 笔记内部 ID |
| `candidate_id` | UUID | 来源候选 |
| `source_url` | text | 笔记链接 |
| `title` | text nullable | 最小化可见标题 |
| `captured_at` | timestamptz | 采集时间 |
| `capture_complete` | boolean | 是否完整遍历 |
| `expected_image_count` | integer nullable | 页面可见预期数量 |
| `captured_image_count` | integer | 截图数量 |
| `workflow_status` | enum | 笔记处理状态 |
| `vision_status` | enum | `not_requested/pending/processing/completed/failed` |
| `deleted_at` | timestamptz nullable | 删除时间 |

### 2.6 `image_assets`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 资产 ID |
| `note_id` | UUID | 所属笔记 |
| `source_index` | integer | 轮播原始顺序，从 0 开始 |
| `capture_method` | enum | `visible_download/rendered_screenshot` |
| `temp_uri` | text nullable | 临时资产引用 |
| `thumbnail_uri` | text nullable | 可选内部缩略图 |
| `width` | integer | 宽度 |
| `height` | integer | 高度 |
| `mime_type` | text | JPEG/PNG/WebP |
| `sha256` | text | 精确 Hash |
| `phash` | text nullable | 感知 Hash |
| `capture_status` | enum | `success/duplicate/failed/expired/deleted` |
| `expires_at` | timestamptz nullable | 原始帧到期时间 |
| `thumbnail_expires_at` | timestamptz nullable | 缩略图到期时间 |
| `created_at` | timestamptz | 创建时间 |

禁止字段：原始 CDN URL、签名参数、Cookie、作者隐私信息。

### 2.7 `vision_results`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 结果 ID |
| `note_id` | UUID | 所属笔记 |
| `provider_name` | text | Provider 名称 |
| `model_name` | text | 模型名称 |
| `model_version` | text nullable | 模型版本 |
| `prompt_version` | text | Prompt 版本 |
| `input_asset_ids` | jsonb | 输入图片 ID 和顺序 |
| `input_hash` | text | 输入资产集合和顺序的稳定 Hash |
| `result_json` | jsonb | Schema 校验后的结构化结果 |
| `status` | enum | `completed/invalid/timeout/failed` |
| `error_code` | text nullable | 错误码 |
| `created_at` | timestamptz | 创建时间 |

唯一键建议：`(note_id, provider_name, model_name, prompt_version, input_hash)`。

### 2.8 `audit_events`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 审计 ID |
| `actor_type` | enum | `user/service/system` |
| `actor_id` | text nullable | 操作者 |
| `action` | text | 行为名称 |
| `target_type` | text | 目标类型 |
| `target_id` | UUID/text | 目标 ID |
| `run_id` | UUID nullable | 关联运行 |
| `before_state` | jsonb nullable | 变更前状态，需脱敏 |
| `after_state` | jsonb nullable | 变更后状态，需脱敏 |
| `metadata` | jsonb nullable | 额外信息，需脱敏 |
| `created_at` | timestamptz | 发生时间 |

禁止保存图片二进制、Cookie、Token、验证码和授权请求头。

## 3. 状态枚举

### 3.1 BrowserRun 状态

```text
QUEUED
POLICY_CHECKED
ACQUIRING_PROFILE
CHECKING_SESSION
SEARCHING
COLLECTING_RESULTS
OPENING_NOTE
CAPTURING
CAPTURED
VISION_PENDING
VISION_PROCESSING
COMPLETED
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

### 3.2 资产状态

```text
success
duplicate
failed
expired
deleted
```

### 3.3 错误码

```text
SOURCE_POLICY_DISABLED
PROFILE_LEASE_CONFLICT
AUTH_REQUIRED
CHALLENGE_PRESENT
SELECTOR_DRIFT
PAGE_TIMEOUT
SESSION_CLOSED
RESULT_PARSE_FAILED
NOTE_OPEN_FAILED
CAPTURE_INCOMPLETE
FRAME_INVALID
MODEL_UNAVAILABLE
VISION_INVALID_RESPONSE
SYNC_FAILED
```

## 4. Artifact 文件

```text
artifacts/browser-runs/<run_id>/
├── manifest.json
├── steps.jsonl
├── result.json
├── diagnostics.json
├── failure.jpg
└── frames-manifest.json
```

`frames-manifest.json` 只记录：资产 ID、source index、宽高、Hash、临时 URI、过期时间和采集状态。

## 5. 幂等键

| 对象 | 幂等键 |
|---|---|
| 候选内容 | `sha256(source_platform + normalized_url)` |
| 笔记采集批次 | `candidate_id + capture_policy_version` |
| 图片帧 | `note_id + source_index + sha256(frame_bytes)` |
| 视觉结果 | `note_id + provider + model + prompt_version + input_hash` |
| 删除请求 | `target_type + target_id + deletion_policy_version` |

## 6. 配置项

```dotenv
SOURCE_ACCESS_MODE=disabled
CAPTURE_MODE=visible_download_or_rendered
ALLOW_VISIBLE_DOWNLOAD=true
ALLOW_NETWORK_EXTRACTION=false
ALLOW_SOCIAL_WRITE_ACTIONS=false
ALLOW_STEALTH=false
ALLOW_CAPTCHA_BYPASS=false
ALLOW_COOKIE_EXPORT=false
ALLOW_RAW_IMAGE_PERSISTENCE=false

BROWSER_MAX_RESULTS=30
BROWSER_MAX_SCROLLS=5
BROWSER_MAX_FRAMES_PER_NOTE=30
BROWSER_STEP_TIMEOUT_SECONDS=30

VISION_PROVIDER_MODE=disabled
VISION_MODEL_NAME=
VISION_TIMEOUT_SECONDS=60
VISION_MAX_IMAGES_PER_NOTE=8
VISION_ALLOW_DATA_EGRESS=false

RAW_ASSET_TTL_HOURS=24
FAILURE_SCREENSHOT_TTL_DAYS=14
TRACE_TTL_DAYS=7
THUMBNAIL_TTL_DAYS=30
```
