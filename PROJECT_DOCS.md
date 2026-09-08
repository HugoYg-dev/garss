# 🐣 嘎!RSS (garss) 项目深度分析文档

> **项目名称**: Github Actions RSS (garss)
> **作者**: zhaoolee
> **项目定位**: 基于 GitHub Actions 的 RSS 聚合 + 邮件推送 + 静态展示站点
> **核心理念**: 为打破信息茧房而生，提供无广告的优质信息流

---

## 一、项目概览

garss 是一个完全运行在 GitHub Actions 上的自动化系统，核心功能是：

1. **定时抓取** 228 个 RSS 源的最新文章
2. **生成展示页面**：将抓取结果渲染到 `README.md`，同时部署为 Docsify 静态文档站
3. **邮件推送**：将当天新文章以邮件形式推送给订阅者
4. **OPML 导出**：自动生成标准 OPML 订阅列表文件，方便用户一键导入 RSS 阅读器

### RSS 源分类（16 大类，228 个源）

| 分类 | 说明 |
|------|------|
| 软件工具 | 不死鸟、小众软件、异次元软件世界等 |
| 活着的个人独立博客 | 阮一峰、张鑫旭、DIYgod、云风等 135+ 个博客 |
| 数码 | 数码相关资讯 |
| IT团队博客 | 美团技术、淘系技术等团队博客 |
| 公司官方新闻 | 企业官方信息 |
| 互联网类 | 互联网行业资讯 |
| 金融类 | 金融财经信息 |
| 科技类 | 科技新闻与评论 |
| 学习类 | 学习资源与教程 |
| 学术类 | 学术研究动态 |
| 生活类 | 生活方式内容 |
| 设计类 | 设计相关资源 |
| 内容平台 | 知乎、掘金等平台热门内容 |
| 影视资源 | 影视相关信息 |
| 资源类 | 各类资源分享 |
| Telegram优质频道 | Telegram 频道 RSS 订阅 |

---

## 二、项目架构

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (cron)                     │
│              每日 UTC 22:00 (北京时间 06:00) 触发             │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      main.py 主程序                          │
│                                                             │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │create_json│  │ create_opml  │  │  replace_readme    │    │
│  │  生成JSON │  │  生成OPML    │  │  抓取RSS+渲染页面   │    │
│  └──────────┘  └──────────────┘  └─────────┬──────────┘    │
│                                             │               │
│                                    ┌────────▼────────┐      │
│                                    │  get_rss_info   │      │
│                                    │  多进程抓取RSS   │      │
│                                    │  (Pool=8进程)    │      │
│                                    └────────┬────────┘      │
│                                             │               │
│  ┌──────────────────┐  ┌──────────────────┐ │               │
│  │ cp_readme_to_docs│  │ cp_media_to_docs │ │               │
│  │  同步到docs目录   │  │  同步媒体文件     │ │               │
│  └──────────────────┘  └──────────────────┘ │               │
│                                             │               │
│                                    ┌────────▼────────┐      │
│                                    │   send_mail     │      │
│                                    │   邮件推送       │      │
│                                    └─────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Git Auto Commit & Push                          │
│     自动提交 README.md + docs/ 并推送到 GitHub                │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、文件结构详解

```
garss/
├── main.py                          # 🔑 核心程序入口（358行）
├── EditREADME.md                    # 📝 README模板文件（含模板变量）
├── README.md                        # 📄 生成的展示页面（由程序自动生成，勿手动编辑）
├── garssInfo.json                   # 📊 RSS源信息JSON（由程序自动生成）
├── Pipfile                          # 📦 Python依赖管理
├── Pipfile.lock                     # 🔒 依赖锁定文件
├── tasks.json                       # 📮 邮件接收者列表
├── rss-template-v1.txt              # 📋 OPML v1模板
├── rss-template-v2.txt              # 📋 OPML v2模板（含元数据）
├── zhaoolee_github_garss_subscription_list_v1.opml  # 生成的OPML v1
├── zhaoolee_github_garss_subscription_list_v2.opml  # 生成的OPML v2
├── tagit.sh                         # 🔧 快捷Git提交脚本
├── _config.yml                      # Jekyll主题配置（time-machine）
├── .gitignore                       # Git忽略规则
├── _media/                          # 媒体资源（favicon、logo等）
│   ├── ga-rss.png                   # 项目logo
│   ├── favicon.ico                  # 网站图标
│   └── favicon/                     # 各RSS源的favicon图标
├── docs/                            # Docsify文档站点
│   ├── index.html                   # Docsify入口页（含搜索、评论等插件）
│   ├── README.md                    # 从根目录复制而来
│   ├── _sidebar.md                  # 侧边栏
│   ├── _navbar.md                   # 导航栏
│   ├── _media/                      # 从根目录复制而来
│   └── .nojekyll                    # 禁用Jekyll处理
└── .github/
    └── workflows/
        └── main.yml                 # GitHub Actions 工作流配置
```

