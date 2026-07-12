# 生产部署速查

本目录仅放部署辅助文件。应用镜像来自 **GHCR**，**不**在此构建；**不**部署 Alist（另机）/ MetaTube。

## 依赖关系

| 服务 | 谁部署 |
|------|--------|
| TV（本应用） | 本机 `docker compose` |
| MetaTube | 已有远程实例 |
| Alist | **另机 VPS**（只填 URL + Token，compose 已移除） |
| AutoFilm | 可选：`cp config/autofilm/config.example.yaml config/autofilm/config.yaml` 后 `docker compose --profile autofilm up -d`（详见 `config/autofilm/README.md`） |

## 三分钟上线

```bash
mkdir -p ~/tv/{media/local,media/strm,data} && cd ~/tv

# 从仓库取 compose（改 owner/repo）
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/<owner>/<repo>/main/docker-compose.yml

# 环境变量
curl -fsSL -o .env.example \
  https://raw.githubusercontent.com/<owner>/<repo>/main/.env.example
cp .env.example .env
# 编辑：TV_IMAGE、METATUBE_*、ALIST_* 
```

`.env` 最少：

```env
TV_IMAGE=ghcr.io/<owner>/<repo>:latest
METATUBE_BASE_URL=https://openai-proxy.caowxj.eu.org
METATUBE_TOKEN=***
ALIST_BASE_URL=https://你的-alist
ALIST_TOKEN=***
HOST_PORT=8000
CORS_ORIGINS=*
```

```bash
# 私有包
echo "$GITHUB_PAT" | docker login ghcr.io -u USER --password-stdin

docker compose pull
docker compose up -d
curl -sS http://127.0.0.1:8000/api/health
```

浏览器：`http://服务器:8000`

## 常用命令

```bash
docker compose logs -f --tail=200
docker compose pull && docker compose up -d   # 升级
docker compose down                             # 停（保留 ./data ./media）
```

## 媒体库

| 类型 | 宿主机目录 | 库路径（UI） |
|------|------------|--------------|
| 本地视频 | `./media/local` | `local` |
| 网盘 strm | `./media/strm` | `strm` |

`.strm` 一行：完整 `https://...`，或 Alist 站内路径（由远程 Alist 解析）。

## 可选 AutoFilm

```bash
# 需同时拿到仓库里的 config/autofilm/
cp config/autofilm/config.example.yaml config/autofilm/config.yaml
# 填远程 Alist token、source_dir；推荐 mode: AlistPath
docker compose --profile autofilm up -d
docker compose logs -f autofilm
```

详见仓库内 `config/autofilm/README.md`。TV 的 `ALIST_*` 与 AutoFilm 须指向同一 Alist。

## 不要做的事

- 不要在生产机 `docker compose build`（用 GHCR）
- 不要在本 compose 里再起 Alist（已在另机）
- 不要把 `.env` / `config/autofilm/config.yaml` 提交到 Git
