import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import libraries, media, scan, tasks, library_tools
from app.db import Base, get_db
from app.deps import require_auth
from app.models import BackgroundJob, BackgroundJobItem, Library, MediaItem, utcnow
from app.services import scanner, task_runner as runner, task_store as store
from app.services import file_readiness, auto_scan, task_control


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, database_url=f"sqlite:///{tmp_path.as_posix()}/jobs.db",
        media_root=str(tmp_path), auto_translate=False, auto_scrape=True, scrape_source="stashscrapers",
        stashscrapers_token="test-secret-never-in-job", stashscrapers_scraper_priority='["A","B"]')
    for module in (config, runner, store, scanner, file_readiness, auto_scan, task_control):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(libraries, "reload_watches", lambda: None)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    root = tmp_path / "local"
    root.mkdir()
    with factory() as db:
        lib = Library(name="Task fixtures", path=str(root), type="local")
        db.add(lib)
        db.commit()
        lib_id = lib.id
    app = FastAPI()
    for router, prefix in ((tasks.router, "/api"), (libraries.router, "/api/libraries"),
                           (library_tools.router, "/api/libraries"),
                           (media.router, "/api/media"), (scan.router, "/api")):
        app.include_router(router, prefix=prefix)

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    calls = []

    async def scrape_ok(db, item, **kwargs):
        calls.append((item.id, kwargs))
        item.title = "Updated " + (item.number or "URL")
        item.scraped_at = utcnow()
        db.commit()
        return True

    monkeypatch.setattr(runner, "scrape_media_item", scrape_ok)
    with TestClient(app) as api:
        yield api, factory, lib_id, root, calls, settings
    engine.dispose()


def add_media(workspace, number="ABP-001", *, scraped=False, exists=True):
    _, factory, lib_id, root, _, _ = workspace
    path = root / f"{number or 'unknown'}.mp4"
    if exists:
        path.write_bytes(b"fixture")
    with factory() as db:
        item = MediaItem(library_id=lib_id, path=str(path.resolve()), filename=path.name,
            source_type="local", number=number, scraped_at=utcnow() if scraped else None)
        db.add(item)
        db.commit()
        return item.id


def run(workspace, task):
    api, factory, *_ = workspace
    runner.execute_job(task["job_id"], factory)
    response = api.get("/api/tasks/" + task["job_id"])
    assert response.status_code == 200
    return response.json()


def test_three_entry_points_persist_and_return_without_scraping(workspace):
    api, factory, lib_id, _, calls, _ = workspace
    media_id = add_media(workspace)
    urls = [f"/api/libraries/{lib_id}/scan", f"/api/libraries/{lib_id}/rescrape-pending", f"/api/media/{media_id}/rescrape-task"]
    for url in urls:
        response = api.post(url, json={})
        assert response.status_code == 202, response.text
        task = response.json()
        assert task["status"] == "pending" and task["job_id"]
        assert api.post(url, json={}).json()["job_id"] == task["job_id"]
        with factory() as db:
            row = db.get(BackgroundJob, task["job_id"])
            assert "test-secret" not in row.params_json
        assert "test-secret" not in api.get("/api/tasks/" + task["job_id"]).text
    history = api.get("/api/tasks")
    assert history.headers["Cache-Control"] == "no-store"
    assert len(history.json()) == 3 and not calls
    task = api.get("/api/tasks").json()[0]
    assert api.get("/api/scan/jobs/" + task["job_id"]).json()["job_id"] == task["job_id"]