---

## 四、核心代码深度分析 (`main.py`)

### 4.1 依赖库

| 库名 | 用途 |
|------|------|
| `feedparser` | RSS/Atom Feed 解析 |
| `requests` | HTTP 请求（抓取RSS源） |
| `yagmail` | 邮件发送（基于Gmail SMTP） |
| `markdown` | Markdown → HTML 转换 |
| `pytz` | 时区处理（Asia/Shanghai） |
| `multiprocessing` | 多进程并发抓取 |
| `json` | JSON 数据读写 |
| `re` | 正则表达式（模板解析） |
| `shutil` | 文件/目录复制 |
| `urllib.parse` | URL 解析 |

### 4.2 函数详解

#### `main()` — 程序入口（L339-358）

执行顺序：
```
create_json()       →  生成 garssInfo.json
create_opml()       →  生成 OPML v1/v2 订阅文件
replace_readme()    →  抓取RSS + 渲染 README.md（核心逻辑）
markdown转HTML      →  将README内容转为HTML（用于邮件）
cp_readme_md_to_docs()  →  复制 README.md 到 docs/
cp_media_to_docs()      →  复制 _media/ 到 docs/
get_email_list()    →  从 tasks.json 读取收件人
send_mail()         →  发送邮件摘要
```

#### `get_rss_info(feed_url, index, rss_info_list)` — RSS抓取（L17-65）

- **重试机制**: 最多重试 3 次，超时时间递增（8s → 16s → 24s）
- **User-Agent伪装**: 使用 Chrome UA 避免被拒
- **数据提取**: 从 feed entries 中提取 `title`、`link`、`date` 三个字段
- **进度追踪**: 通过共享的 `Manager().list()` 实时输出剩余/已完成数量
- **容错**: 异常时静默继续，不影响其他源的抓取

#### `replace_readme()` — 核心渲染逻辑（L99-207）

这是项目最核心最复杂的函数，负责将 `EditREADME.md` 模板渲染为最终的 `README.md`：

1. **读取模板**: 从 `EditREADME.md` 读取内容
2. **正则提取RSS源**: 用正则 `\{\{latest_content\}\}.*\[订阅地址\]\(.*\)` 提取所有RSS条目
3. **填充统计信息**: 替换 `{{rss_num}}`（源数量）和 `{{ga_rss_datetime}}`（生成时间）
4. **多进程抓取**: 创建 8 进程的 `Pool`，并发抓取所有 RSS 源
5. **渲染最新内容**: 对每个RSS源，取最新的 1-2 篇文章生成 Markdown 链接
6. **当日标记**: 当天发布的文章会显示 🌈 标志
7. **生成新闻索引**: 收集当天所有新文章，生成 HTML 格式的新闻索引区域
8. **CDN替换**: 将本地 `_media` 路径替换为 jsDelivr CDN 路径
9. **提取邮件内容**: 用正则从 `邮件内容区开始>` 和 `<邮件内容区结束` 之间提取邮件正文

#### `send_mail(email, title, contents)` — 邮件发送（L69-97）

- **配置来源优先级**: GitHub Secrets 环境变量 > 本地 `secret.json` 文件
- **所需凭据**: `USER`（发件邮箱）、`PASSWORD`（密码/授权码）、`HOST`（SMTP服务器）
- **发送库**: 使用 `yagmail`（基于SMTP）

#### `create_opml()` — 生成OPML订阅文件（L229-321）

