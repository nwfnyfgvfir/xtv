# TV — 轻量自研影音 Web

类 Jellyfin 的轻量媒体站：**自有**媒体库 / 刮削 / 播放 UI。

| 组件 | 部署位置 |
|------|----------|
| 本应用（API + SPA） | 本机 / 本 VPS · GHCR 镜像 |
| **MetaTube** | 远程已有服务，**不在本仓库部署** |

元数据可选 MetaTube 或 Stash 刮削服务；播放支持本地 Range 流与 HTTP(S) `.strm` 直链。两个刮削后端均通过 HTTP 连接，本项目不捆绑部署。

---

## 功能

- 扫描本地视频与 `.strm`
- 原文件名直接查询，支持有上限的并发刮削
- 仅扫描媒体库根目录，文件移入后直接入库；文件事件触发增量处理
- 原文件名查询 + MetaTube 自动刮削（海报 / 标题 / 演员）
- 可切换 Stash 刮削后端，复用其已安装的社区刮削器，支持番号与来源 URL 刮削
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
              └─ HTTP ──► MetaTube / Stash（设置页选择）
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

### 持久化后台任务

扫描目录、批量补刮、详情页单片重刮以及文件监控触发的扫描均进入 SQLite 持久队列。启动请求立即返回任务 ID，后台按队列顺序执行；无需增加独立队列服务。升级后首次启动会自动创建任务表，持久化能力适用于新版创建的任务，旧版本的内存任务无法迁移。

- 点击右上角铃铛图标打开 **消息**，查看正在执行和最近 50 条任务。任务进度、取消、继续和失败重试统一在该侧栏中显示；媒体库与详情页不再放置任务卡片。手动提交任务后会打开消息栏，不叠加成功提示。
- 刷新、切换页面或关闭浏览器后，后台继续执行。重新打开会从服务端恢复状态；网络断开后自动重连，进度查询没有原先的十分钟上限。
- **取消任务**：排队任务立即取消；执行中的网络等待（含刮削、重试、演员信息及翻译）可以中断，目录枚举与文件处理在短检查间隔内响应。成功结果保留，未完成的当前条目回到待处理状态，可用 **继续未完成** 接着执行。跨进程取消信号使用数据库旁的标记文件，避免等待中的网络请求持有数据库写锁时无法取消。底层磁盘系统调用仍需等待操作系统返回；上游已接收的刮削请求也不保证能从服务端撤回。
- **跳过原因**：消息侧栏支持展开每条被跳过的文件或步骤，查看“影片已完成刮削”“文件已移除或扩展名不受支持”“不处理子目录文件”等实际原因。所有刮削源均未命中或执行失败时记为失败，不记为跳过。
- **历史记录**：已结束任务默认显示为紧凑条目，需要时展开详情，零步骤任务不展示空进度条。支持单条 **删除记录** 或 **清空历史**；只移除已结束任务及其恢复记录，不影响影片、收藏、播放进度或磁盘文件。运行中、排队中和正在取消的任务不能删除，清空历史也会保留它们。
- **重试失败**：创建一个关联原任务的重试任务，只处理失败条目；重复提交会返回已创建的重试任务。重试仍失败时，可在该重试任务上继续重试。
- **单片重刮**：详情页“管理与刮削”默认选择“跟随全局后端顺序”，按设置页的后端优先级依次尝试。也可明确选择 MetaTube 或 Stash 后端，再选择该后端的刮削器、优先级或自动选择；明确选择后仅尝试指定后端。本次选择随任务保存，不修改全局配置，继续和重试沿用原选择。各后端的连接地址和凭证需先在设置页保存。只创建该影片的一个刮削步骤，不遍历媒体库、不索引其他文件、不清理其他记录。
- 服务重启后，排队任务继续执行；执行中的任务显示 **已中断**，点击 **继续未完成** 恢复。已入库成功的刮削和已完成步骤会被跳过。
- 扫描包含文件索引、核对移除文件、自动刮削等步骤，进度以步骤计数；补刮和单片重刮以影片计数。扫描生成后续刮削清单时，总步骤数会增加。扫描中断或存在索引失败时会保留媒体记录，避免误清理。

