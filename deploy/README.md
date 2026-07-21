# 生产部署速查

本目录仅放部署辅助文件。应用镜像来自 **GHCR**，**不**在此构建；**不**部署 MetaTube。

## 依赖关系

| 服务 | 谁部署 |
|------|--------|
| TV（本应用） | 本机 `docker compose` |
| MetaTube | 已有远程实例 |

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
# 编辑：TV_IMAGE、METATUBE_*
```

`.env` 最少：

```env
TV_IMAGE=ghcr.io/<owner>/<repo>:latest
METATUBE_BASE_URL=https://openai-proxy.caowxj.eu.org
METATUBE_TOKEN=***
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
| HTTP strm | `./media/strm` | `strm` |

`.strm` 一行：完整 `https://...`（或 `http://...`）直链。

## Nginx 反代（推荐）

完整示例见同目录 [`nginx.conf.example`](./nginx.conf.example)。

要点：

| 项 | 说明 |
|----|------|
| 上游 | `127.0.0.1:8000`（compose `HOST_PORT`） |
| TLS | 证书由 certbot / 现有证书管理；HTTP 301 到 HTTPS |
| 视频 Range | `/api/stream/` 必须 `proxy_buffering off` 并转发 `Range` |
| 超时 | 刮削/大文件建议 `proxy_read_timeout` ≥ 3600s |
| 图片代理 | `/api/images/proxy` 可开 nginx 缓存（应用内已有短 LRU） |
| 鉴权 | 浏览器 `<img>` 走同源代理，**无需** JWT；API 其它路径仍走 JWT |

```bash
# 示例：复制并启用
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/tv
sudo ln -sf /etc/nginx/sites-available/tv /etc/nginx/sites-enabled/tv
# 编辑 server_name 与 ssl_certificate*
sudo nginx -t && sudo systemctl reload nginx
```

环境变量建议生产开启登录：

```env
ADMIN_PASSWORD=***
JWT_SECRET=***至少32字节随机串***
```

## 不要做的事

- 不要在生产机 `docker compose build`（用 GHCR）
- 不要把 `.env` 提交到 Git
