# TV — 轻量自研影音 Web

类 Jellyfin 的轻量媒体站：**自有**媒体库 / 刮削 / 播放 UI。

| 组件 | 部署位置 |
|------|----------|
| 本应用（API + SPA） | 本机 / 本 VPS · GHCR 镜像 |
| **MetaTube** | 远程已有服务，**不在本仓库部署** |

元数据可选 MetaTube、Stash 或独立的拾录 / StashScrapers 刮削服务；播放支持本地 Range 流与 HTTP(S) `.strm` 直链。三个刮削后端均通过 HTTP 连接，本项目不捆绑部署。

---

## 功能

- 扫描本地视频与 `.strm`
- 番号解析 + MetaTube 自动刮削（海报 / 标题 / 演员）
- 可切换 Stash 刮削后端，复用其已安装的社区刮削器，支持番号与来源 URL 刮削
- 支持拾录 / StashScrapers 的独立 REST 接口，直接复用社区规则，无需运行完整 Stash
- 标题 / 简介 / 标签自动翻译（Google、必应、DeepL、OpenAI 兼容 AI 接口）
- 浏览器播放（本地 Range 流 / HTTP 直链 `.strm`）
- 播放进度记忆
- 打 Git tag `v*` → GitHub Actions 构建并推送到 **GHCR**（生产只 `pull`，不本地 build）

---

## 架构

```text
浏览器 ──► TV 容器 :8000 (SPA + FastAPI)
              │
              ├─ SQLite  /data
              ├─ 媒体    /media  (local 视频 / strm 文本)
              └─ HTTP ──► MetaTube / Stash / StashScrapers（设置页选择）
```

---

# 生产部署（推荐）

**前提：** 仓库已打过 `v*` tag，GHCR 上已有镜像；MetaTube 已在其他机器就绪。

## 1. 准备目录

在目标机器上只需 **compose + 环境变量 + 数据卷**，不必克隆完整源码：

```bash
mkdir -p ~/tv/{media/local,media/strm,data}
cd ~/tv
```

下载部署文件（二选一）：

```bash
# A) 从仓库拷贝
#   docker-compose.yml
#   .env.example → 改名为 .env

# B) 最小：自建 compose（与仓库一致）
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/<owner>/<repo>/main/docker-compose.yml
cp .env.example .env   # 或按下文手写 .env
```

目录建议：

```text
~/tv/
├── docker-compose.yml
├── .env                 # 密钥，勿提交
├── media/
│   ├── local/           # 实体视频
│   └── strm/            # .strm 文本（http/https 直链）
└── data/                # SQLite app.db
```

## 2. 配置 `.env`

```bash
cp .env.example .env
nano .env   # 或 vim
```

必改项：

| 变量 | 说明 |
|------|------|
| `TV_IMAGE` | GHCR 镜像，如 `ghcr.io/<owner>/<repo>:latest` 或 `:0.1.0` |
| `METATUBE_BASE_URL` | MetaTube 根地址 |
| `METATUBE_TOKEN` | Bearer Token |
| `HOST_PORT` | 宿主机端口，默认 `8000` |
| `CORS_ORIGINS` | 生产同源可填 `*`；反代固定域名可写 `https://tv.example.com` |

示例：

```env
TV_IMAGE=ghcr.io/yourname/tv:latest
HOST_PORT=8000
MEDIA_DIR=./media
DATA_DIR=./data

METATUBE_BASE_URL=https://openai-proxy.caowxj.eu.org
METATUBE_TOKEN=你的_metatube_token

CORS_ORIGINS=*
```

容器内固定：

- `MEDIA_ROOT=/media`
- `DATABASE_URL=sqlite:////data/app.db`

由 `docker-compose.yml` 注入，一般不用在 `.env` 里改路径逻辑。

## 3. 登录 GHCR 并启动

私有包需登录（公开包可跳过）：

```bash
echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin
# PAT 权限：read:packages（拉取）；推送镜像在 CI 里用 GITHUB_TOKEN
```

启动（**只 pull，不 build**）：

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f --tail=100
```

健康检查：

```bash
curl -sS http://127.0.0.1:8000/api/health
# 期望 JSON 含 status / metatube 连通信息
```

浏览器打开：`http://<服务器IP>:8000`

