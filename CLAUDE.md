# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Lightweight self-hosted media web app (Jellyfin-like): scan local video / `.strm`, scrape metadata via **remote MetaTube**, play via local Range stream or Alist `raw_url`. **MetaTube and Alist are external** — not deployed by this repo’s compose.

```text
Browser → TV (:8000 SPA + FastAPI)
            ├─ SQLite /data
            ├─ media /media (local files + .strm)
            ├─ HTTP → MetaTube (scrape)
            └─ HTTP → Alist (.strm path → raw_url)
```

Optional compose profile **AutoFilm** (remote Alist → write `.strm` under shared media volume).

## Commands

### Backend (FastAPI)

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# Git Bash / Linux
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # Windows venv
# or: source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
```

Health: `http://127.0.0.1:8000/api/health`

```bash
# All tests
cd backend
.venv\Scripts\python -m pytest -q

# Single test file / case
.venv\Scripts\python -m pytest tests/test_naming.py -q
.venv\Scripts\python -m pytest tests/test_naming.py::test_fc2 -q
```

Notable test modules: `test_naming`, `test_strm`, `test_scanner_prune`, `test_path_refresh`, `test_sorting`, `test_metatube`, `test_translate`, `test_image_cache`, `test_actors_merge`, `test_actor_favorites`.

`pytest` is used by tests but not listed in `requirements.txt` — install into the venv if missing: `pip install pytest`.

Settings load from **repo root** `.env` (`backend/app/config.py` → `ROOT_DIR = Path(__file__).resolve().parents[2]`). Copy `.env.example` → `.env` for local work.

Dev-oriented `.env` values:

```env
DATABASE_URL=sqlite:///./data/app.db
MEDIA_ROOT=./media
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
# ADMIN_PASSWORD empty → auth disabled (dev)
```

### Frontend (Vue 3 + Vite)

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173 — proxies /api → :8000
npm run build    # output used by Docker into backend static
npm run preview
```

No frontend test or lint scripts in `package.json`. Optional typecheck: `npx vue-tsc --noEmit`.

### Docker / production

```bash
# From repo root — compose pulls GHCR image (no local build by default)
cp .env.example .env   # set TV_IMAGE, METATUBE_*, ALIST_*, etc.
docker compose pull && docker compose up -d
curl -sS http://127.0.0.1:8000/api/health

# Optional AutoFilm profile (remote Alist → write .strm under media)
cp config/autofilm/config.example.yaml config/autofilm/config.yaml
docker compose --profile autofilm up -d

# Local image debug (optional)
docker build -t tv:local .
```

Release: push git tag `v*` → `.github/workflows/release-ghcr.yml` builds multi-stage image (Node build frontend → Python runtime, SPA under `app/static`).

Container paths (compose injects): `MEDIA_ROOT=/media`, `DATABASE_URL=sqlite:////data/app.db`.

## Architecture

### Layout

| Path | Role |
|------|------|
| `backend/app/main.py` | FastAPI app, lifespan (DB init, scheduler, fs watcher), CORS, SPA fallback |
| `backend/app/api/` | Route modules mounted under `/api` |
| `backend/app/services/` | Scan, scrape, MetaTube/Alist clients, naming, translate, actors merge, jobs, watcher, images |
| `backend/app/models.py` | SQLAlchemy models |
| `backend/app/schemas.py` | Pydantic request/response models |
| `backend/app/config.py` | pydantic-settings; env + DB overrides for some settings |
| `frontend/src/views/` | library, detail, search, actors, actor detail, favorites, settings, login |
| `frontend/src/components/VideoPlayer.vue` | Artplayer + custom gestures/lock |
| `frontend/src/api/` | Axios client (`baseURL: /api`) + typed helpers |
| `media/local`, `media/strm` | Dev media roots (container: `/media`) |
| `data/` | Dev SQLite / logs / optional image-cache (container: `/data`) |

### Domain model (SQLite)

