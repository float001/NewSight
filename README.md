## NewSight

面向安全从业者的「本机实时漏洞/安全新闻监控」流水线：

- **每小时抓取 RSS**（Python）
- **标题静态匹配**（内置中英文安全相关关键词，可配置扩展）
- **写入 Markdown**：
  - **今日**：`content/today.md`
  - **归档**：`content/archive/YYYY/MM/YYYY-MM-DD.md`
- **GitHub Pages 展示**：`site/` 使用 **Astro** 构建静态站，Actions 部署 Pages

### 仓库结构

| 路径 | 作用 |
| --- | --- |
| `vulnwatch/` | RSS 获取、去重、静态匹配、生成 Markdown |
| `content/` | 输出目录：`today.md` 与 `archive/` |
| `site/` | Astro 前端站点：展示 today 与归档 |
| `config.yaml` | 配置（RSS/关键词/安全匹配/输出路径） |
| `run-hourly.sh` | 单次运行脚本（适配 `.env`，可自动推送 `content/` 到 GitHub） |

### 安装（本机）

建议使用 venv（PEP 668 环境下必须）：

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 配置

编辑 `config.yaml`：

- **`rss`**：你的 RSS 列表或 OPML（必填，否则会生成空的 `today.md`）
- **`rss_config.timeout_s`**：单个 feed 拉取超时（秒）
- **`rss_config.opml_timeout_s`**：OPML 拉取超时（秒）（GitHub raw 可能较慢）
- **`rss_config.opml_retries`**：OPML 拉取失败重试次数
- **`rss_config.opml_retry_backoff_s`**：OPML 重试退避时间（秒），每次重试会递增等待
- **`keywords.fetch_within_hours`**：只处理“当前时间往前 N 小时”窗口内发布的资讯；但 `today.md` 会从 `state.db` 渲染**当日全量**
- **`keywords.include` / `exclude`**：标题子串粗筛（`include` 为空表示不过滤）
- **`security_match.patterns`**：在内置中英文安全相关子串基础上追加；任一子串命中标题则视为安全相关并入库（仍兼容旧配置里的 `vuln` / `security` 键作为追加项）
- **`log.level`**：日志级别（`INFO` 默认；排查问题可用 `DEBUG`）
- **`db_path`**：本地 SQLite（默认 `state/state.db`），用于当日全量累计与去重

环境变量（推荐写进 `.env`，`run-hourly.sh` 会自动加载）：

```bash
NewSight_GITHUB_TOKEN="..."   # 可选：用于自动推送 content/ 到 GitHub
```

### 运行

单次运行：

```bash
./run-hourly.sh
```

运行后会生成/更新：

- `content/today.md`
- `content/archive/YYYY/MM/YYYY-MM-DD.md`

### 每小时定时（cron）

```cron
0 * * * * /path/to/repo/run-hourly.sh >> /path/to/repo/run.log 2>&1
```

### GitHub Pages

- 工作流：`/.github/workflows/pages.yml`
- 前端：`site/`（Astro）