## 4. 首次使用

1. 打开 **设置**，确认 MetaTube 配置与连通  
2. **媒体库** → 添加库  
   - 本地片：路径 `local`（相对容器内 `/media`）  
   - HTTP strm：路径 `strm`  
3. 把文件放进宿主机 `media/local/` 或 `media/strm/`  
4. 点 **扫描** → 自动番号解析与刮削  
5. 详情页 **播放**

`.strm` 文件内容一行完整 `https://...`（或 `http://...`）→ 播放器直链。非 HTTP 目标会被拒绝播放。

### Stash 社区刮削器（可选）

1. 在已有或另行部署的 Stash 中完成初始化，进入 **设置 → 元数据提供者 → 可用刮削器**，安装需要的社区刮削器。
2. 在本项目 **设置 → 刮削后端** 选择 **Stash（社区刮削器）**，填写服务地址和 API Key，保存后刷新源列表。地址支持根地址或完整的 `/graphql` 地址，且须能从本项目后端访问；容器里的 `127.0.0.1` 指向容器自身。
3. API Key 从 Stash **设置 → 安全 → 身份验证** 获取。Stash 未开启鉴权时可以留空；已保存的 Key 不回显，输入框留空保留原值。
4. 从源列表选择刮削器，设置优先级及“失败时 fallback”。这个开关决定是否继续尝试 **Stash 的其他刮削器**。MetaTube 与 Stash 的优先级和凭证各自保存，切换后端不会覆盖另一边的配置。
5. 扫描时使用番号搜索；影片详情页也可手动选择刮削器重新刮削。对于标记 **仅 URL** 的源，在详情页填写来源页面 URL；填写后由 Stash 自动匹配 URL 刮削器，不使用下拉框的单源或 fallback 设置。没有番号的影片也可以通过来源 URL 刮削。

环境变量示例（设置页保存的值优先）：

```env
SCRAPE_SOURCE=stash
STASH_BASE_URL=http://stash:9999
STASH_API_KEY=your-stash-api-key
STASH_SCRAPER_PRIORITY=["JavBus","DMM"]
STASH_FALLBACK=false
```

刮削器 ID 以实际安装后返回的列表为准。建议只安装、选择需要的刮削器，并按需关闭 fallback，减少逐个尝试带来的等待。

接入通过 Stash 的只读 GraphQL 刮削查询完成，无需把本项目媒体再次导入 Stash。名称搜索返回的详情链接会继续读取完整元数据；标题、简介、演员、标签、发行日期和时长进入现有入库与翻译流程。Stash 返回的 Base64 封面和头像保存到 `data/scraped-images`，不会嵌入媒体列表响应，也不依赖 MetaTube 图片接口。

支持名称搜索，以及使用标题 / 番号的元数据片段搜索。**仅依赖 Stash 本地文件名或指纹的片段刮削器不能直接处理本项目文件**，可改用其名称搜索或来源 URL。具体站点是否可用仍取决于 Stash 中的刮削器版本、登录配置与网络环境。

