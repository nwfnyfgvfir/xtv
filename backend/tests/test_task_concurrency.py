import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.models import Actor, BackgroundJob, BackgroundJobItem, MediaItem, utcnow
from app.services import task_runner as runner, task_store as store, scrape
from test_persistent_tasks import workspace, add_media, run


def until(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Concurrent work did not reach the expected checkpoint')


def blocking_scraper(monkeypatch, expected, release):
    lock = threading.Lock()
    state = {'active': 0, 'peak': 0, 'entered': set(), 'closed': set()}
    async def blocked(db, item, **kwargs):
        media_id = item.id
        with lock:
            state['active'] += 1
            state['peak'] = max(state['peak'], state['active'])
            state['entered'].add(media_id)
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
            item.scraped_at = utcnow()
            db.commit()
            return True
        finally:
            with lock:
                state['active'] -= 1
                state['closed'].add(media_id)
    monkeypatch.setattr(runner, 'scrape_media_item', blocked)
    return state


def test_batch_scrapes_overlap_and_atomic_progress_has_no_lost_updates(workspace, monkeypatch):
    api, factory, lib_id, _, _, _ = workspace
    ids = {add_media(workspace, f'ABP-00{n}') for n in range(1, 4)}
    task = api.post(f'/api/libraries/{lib_id}/rescrape-pending').json()
    release = threading.Event()
    state = blocking_scraper(monkeypatch, 3, release)
    with ThreadPoolExecutor(max_workers=3) as steps, ThreadPoolExecutor(max_workers=1) as jobs:
        future = jobs.submit(runner.execute_job, task['job_id'], factory, step_pool=steps, concurrency=3)
        try:
            until(lambda: state['entered'] == ids)
            assert state['peak'] == 3
            assert api.get('/api/tasks/' + task['job_id']).json()['running_items'] == 3
        finally:
            release.set()
            future.result(timeout=8)
    done = api.get('/api/tasks/' + task['job_id']).json()
    assert done['status'] == 'done' and done['processed'] == done['succeeded'] == done['scraped'] == 3
    with factory() as db:
        assert db.query(BackgroundJobItem).filter_by(job_id=task['job_id'], status='succeeded').count() == 3


def test_cancelling_parallel_batch_stops_all_items_and_resume_keeps_checkpoints(workspace, monkeypatch):
    api, factory, lib_id, _, calls, _ = workspace
    ids = {add_media(workspace, f'ABP-00{n}') for n in range(1, 4)}
    original = runner.scrape_media_item
    task = api.post(f'/api/libraries/{lib_id}/rescrape-pending').json()
    release = threading.Event()
    state = blocking_scraper(monkeypatch, 3, release)
    with ThreadPoolExecutor(max_workers=3) as steps, ThreadPoolExecutor(max_workers=1) as jobs:
        future = jobs.submit(runner.execute_job, task['job_id'], factory, step_pool=steps, concurrency=3)
        try:
            until(lambda: state['entered'] == ids)
            started = time.monotonic()
            api.post('/api/tasks/' + task['job_id'] + '/cancel').raise_for_status()
            future.result(timeout=2)
            assert time.monotonic() - started < 2 and state['closed'] == ids
        finally:
            release.set()
            future.result(timeout=8)
    done = api.get('/api/tasks/' + task['job_id']).json()
    assert done['status'] == 'cancelled' and done['processed'] == done['failed'] == 0
    monkeypatch.setattr(runner, 'scrape_media_item', original)
    assert run(workspace, api.post('/api/tasks/' + task['job_id'] + '/resume').json())['scraped'] == 3
    assert {media_id for media_id, _ in calls} == ids


def test_independent_tasks_overlap_but_share_one_global_concurrency_limit(workspace, monkeypatch):
    api, factory, _, _, _, settings = workspace
    settings.task_concurrency = 2
    ids = [add_media(workspace, f'ABP-00{n}') for n in range(1, 5)]
    tasks = [api.post(f'/api/media/{media_id}/rescrape-task', json={}).json() for media_id in ids]
    monkeypatch.setattr(runner, 'SessionLocal', factory)
    release = threading.Event()
    state = blocking_scraper(monkeypatch, 2, release)
    worker = runner.TaskRunner()
    worker.start()
    try:
        until(lambda: len(state['entered']) == 2)
        with factory() as db:
            assert db.query(BackgroundJob).filter_by(status='running').count() == 2
            assert db.query(BackgroundJob).filter_by(status='pending').count() == 2
        release.set()
        def all_done():
            with factory() as db:
                return db.query(BackgroundJob).filter_by(status='done').count() == 4
        until(all_done)
        assert state['peak'] == 2 and state['entered'] == set(ids)
        assert all(api.get('/api/tasks/' + task['job_id']).json()['scraped'] == 1 for task in tasks)
    finally:
        release.set()
        worker.stop()
        assert not worker.thread.is_alive()


def test_cancel_queued_parallel_item_does_not_wait_for_another_jobs_network(workspace, monkeypatch):
    api, factory, _, _, _, _ = workspace
    first, second = add_media(workspace), add_media(workspace, 'ABP-002')
    tasks = [api.post(f'/api/media/{media_id}/rescrape-task', json={}).json() for media_id in (first, second)]
    release = threading.Event()
    state = blocking_scraper(monkeypatch, 1, release)
    with ThreadPoolExecutor(max_workers=1) as steps, ThreadPoolExecutor(max_workers=2) as jobs:
        first_job = jobs.submit(runner.execute_job, tasks[0]['job_id'], factory, step_pool=steps)
        until(lambda: first in state['entered'])
        second_job = jobs.submit(runner.execute_job, tasks[1]['job_id'], factory, step_pool=steps)
        try:
            until(lambda: api.get('/api/tasks/' + tasks[1]['job_id']).json()['status'] == 'running')
            started = time.monotonic()
            api.post('/api/tasks/' + tasks[1]['job_id'] + '/cancel').raise_for_status()
            second_job.result(timeout=2)
            assert time.monotonic() - started < 2 and not first_job.done()
            assert second not in state['entered']
        finally:
            release.set()
            first_job.result(timeout=8)
            second_job.result(timeout=8)


def test_real_metadata_pipeline_overlaps_translation_without_holding_sqlite_writer(workspace, monkeypatch):
    api, factory, lib_id, _, _, settings = workspace
    settings.scrape_source, settings.auto_translate, settings.metatube_token = 'metatube', True, 'fixture'
    for n in range(1, 4):
        add_media(workspace, f'FC2-PPV-106619{n}')
    barrier = threading.Barrier(3)
    queries = []
    class Client:
        def __init__(self, _):
            self.token = 'fixture'
        async def search_movie(self, query, **kwargs):
            queries.append(query)
            return [{'provider': 'fixture', 'id': query}]
        async def get_movie(self, provider, movie_id, **kwargs):
            return {'number': movie_id.replace('-PPV', ''), 'title': 'Provider title',
                'actors': [{'name': 'Shared actor', 'provider': 'fixture', 'id': 'shared', 'image_url': 'http://fixture/actor.png'}]}
    async def translated(db, item, **kwargs):
        barrier.wait(timeout=5)
        item.title = 'Translated title'
    monkeypatch.setattr(scrape, 'MetaTubeClient', Client)
    monkeypatch.setattr(scrape, 'apply_translations', translated)
    monkeypatch.setattr(runner, 'scrape_media_item', scrape.scrape_media_item)
    task = api.post(f'/api/libraries/{lib_id}/rescrape-pending').json()
    with ThreadPoolExecutor(max_workers=3) as steps:
        runner.execute_job(task['job_id'], factory, step_pool=steps, concurrency=3)
    done = api.get('/api/tasks/' + task['job_id']).json()
    assert done['scraped'] == done['succeeded'] == 3 and done['failed'] == 0
    assert sorted(queries) == [f'FC2-PPV-106619{n}' for n in range(1, 4)]
    with factory() as db:
        assert db.query(Actor).count() == 1
        for item in db.query(MediaItem):
            assert item.number == item.filename[:-4] and item.title == 'Translated title'
            assert len(item.actors) == 1