def test_batch_checkpoint_and_retry_only_failed_with_original_policy(workspace, monkeypatch):
    api, _, lib_id, _, calls, settings = workspace
    first, second = add_media(workspace), add_media(workspace, "ABP-002")
    add_media(workspace, "ABP-003", scraped=True)
    unnamed = add_media(workspace, None)
    original = runner.scrape_media_item

    async def fail_second(db, item, **kwargs):
        if item.id == second:
            calls.append((item.id, kwargs))
            return False
        return await original(db, item, **kwargs)

    monkeypatch.setattr(runner, "scrape_media_item", fail_second)
    task = api.post(f"/api/libraries/{lib_id}/rescrape-pending").json()
    done = run(workspace, task)
    assert (done["total"], done["processed"], done["succeeded"], done["failed"]) == (3, 3, 2, 1)
    assert done["retryable"] and done["status"] == "done"
    failures = api.get(f"/api/tasks/{task['job_id']}/items?status=failed").json()
    assert [row["media_id"] for row in failures] == [second]
    settings.scrape_source = "metatube"
    monkeypatch.setattr(runner, "scrape_media_item", original)
    retry = api.post(f"/api/tasks/{task['job_id']}/retry").json()
    assert retry["job_id"] != task["job_id"] and retry["parent_id"] == task["job_id"]
    retried = run(workspace, retry)
    assert retried["total"] == retried["scraped"] == 1 and retried["failed"] == 0
    assert [item_id for item_id, _ in calls] == [first, second, unnamed, second]
    assert calls[-1][1]["settings_override"].scrape_source == "stashscrapers"
    assert api.get(f"/api/tasks/{task['job_id']}").json()["failed"] == 1
    assert not api.get(f"/api/tasks/{task['job_id']}").json()["retryable"]
    assert api.post(f"/api/tasks/{task['job_id']}/retry").json()["job_id"] == retry["job_id"]


def test_cancel_running_batch_finishes_current_then_resume_skips_success(workspace, monkeypatch):
    api, _, lib_id, _, calls, _ = workspace
    first, second = add_media(workspace), add_media(workspace, "ABP-002")
    task = api.post(f"/api/libraries/{lib_id}/rescrape-pending").json()
    original = runner.scrape_media_item

    async def cancel_after_first(db, item, **kwargs):
        response = api.post(f"/api/tasks/{task['job_id']}/cancel")
        assert response.json()["status"] == "cancelling"
        return await original(db, item, **kwargs)

    monkeypatch.setattr(runner, "scrape_media_item", cancel_after_first)
    cancelled = run(workspace, task)
    assert cancelled["status"] == "cancelled" and cancelled["processed"] == 1 and cancelled["resumable"]
    monkeypatch.setattr(runner, "scrape_media_item", original)
    continued = api.post(f"/api/tasks/{task['job_id']}/resume").json()
    assert run(workspace, continued)["scraped"] == 2
    assert [item_id for item_id, _ in calls] == [first, second]


def test_cancel_queued_job_makes_no_requests(workspace):
    api, _, lib_id, _, calls, _ = workspace
    add_media(workspace)
    task = api.post(f"/api/libraries/{lib_id}/rescrape-pending").json()
    api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
    assert run(workspace, task)["status"] == "cancelled" and not calls
    assert run(workspace, api.post(f"/api/tasks/{task['job_id']}/resume").json())["scraped"] == 1


def test_restart_recovers_committed_scrape_without_repeating_it(workspace):
    api, factory, lib_id, _, calls, _ = workspace
    first, second = add_media(workspace), add_media(workspace, "ABP-002")
    task = api.post(f"/api/libraries/{lib_id}/rescrape-pending").json()
    with factory() as db:
        job = db.get(BackgroundJob, task["job_id"])
        job.status, job.manifest_ready = "running", True
        for media_id in (first, second):
            store.add_item(db, job, "scrape", f"scrape:{media_id}", str(media_id), media_id=media_id)
        db.flush()
        rows = db.query(BackgroundJobItem).order_by(BackgroundJobItem.id).all()
        rows[0].status, rows[0].started_at = "running", utcnow() - timedelta(seconds=1)
        db.get(MediaItem, first).scraped_at = utcnow()
        db.commit()
    runner.recover_interrupted(factory)
    restored = api.get(f"/api/tasks/{task['job_id']}").json()
    assert restored["status"] == "interrupted" and restored["scraped"] == 1 and restored["processed"] == 1
    assert run(workspace, api.post(f"/api/tasks/{task['job_id']}/resume").json())["scraped"] == 2
    assert [media_id for media_id, _ in calls] == [second]


