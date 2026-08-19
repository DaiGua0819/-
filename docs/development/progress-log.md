# XVI 开发进度记录

## 当前状态

- **更新时间**：2026-08-11
- **总体状态**：已完成 Fixture 垂直切片，进入 Docker 验证和真实来源前置准备
- **代码状态**：Fixture 采集链路、Docker 镜像和静态检查已通过
- **当前阶段**：Phase 3 Fixture 采集链路与 Docker 验证
- **真实来源访问**：未启用
- **视觉模型**：尚未接入

## 已完成事项

### 2026-08-11：需求规格阅读

- 已完整阅读原始开发规格：
  `C:\Users\xinli.wang\Downloads\XHS_VISUAL_INTELLIGENCE_MVP_DEVELOPMENT_SPEC.md`
- 已确认原规格覆盖产品范围、浏览器适配、视觉分析、任务编排、飞书、安全、测试和验收。

### 2026-08-11：方案调整

已确认第一阶段调整为：

1. 优先实现授权浏览器采集；
2. 通过正常网页可见操作搜索和打开笔记；
3. 只截取浏览器已经渲染的图片区域；
4. 视觉模型采用可插拔 Provider；
5. 不以自训练模型作为第一阶段前置条件；
6. 自训练、标注、LightGBM、MLflow 和主动学习后置；
7. 默认不保存原始帧，不导出 Cookie，不访问私有接口。

### 2026-08-11：文档体系初始化

已建立：

- 需求基线；
- 技术架构设计；
- ADR-001；
- 实施计划；
- 进度记录；
- 踩坑记录；
- 运行手册；
- 数据字典。

## 当前待办

- [x] 初始化 Python 工程和 `uv` 配置；
- [x] 建立基础测试框架；
- [x] 建立安全开关和配置校验；
- [x] 建立最小领域模型和错误码；
- [x] 建立本地 Fixture Web App；
- [x] 实现 Fixture SourceAdapter；
- [ ] 实现 Profile 锁和租约；
- [x] 实现轮播截图状态机；
- [ ] 实现 Mock VisionProvider；
- [ ] 生成并提交 `uv.lock`，锁定完整依赖解析结果。

## 当前阻塞项

1. 首批品牌、地点、事件词尚未确认。
2. `authorized_browser` 审批范围、账号和有效期尚未确认。
3. 真实小红书登录后的 Selector 尚未现场验证。
4. Docker 容器内 `lark-cli` 二进制和用户认证卷尚未集成验证。
5. `uv.lock` 尚未生成；当前 Docker 构建仍按精确项目依赖版本解析。
6. 视觉模型 Provider 尚未确定；第一阶段保持关闭。

## 记录规则

每完成一个实施任务，追加：

- 日期；
- 任务和关联文档；
- 修改文件；
- 测试命令和结果；
- 已知限制；
- 新增决策或踩坑。

### 2026-08-11：文档复核

- 已逐份复核 8 个文档文件和 docs 目录结构。
- 确认需求、架构、ADR、实施计划、运行手册和数据字典均以“授权浏览器采集优先、VisionProvider 可插拔、暂不自训练”为一致基线。
- 修正数据字典：为 `vision_results` 增加 `input_hash` 字段，使其与视觉结果唯一键定义一致。
- 当前未修改任何业务代码，真实来源访问仍未启用。

### 2026-08-11：第一阶段 Fixture 采集实现与 Docker 验证准备

- 已建立 Python 工程和最小领域模型、配置安全门禁、Selector Registry、Fixture SourceAdapter、轮播采集器、FrameStore、ArtifactWriter、飞书 CLI 只读查询适配器以及 XHS Web 适配器骨架。
- Fixture 采集链路已覆盖：页面可见搜索、候选笔记打开、可见下载按钮、下载失败时渲染区域截图兜底、三张轮播、首帧回环检测、图片格式校验、SHA-256/pHash 和运行 Artifact。
- 已修正 Docker 验证镜像：包含测试文件、`pytest`、`pytest-asyncio`、`ruff`、`mypy` 和项目配置。
- 已将 `browser-worker` 标记为一次性 Fixture 验证任务并关闭自动重启，避免容器退出后重复采集。
- 已新增 ADR-002，明确“原图”只指页面可见下载入口产生的文件；截图只作为可见下载不可用时的渲染区域兜底。
- 本次文档和代码修改尚未完成 Docker 实际构建与检查，待执行的命令包括 `docker compose build`、`docker compose config`、Docker 内 Pytest、Ruff 和 Mypy。

