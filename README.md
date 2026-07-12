# TV — 轻量自研影音 Web

类 Jellyfin 的轻量媒体站：**自有**媒体库 / 刮削 / 播放 UI。  
元数据走远程 **MetaTube**，网盘直链可配合 **Alist / AutoFilm**（`.strm`）。

## 功能

- 扫描本地视频与 `.strm`
- 番号解析 + MetaTube 自动刮削（海报 / 标题 / 演员）
- 浏览器播放（本地 Range 流 / HTTP 直链 / Alist `raw_url`）
- 播放进度记忆
- 打 Git tag `v*` 自动构建镜像并推送到 **GHCR**

## 目录

```text
backend/     FastAPI
frontend/    Vue 3 + Element Plus
media/       媒体根（local / strm）
data/        SQLite 等运行时数据
Dockerfile   多阶段镜像（前端 + API）
.github/workflows/release-ghcr.yml
```

## 快速开始（开发）

### 1. 环境变量

```bash
cp .env.example .env
# 编辑 METATUBE_TOKEN 等
```

默认 MetaTube：

- `METATUBE_BASE_URL=https://openai-proxy.caowxj.eu.org`
- 鉴权：`Authorization: Bearer <token>`

### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>（`/api` 代理到 8000）。

### 4. 使用

1. **设置**页确认 MetaTube 连通  
2. **媒体库** → 添加库，路径示例：`local`（相对 `MEDIA_ROOT`）  
3. 把影片放到 `media/local/`，文件名尽量规范：`SSIS-001.mp4`、`ABC-123-C.mkv`  
4. 点 **扫描** → 列表出现条目并自动刮削  
5. 点进详情 **播放**

`.strm`：文本一行 URL 或 Alist 路径，放在 `media/strm/` 并扫描。

## Docker

### 本地构建运行

```bash
docker compose up -d --build
# http://localhost:8000
```

可选完整依赖（Alist + AutoFilm）：

```bash
docker compose --profile full up -d
```

### 发布到 GHCR

推送 tag 即可：

```bash
git tag v0.1.0
git push origin v0.1.0
```

Actions 会构建并推送：

- `ghcr.io/<owner>/<repo>:0.1.0`
- `ghcr.io/<owner>/<repo>:latest`（正式版 tag）

```bash
docker pull ghcr.io/<owner>/<repo>:0.1.0
docker run -d -p 8000:8000 --env-file .env \
  -v ./media:/media -v ./data:/data \
  ghcr.io/<owner>/<repo>:0.1.0
```

## 番号命名建议

| 类型 | 示例 |
|------|------|
| 有码 | `SSIS-001.mp4` |
| 中字 | `ABC-330-C.mp4` |
| 多碟 | `ABC-330-cd1.mp4` |
| FC2 | `FC2-1234567.mp4` |
| HEYZO | `HEYZO-1234.mp4` |

## API 摘要

| 方法 | 路径 |
|------|------|
| GET | `/api/health` |
| CRUD | `/api/libraries` |
| POST | `/api/libraries/{id}/scan` |
| GET | `/api/media` |
| GET | `/api/media/{id}/play` |
| GET | `/api/stream/{id}` |
| GET/PUT | `/api/settings` |

## 安全

- **不要**把 `.env` 提交进 Git  
- MetaTube token 仅运行时注入  

## License

自用 / 按需自行声明。
