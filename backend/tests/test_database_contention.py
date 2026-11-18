import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.models import AppSetting, BackgroundJob, BackgroundJobItem, Library, MediaItem
from app.services import task_runner as runner, task_store as store, task_control
from test_persistent_tasks import workspace, run


def test_scan_index_survives_another_connection_writing_after_its_read(workspace, monkeypatch):
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    (root / 'ABC-123.mp4').write_bytes(b'fixture')
    task = api.post(f'/api/libraries/{lib_id}/scan').json()
    original = runner.check_file
    entered, committed = threading.Event(), threading.Event()
    writes = []

    def concurrent_write():
        with factory() as db:
            entered.set()
            db.add(AppSetting(key='concurrent-write', value='fixture'))
            db.commit()
            committed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        def checked(db, *args, **kwargs):
            check = original(db, *args, **kwargs)
            if db.in_nested_transaction() and not writes:
                db.execute(text('SELECT COUNT(*) FROM media_items')).scalar_one()
                writes.append(pool.submit(concurrent_write))
                assert entered.wait(2)
                # A reader can overlap the writer; a transaction that already
                # reserved the write lock lets it commit after the batch ends.
                committed.wait(0.1)
            return check

        monkeypatch.setattr(runner, 'check_file', checked)
        result = run(workspace, task)
        for future in writes:
            future.result(timeout=6)
    assert writes and committed.is_set()
    assert result['status'] == 'done' and result['failed'] == 0, result
    assert result['created'] == 1
    assert result['succeeded'] == result['processed'] == result['total']
    with factory() as db:
        assert db.query(MediaItem).count() == 1


def test_index_and_progress_rollback_together_if_batch_cannot_finish(workspace, monkeypatch):
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    (root / 'ABC-123.mp4').write_bytes(b'fixture')
    task = api.post(f'/api/libraries/{lib_id}/scan').json()

    finish = store.finish_item
    def progress_failure(*args, **kwargs):
        raise RuntimeError('Fixture progress write failed')

    monkeypatch.setattr(store, 'finish_item', progress_failure)
    result = run(workspace, task)
    assert result['status'] == 'error'
    with factory() as db:
        assert db.query(MediaItem).count() == 0
        assert db.get(BackgroundJob, task['job_id']).created == 0
    assert result['resumable']
    monkeypatch.setattr(store, 'finish_item', finish)
    resumed = api.post(f"/api/tasks/{task['job_id']}/resume").json()
    result = run(workspace, resumed)
    assert result['status'] == 'done' and result['created'] == 1 and result['failed'] == 0


def test_multiple_library_scans_and_scrapes_share_sqlite_without_lost_progress(workspace, monkeypatch):
    api, factory, lib_id, root, calls, settings = workspace
    settings.file_settle_seconds, settings.task_concurrency = 0, 3
    libraries = [(lib_id, root)]
    with factory() as db:
        for index in range(2):
            directory = root.parent / f'parallel-{index}'
            directory.mkdir()
            lib = Library(name=f'Parallel {index}', path=str(directory), type='local')
            db.add(lib)
            db.flush()
            libraries.append((lib.id, directory))
        db.commit()
    tasks = []
    for library_id, directory in libraries:
        for index in range(40):
            (directory / f'ABC-{index:03}.mp4').write_bytes(b'fixture')
        tasks.append(api.post(f'/api/libraries/{library_id}/scan').json())
    barrier, lock = threading.Barrier(3), threading.Lock()
    entered = set()
    original = runner._index_batch

    def simultaneous_index(factory, job_id, stop):
        with lock:
            first_batch = job_id not in entered
            entered.add(job_id)
        if first_batch:
            barrier.wait(timeout=8)
        return original(factory, job_id, stop)

    monkeypatch.setattr(runner, '_index_batch', simultaneous_index)
    monkeypatch.setattr(runner, 'SessionLocal', factory)
    worker = runner.TaskRunner()
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with factory() as db:
                statuses = [db.get(BackgroundJob, task['job_id']).status for task in tasks]
            if all(status not in store.ACTIVE for status in statuses):
                break
            time.sleep(0.02)
        results = [api.get('/api/tasks/' + task['job_id']).json() for task in tasks]
        assert len(entered) == 3
        for result in results:
            assert result['status'] == 'done' and result['failed'] == 0, result
            assert result['created'] == result['scraped'] == 40
            assert result['succeeded'] == result['processed'] == result['total']
        assert len(calls) == len({media_id for media_id, _ in calls}) == 120
        with factory() as db:
            assert db.query(MediaItem).count() == 120
            assert db.query(BackgroundJobItem).filter_by(status='running').count() == 0
    finally:
        worker.stop()
        assert not worker.thread.is_alive()


def test_cancel_during_reserved_index_transaction_releases_writer_and_can_resume(workspace, monkeypatch):
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    (root / 'ABC-123.mp4').write_bytes(b'fixture')
    task = api.post(f'/api/libraries/{lib_id}/scan').json()
    entered = threading.Event()
    original = runner.check_file

    def checked(db, *args, **kwargs):
        if db.in_nested_transaction() and not entered.is_set():
            entered.set()
            deadline = time.monotonic() + 5
            while not task_control.requested(task['job_id']):
                assert time.monotonic() < deadline, 'Cancellation signal did not arrive'
                time.sleep(0.01)
        return original(db, *args, **kwargs)

    monkeypatch.setattr(runner, 'check_file', checked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.execute_job, task['job_id'], factory)
        assert entered.wait(5)
        started = time.monotonic()
        api.post(f"/api/tasks/{task['job_id']}/cancel").raise_for_status()
        future.result(timeout=3)
        assert time.monotonic() - started < 3
    with factory() as db:
        assert db.get(BackgroundJob, task['job_id']).status == 'cancelled'
        assert db.query(MediaItem).count() == 0
    resumed = api.post(f"/api/tasks/{task['job_id']}/resume").json()
    result = run(workspace, resumed)
    assert result['status'] == 'done' and result['created'] == 1 and result['failed'] == 0