已知限制：真实小红书登录后的选择器尚未现场验证；Docker 镜像尚未集成或验证容器内 `lark-cli` 及其用户认证配置；尚未生成 `uv.lock`；真实来源 Live Smoke 不进入普通 CI。

### 2026-08-11：Docker 验证结果

已在 Windows Docker 环境执行并通过：

- `docker compose config`：通过，Compose 服务、健康检查、卷、一次性 Worker 配置均可解析。
- `docker compose build`：通过，生成 `api` 和 `browser-worker` 镜像；构建采用 Playwright `v1.54.0-noble`，运行用户为非 root 的 `xvi`。
- `docker compose run --rm --no-deps --entrypoint pytest browser-worker -q`：`7 passed`。
- `docker compose run --rm --no-deps --entrypoint ruff browser-worker check .`：`All checks passed!`。
- `docker compose run --rm --no-deps --entrypoint ruff browser-worker format --check .`：`39 files already formatted`。
- `docker compose run --rm --no-deps --entrypoint mypy browser-worker src apps`：`Success: no issues found in 31 source files`。
- `docker compose run --rm --no-deps --entrypoint python browser-worker -m xvi.cli config validate`：默认 `source_access_mode=disabled`、`capture_mode=visible_download_or_rendered`、`allow_visible_download=true`。
- `docker compose run --rm --no-deps --entrypoint python browser-worker scripts/check_forbidden_dependencies.py`：`forbidden dependency scan passed`。
- 一次性 `browser-worker` Fixture Smoke：成功发现 1 条候选，保存 3 张 `640x480` PNG；三张均为 `visible_download`，`capture_complete=true`，每张具有不同 SHA-256/pHash；Artifact 由测试确认包含 `manifest.json`、`steps.jsonl` 和 `result.json`。

本轮修复记录：

1. Playwright Noble 基础镜像未包含 `python3-venv`，改用固定版本 `uv==0.7.20` 创建虚拟环境。
2. 开发检查依赖和测试文件加入运行镜像，确保检查也在 Docker 内执行。
3. 修复非 root 用户对 Ruff/Pytest 缓存目录的写权限。
4. 修复 Fixture 测试包 docstring、Artifact `status` 重复参数、SourceAdapter 类型契约、飞书 JSON 类型收窄和 Ruff/Mypy 规则问题。
5. Fixture 画面改为可见 Canvas 绘制，轮播变化使用渲染区域截图 SHA-256 检测，确保三帧稳定区分。

尚未验证：真实小红书登录后的 Selector、人工授权 Browser Profile、容器内 `lark-cli` 二进制和认证卷、真实来源 Live Smoke；`uv.lock` 仍待在 Docker 依赖流程中生成。

### 2026-08-11：交付复核与未完成项确认

- `config.yml` 与 `configs/selectors/xhs_web.yaml` SHA-256 一致，Selector 配置没有发生漂移。
- 所有变更 Python 文件的 IDE 诊断均无错误；来源访问边界扫描未发现响应监听、`storage_state`、Cookie 读取、`src/srcset` 提取、HTTP 图片请求或禁止依赖引用。
- 已新增 `.gitignore`，忽略本地 `.env` 和测试缓存，避免验证配置误提交。
- 宿主机未安装 Git，`git status`/`git diff --check` 未能执行；没有创建或修改 Git commit。
- 已在临时 Docker Builder 中确认 `uv lock` 可以解析 44 个包，但由于当前环境未将临时容器文件写回工作区，项目 `uv.lock` 仍未生成；下一步应使用项目认可的 Docker 依赖导出流程写入并复核该文件。
- 容器运行时确认未安装 `lark-cli`，因此飞书 Base 的真实 Docker 查询和认证卷仍是集成阻塞项；当前仅完成宿主机 CLI 适配器的 JSON/字段映射测试。

### 2026-08-11：本地单容器 Bundle 构建与运行完成

本轮将本地 Compose 从 PostgreSQL、Redis、API、Browser Worker 四个容器收敛为一个 `xvi` 容器：

- 镜像：`xiaohongshu:all-in-one`；
- Supervisor PID 1 管理 PostgreSQL、Redis、FastAPI 和一次性 Browser Worker；
- PostgreSQL 数据保存到 `postgres_data`，Redis AOF/RDB 保存到 `redis_data`；
- 图片、Artifact、Profile 和飞书配置继续使用独立 named volume；
- 只对宿主机暴露 API `8000`，PostgreSQL/Redis 仅监听容器内 `127.0.0.1`。