创建时保存刮削后端、源优先级、扫描扩展名及本次重刮来源；执行、继续和重试沿用该策略。服务连接地址与凭证使用执行时的设置，凭证不会复制到任务记录或任务接口。活动任务按操作类型和资源去重；参数不同的重复请求返回 `409`，便于先取消旧任务再提交。多个应用进程通过数据库旁的文件锁共用一个任务调度器。默认全局最多并发刮削 3 部影片；同一批影片及不同任务可同时处理，每部影片内部仍按来源优先级顺序查询。在设置页“媒体库 → 并发刮削数量”可调整为 1–8，改动在当前任务结束后生效，也可用 `TASK_CONCURRENCY` 配置默认值。扫描的文件索引、核对与同媒体库的批量操作仍按顺序执行，避免并发清理或重复处理同一影片。

SQLite 文件索引批次在进入嵌套事务前使用 `BEGIN IMMEDIATE` 申请写锁，避免并发写入使读取快照无法升级为写事务。媒体索引和对应任务进度在同一批次内提交或回滚，进度写入失败时不会留下已提前提交的媒体记录。该事务仅覆盖文件索引批次；刮削、演员查询和翻译的网络请求继续并发执行。

接口：`POST /api/libraries/{id}/scan`、`POST /api/libraries/{id}/rescrape-pending`、`POST /api/media/{id}/rescrape-task` 均返回 `202` 和任务信息。`GET /api/tasks` 查询历史或活动任务，`GET /api/tasks/{id}` 查询进度，`GET /api/tasks/{id}/items?status=failed` 分页查看失败项；对 `/api/tasks/{id}/cancel`、`resume`、`retry` 发送 `POST` 操作任务。`GET /api/scan/jobs/{id}` 保留兼容查询，旧同步单片接口 `/api/media/{id}/rescrape` 已标记弃用。

`DELETE /api/tasks/{id}` 删除单条已结束记录，`DELETE /api/tasks/history` 清空已结束任务；删除活动任务返回 `409`，这些接口沿用管理员鉴权和禁止缓存规则。

### 原文件名查询与根目录扫描

中文字幕标记独立于名称查询：文件名去扩展名后，以数字加 `c`、`ch`、`-c`、`-ch` 结尾（忽略大小写），或明确带有“中文字幕”“中字”时，标记为中字。例如 `ABC-123C.mp4`、`ABC-123-CH.strm`。`CD1`、`CHS` 和普通英文单词不按此规则识别。只增加字幕标记，查询字符串保持原样；已索引影片重新扫描时会补齐缺失标记，原有中字标记保留。该规则依据命名推断，不检测文件内实际字幕轨。

媒体库右上角菜单 → **扫描设置**，开关自动扫描。扫描使用持久化后台任务，只处理所选媒体库根目录中的文件。

- **查询文件名**：默认使用源文件名去掉扩展名后的原文。例如 `FC2-PPV-1066192.mp4` 查询 `FC2-PPV-1066192`；保留 `PPV`、大小写、分隔符、标题与清晰度等内容。应用不提取、猜测或规范化本地编号，不使用父目录兜底，不提供手动番号覆盖、锁定及识别预览，也不自动重命名磁盘文件。匹配与结果排序由刮削源负责；源不支持当前文件名时，继续尝试其余适用源。Stash 查询的字幕后缀例外见下方说明。原有媒体、收藏、播放进度及元数据保留，旧锁定设置不再生效。旧的编号字段在下一次扫描或刮削时同步为源文件名，接口始终显示原文件名。

- **Stash 字幕后缀查询**：仅对 Stash 后端的名称和片段查询，先移除数字末尾的 `c`、`ch`、`-c`、`-ch` 字幕后缀（忽略大小写）。例如 `ADN-281-C.mp4` 向 Stash 查询 `ADN-281`，但文件名和页面编号仍为 `ADN-281-C`，刮削后继续保留 `C` 标记和“中文字幕”标签。Stash-box 的名称查询也应用此规则。不会移除 `CD1`、`CHS`、`PPV` 或其他编号部分；MetaTube 及来源 URL 查询保持原样，跨后端回退仍将原始查询交给其他后端。