def test_scan_checkpoints_index_prune_and_auto_scrape(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    first = add_media(workspace)
    removed = add_media(workspace, "OLD-001", exists=False)
    (root / "ABP-002.mp4").write_bytes(b"fixture")
    done = run(workspace, api.post(f"/api/libraries/{lib_id}/scan").json())
    assert (done["scanned"], done["created"], done["removed"], done["scraped"]) == (2, 1, 1, 2)
    assert done["total"] == done["processed"] == 5 and done["failed"] == 0
    with factory() as db:
        assert db.get(MediaItem, removed) is None
        assert db.get(MediaItem, first).scraped_at
    assert len(calls) == 2


def test_scan_interruption_does_not_prune_and_can_continue(workspace, monkeypatch):
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    removed = add_media(workspace, "OLD-001", exists=False)
    for number in ("ABP-001", "ABP-002"):
        (root / (number + ".mp4")).write_bytes(b"fixture")
    task = api.post(f"/api/libraries/{lib_id}/scan").json()
    stop = threading.Event()
    finish = store.finish_item

    def interrupt_after_index(db, job, item, *args, **kwargs):
        finish(db, job, item, *args, **kwargs)
        if item.phase == "index":
            stop.set()

    monkeypatch.setattr(store, "finish_item", interrupt_after_index)
    runner.execute_job(task["job_id"], factory, stop)
    with factory() as db:
        assert db.get(MediaItem, removed) is not None
        assert db.get(BackgroundJob, task["job_id"]).processed == 1
    monkeypatch.setattr(store, "finish_item", finish)
    continued = api.post(f"/api/tasks/{task['job_id']}/resume").json()
    done = run(workspace, continued)
    assert done["scanned"] == 2 and done["removed"] == 1 and done["status"] == "done"


def test_failed_index_prevents_prune_and_retry_does_not_repeat_successful_files(workspace, monkeypatch):
    api, factory, lib_id, root, calls, _ = workspace
    missing = add_media(workspace, "OLD-001", exists=False)
    for number in ("ABP-001", "ABP-002"):
        (root / (number + ".mp4")).write_bytes(b"fixture")
    original = runner._ingest_file

    def fail_first(db, lib, path, *args, **kwargs):
        if path.name == "ABP-001.mp4":
            raise ValueError("fixture read failure")
        return original(db, lib, path, *args, **kwargs)

    monkeypatch.setattr(runner, "_ingest_file", fail_first)
    task = api.post(f"/api/libraries/{lib_id}/scan").json()
    done = run(workspace, task)
    assert done["failed"] == 1 and done["removed"] == 0 and done["skipped"] == 1
    monkeypatch.setattr(runner, "_ingest_file", original)
    retry = api.post(f"/api/tasks/{task['job_id']}/retry").json()
    done = run(workspace, retry)
    assert done["scanned"] == done["scraped"] == 1 and done["failed"] == 0
    with factory() as db:
        assert db.get(MediaItem, missing) is not None
    assert len(calls) == 2


def test_single_rescrape_keeps_overrides_and_runs_as_background_job(workspace):
    api, _, _, _, calls, _ = workspace
    media_id = add_media(workspace, scraped=True)
    task = api.post(f"/api/media/{media_id}/rescrape-task", json={"number": "abp 002", "provider": "B", "fallback": False}).json()
    assert not calls
    done = run(workspace, task)
    assert done["scraped"] == 1 and done["status"] == "done"
    assert calls[0][1]["force"] is True and calls[0][1]["provider_override"] == "B"
    assert "fallback_override" not in calls[0][1]
    assert api.get(f"/api/media/{media_id}").json()["number"] == "ABP-001"


@pytest.mark.parametrize("source", ["metatube", "stash", "stashscrapers"])
def test_single_rescrape_uses_selected_backend_and_saved_priority(workspace, source):
    api, factory, _, _, calls, settings = workspace
    settings.metatube_provider_priority = '["MetaFirst"]'
    settings.stash_scraper_priority = '["StashFirst"]'
    media_id = add_media(workspace)
    body = {"scrape_source": source, "provider": "Selected"}
    response = api.post(f"/api/media/{media_id}/rescrape-task", json=body)
    assert response.status_code == 202, response.text
    task = response.json()
    assert api.post(f"/api/media/{media_id}/rescrape-task", json=body).json()["job_id"] == task["job_id"]
    assert settings.scrape_source == "stashscrapers"
    with factory() as db:
        params = json.loads(db.get(BackgroundJob, task["job_id"]).params_json)
        assert params["settings"]["scrape_source"] == source
        assert "test-secret" not in json.dumps(params)
    settings.scrape_source = "stash" if source != "stash" else "metatube"
    settings.stashscrapers_scraper_priority = '["Changed"]'
    assert run(workspace, task)["scraped"] == 1
    selected = calls[-1][1]
    assert selected["settings_override"].scrape_source == source
    assert selected["settings_override"].stashscrapers_scraper_priority == '["A","B"]'
    assert selected["provider_override"] == "Selected"


def test_single_rescrape_backend_is_preserved_on_resume_and_retry(workspace, monkeypatch):
    api, _, _, _, calls, settings = workspace
    media_id = add_media(workspace)
    task = api.post(f"/api/media/{media_id}/rescrape-task", json={"scrape_source": "stash"}).json()
    api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
    settings.scrape_source = "metatube"
    original = runner.scrape_media_item

    async def fail(db, item, **kwargs):
        assert kwargs["settings_override"].scrape_source == "stash"
        return False

    monkeypatch.setattr(runner, "scrape_media_item", fail)
    resumed = api.post(f"/api/tasks/{task['job_id']}/resume").json()
    assert run(workspace, resumed)["failed"] == 1
    monkeypatch.setattr(runner, "scrape_media_item", original)
    retry = api.post(f"/api/tasks/{task['job_id']}/retry").json()
    assert run(workspace, retry)["scraped"] == 1
    assert calls[-1][1]["settings_override"].scrape_source == "stash"
    assert settings.scrape_source == "metatube"


def test_backend_order_is_snapshotted_for_queued_scan(workspace):
    api, _, lib_id, _, calls, settings = workspace
    settings.scrape_source_priority = '["metatube","stash"]'
    add_media(workspace)
    task = api.post(f'/api/libraries/{lib_id}/rescrape-pending').json()
    settings.scrape_source_priority = '["stashscrapers"]'
    assert run(workspace, task)['scraped'] == 1
    assert calls[-1][1]['settings_override'].scrape_source_priority == '["metatube","stash"]'
    assert calls[-1][1]['source_override'] is None


@pytest.mark.parametrize("global_source, selected, status", [
    ("metatube", "stash", 202), ("metatube", "stashscrapers", 202),
    ("stash", "metatube", 400), ("stash", None, 202), ("metatube", None, 400),
])
def test_single_rescrape_url_is_validated_for_selected_backend(workspace, global_source, selected, status):
    api, _, _, _, _, settings = workspace
    settings.scrape_source = global_source
    media_id = add_media(workspace)
    body = {"url": "https://source.example/scene/1"}
    if selected:
        body["scrape_source"] = selected
    response = api.post(f"/api/media/{media_id}/rescrape-task", json=body)
    assert response.status_code == status, response.text
    assert settings.scrape_source == global_source


def test_single_rescrape_rejects_unknown_backend_and_conflicting_backend(workspace):
    api, _, _, _, _, _ = workspace
    media_id = add_media(workspace)
    url = f"/api/media/{media_id}/rescrape-task"
    assert api.post(url, json={"scrape_source": "unknown"}).status_code == 422
    first = api.post(url, json={"scrape_source": "stash", "provider": "A"}).json()
    conflict = api.post(url, json={"scrape_source": "metatube", "provider": "A"})
    assert conflict.status_code == 409 and conflict.headers["X-Task-Id"] == first["job_id"]


def test_single_rescrape_does_not_scan_library_or_touch_other_files(workspace, monkeypatch):
    api, factory, _, root, calls, _ = workspace
    media_id = add_media(workspace, scraped=True)
    missing_id = add_media(workspace, 'ABP-002', exists=False)
    unindexed = root / 'ABP-003.mp4'
    unindexed.write_bytes(b'not scanned')
    def unexpected_walk(*args, **kwargs):
        raise AssertionError('Single-scene rescrape must not walk the media library')
    monkeypatch.setattr(runner, 'iter_files', unexpected_walk)
    result = run(workspace, api.post(f'/api/media/{media_id}/rescrape-task', json={}).json())
    assert result['status'] == 'done' and result['total'] == result['scraped'] == 1
    assert [item_id for item_id, _ in calls] == [media_id]
    with factory() as db:
        assert db.query(BackgroundJob).count() == 1
        assert db.query(BackgroundJobItem).one().phase == 'scrape'
        assert db.query(MediaItem).count() == 2 and db.get(MediaItem, missing_id) is not None


def test_concurrent_duplicate_submission_creates_one_job(workspace):
    _, factory, lib_id, *_ = workspace
    barrier = threading.Barrier(4)

    def submit(_):
        with factory() as db:
            lib = db.get(Library, lib_id)
            barrier.wait(timeout=5)
            return store.enqueue(db, "scan", lib).job_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(submit, range(4)))) == 1


