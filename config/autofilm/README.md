# AutoFilm 配置（可选）

用 [AutoFilm](https://github.com/AkimioJR/AutoFilm) 扫描**远程 Alist**，在本地生成 `.strm`，供本 TV 应用扫描播放。

> **Alist 不在本 compose 内**，装在另机 VPS；此处只配 AutoFilm 客户端。

## 目录与挂载

| 宿主机 | 容器 | 用途 |
|--------|------|------|
| `config/autofilm/` | `/config` | 须有 `config.yaml` |
| `media/`（`MEDIA_DIR`） | `/media` | `.strm` 输出，与 TV 共用 |
| `data/autofilm-logs/` | `/logs` | 日志 |

官方镜像启动命令等价于：

```bash
docker run -d --name autofilm \
  -v ./config:/config -v ./media:/media -v ./logs:/logs \
  akimio/autofilm
```

本仓库用 compose profile `autofilm` 做同样挂载。

## 快速开始

```bash
# 1. 配置（缺这一步会启动成功但三个模块都「未检测到」）
cp config/autofilm/config.example.yaml config/autofilm/config.yaml
# 编辑 config.yaml：
#   alist[].base_url / token  → 远程 Alist
#   alist2strm_tasks[].source_dir → 网盘路径
#   target_dir 保持 /media/strm/... 即可

# 2. 启动（可与 tv 一起）
docker compose --profile autofilm up -d --force-recreate autofilm

# 3. 看日志
docker compose logs -f autofilm
# 期望：不再出现「未检测到 Alist2Strm 模块配置」
# 正常：Ani2Alist / LibraryPoster 若保持 [] 仍会 WARNING（本项目可忽略）

# 4. 确认输出
ls media/strm/jav   # 应出现 *.strm

# 5. TV 侧
# 设置里填好 ALIST_BASE_URL / ALIST_TOKEN（与 AutoFilm 同一 Alist）
# 媒体库添加路径 strm 或 strm/jav → 扫描 → 播放
```

仅启动 AutoFilm、不启 TV：

```bash
docker compose --profile autofilm up -d autofilm
```

## `.strm` 三种 mode（与 TV 播放）

| mode | `.strm` 内容 | TV 行为 | 建议 |
|------|--------------|---------|------|
| **AlistPath** | Alist 站内路径，如 `/cloud/jav/SSIS-001.mp4` | 调 `ALIST_*` → `raw_url` | **推荐**（密钥只在服务端） |
| **AlistURL** | `public_url` + 路径 | 当 HTTP 直链播 | 需公网 URL 可播 |
| **RawURL** | 存储商直链 | 当 HTTP 直链播 | 可能过期，需靠定时重扫 |

本应用播放逻辑（`GET /api/media/{id}/play`）：

- 行内容以 `http://` / `https://` 开头 → `kind=direct`
- 否则 → 当 Alist 路径，`kind=alist`

因此 **AlistPath** 与 TV 的 `ALIST_TOKEN` 最契合。

## 必改字段

```yaml
alist:
  - id: remote
    base_url: https://你的-alist   # AutoFilm 容器能访问
    public_url: https://你的-alist # AlistURL 模式需要
    token: "alist-xxx"             # 永久令牌

alist2strm_tasks:
  - id: jav-cloud
    alist: remote                  # 对应上面 id
    source_dir: /cloud/jav         # Alist 里真实路径
    target_dir: /media/strm/jav
    mode: AlistPath
    cron: "0 0 3 * * *"            # 秒 分 时 日 月 周
```

## Cron 说明

格式为 **6 段**：`秒 分 时 日 月 星期`（与 Linux 5 段不同）。

| 示例 | 含义 |
|------|------|
| `0 0 3 * * *` | 每天 03:00:00 |
| `0 0 */6 * * *` | 每 6 小时 |
| `0 30 2 * * 1` | 每周一 02:30 |

容器启动后会按调度执行；是否立刻跑一轮取决于 AutoFilm 版本行为，可看 `/logs`。

## 与 TV `.env` 的关系

| 用途 | 配置位置 |
|------|----------|
| TV 解析 AlistPath / 设置页 | 根目录 `.env` → `ALIST_BASE_URL`、`ALIST_TOKEN` |
| AutoFilm 扫库写 strm | `config/autofilm/config.yaml` → `alist[]` |

两边应指向**同一** Alist；Token 权限需能列目录、`fs/get`。

## 同步与误删保护

```yaml
sync:
  enabled: true
  smart_protection:
    enabled: true
    threshold: 100   # 单次待删 .strm 超过该数则暂缓
    grace_scans: 3   # 连续确认次数
```

Alist 短暂故障时建议保持 `smart_protection.enabled: true`。

## 不需要的功能

- `media_servers` / `library_poster_tasks`：面向 Jellyfin/Emby，本项目留空  
- `ani2alist_tasks`：动漫追更写回 Alist，按需自行加  

## 日志对照

| 日志 | 含义 |
|------|------|
| `未检测到 Alist2Strm 模块配置` | **异常**：没有可读的 `config.yaml`，或键名/缩进错误，或 `alist2strm_tasks` 为空 |
| `未检测到 Ani2Alist 模块配置` | **正常**（本项目默认 `ani2alist_tasks: []`） |
| `未检测到 LibraryPoster 模块配置` | **正常**（本项目默认 `library_poster_tasks: []`，不接 Jellyfin/Emby） |

镜像只加载 **`/config/config.yaml`**。仓库里的 `config.example.yaml` **不会**被自动使用。

## 排障

| 现象 | 处理 |
|------|------|
| 三个模块都未检测到 | `ls config/autofilm/config.yaml`；没有则 `cp` example；改完后 `--force-recreate autofilm` |
| 仅 Alist2Strm 未检测到 | 检查 `alist2strm_tasks` 是否非空、YAML 缩进、键名是否与镜像 schema 一致 |
| 容器反复退出 | 是否缺少 `/config/config.yaml`；YAML 缩进 |
| 连不上 Alist | 从 **AutoFilm 宿主机** `curl` 一下 `base_url`；防火墙/证书 |
| 有日志无 `.strm` | `source_dir` 是否在 Alist 存在；账号是否可见该路径 |
| TV 扫不到 | 是否扫的是 `strm` 库；文件是否在 `media/strm` 下 |
| 能扫不能播（AlistPath） | TV 的 `ALIST_*` 是否与 AutoFilm 同一站点；Token 有效 |
| 直链 403/过期 | 改用 `AlistPath`，或缩短 cron 刷新 RawURL |

```bash
docker compose logs -f autofilm
ls -la media/strm/jav | head
```

## 安全

- `config.yaml` 含 Token，已在根 `.gitignore` 忽略（只提交 `config.example.yaml`）  
- 不要把生产 Token 写进 example  
