# XVI 当前实施计划

- **计划版本**：Phase 1 v1.0
- **更新时间**：2026-08-11
- **当前阶段**：Phase 3 Fixture 采集链路与 Docker 验证
- **目标**：全 Docker 完成授权浏览器采集，优先保存可见下载文件，再以渲染截图兜底；视觉模型后置
- **已完成切片**：Python 工程、配置安全门禁、Fixture 搜索/打开/轮播采集、图片校验、Artifact 和 Docker 验证工具链已写入代码

## 1. 实施原则

1. 先完成本地 Fixture，再接触真实来源。
2. 一次只实现一个可验证的垂直切片。
3. 先确认行为和接口，再写代码。
4. 所有浏览器行为必须有停止条件、Artifact 和错误码。
5. 默认关闭真实来源访问。
6. 视觉模型失败不能导致重复来源访问。
7. 不将自训练模型、飞书同步或复杂调度作为采集链路前置条件。
8. 每个任务完成后更新进度、测试结果和已知限制。

## 2. 阶段计划

### Phase 0：工程基线

**目标**：建立可运行、可检查的 Python 工程。

交付：

- `pyproject.toml` 和 `uv.lock`；
- Ruff、Mypy、Pytest；
- `.env.example`；
- 基础 CI；
- 禁止依赖扫描；
- 敏感信息扫描；
- 基础项目说明。

验收：

- 本地依赖可安装；
- 空服务可启动；
- 默认来源访问关闭；
- 不包含 stealth、指纹、代理轮换和验证码依赖。

### Phase 1：配置、领域模型和安全门禁

**目标**：让不安全配置在启动或运行前失败。

交付：

- `SourceAccessMode`、`CaptureMode`、运行状态和错误码；
- Pydantic Settings；
- 审批状态模型；
- Profile 和运行权限校验；
- 配置校验 CLI。

验收：

- `ALLOW_STEALTH=true` 等禁止组合无法启动；
- 无有效审批不能启用 `authorized_browser`；
- 生产环境禁止使用默认 Secret。

### Phase 2：最小持久化与运行状态

**目标**：保存 Profile、任务、候选、笔记、图片资产和运行记录。

交付：

- Async SQLAlchemy；
- 初始 Alembic 迁移；
- Repository；
- 最小状态机；
- 审计事件；
- 文件和临时资产抽象。

验收：

- 空库可升级；
- 关键幂等键稳定；
- 非法状态迁移失败；
- 删除或过期资产后没有悬挂 URI。

### Phase 3：Fixture 浏览器流水线

**目标**：不访问真实平台，完成搜索、打开笔记和轮播截图的完整验证。

交付：

- `FixtureSourceAdapter`；
- 本地 Fixture Web App；
- Profile 模拟；
- 搜索结果 Fixture；
- 单图、多图、懒加载、循环、挑战和选择器漂移 Fixture；
- Playwright Contract Tests。

验收：

- 可完成一次 Fixture 搜索；
- 可打开一条多图笔记；
- 可识别轮播停止；
- 挑战页立即停止；
- Selector Drift 不返回空结果。

### Phase 4：真实 Profile 和授权浏览器采集

**目标**：在审批和人工在场条件下完成最小 Live Smoke。

交付：

- `launch_persistent_context`；
- Profile 文件锁；
- 数据库租约；
- 人工登录 CLI；
- Session Probe；
- 搜索、候选、笔记和轮播适配器；
- 可见下载捕获与渲染截图兜底；
- Docker Compose 中的 Chromium Worker；
- 运行 Artifact。

限制：

- 一个测试 Profile；
- 一个检索词；
- 最多 3 条候选；
- 只读；
- 操作员在场；
- 不进入普通 CI。

### Phase 5：VisionProvider

**目标**：让已采集图片可以交给视觉模型处理。

交付：

- Provider Protocol；
- Mock Provider；
- 严格 JSON Schema；
- Prompt 版本管理；
- 超时、重试和无效响应处理；
- Local 或 Approved External Provider；
- 模型调用审计。

验收：

- Mock 端到端测试通过；
- 模型无效 JSON 不进入正式决策；
- 模型不可用不重新访问来源；
- 图片出域策略可配置。

### Phase 6：采集与视觉端到端

**目标**：完成一次真实或 Fixture 的“搜索 → 可见下载/渲染截图 → 资产校验 → 清理”流程。

交付：

- `xvi search run-once`；
- 图片临时存储；
- 可见下载和渲染截图两种采集方式；
- Hash 和基础质量信息；
- 资产清单和 TTL Cleanup；
- 失败重试和运行报告。

验收：

- 每条图片有顺序和 Hash；
- 每次运行有 Artifact；
- 原始帧按策略清理；
- 失败状态可以定位到具体步骤。

## 3. 后置计划

完成 Phase 6 后，再评估：

- Celery/Redis 调度；
- 飞书投影；
- Label Studio；
- 人工反馈；
- DINOv2 或其他本地 Embedding；
- 自训练分类器；
- LightGBM；
- MLflow；
- 主动学习；
- 生产级多 Profile 调度。

## 4. 单个开发任务的完成标准

每个任务必须包含：

- 关联需求编号或 ADR；
- 实现范围和不在范围；
- 计划修改/新增的文件；
- 验收条件；
- 相关测试；
- 实际测试结果；
- 已知限制；
- 新增踩坑记录（如有）。

## 5. 当前下一步

1. 实现 Profile 文件锁、数据库租约和真实来源访问前的 Policy Gate；
2. 在 Docker 中接入并验证用户提供的 `lark-cli` 二进制和认证卷，保持飞书 Base 只读；
3. 由操作员提供授权 Profile 后，更新并现场验证真实小红书 Selector；
4. 完成上述前置条件后，再安排人工在场的单查询 Live Smoke；
5. 后续再实现 Mock/Approved VisionProvider 和临时资产 TTL Cleanup。

当前不允许在真实 Selector 未经现场验证前批量运行，也不允许把真实来源访问加入普通 CI。