- **扫描范围**：所有子目录都跳过，不枚举其中的文件，不依赖目录名。下载器可在任意名称的子目录中工作，下载完成后将成品移入根目录。根目录中的受支持文件直接入库，不做下载状态、零字节或临时文件名判断，不等待稳定时间，也不定时复查。已有子目录媒体的索引保留。
- **扫描格式**：不扫描 `.ts` 文件，也不识别 TS 分片或读取 M3U8 清单；扫描扩展名中填写 `ts` 也不会启用。已有 TS 索引保留，磁盘文件不受影响。`.m2ts` 仍按普通视频处理。
- **自动扫描**：所有媒体库统一使用非递归文件事件监听，仅为根目录中的变化文件建任务；子目录内的下载事件不触发扫描。事件合并 `15` 秒，不因事件多而升级为全库扫描。首次入库、事件遗漏或服务停机期间的变化由手动扫描补齐。监听失败或停止时在媒体库和系统状态页提示，检查目录与权限后重新保存扫描设置可重试监听。关闭自动扫描后只进行手动扫描。
- **磁盘开销边界**：手动扫描只列出根目录，自动扫描只处理根目录的变化文件，不遍历子目录，也不轮询或定时核对。STRM 入库时读取播放地址，不读取视频正文。原生事件能否可靠到达取决于实际文件系统及挂载方式；服务停机期间及遗漏的变化需要手动扫描。

下载器也可向 `POST /api/libraries/{id}/download-complete` 提交 `{"paths":["SSIS-001.mp4"]}`（启用登录时携带 Bearer Token），为已移入根目录的文件创建增量扫描任务。活动扫描参数冲突时返回 `409`，稍后重试即可。