- 从 `EditREADME.md` 解析出所有 RSS 源信息
- 生成两个版本的 OPML 文件:
  - **v1** (`rss-template-v1.txt`): 简洁格式，仅含基本 outline 属性
  - **v2** (`rss-template-v2.txt`): 完整格式，含 `dateCreated`、`dateModified`、`ownerName` 等元数据

#### `create_json()` — 生成JSON数据（L323-337）

- 从 `EditREADME.md` 提取所有 RSS 源的 `title`、`description`、`xmlUrl`
- 写入 `garssInfo.json`，供外部程序或 API 使用

#### 辅助函数

| 函数 | 功能 |
|------|------|
| `cp_readme_md_to_docs()` | 将 README.md 复制到 docs/ 目录 |
| `cp_media_to_docs()` | 将 _media/ 目录复制到 docs/（先删后建） |
| `get_email_list()` | 从 tasks.json 读取邮件接收者列表 |

---

## 五、数据流

```
EditREADME.md (模板，含 {{变量}} 占位符)
       │
       ├──正则提取──→ RSS源URL列表
       │                  │
       │            多进程抓取(Pool=8)
       │                  │
       │                  ▼
       │            rss_info_list (每个源的最新文章)
       │                  │
       ├──模板渲染──→ README.md (最终展示页面)
       │                  │
       │                  ├──复制──→ docs/README.md (Docsify站点)
       │                  │
       │                  └──正则提取邮件区──→ 邮件内容 ──→ yagmail发送
       │
       ├──正则提取──→ OPML v1/v2 文件
       │
       └──正则提取──→ garssInfo.json
```

### 模板变量说明 (`EditREADME.md` 中使用)

| 变量 | 说明 | 替换时机 |
|------|------|---------|
| `{{rss_num}}` | RSS 源总数 | 程序运行时计算 |
| `{{ga_rss_datetime}}` | 生成时间（北京时间） | 程序运行时取当前时间 |
| `{{latest_content}}` | 每个 RSS 源的最新文章链接 | 抓取后填充 |
| `{{news}}` | 当日新文章索引（HTML格式） | 抓取后生成 |
| `{{new_num}}` | 当日新文章数量 | 抓取后统计 |

---

## 六、CI/CD 流程 (GitHub Actions)

### 工作流配置 (`main.yml`)

```yaml
触发条件:
  - 定时: cron '0 22 * * *'  # UTC 22:00 = 北京时间 06:00
  - 推送: main 分支

运行环境: ubuntu-22.04
Python版本: 3.9
包管理器: pipenv
```

### 执行步骤

```
1. actions/checkout@v3        检出代码
2. actions/setup-python@v4    安装 Python 3.9 (开启pipenv缓存)
3. pip install pipenv         安装 pipenv
4. pipenv install             安装项目依赖
5. pipenv run build           执行 main.py（= python main.py）
6. git add + commit + push    自动提交变更并推送
```

### 环境变量 / Secrets

| Secret | 用途 |
|--------|------|
| `USER` | 发件邮箱地址 |
| `PASSWORD` | 邮箱密码或授权码 |
| `HOST` | SMTP 服务器地址 |

---

## 七、文档站点 (Docsify)