def test_different_override_does_not_silently_reuse_active_task(workspace):
    api, _, lib_id, *_ = workspace
    media_id = add_media(workspace)
    first = api.post(f"/api/media/{media_id}/rescrape-task", json={"provider": "A"}).json()
    conflict = api.post(f"/api/media/{media_id}/rescrape-task", json={"provider": "B"})
    assert conflict.status_code == 409 and conflict.headers["X-Task-Id"] == first["job_id"]
    assert api.delete(f"/api/libraries/{lib_id}").status_code == 409
    assert api.post(f"/api/media/{media_id}/rescrape", json={}).status_code == 409


def test_missing_directory_keeps_media_and_allows_resume(workspace):
    api, factory, lib_id, root, *_ = workspace
    old = add_media(workspace, exists=False)
    root.rmdir()
    task = api.post(f"/api/libraries/{lib_id}/scan").json()
    done = run(workspace, task)
    assert done["status"] == "error" and done["resumable"]
    with factory() as db:
        assert db.get(MediaItem, old) is not None
    root.mkdir()
    assert run(workspace, api.post(f"/api/tasks/{task['job_id']}/resume").json())["status"] == "done"


def test_worker_file_lock_excludes_second_worker(workspace):
    owner, standby = runner.TaskRunner(), runner.TaskRunner()
    lock = owner._lock()
    assert lock is not None
    try:
        assert standby._lock() is None
    finally:
        lock.close()
    acquired = standby._lock()
    assert acquired is not None
    acquired.close()


