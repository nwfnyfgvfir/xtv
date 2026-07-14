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

`pytest` is used by tests but not listed in `requirements.txt` — install into the venv if missing: `pip install pytest`.

Settings load from **repo root** `.env` (`backend/app/config.py` → `ROOT_DIR.parents[2]`). Copy `.env.example` → `.env` for local work.

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

## Architecture

### Layout

| Path | Role |
|------|------|
| `backend/app/main.py` | FastAPI app, lifespan (DB init, scheduler, fs watcher), CORS, SPA fallback |
| `backend/app/api/` | Route modules mounted under `/api` |
| `backend/app/services/` | Scan, scrape, MetaTube/Alist clients, naming, translate, jobs, watcher, images |
| `backend/app/models.py` | SQLAlchemy models (Library, MediaItem, Actor, progress, favorites, settings) |
| `backend/app/config.py` | pydantic-settings; env + DB overrides for some settings |
| `frontend/src/views/` | Pages: library, detail, search, actors, favorites, settings, login |
| `frontend/src/components/VideoPlayer.vue` | Artplayer + custom gestures/lock |
| `frontend/src/api/` | Axios client (`baseURL: /api`) + typed API helpers |
| `media/local`, `media/strm` | Dev media roots (container: `/media`) |
| `data/` | Dev SQLite / logs (container: `/data`) |

### Backend request flow

1. **`api_router`** (`backend/app/api/__init__.py`) prefixes all routes with `/api`.
2. **Auth**: `ADMIN_PASSWORD` set → JWT required via `deps.require_auth` (except health + login). Empty password → auth off.
3. **Libraries** point at paths under `MEDIA_ROOT` (e.g. `local`, `strm`). **Scan** walks files → `naming.extract_number` → optional **scrape** (MetaTube) → optional **translate**.
4. **Playback** (`playback.py`): local file → `/api/stream/{id}` (Range); `.strm` HTTP line → direct URL; Alist path → `AlistClient` `raw_url`. Progress GET/PUT on media id.
5. **Settings**: env defaults + `app_settings` table overrides; settings UI can update MetaTube/Alist/image proxy/translate provider without restart for many keys. Translate engines: `google` (free gtx) | `bing` (free Edge); scrape applies title/plot/tags only.
6. **Background**: APScheduler for library auto-scan intervals; watchdog for filesystem changes when enabled on a library.

### Frontend flow

- Vue Router SPA; Pinia present; Element Plus UI.
- `useAuth` stores JWT in `localStorage` (`tv-token`) and attaches Axios interceptor.
- Library/detail/search call `/api/media*`; play uses `VideoPlayer` with play URL from `/api/media/{id}/play`.
- Vite dev server proxies `/api` → `127.0.0.1:8000`. Production: FastAPI serves built assets from `app/static` and SPA fallback.

### Playback / `.strm` semantics

| `.strm` content | Behavior |
|-----------------|----------|
| `https://...` | Player uses URL directly (`source_type` strm) |
| Alist path e.g. `/cloud/jav/x.mp4` | Backend resolves via Alist API (`source_type` alist) |

Filename numbering conventions (scraping): `SSIS-001`, `ABC-330-C`, `ABC-330-cd1`, `FC2-…`, `HEYZO-…` — see `services/naming.py` and README.

### VideoPlayer notes (frequent touch point)

Custom full-area gesture layer over Artplayer (`lock: false`):

- Single-tap control bar: snapshot visibility at **pointerdown**, apply after 300ms (avoids tablet desktop-path mousemove + toggle race).
- `Artplayer.CONTROL_HIDE_TIME` set to 6s.
- Double-tap seek L/R/C; horizontal drag seek; custom lock + 「开锁」FAB.
- Keep gesture layer capturing while locked so clicks do not hit `$video` (desktop Artplayer click toggles play without checking lock).

### External dependencies (runtime)

- **MetaTube**: scrape posters/title/actors (`METATUBE_BASE_URL` + token).
- **Alist**: resolve path-style `.strm` (`ALIST_BASE_URL` + token).
- **AutoFilm** (optional compose profile): generates `.strm` from remote Alist into shared media volume.

Do not commit `.env` or `config/autofilm/config.yaml` with secrets.