接口与运行方式依据 [Stash API 文档](https://docs.stashapp.cc/api/)、[Stash GraphQL 刮削定义](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scraper.graphql)及 [CommunityScrapers](https://github.com/stashapp/CommunityScrapers)交叉核对。

### 拾录 / StashScrapers（独立刮削服务）

接入 [stashscrapers](https://github.com/nwfnyfgvfir/stashscrapers) 的 REST API，无需部署完整 Stash。本项目只调用服务，不读取另一项目的本地代码或数据目录。

1. 先启动拾录服务，安装社区规则并启用需要的刮削器。Python、CDP、站点 Cookie 等依赖在拾录中配置，社区规则每日更新也由拾录管理。
2. 本项目进入 **设置 → 刮削来源**，将刮削后端切换为 **拾录 / StashScrapers（独立刮削服务）**。
3. 填写服务根地址，例如 `http://stashscrapers:8080`，也支持以 `/api` 结尾的地址。地址必须能从本项目后端访问；Docker 容器中的 `127.0.0.1` 指向容器自身。
4. 如拾录设置了 `STASHSCRAPERS_TOKEN`，在本项目填写相同的 **Bearer Token**；未开启鉴权时可留空。保存后凭证不回显，输入框留空保留已保存的值。
5. 保存后刷新源列表。只显示已启用且具有可用影片动作的刮削器，保留其带目录的原始 ID。可配置优先级、单源和失败后尝试其他源，三种后端的配置各自保留。
6. 支持名称查询和番号片段查询。名称搜索先核对候选番号，再读取详情；片段查询保留实际媒体文件名及后缀，以兼容依赖文件名的社区规则。定向片段或已匹配候选的详情可以不返回 `Code`，但必须有有效元数据；明确返回其他番号的结果会被排除。仅 URL 的源需要在详情页填写来源 URL，URL 刮削仍遵循所选刮削器、优先级和 fallback。没有番号的影片可从 URL 返回的代码补齐番号。

环境变量示例（设置页保存的值优先）：

```env
SCRAPE_SOURCE=stashscrapers
STASHSCRAPERS_BASE_URL=http://stashscrapers:8080
STASHSCRAPERS_TOKEN=your-service-token
STASHSCRAPERS_SCRAPER_PRIORITY=["JavBus","1pondo"]
STASHSCRAPERS_FALLBACK=false
```

刮削顺序如下：

- 有优先级列表：按列表逐个尝试，首次有效命中后停止；全部失败后，只有开启 fallback 才尝试其余适用源。
- 优先级为空、兼容单源非空：先尝试该源，失败后由 fallback 决定是否继续。
- 优先级和兼容单源都为空：自动按拾录目录返回的顺序尝试全部适用源，首次有效命中后停止；当前拾录按刮削器 ID 排序。此模式不受 fallback 开关限制。
- 番号模式只使用已启用、运行依赖齐全且支持影片名称或片段查询的源。仅 URL、仅演员或缺少依赖的源不会参与；“可用”表示动作依赖齐全，不保证网站能访问或支持当前番号。

详情页默认 **跟随全局配置**，保留完整优先级和 fallback 策略；也可临时选择 **自动（全部适用源）** 或指定一个源。刮削不会合并所有源的字段。名称动作失败仍会尝试同源的片段动作；候选片段详情失败仍可尝试同源 URL 详情。回退到其余源时不会重复调用已经尝试的源。

支持 `010124_001.mp4`、`010124-01.mp4` 等日期型番号。旧库中原来未识别番号的文件需要重新扫描；已成功刮削的影片不会在普通扫描时重刮，可在详情页重新刮削。扫描的“刮削成功”数只统计实际更新成功的项目。后端日志记录 `StashScrapers plan`、`try scraper=... operation=...`、候选被排除及命中停止，便于核对实际调用的源。

API 使用 `GET /api/health`、`GET /api/scrapers`、`POST /api/search` 和 `POST /api/detail`。搜索后的详情请求回传原始 fragment 与 `rules_version`；若规则自动更新触发版本冲突，重新读取目录并重查一次，持续冲突时保留原媒体信息。连接检查同时检查资源是否就绪，以及 Token 能否读取目录，服务进程启动不等于规则已可用。

接口根据该项目的 [API 文档](https://github.com/nwfnyfgvfir/stashscrapers/blob/main/docs/API.md)与实际服务代码适配。具体网站是否可用取决于规则、运行依赖、站点鉴权和网络条件。

### AI 翻译（可选）

在 **设置 → 翻译服务** 选择 **AI 翻译（OpenAI 兼容）**，填写 API 地址、模型名称和 API Key 后保存。API 地址支持域名根地址、以 `/v1` 结尾的地址或完整的 `/v1/chat/completions` 地址，缺少的路径会自动补齐。模型名称填写所用服务实际提供的名称；本地免鉴权服务可以不填 Key。已保存的 Key 不会回显，输入框留空会保留原值。

也可以在 `.env` 配置：

```env
TRANSLATE_PROVIDER=ai
TRANSLATE_AI_API_URL=https://api.example.com/v1/chat/completions
TRANSLATE_AI_API_KEY=your-api-key
TRANSLATE_AI_MODEL=your-model-name
```

开启“刮削后自动翻译”后生效，翻译失败会回退必应，仍失败则保留原文。修改地址、模型或 Key 后不会复用旧配置的翻译缓存；已入库的元数据需要重新刮削才能重新翻译。请求格式参考 [OpenAI Chat Completions 官方文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

## 5. 更新版本

```bash
# 固定版本时改 .env 里 TV_IMAGE 的 tag，例如 :0.2.0
docker compose pull
docker compose up -d
```

数据在 `./data`、`./media` 卷中，升级不丢库。

## 6. 反向代理（可选）

Nginx 示例（HTTPS 终止后反代容器）：

```nginx
server {
    listen 443 ssl http2;
    server_name tv.example.com;
    # ssl_certificate ...;

    client_max_body_size 0;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 本地大文件 Range 流
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
```

此时 `.env` 可设：

```env
CORS_ORIGINS=https://tv.example.com
HOST_PORT=8000
```

---

# 发布镜像到 GHCR（维护者）

本机 **不必** `docker build` 上线；CI 在 tag 时构建。

```bash
git tag v0.1.0
git push origin v0.1.0
```

Actions（`.github/workflows/release-ghcr.yml`）推送：

| Tag | 镜像标签 |
|-----|----------|
| `v0.1.0` | `ghcr.io/<owner>/<repo>:0.1.0`、`:0.1`、`:latest` |
| `v0.1.0-rc.1` | 版本号标签，**不**打 `latest` |

首次推送后在 GitHub → Packages 设置包可见性（public / 协作拉取权限）。

本地调试镜像（可选，生产不推荐）：

```bash
docker build -t tv:local .
docker run --rm -p 8000:8000 --env-file .env \
  -v "$(pwd)/media:/media" -v "$(pwd)/data:/data" tv:local
```

`docker-compose.yml` **默认不 build**，只使用 `TV_IMAGE`。

---

# 开发环境

## 1. 环境变量

```bash
cp .env.example .env
# 开发时 CORS 建议：
# CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
# MEDIA_ROOT / DATABASE_URL 可用相对路径（见 .env.example 开发说明）
```

开发可在 `.env` 使用：

```env
DATABASE_URL=sqlite:///./data/app.db
MEDIA_ROOT=./media
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

## 2. 后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>

## 3. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>（Vite 将 `/api` 代理到 8000）。

## 4. 测试

```bash
cd backend
.venv\Scripts\python -m pytest -q
```

---

# 番号命名建议

| 类型 | 示例 |
|------|------|
| 有码 | `SSIS-001.mp4` |
| 中字 | `ABC-330-C.mp4` |
| 多碟 | `ABC-330-cd1.mp4` |
| FC2 | `FC2-1234567.mp4` |
| HEYZO | `HEYZO-1234.mp4` |

---

# API 摘要

| 方法 | 路径 |
|------|------|
| GET | `/api/health` |
| CRUD | `/api/libraries` |
| POST | `/api/libraries/{id}/scan` |
| GET | `/api/media` |
| GET | `/api/media/{id}/play` |
| GET | `/api/stream/{id}` |
| GET/PUT | `/api/settings` |

---

# 排障

| 现象 | 排查 |
|------|------|
| `pull` 拒绝 / not found | 检查 `TV_IMAGE`、是否 `docker login ghcr.io`、包是否 public |
| MetaTube 失败 | Token 是否 `Bearer` 可用；VPS 能否访问 `METATUBE_BASE_URL` |
| `.strm` 无法播放 | 文件首行是否为完整 `http(s)://` 直链；浏览器能否直接打开该 URL |
| 扫描为空 | 卷挂载是否指向有文件的目录；库路径是否为 `local` / `strm` |
| 数据库路径错乱 | 生产务必用 compose 注入的 `sqlite:////data/app.db` + `/data` 卷 |

查看日志：

```bash
docker compose logs -f tv
```

---

# 安全

- **不要**把 `.env` 提交进 Git  
- MetaTube token 仅运行时注入  
- 公网暴露时建议 HTTPS 反代 + 限制来源 / 后续加鉴权  
- Token 曾在聊天或截图出现过时，上线前在 MetaTube 侧轮换  

---

# 目录（源码仓库）

```text
backend/          FastAPI
frontend/         Vue 3 + Element Plus
media/            开发用媒体根
data/             开发用 SQLite
Dockerfile        CI 多阶段构建（前端 + API）
docker-compose.yml  生产：pull GHCR
.github/workflows/release-ghcr.yml
```

---

# License

自用 / 按需自行声明。