下载临时目录和成品目录应分开设置：[N_m3u8DL-RE 的 `--tmp-dir` / `--save-dir`](https://github.com/nilaoda/N_m3u8DL-RE)、[yt-dlp 的临时路径配置](https://github.com/yt-dlp/yt-dlp#output-template-examples)均支持这种布局。

环境变量 `SCAN_EVENT_DEBOUNCE_SECONDS=15` 控制文件事件的合并时间。原有媒体、收藏、播放进度和后台任务保留。

### 媒体库排序

媒体库标签栏点击“排序”，或进入“设置 → 媒体库 → 媒体库顺序”，拖动手柄即可调整顺序，松开后自动保存到服务端。支持手机触摸拖动、上下按钮及键盘方向键。排序后的媒体库列表在刷新及其他设备上保持一致，不更改当前选中的媒体库、影片归属或后台任务；新建媒体库追加在最后。

### 封面显示与图片回退

媒体库、详情页和重复影片对比统一使用横版 `3:2` 海报画框，未刮削、加载中、已刮削、无图及加载失败时保持相同尺寸，加载骨架也使用同一比例。图片直接拉伸铺满画框，完整保留内容，不裁剪、不留空边、不加模糊背景；原图比例不同时允许拉伸变形。详情页点击封面可按原始比例查看图片。各页面按“完整封面 → 对应本地备份 → 缩略图 → 对应本地备份 → 背景大图 → 对应本地备份”的顺序尝试；头像也会在远程失败后尝试本地备份。同一地址只尝试一次，全部加载失败时显示占位图，详情页还提供图片重试操作。已有影片升级后刷新页面即可生效，无需重新刮削。

图片代理按实际图片内容判断类型，不将 HTML、JSON 或空响应保存成图片；已有此类错误缓存会被绕过并重新请求。内嵌图片也会检查实际类型后再保存，避免把上游错误页持久化成封面。元数据刮削成功与图片是否可用分别处理，上游未返回有效图片时会显示占位图。

**图片加载只保留两种方式**：在“设置 → 图片设置”选择“本站代理”或“远程代理（统一模板）”。远程模板须为包含 `{url}` 的 HTTP(S) 地址；通用代理如 `https://wsrv.nl/?url={url}`，MetaTube 如 `https://metatube.example/v1/images/primary/{provider}/{id}?url={url}&quality={quality}`。两者使用同一个输入框和同一套模板处理，也可点击“填入 MetaTube 模板”按当前刮削服务地址填写。各变量会分别编码；`{quality}` 默认 `90`。需要 `{provider}`、`{id}` 的模板仅能用于有对应影片标识的图片；Stash 图片、无影片标识的头像会直连原图，失败后使用永久备份。只含 `{url}` 的模板适用于所有来源。无效模板会明确报错，不自动切换到本站代理。

**本地图片只用一套永久备份**：远程图片自动后台下载，保留原 URL；Stash 内嵌图也使用同一个文件存储。本站代理优先复用永久备份，没有可用备份时获取原图，成功后为已登记的影片或头像补齐备份；外部远程模板加载正常时不请求本地文件，失败后才使用备份。任意匿名代理请求不会自动创建永久备份。短期内存缓存仅用于减少重复请求，没有独立磁盘缓存开关、容量限制或淘汰流程。

备份队列写入数据库，最多同时下载两张，失败按退避时间重试，重启后继续。支持 JPG、PNG、WebP、GIF 和 AVIF，单张上限 `5 MiB`；本站代理与后台下载共用图片类型、体积和逐次重定向地址检查，不把错误页或空响应保存为图片。已有影片和头像会按数据库中的地址补备份，不扫描视频文件。可点击“刷新备份状态”查看已完成、下载中及待下载/重试数量。远程地址在首次成功备份前已失效的图片无法凭空恢复。

Docker 默认图片文件位于 `/data/scraped-images/`，队列记录随 `/data/app.db` 保存；宿主机对应 `${DATA_DIR:-./data}`。保留 `/data` 挂载即可跨容器重建使用。旧 `IMAGE_LOCAL_CACHE`、`IMAGE_CACHE_MAX_MB` 及单独的 `metatube` 图片代理模式已经移除，不转换旧配置，也不读取或迁移 `image-cache`。请手动选择新的图片加载方式和模板；现有永久备份不受影响，按需重新刮削即可。

**本站图片访问地址（B 地址）**：在“设置 → 图片设置”填写，例如 `https://images.example.com`，也支持带部署子路径的 `https://images.example.com/tv`；环境变量默认值为 `IMAGE_SITE_BASE_URL`。留空继续使用当前页面地址。设置后 Stash 内嵌图片、远程图片的本地兜底地址和“本站代理”统一使用 B 地址，例如 `https://images.example.com/api/images/scraped/文件名.png` 或 `https://images.example.com/api/images/proxy?url=...`。远程模板仍直接请求其配置的服务，本地兜底使用 B。主页面、API 和视频播放继续使用 A 地址。

B 地址应通过 DNS、证书及反向代理接入**同一个 TV 服务**；仅填写设置不会自动部署域名。可参考 [独立图片域名 Nginx 示例](deploy/nginx.images.conf.example)，只开放图片资源路径，不开放管理 API。HTTPS 主页面配 HTTPS 图片地址，避免浏览器混合内容限制。数据库继续保存原始远程 URL 和相对本地路径，图片仍在原来的 `/data/scraped-images/`；修改、替换或清空 B 后刷新页面即可生效，已有图片无需迁移或重刮。后台备份通过原有图片来源下载，不绕行 B 地址。

本站图片接口分工：`GET /api/images/proxy?url=...` 获取远程图并复用备份；`GET /api/images/scraped/{name}` 提供内嵌图和永久备份文件；`GET /api/images/backups` 仅查询备份状态，需要登录，继续使用主站 API 地址。后两者不是额外的代理模式。

### 后端优先级与演员头像

设置 → 刮削来源 → **刮削后端优先级** 可选择和调整 MetaTube、Stash 的尝试顺序。只尝试该列表中的后端，列表为空时仅使用当前默认后端；各后端的连接配置需先保存。在一个后端内，先尝试刮削器优先级列表，再继续其余适用刮削器；该后端未命中或服务执行失败后继续下一个后端，命中后停止，不合并不同后端的字段。扫描、批量补刮及详情页“跟随全局后端顺序”使用此策略；详情页明确指定后端、刮削器或来源 URL 时，仅使用指定选择。新建任务保存后端与刮削器顺序，继续和重试沿用创建时的策略。也可使用 `SCRAPE_SOURCE_PRIORITY=["metatube","stash"]` 配置默认顺序。

设置 → 刮削来源 → **测试刮削器** 可输入番号或标题执行一次真实查询；Stash 还支持来源 URL。可指定单个刮削器，也可按当前优先级自动选择。测试只返回元数据预览，不修改媒体、演员或任务记录，并使用已经保存的服务地址与凭证。

演员详情页的 **重新刮削头像** 可独立补刮头像，按演员记录的来源查询，无需重刮影片。成功后提交新头像并加入图片备份队列；未命中或获取失败时保留旧头像。

### Stash 社区刮削器与 Stash-box（可选）

1. 在 Stash 中安装需要的社区刮削器，或配置所需的 Stash-box（如 StashDB）。Stash-box 的服务地址和凭证继续由 Stash 管理，TV 不读取它的 API Key。
2. 在本项目 **设置 → 刮削后端** 选择 **Stash（社区刮削器 / Stash-box）**，填写现有 Stash 服务地址和 API Key，保存后刷新源列表。已配置的实例会显示为 `名称（Stash-box）`，可与社区刮削器一起设置优先级。地址支持根地址或完整的 `/graphql` 地址，且须能从本项目后端访问；容器里的 `127.0.0.1` 指向容器自身。
3. API Key 从 Stash **设置 → 安全 → 身份验证** 获取。Stash 未开启鉴权时可以留空；已保存的 Key 不回显，输入框留空保留原值。
4. 从源列表选择刮削器或 Stash-box，拖动手柄设置优先级。优先源全部未命中后始终继续尝试其余适用源；优先级只决定先后顺序。MetaTube 与 Stash 的优先级和凭证各自保存，切换后端不会覆盖另一边的配置。
5. 扫描时以原文件名搜索，Stash 名称/片段查询会临时移除末尾的 `C/CH` 字幕后缀，原编号和中文字幕标记保留；影片详情页可选择来源重刮。对于标记 **仅 URL** 的源，填写站点影片链接后由 Stash 匹配 URL 刮削器，来源 URL 不作后缀调整。Stash-box 支持 `/scenes/<UUID>` 场景链接：与配置地址同源时自动识别；若 Stash 使用内网地址、链接使用外网域名，请手动选择对应的 Stash-box。没有番号的影片也可通过来源 URL 刮削。

环境变量示例（设置页保存的值优先）：

```env
SCRAPE_SOURCE=stash
STASH_BASE_URL=http://stash:9999
STASH_API_KEY=your-stash-api-key
STASH_SCRAPER_PRIORITY=["JavBus","DMM"]
```

刮削器 ID 以实际安装后返回的列表为准。优先选择命中率较高的刮削器，命中后会停止，不再额外调用后续源。

Stash-box 来源使用基于端点生成的稳定 ID，配置列表重新排序不会改变 TV 保存的优先级。查询由 `TV → Stash → Stash-box` 完成，TV 不直接连接 Stash-box、不另外保存它的凭证，也不会自动导入或扫描 Stash 的媒体库。较旧 Stash 若不支持端点选择，会在明确的字段兼容错误后回退到当前配置索引。Box 中必须存在匹配元数据；名称查询由 Box 匹配和排序，场景链接仍严格核对场景 UUID。当前不执行视频指纹计算，也不使用依赖 Stash 本地影片 ID 的匹配。

接入通过 Stash 的只读 GraphQL 刮削查询完成，无需把本项目媒体再次导入 Stash。名称搜索返回的详情链接会继续读取完整元数据；标题、简介、演员、标签、发行日期和时长进入现有入库与翻译流程。Stash 返回的 Base64 封面和头像保存到 `data/scraped-images`，不会嵌入媒体列表响应，也不依赖 MetaTube 图片接口。

支持名称搜索，以及使用标题 / 番号的元数据片段搜索。**仅依赖 Stash 本地文件名或指纹的片段刮削器不能直接处理本项目文件**，可改用其名称搜索或来源 URL。具体站点是否可用仍取决于 Stash 中的刮削器版本、登录配置与网络环境。

接口与运行方式依据 Stash 官方的 [GraphQL 刮削定义](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scraper.graphql)、[Stash-box 配置字段](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/stash-box.graphql)、[刮削查询实现](https://github.com/stashapp/stash/blob/develop/internal/api/resolver_query_scraper.go)及 [Stash-box 场景客户端](https://github.com/stashapp/stash/blob/develop/pkg/stashbox/scene.go)核对。

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
conda create -n tv python=3.10 nodejs -y
cd backend
conda run -n tv python -m pip install -r requirements.txt
conda run -n tv python -m uvicorn app.main:app --reload --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>

## 3. 前端

```bash
cd frontend
conda run -n tv npm ci
conda run -n tv npm run dev
```

打开 <http://127.0.0.1:5173>（Vite 将 `/api` 代理到 8000）。

## 4. 测试

```bash
cd backend
conda run -n tv python -m pytest -q
```

测试应使用独立的 `DATABASE_URL` / `MEDIA_ROOT`，避免写入真实媒体库。所有 Python、Node 和 npm 开发命令均通过 `conda run -n tv` 执行，无需在非交互式终端激活环境。

---

# 原文件名查询示例

`FC2-PPV-1066192.mp4` 查询 `FC2-PPV-1066192`；`ABC-330-C.mp4` 默认查询 `ABC-330-C`，Stash 查询 `ABC-330`；`010124_001.mp4` 查询 `010124_001`。除 Stash 的末尾字幕标记外，其余文本保持原样，由刮削源解释和匹配。本地编号始终保留原文件名去掉扩展名后的写法。

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
