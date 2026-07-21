# TV — 轻量自研影音 Web

类 Jellyfin 的轻量媒体站：**自有**媒体库 / 刮削 / 播放 UI。

| 组件 | 部署位置 |
|------|----------|
| 本应用（API + SPA） | 本机 / 本 VPS · GHCR 镜像 |
| **MetaTube** | 远程已有服务，**不在本仓库部署** |

元数据走远程 MetaTube；播放支持本地 Range 流与 HTTP(S) `.strm` 直链。

---

## 功能

- 扫描本地视频与 `.strm`
- 番号解析 + MetaTube 自动刮削（海报 / 标题 / 演员）
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
              └─ HTTP ──► 远程 MetaTube（刮削）
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