实际验证结果：

1. `docker compose build`：通过，安装 PostgreSQL `16.14`、Redis `7.0.15`、Supervisor `4.2.5` 和现有 Playwright/Python 依赖。
2. `docker compose config`：通过，Compose 仅包含 `xvi` 服务和六个 named volume。
3. `docker compose up -d xvi`：通过，容器状态为 `healthy`。
4. `supervisorctl status`：`api RUNNING`、`postgres RUNNING`、`redis RUNNING`、`browser-worker EXITED`；Worker 的退出码为 0，符合当前一次性 Fixture 任务设计。
5. `pg_isready`：`127.0.0.1:5432 - accepting connections`。
6. `redis-cli ping`：`PONG`。
7. API `/health`：返回 `{"status":"ok","version":"0.1.0"}`。
8. Fixture Worker：成功保存 3 张 `640x480` PNG，均为 `visible_download`，`capture_complete=true`。
9. 容器内检查：Pytest `7 passed`；Ruff check、Ruff format、Mypy、配置校验和禁止依赖扫描均通过。
10. 数据持久化：写入 Redis 测试键并执行 `docker compose restart xvi` 后可读回；重启后 PostgreSQL `xvi` 数据库仍可访问；容器重新恢复 `healthy`。
11. 停止行为：`docker compose stop xvi` 能正常停止，`docker compose start xvi` 能恢复四个进程和健康状态；入口脚本 `bash -n` 通过。

限制和注意事项：

- 这是本地单容器 Bundle，不建议作为生产部署；生产应恢复 API、Browser Worker、PostgreSQL、Redis 独立服务。
- 当前 Python 代码尚未接入 PostgreSQL/Redis 客户端、Repository、迁移或队列；本轮只保证基础服务随容器启动和数据卷持久化。
- 单容器使用 Ubuntu Noble 仓库的 Redis `7.0.15`，不是原 Compose 的 `redis:7.4-alpine`；当前代码未依赖 Redis 版本差异，后续若需要 Redis 7.4 应单独固定安装源和版本。
- 单容器没有安装 `pgvector` 扩展；当前代码未使用数据库向量能力，后续接入数据库前需要单独决定 PostgreSQL/pgvector 安装方案。
- Browser Worker 每次容器启动都会执行一次 Fixture；真实来源启用前必须改为明确的任务模式，避免容器重启造成重复采集。
- 容器内仍未安装 `lark-cli`，飞书 Base 的真实 Docker 查询和认证卷集成仍未完成；真实小红书 Selector、授权 Profile 和 Live Smoke 已在宿主机本地完成一次单查询验收，但容器内真实来源 Live Smoke 尚未完成。
### 本轮：宿主机真实小红书 Live Smoke 验收

已在 Windows 宿主机使用持久化授权 Profile `.data/profiles/xhs-local`，通过可见 CloakBrowser 执行一次真实只读搜索：

- 固定查询：`小奥汀 快闪`，来源为飞书 Base 2 的第一条 P0 检索规则。
- 结果：搜索到 15 条候选，第一篇笔记成功打开；笔记标题为“快闪进行中|千禧数码屋信号满格，正式营业”。
- 采集：轮播完成 10 张 `702x936` JPEG 渲染截图，`capture_complete=true`；每张均记录 SHA-256 与 pHash，本次轮播内未发现重复帧。
- Artifact：`.data/artifacts/44c36846-a7d5-4bea-98be-5d2c78252c76/`，包含 `manifest.json`、`steps.jsonl`、`result.json`；图片位于 `.data/assets/281ae662-5d36-4f83-95a5-502dd4b3ca8a/`。
- 适配修复：Selector Registry 版本升级到 `1.0.2`，增加真实结果卡片、笔记容器、活动轮播图和下一张控件选择器；搜索结果和笔记容器均增加可见条件等待；保留可见笔记链接中的访问参数。
- 约束：本次只执行搜索、打开、查看和渲染区域截图，没有执行点赞、评论、关注、私信、发布或 Cookie 导出；浏览器和 Profile 已停止/释放。

Docker 化仍需单独完成容器内真实来源集成：当前镜像未安装 `cloakbrowser` 和 `lark-cli`，Compose 未提供 headed 显示环境，`scripts/local_xhs_browser.py` 默认使用 `.data/*` 路径且尚未接入 `/data/*` named volumes；因此本次结果只能证明宿主机本地真实链路，不代表容器内真实 Live Smoke 已通过。