def test_targeted_watcher_scan_preserves_other_paths(workspace):
    api, factory, lib_id, root, calls, settings = workspace
    settings.auto_scrape = False
    other_missing = add_media(workspace, "OTHER-001", exists=False)
    scoped = root / "incoming"
    scoped.mkdir()
    (scoped / "ABP-001.mp4").write_bytes(b"fixture")
    with factory() as db:
        job = store.enqueue(db, "scan", db.get(Library, lib_id), inputs={"paths": [str(scoped), str(scoped / 'ABP-001.mp4')]})
        job_id = job.job_id
    done = run(workspace, {"job_id": job_id})
    assert done["scanned"] == 1 and done["removed"] == 0 and not calls
    with factory() as db:
        assert db.get(MediaItem, other_missing) is not None


def test_full_scan_still_prunes_files_excluded_by_extension_settings(workspace):
    api, factory, lib_id, _, _, settings = workspace
    old = add_media(workspace)
    settings.scan_extensions = "mkv"
    done = run(workspace, api.post(f"/api/libraries/{lib_id}/scan").json())
    assert done["scanned"] == 0 and done["removed"] == 1
    with factory() as db:
        assert db.get(MediaItem, old) is None


def test_recovery_leaves_queued_tasks_ready_to_run(workspace):
    api, factory, lib_id, *_ = workspace
    add_media(workspace)
    job = api.post(f"/api/libraries/{lib_id}/rescrape-pending").json()
    runner.recover_interrupted(factory)
    assert api.get(f"/api/tasks/{job['job_id']}").json()["status"] == "pending"
    assert run(workspace, job)["scraped"] == 1


def test_task_history_and_controls_require_authentication(workspace, monkeypatch):
    from app import deps
    api, _, _, _, _, settings = workspace
    settings.admin_password = "test-admin-password"
    settings.auth_required = True
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    del api.app.dependency_overrides[require_auth]
    for method, url in (("GET", "/api/tasks"), ("GET", "/api/tasks/missing"),
                        ("GET", "/api/tasks/missing/items"), ("POST", "/api/tasks/missing/cancel"),
                        ("POST", "/api/tasks/missing/resume"), ("POST", "/api/tasks/missing/retry"),
                        ("DELETE", "/api/tasks/missing"), ("DELETE", "/api/tasks/history")):
        assert api.request(method, url).status_code == 401