- **Library** — named folder under `MEDIA_ROOT` (e.g. `local`, `strm`); optional auto-scan interval + fs watcher.
- **MediaItem** — one file; unique `(library_id, path)`; `source_type` local/strm/alist; scrape fields (number, title, plot, cover…); `strm_target` for `.strm` content.
- **Actor** ↔ **MediaItem** via `media_actors`; actors keyed by `(provider, provider_id)` with merge logic in `services/actors.py`.
- **PlaybackProgress** — per-media position.
- **Favorite** / **ActorFavorite** — media favorites and actor favorites.
- **app_settings** — runtime key/value overrides for MetaTube/Alist/translate/image proxy (settings UI).

### Backend request flow

1. **`api_router`** (`backend/app/api/__init__.py`) prefixes all routes with `/api`.
2. **Auth**: `ADMIN_PASSWORD` set → JWT via `deps.require_auth` (except health + login). Empty password → auth off.
3. **Libraries** → paths under `MEDIA_ROOT`. **Scan** walks files → `naming.extract_number` → optional **scrape** (MetaTube) → optional **translate** (title/plot/tags → 简中).
4. **Playback** (`api/playback.py`):
   - local → `/api/stream/{id}` (Range);
   - `.strm` HTTP line → direct URL (`kind=direct`);
   - Alist path → `AlistClient.raw_url` (`kind=alist`).
   - Progress GET/PUT on media id.
5. **Actors / favorites**: list/detail, favorite toggles, actor media list; image URLs rewritten through image proxy.
6. **Settings**: env defaults + `app_settings` table; UI can update MetaTube/Alist/image proxy/translate without restart for many keys.
   - Translate: `google` (free gtx) | `bing` (free Edge).
   - Image proxy modes: `site` (`/api/images/proxy`) | `metatube` | `external` (template with `{url}`); optional disk cache under data when `IMAGE_LOCAL_CACHE`.
7. **Background**: APScheduler for library auto-scan; watchdog for filesystem changes when enabled on a library.

### Frontend flow

- Vue Router SPA; Pinia present; Element Plus UI.
- Routes: `/`, `/search`, `/media/:id`, `/actors`, `/actors/:id`, `/favorites`, `/settings`, `/login`.
- `useAuth` stores JWT in `localStorage` (`tv-token`) + Axios interceptor.
- Lists/detail call `/api/media*`, `/api/actors*`, `/api/favorites*`; play uses `VideoPlayer` with URL from `/api/media/{id}/play`.
- Vite dev proxies `/api` → `127.0.0.1:8000`. Production: FastAPI serves `app/static` + SPA fallback.

### Playback / `.strm` semantics

| `.strm` content | Behavior |
|-----------------|----------|
| `https://...` | Player uses URL directly |
| Alist path e.g. `/cloud/jav/x.mp4` | Backend resolves via Alist API |

Filename numbering (scraping): `SSIS-001`, `ABC-330-C`, `ABC-330-cd1`, `FC2-…`, `HEYZO-…` — see `services/naming.py` and README.

### VideoPlayer notes (frequent touch point)

Artplayer (`lock: false`) + custom full-area gesture layer:

- Single-tap control bar: snapshot visibility at **pointerdown**, apply after 300ms (tablet desktop-path mousemove race).
- `Artplayer.CONTROL_HIDE_TIME` = 6s.
- Double-tap seek L/R/C; horizontal drag seek; custom 「锁」 + 「开锁」FAB.
- Gesture layer stays capturing while locked so clicks never hit `$video` (desktop Artplayer click toggles play without checking lock).
- `autoOrientation: true` — on **native** fullscreen (mobile), try `screen.orientation.lock` when video aspect mismatches viewport. iOS often uses `webkitEnterFullscreen` and may not lock orientation.
- Both `fullscreen` and `fullscreenWeb` enabled; custom lock is separate from Artplayer’s mobile lock plugin.

### External dependencies (runtime)

- **MetaTube**: scrape posters/title/actors (`METATUBE_BASE_URL` + token).
- **Alist**: resolve path-style `.strm` (`ALIST_BASE_URL` + token); browser must be able to reach returned `raw_url` for playback.
- **AutoFilm** (optional profile): generates `.strm` from remote Alist into shared media volume — see `config/autofilm/README.md`.

Do not commit `.env` or `config/autofilm/config.yaml` with secrets.