项目使用 [Docsify](https://docsify.js.org/) 构建文档站点，配置在 `docs/index.html`：

- **主题**: `docsify-themeable` (theme-simple)
- **插件**:
  - 全文搜索 (`search.min.js`)
  - Emoji 支持 (`emoji.min.js`)
  - 图片缩放 (`zoom-image.min.js`)
  - Gitalk 评论 (`gitalk.min.js`) — 基于 GitHub Issues
- **统计**: 百度统计
- **广告**: Google AdSense
- **侧边栏**: 单页面 `嘎!RSS`
- **导航栏**: 链接到 GitHub 仓库

---

## 八、配置文件说明

### `tasks.json` — 邮件接收者

```json
{
    "tasks": [
        { "email": "example@gmail.com" }
    ]
}
```

支持多个接收者，程序会遍历 `tasks` 数组中的所有 `email`。

### `secret.json` — 本地邮箱凭据（不入库）

```json
{
    "user": "your-email@example.com",
    "password": "your-password-or-app-token",
    "host": "smtp.example.com"
}
```

仅在本地开发时使用，`.gitignore` 已排除此文件。

### `.gitignore` 规则

```
secret.json          # 邮箱凭据（敏感信息）
local_secret.json    # 本地凭据备份
.DS_Store            # macOS 系统文件
./README.md          # README 为自动生成，不需纳入版本控制模板
```

> **注意**: `README.md` 被忽略是因为它是由程序从 `EditREADME.md` 自动生成的。真正需要编辑的源文件是 `EditREADME.md`。

### `_config.yml` — Jekyll 主题

```yaml
theme: jekyll-theme-time-machine
```

用于 GitHub Pages 的 Jekyll 主题配置（与 Docsify 文档站并存）。

---

## 九、设计亮点与技术细节

### 9.1 模板驱动架构

项目核心设计理念是 **"单一数据源"**：
- `EditREADME.md` 是唯一需要手动维护的文件
- 所有 RSS 源信息（名称、描述、URL）都内嵌在此文件的 Markdown 表格中
- `README.md`、`garssInfo.json`、OPML 文件全部从此模板自动生成

### 9.2 多进程并发

使用 `multiprocessing.Pool(8)` 进行 8 进程并发抓取，配合 `Manager().list()` 实现跨进程数据共享和进度追踪。这对于 228 个 RSS 源的批量抓取至关重要。

### 9.3 容错机制

- 每个 RSS 源最多重试 3 次，超时递增
- 单个源抓取失败不影响整体流程
- 抓取失败的源会显示 "暂无法通过爬虫获取信息" 并链接到源站主页
- 邮件发送失败也有 try/catch 保护

### 9.4 邮件内容区域标记

通过在 `EditREADME.md` 中嵌入特殊标记 `邮件内容区开始>` 和 `<邮件内容区结束`，巧妙地复用同一份文档既作为网页展示，又作为邮件正文模板。

### 9.5 CDN 加速

生成的 `README.md` 中，本地 `_media` 路径会被替换为 jsDelivr CDN 路径：
```
./_media → https://cdn.jsdelivr.net/gh/zhaoolee/garss/_media
```

### 9.6 当日高亮

当天发布的文章会带有 🌈 标志，在新闻索引区域使用交替背景色（`#FAF6EA`）提升可读性。

---

## 十、本地开发指南

### 环境要求

- Python 3.9+
- pipenv

### 安装与运行

```bash
# 安装 pipenv
pip install pipenv

# 安装依赖
pipenv install

# 创建邮箱配置（可选，不创建则不发邮件）
cat > secret.json << 'EOF'
{
    "user": "your-email@gmail.com",
    "password": "your-app-password",
    "host": "smtp.gmail.com"
}
EOF

# 运行
pipenv run build
# 等效于: pipenv run python main.py
```

### 添加新 RSS 源

1. 编辑 `EditREADME.md`
2. 在对应分类表格中添加一行，格式为：
   ```
   | 编号 | 名称 | 描述 | {{latest_content}} | [订阅地址](RSS_URL) |
   ```
3. 提交推送到 `main` 分支，GitHub Actions 会自动执行抓取

### 添加邮件接收者

编辑 `tasks.json`，在 `tasks` 数组中添加新的邮箱对象：
```json
{ "email": "new-subscriber@example.com" }
```

---

## 十一、依赖清单

| 包名 | 版本 | 用途 |
|------|------|------|
| `requests` | * | HTTP 请求 |
| `feedparser` | * | RSS/Atom 解析 |
| `pytz` | * | 时区转换 |
| `yagmail` | * | 邮件发送 |
| `markdown` | * | Markdown → HTML |

> 所有依赖均未锁定版本（使用 `*`），具体版本由 `Pipfile.lock` 锁定。

---

## 十二、潜在改进方向

1. **异步化**: 将 `multiprocessing` 替换为 `asyncio + aiohttp`，减少资源开销
2. **增量更新**: 记录上次抓取结果，只推送真正的新内容
3. **配置分离**: 将 RSS 源列表从 Markdown 模板中提取为独立配置文件（如 YAML/JSON）
4. **错误报告**: 汇总失败的 RSS 源信息，通过邮件或 Issue 通知维护者
5. **RSS分类管理**: 支持按分类筛选和订阅
6. **历史归档**: 保存每日抓取快照，支持历史数据查询
