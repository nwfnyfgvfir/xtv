import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models import BackgroundJob, BackgroundJobItem, MediaItem, utcnow
from app.services import task_runner as runner, task_store as store, task_control
from test_persistent_tasks import workspace, add_media, run


@pytest.mark.parametrize('kind', ['scan', 'rescrape_pending', 'rescrape'])
def test_cancel_interrupts_in_flight_scrape_without_waiting_for_response(workspace, monkeypatch, kind):
    api, factory, lib_id, _, calls, _ = workspace
    media_id = add_media(workspace)
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    original = runner.scrape_media_item
    async def blocked(db, item, **kwargs):
        entered.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.05)
        finally:
            closed.set()
        return await original(db, item, **kwargs)
    monkeypatch.setattr(runner, 'scrape_media_item', blocked)
    url = f'/api/media/{media_id}/rescrape-task' if kind == 'rescrape' else f'/api/libraries/{lib_id}/' + ('scan' if kind == 'scan' else 'rescrape-pending')
    task = api.post(url, json={}).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.execute_job, task['job_id'], factory)
        try:
            assert entered.wait(5)
            started = time.monotonic()
            api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
            future.result(timeout=1.5)
            assert time.monotonic() - started < 1.5
            assert closed.is_set() and not calls
        finally:
            release.set()
            future.result(timeout=5)
    result = api.get('/api/tasks/' + task['job_id']).json()
    assert result['status'] == 'cancelled' and result['failed'] == 0 and result['resumable']
    monkeypatch.setattr(runner, 'scrape_media_item', original)
    assert run(workspace, api.post(f"/api/tasks/{task['job_id']}/resume").json())['scraped'] == 1


def test_stale_cancel_does_not_resurrect_completed_task(workspace):
    _, factory, lib_id, _, _, _ = workspace
    with factory() as db:
        from app.models import Library
        job_id = store.enqueue(db, 'scan', db.get(Library, lib_id)).job_id
        job = db.get(BackgroundJob, job_id)
        job.status = 'running'
        db.commit()
        stale = db.get(BackgroundJob, job_id)
        assert stale.status == 'running'
        with factory() as worker:
            finished = worker.get(BackgroundJob, job_id)
            finished.status, finished.active_key, finished.finished_at = 'done', None, utcnow()
            worker.commit()
        result = store.cancel(db, stale)
        assert result.status == 'done' and result.active_key is None


def test_cancellation_signal_breaks_network_wait_while_scrape_holds_database_writer(workspace, monkeypatch):
    api, factory, lib_id, _, calls, _ = workspace
    media_id = add_media(workspace)
    entered, release = threading.Event(), threading.Event()
    async def blocked_writer(db, item, **kwargs):
        item.title = 'Uncommitted metadata must be rolled back'
        db.flush()
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.05)
        return False
    monkeypatch.setattr(runner, 'scrape_media_item', blocked_writer)
    # Emulate a different API process: only the shared marker can bypass its writer lock.
    monkeypatch.setattr(task_control, 'local_requested', lambda _: False)
    task = api.post(f'/api/media/{media_id}/rescrape-task', json={}).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.execute_job, task['job_id'], factory)
        try:
            assert entered.wait(5)
            started = time.monotonic()
            api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
            future.result(timeout=2)
            assert time.monotonic() - started < 2
        finally:
            release.set()
            future.result(timeout=5)
    with factory() as db:
        assert db.get(BackgroundJob, task['job_id']).status == 'cancelled'
        assert db.get(MediaItem, media_id).title is None
    assert not calls


def test_directory_enumeration_checks_cancel_before_all_entries_are_yielded(workspace, monkeypatch):
    import os
    from app.services import file_readiness
    api, factory, lib_id, root, _, _ = workspace
    for index in range(40):
        (root / str(index)).mkdir()
    task = api.post(f'/api/libraries/{lib_id}/scan').json()
    scandir = os.scandir
    counted = []
    class Listing:
        def __init__(self, path):
            self.source = scandir(path)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.source.close()
        def __iter__(self):
            for entry in self.source:
                counted.append(entry.name)
                if len(counted) == 5:
                    api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
                yield entry
    monkeypatch.setattr(file_readiness.os, 'scandir', Listing)
    result = run(workspace, task)
    assert result['status'] == 'cancelled' and len(counted) == 5


@pytest.mark.parametrize('status', ['pending', 'running', 'cancelling'])
def test_active_task_record_cannot_be_deleted(workspace, status):
    api, factory, lib_id, _, _, _ = workspace
    task = api.post(f'/api/libraries/{lib_id}/scan').json()
    with factory() as db:
        db.get(BackgroundJob, task['job_id']).status = status
        db.commit()
    response = api.delete('/api/tasks/' + task['job_id'])
    assert response.status_code == 409
    assert api.get('/api/tasks/' + task['job_id']).json()['status'] == status


def test_deleting_history_removes_steps_without_touching_media_or_files(workspace):
    api, factory, lib_id, root, _, _ = workspace
    media_id = add_media(workspace)
    before = (root / 'ABP-001.mp4').read_bytes()
    task = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert task['status'] == 'done'
    response = api.delete('/api/tasks/' + task['job_id'])
    assert response.status_code == 204 and response.headers['cache-control'] == 'no-store'
    assert api.get('/api/tasks/' + task['job_id']).status_code == 404
    with factory() as db:
        assert db.get(MediaItem, media_id).scraped_at
        assert db.query(BackgroundJobItem).count() == 0
    assert (root / 'ABP-001.mp4').read_bytes() == before


def test_clear_history_keeps_active_jobs_and_its_own_steps(workspace):
    api, factory, lib_id, _, _, _ = workspace
    finished = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    active = api.post(f'/api/libraries/{lib_id}/scan').json()
    result = api.delete('/api/tasks/history')
    assert result.status_code == 200 and result.json()['deleted'] == 1
    assert api.get('/api/tasks/' + active['job_id']).json()['status'] == 'pending'
    assert api.get('/api/tasks/' + finished['job_id']).status_code == 404
