# XVI 运行手册

- **文档状态**：Phase 1 初版
- **更新时间**：2026-08-11
- **适用范围**：本地单容器 Bundle、授权浏览器采集、可见下载/渲染资产、视觉模型调用和故障处理

## 1. 启动前检查

1. 确认 `SOURCE_ACCESS_MODE` 当前值。
2. 确认目标 Profile 有有效审批记录。
3. 确认审批未过期且允许的动作包含 search/open/view/capture-rendered-region。
4. 确认 Profile 没有活跃租约。
5. 确认 `ALLOW_STEALTH`、`ALLOW_CAPTCHA_BYPASS`、`ALLOW_COOKIE_EXPORT` 和 `ALLOW_SOCIAL_WRITE_ACTIONS` 都是 `false`。
6. 确认运行结果数量、滚动次数和图片数限制已设置。
7. 确认 Artifact 和临时目录可写，且不在 Git 或公共共享目录中。
8. 确认视觉 Provider 状态和数据出域策略。

## 2. 人工登录

建议命令：

```bash
xvi profile login --profile <profile-name>
```

流程：

1. 获取 Profile 锁。
2. 以 headed 模式打开浏览器。
3. 操作员完成正常登录、扫码或平台要求的验证。
4. 系统仅通过可见页面状态检查登录是否成功。
5. 记录登录运行 ID、状态和时间。
6. 关闭浏览器并释放锁。

禁止：

- 导出 Cookie；
- 保存二维码截图到长期存储；
- 复制 Profile 到其他机器；
- 自动处理验证码或安全挑战。

## 3. AUTH_REQUIRED：登录失效

处理步骤：

1. 确认当前运行已暂停。
2. 确认 Profile 没有其他活跃租约。
3. 检查失败 Artifact，不要打印敏感页面内容。
4. 执行人工登录命令。
5. 使用只读状态命令确认会话恢复。
6. 恢复 Profile 调度。
7. 重新投递因登录失效中止的运行。

不应做：

- 自动切换账号；
- 复制其他 Profile；
- 自动刷新并反复尝试；
- 删除锁文件强行启动。

## 4. BLOCKED / CHALLENGE_PRESENT：挑战页面

处理步骤：

1. 立即停止当前运行。
2. 暂停目标 Profile。
3. 记录脱敏截图和错误码。
4. 保存当前步骤和页面 URL Hash/host。
5. 通知运行管理员和合规负责人。
6. 等待人工确认下一步。

禁止自动刷新、切换账号、调用验证码服务、启用代理或绕过安全验证。

## 5. SELECTOR_DRIFT：选择器漂移

处理步骤：

1. 保留失败 Artifact。
2. 确认不是登录失效或挑战页面。
3. 在 Fixture 中复现 DOM 变化。
4. 更新 Selector Registry，而不是直接在业务代码中添加硬编码。
5. 增加或更新本地 Fixture。
6. 运行 Contract Tests。
7. 使用测试 Profile 进行单查询 Live Smoke。
8. 审批新的 Selector 版本。
9. 对漂移期间被错误标记为空结果的任务进行重跑。

恢复前必须确认：搜索框、结果卡片、笔记区域和轮播区域均能被定位。

## 6. CAPTURE_INCOMPLETE：轮播不完整

处理步骤：

1. 检查 `frames-manifest.json` 的最后索引和 Hash。
2. 检查是否达到最大帧数。
3. 检查下一张按钮是否没有变化或被页面遮挡。
4. 只允许按配置进行一次重新打开笔记。
5. 再次失败则保留 `capture_complete=false`。
6. 不得把不完整笔记当作完整成功。
7. 不完整结果进入复核或灰区，不进入高置信度发布。

## 7. MODEL_UNAVAILABLE：视觉模型不可用

处理步骤：

1. 保留已采集资产引用和运行状态。
2. 检查 Provider 健康状态、超时和配额。
3. 只重试 VisionProvider，不重新访问来源。
4. 超过重试次数后标记 `MODEL_UNAVAILABLE`。
5. 如果原始帧已过期，记录无法重跑的原因。
6. 恢复模型后从已有资产继续处理。

## 8. 临时资产清理

每日执行 Cleanup：

1. 查询已过期的原始帧和失败截图。
2. 校验资产未处于正在推理状态。
3. 删除文件或对象。
4. 清空数据库中的临时 URI。
5. 保留清理结果、时间、数量和失败原因。
6. 对连续清理失败产生告警。

不得删除仍被活动运行引用的临时资产。

## 9. 紧急停止

触发条件：

- 发现不安全依赖；
- 出现 Cookie/Token 泄露迹象；
- 访问模式或审批配置错误；
- 发生挑战页面批量出现；
- 选择器漂移导致错误采集；
- 视觉模型 Provider 未经批准发生数据出域。

处理步骤：

1. 将全局 `SOURCE_ACCESS_MODE` 设置为 `disabled`。
2. 暂停所有 Profile。
3. 停止 Browser Worker。
4. 保留脱敏审计和 Artifact。
5. 隔离临时资产并按合规策略处理。
6. 创建事故记录和 ADR/踩坑记录。
7. 未完成审查前不得恢复真实来源访问。

## 10. 只读 Live Smoke

仅允许在以下条件全部满足时执行：

- 有有效授权和测试 Profile；
- 操作员在场；
- 单个检索词；
- 最多 3 条候选；
- 不执行任何写操作；
- 不进入普通 CI；
- 运行 Artifact 已启用；
- 能够随时停止任务。

## 11. 本地单容器 Bundle

本地开发可以使用单容器模式：`xvi` 容器内由 Supervisor 管理 PostgreSQL、Redis、FastAPI 和一次性 Browser Worker。该模式用于本地 Fixture 验证，不作为生产部署边界。

启动：

```powershell
Copy-Item .env.example .env
docker compose build
docker compose up -d xvi
docker compose ps
docker compose logs -f xvi
```

检查四类进程：

```powershell
docker compose exec xvi supervisorctl status
docker compose exec xvi pg_isready -h 127.0.0.1 -U xvi
docker compose exec xvi redis-cli -h 127.0.0.1 ping
docker compose exec xvi python -m xvi.cli config validate
```

Worker 当前只执行一次 Fixture 采集，成功后显示 `EXITED (expected)` 属于正常状态；需要重新运行时执行：

```powershell
docker compose exec xvi supervisorctl start browser-worker
```

数据目录：

- `/data/postgres`：PostgreSQL 数据卷；
- `/data/redis`：Redis AOF/RDB 数据卷；
- `/data/assets`：图片资产卷；
- `/data/artifacts`：运行 Artifact 卷；
- `/data/profiles`：授权浏览器 Profile 卷。

停止时使用 `docker compose down` 保留数据。不要使用 `docker compose down -v`，除非明确要删除所有本地数据库、缓存和采集结果。

注意：当前 Python 业务代码尚未接入 PostgreSQL/Redis 客户端和 Repository；本次单容器改造只保证两个基础服务在本地随容器启动并持久化，不代表业务数据已经写入数据库或 Redis。