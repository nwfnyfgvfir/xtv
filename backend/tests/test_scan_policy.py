import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from watchdog.events import FileCreatedEvent, DirModifiedEvent, FileMovedEvent

from app.models import BackgroundJob, BackgroundJobItem, FileObservation, MediaItem, Library, utcnow
from app.services import file_readiness as ready, auto_scan, scanner
from app.services.naming import source_name
from test_persistent_tasks import workspace, add_media, run


@pytest.fixture(autouse=True)
def native_observer(monkeypatch):
    class NativeObserver:
        alive = False

        def schedule(self, handler, path, recursive):
            self.handler = handler

        def start(self):
            self.alive = True

        def stop(self):
            self.alive = False

        def is_alive(self):
            return self.alive

        def join(self, **kwargs):
            pass

    monkeypatch.setattr(auto_scan, 'Observer', NativeObserver)


@pytest.mark.parametrize('name', ['ABP-001.mp4.part', 'ABP-001.part.mp4', 'ABP-001.tmp.mp4',
    'ABP-001.f137.mp4', 'ABP-001.part.wmv', 'ABP-001.tmp.m2ts', '.ABP-001.mp4',
    'incomplete/ABP-001.mp4', '.cache/ABP-001.mp4'])
def test_process_files_do_not_enter_library(workspace, name):
    api, factory, lib_id, root, calls, _ = workspace
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'partial')
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['created'] == done['scraped'] == 0 and not calls
    with factory() as db:
        assert db.query(MediaItem).count() == 0


def test_rescan_refreshes_missing_subtitle_flag_on_unchanged_scraped_media(workspace):
    api, factory, lib_id, _, calls, settings = workspace
    settings.auto_scrape = False
    media_id = add_media(workspace, 'ABC-123-ch', scraped=True)
    url = f'/api/libraries/{lib_id}/scan'
    run(workspace, api.post(url).json())
    with factory() as db:
        item = db.get(MediaItem, media_id)
        assert item.subtitle_flag == 'C'
        scraped_at = item.scraped_at
        item.subtitle_flag = None
        db.commit()
    done = run(workspace, api.post(url).json())
    assert done['created'] == done['scraped'] == 0 and not calls
    with factory() as db:
        item = db.get(MediaItem, media_id)
        assert item.subtitle_flag == 'C' and item.scraped_at == scraped_at
        assert item.number == 'ABC-123-ch' and item.filename == 'ABC-123-ch.mp4'


def test_rename_refreshes_subtitle_flag(workspace):
    _, factory, lib_id, _, _, settings = workspace
    settings.file_settle_seconds = 0
    media_id = add_media(workspace, 'ABC-123')
    with factory() as db:
        assert scanner.rename_media_item(db, lib_id, media_id, 'ABC-123C.mp4')['ok']
        assert db.get(MediaItem, media_id).subtitle_flag == 'C'
        assert scanner.rename_media_item(db, lib_id, media_id, 'ABC-123-CD1.mp4')['ok']
        assert db.get(MediaItem, media_id).subtitle_flag is None


def test_stability_requires_time_and_detects_same_size_rewrites(workspace):
    _, factory, lib_id, root, _, _ = workspace
    path = root / 'ABP-001.mp4'
    path.write_bytes(b'a')
    now = utcnow()
    with factory() as db:
        lib = db.get(Library, lib_id)
        lib.file_settle_seconds = 60
        assert ready.check_file(db, lib, path, now=now).state == 'waiting'
        db.commit()
        assert ready.check_file(db, lib, path, now=now + timedelta(seconds=59)).state == 'waiting'
        assert ready.check_file(db, lib, path, now=now + timedelta(seconds=60)).state == 'ready'
        db.commit()
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        assert ready.check_file(db, lib, path, now=now + timedelta(seconds=70)).state == 'waiting'
        db.commit()
        assert ready.check_file(db, lib, path, now=now + timedelta(seconds=129)).state == 'waiting'
        assert ready.check_file(db, lib, path, now=now + timedelta(seconds=131)).state == 'ready'


def test_control_file_and_zero_size_wait_even_with_completion_signal(workspace):
    _, factory, lib_id, root, _, _ = workspace
    path = root / 'ABP-001.mp4'
    path.write_bytes(b'partial')
    marker = path.with_name(path.name + '.aria2')
    marker.write_bytes(b'control')
    with factory() as db:
        lib = db.get(Library, lib_id)
        assert ready.check_file(db, lib, path, confirmed=True).state == 'waiting'
        db.commit()
        marker.unlink()
        path.write_bytes(b'')
        assert ready.check_file(db, lib, path, confirmed=True).state == 'waiting'


def test_normal_ts_and_small_strm_are_supported(workspace):
    _, factory, lib_id, root, _, _ = workspace
    ts, strm = root / 'ABP-001.ts', root / 'ABP-002.strm'
    ts.write_bytes(b'fixture')
    strm.write_text('https://example.com/v', encoding='utf-8')
    with factory() as db:
        lib = db.get(Library, lib_id)
        assert ready.check_file(db, lib, ts).state == 'ready'
        assert ready.check_file(db, lib, strm).state == 'ready'
        strm.write_text('# download pending', encoding='utf-8')
        assert ready.check_file(db, lib, strm).state == 'waiting'


def test_waiting_does_not_block_queue_and_completion_can_release_it(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    api.patch(f'/api/libraries/{lib_id}', json={'file_settle_seconds': 60, 'auto_scan_enabled': False}).raise_for_status()
    path = root / 'ABP-001.mp4'
    path.write_bytes(b'fixture')
    task = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert task['status'] == 'done' and task['waiting'] == 1 and not calls
    assert api.get(f'/api/libraries/{lib_id}/waiting').json()['total'] == 1
    completed = api.post(f'/api/libraries/{lib_id}/download-complete', json={'paths': ['ABP-001.mp4', 'ABP-001.mp4']})
    assert completed.status_code == 202, completed.text
    assert run(workspace, completed.json())['scraped'] == 1
    assert api.get(f'/api/libraries/{lib_id}/waiting').json()['total'] == 0


def test_existing_suspects_are_preserved_and_preview_is_read_only(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    media_id = add_media(workspace, 'ABP-001.part')
    before = (root / 'ABP-001.part.mp4').read_bytes()
    run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    with factory() as db:
        assert db.get(MediaItem, media_id) is not None
        observations = db.query(FileObservation).count()
    preview = api.get(f'/api/libraries/{lib_id}/cleanup-preview').json()
    assert preview['read_only'] and [row['id'] for row in preview['items']] == [media_id]
    assert '临时' in preview['items'][0]['reason']
    with factory() as db:
        assert db.query(FileObservation).count() == observations and db.get(MediaItem, media_id)
    assert (root / 'ABP-001.part.mp4').read_bytes() == before and not calls


def test_source_filename_replaces_legacy_lock_and_parent_fallback(workspace):
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    directory = root / 'PARENT-001'
    directory.mkdir()
    path = directory / 'FC2-PPV-1066192.mp4'
    path.write_bytes(b'fixture')
    with factory() as db:
        media = MediaItem(library_id=lib_id, path=str(path), filename=path.name,
            number='FC2-1066192', number_locked=True, source_type='local',
            title='Existing metadata', scraped_at=utcnow(), recognition_version='names-v2:2')
        db.add(media)
        db.commit()
        media_id = media.id
    run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    data = api.get(f'/api/media/{media_id}').json()
    assert data['number'] == 'FC2-PPV-1066192' and data['title'] == 'Existing metadata'
    assert data['scraped_at'] and 'number_locked' not in data
    with factory() as db:
        assert scanner.rename_media_item(db, lib_id, media_id, 'new_name.mp4')['ok']
        assert db.get(MediaItem, media_id).number == 'new_name'


def test_unchanged_files_skip_index_writes_and_parser_calls(workspace, monkeypatch):
    from app.services import task_runner
    api, factory, lib_id, _, _, settings = workspace
    settings.auto_scrape = False
    media_id = add_media(workspace)
    run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    with factory() as db:
        timestamp = db.get(MediaItem, media_id).updated_at
    def unexpected(*args, **kwargs):
        raise AssertionError('unchanged file should not be ingested')
    monkeypatch.setattr(task_runner, '_ingest_file', unexpected)
    task = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert task['failed'] == 0 and task['total'] == 1 and task['created'] == 0 and task['scanned'] == 1
    with factory() as db:
        assert db.get(MediaItem, media_id).updated_at == timestamp


def test_pending_existing_file_keeps_its_index(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    media_id = add_media(workspace)
    api.patch(f'/api/libraries/{lib_id}', json={'file_settle_seconds': 60}).raise_for_status()
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['waiting'] == 1 and done['removed'] == 0 and not calls
    with factory() as db:
        assert db.get(MediaItem, media_id) is not None


def test_legacy_poll_settings_cannot_trigger_directory_reads(workspace, monkeypatch):
    api, factory, lib_id, root, _, _ = workspace
    with factory() as db:
        lib = db.get(Library, lib_id)
        lib.scan_mode, lib.scan_interval_seconds = 'poll', 30
        db.commit()
    (root / 'ABP-001.mp4').write_bytes(b'fixture')
    manager = auto_scan.AutoScanner(factory)
    monkeypatch.setattr(os, 'scandir', lambda *args, **kwargs: pytest.fail('Idle monitoring must not enumerate directories'))
    manager.tick(0)
    manager.tick(30)
    manager.tick(86400)
    manager.tick(172800)
    with factory() as db:
        assert db.query(BackgroundJob).count() == 0
    status = manager.status()
    assert status['observer_type'] == 'native' and status['libraries'][0]['mode'] == 'native'
    assert 'poll_interval_sec' not in status


def test_manual_mode_does_not_walk_or_auto_recheck(workspace, monkeypatch):
    api, factory, lib_id, _, _, _ = workspace
    api.patch(f'/api/libraries/{lib_id}', json={'auto_scan_enabled': False}).raise_for_status()
    manager = auto_scan.AutoScanner(factory)
    monkeypatch.setattr(auto_scan, 'Observer', lambda: pytest.fail('Manual mode must not start a monitor'))
    manager.tick(0); manager.tick(86400)
    assert not manager.states
    with factory() as db:
        assert db.query(BackgroundJob).count() == 0


def test_native_events_ignore_directory_noise_and_coalesce_paths(workspace):
    _, factory, lib_id, root, _, _ = workspace
    manager = auto_scan.AutoScanner(factory)
    handler = auto_scan.Handler(manager, lib_id)
    handler.on_any_event(DirModifiedEvent(str(root)))
    assert not manager.pending
    handler.on_any_event(FileCreatedEvent(str(root / 'ABP-001.mp4')))
    assert manager.pending[lib_id] == {str(root / 'ABP-001.mp4')}
    assert auto_scan.coalesce_paths({str(root), str(root / 'ABP-001.mp4'), str(root / 'child')}) == [str(root)]


def test_due_readiness_recheck_is_targeted(workspace):
    _, factory, lib_id, root, _, _ = workspace
    path = root / 'ABP-001.mp4'
    path.write_bytes(b'fixture')
    with factory() as db:
        db.add(FileObservation(library_id=lib_id, path=str(path), state='waiting', reason='fixture', next_check_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    manager = auto_scan.AutoScanner(factory)
    manager.tick(0)
    with factory() as db:
        task = db.query(BackgroundJob).one()
        assert json.loads(task.params_json)['inputs'] == {'paths': [str(path)]}


def test_recognition_and_manual_lock_endpoints_are_removed(workspace):
    api, factory, lib_id, _, _, _ = workspace
    media_id = add_media(workspace)
    assert api.get(f'/api/media/{media_id}/recognition').status_code == 404
    assert api.patch(f'/api/media/{media_id}/number', json={'number': 'changed', 'locked': True}).status_code == 404
    assert api.post(f'/api/libraries/{lib_id}/recognize', json={'filename': 'movie.mp4'}).status_code == 404
    with factory() as db:
        assert db.get(MediaItem, media_id).number == 'ABP-001'


def test_legacy_identification_upgrade_preserves_metadata(workspace):
    api, factory, lib_id, _, _, settings = workspace
    settings.auto_scrape = False
    media_id = add_media(workspace, scraped=True)
    with factory() as db:
        item = db.get(MediaItem, media_id)
        item.title, item.number = 'Previously scraped title', 'WRONG-001'
        db.commit()
    run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    data = api.get(f'/api/media/{media_id}').json()
    assert data['number'] == 'ABP-001' and data['scraped_at']
    assert data['title'] == 'Previously scraped title'


def test_queued_scrape_rechecks_file_readiness(workspace):
    api, _, lib_id, root, calls, _ = workspace
    add_media(workspace)
    task = api.post(f'/api/libraries/{lib_id}/rescrape-pending').json()
    (root / 'ABP-001.mp4.aria2').write_bytes(b'control')
    done = run(workspace, task)
    assert done['waiting'] == 1 and done['scraped'] == 0 and not calls


def test_disappeared_waiting_file_stops_automatic_rechecks(workspace):
    api, factory, lib_id, root, _, _ = workspace
    api.patch(f'/api/libraries/{lib_id}', json={'file_settle_seconds': 60}).raise_for_status()
    path = root / 'ABP-001.mp4'
    path.write_bytes(b'fixture')
    run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    path.unlink()
    with factory() as db:
        queued = auto_scan.enqueue(db, 'scan', db.get(Library, lib_id), inputs={'paths': [str(path)]})
        job_id = queued.job_id
    run(workspace, {'job_id': job_id})
    with factory() as db:
        observation = db.query(FileObservation).one()
        assert observation.state == 'missing' and observation.next_check_at is None
    assert api.get(f'/api/libraries/{lib_id}/waiting').json()['total'] == 0


def test_native_monitor_failure_is_reported_without_polling_or_daily_scan(workspace, monkeypatch):
    api, factory, lib_id, _, _, _ = workspace
    class UnavailableObserver:
        def schedule(self, *args, **kwargs):
            raise OSError('Unsupported filesystem')
        def stop(self):
            pass
        def is_alive(self):
            return False
    monkeypatch.setattr(auto_scan, 'Observer', UnavailableObserver)
    manager = auto_scan.AutoScanner(factory)
    monkeypatch.setattr(os, 'scandir', lambda *args, **kwargs: pytest.fail('Monitoring failures must not trigger directory reads'))
    manager.tick(0)
    assert manager.status()['libraries'][0]['mode'] == 'unavailable'
    assert '不可用' in manager.status()['libraries'][0]['error']
    from app.api import libraries as library_api
    monkeypatch.setattr(library_api, 'watcher_status', manager.status)
    exposed = api.get('/api/libraries').json()[0]
    assert exposed['watch_mode'] == 'unavailable' and '不可用' in exposed['watch_error']
    with factory() as db:
        lib = db.get(Library, lib_id)
        assert lib.next_full_scan_at is None
        lib.next_full_scan_at = utcnow() - timedelta(seconds=1)
        db.commit()
    manager.tick(86400)
    manager.tick(172800)
    with factory() as db:
        assert db.query(BackgroundJob).count() == 0


def test_event_mode_only_enqueues_changed_paths_and_retries_watch_setup_on_user_reload(workspace, monkeypatch):
    api, factory, lib_id, root, _, _ = workspace
    class NativeObserver:
        alive = False
        starts = 0
        def schedule(self, handler, path, recursive):
            self.handler = handler
        def start(self):
            self.alive = True
            self.starts += 1
        def stop(self):
            self.alive = False
        def is_alive(self):
            return self.alive
        def join(self, **kwargs):
            pass
    observer = NativeObserver()
    monkeypatch.setattr(auto_scan, 'Observer', lambda: observer)
    manager = auto_scan.AutoScanner(factory)
    monkeypatch.setattr(os, 'scandir', lambda *args, **kwargs: pytest.fail('Event mode must not walk the media directory'))
    try:
        manager.tick(0)
        manager.tick(86400)
        with factory() as db:
            assert db.query(BackgroundJob).count() == 0
        path = root / 'new_movie.mp4'
        manager.schedule(lib_id, [str(path)], immediate=True, now=86401)
        manager.tick(86401)
        with factory() as db:
            task = db.query(BackgroundJob).one()
            assert json.loads(task.params_json)['inputs'] == {'paths': [str(path)]}
        observer.alive = False
        manager.tick(86402)
        assert manager.status()['libraries'][0]['mode'] == 'unavailable'
        manager.tick(172800)
        assert observer.starts == 1
        manager.reload()
        manager.tick(172801)
        assert observer.starts == 2 and manager.status()['libraries'][0]['mode'] == 'native'
    finally:
        manager._unwatch(lib_id)


def test_legacy_daily_scan_timestamp_never_enqueues_a_full_scan(workspace, monkeypatch):
    _, factory, lib_id, _, _, _ = workspace
    with factory() as db:
        db.get(Library, lib_id).next_full_scan_at = utcnow() - timedelta(days=1)
        db.commit()
    manager = auto_scan.AutoScanner(factory)
    monkeypatch.setattr(os, 'scandir', lambda *args, **kwargs: pytest.fail('Legacy schedules must not walk the media directory'))
    manager.tick(0)
    manager.tick(86400)
    manager.tick(172800)
    with factory() as db:
        assert db.query(BackgroundJob).count() == 0


def test_library_api_has_no_polling_or_periodic_scan_controls(workspace):
    api, factory, lib_id, root, _, _ = workspace
    response = api.post('/api/libraries', json={'name': 'Event library', 'path': str(root), 'type': 'local'})
    assert response.status_code == 200
    obsolete = {'scan_mode', 'scan_interval_seconds', 'effective_poll_interval_seconds', 'full_scan_interval_seconds'}
    assert not obsolete.intersection(response.json())
    # Older clients may send retired settings, but they cannot reactivate polling.
    updated = api.patch(f'/api/libraries/{lib_id}', json={'scan_mode': 'poll', 'scan_interval_seconds': 30})
    assert updated.status_code == 200 and not obsolete.intersection(updated.json())
    with factory() as db:
        lib = db.get(Library, lib_id)
        assert lib.scan_mode == 'native' and lib.scan_interval_seconds is None


def test_event_mode_rejects_watchdog_implicit_polling_backend(workspace, monkeypatch):
    api, factory, lib_id, _, _, _ = workspace
    observer = auto_scan.PollingObserver()
    monkeypatch.setattr(observer, 'schedule', lambda *args, **kwargs: pytest.fail('Implicit polling must not be scheduled'))
    monkeypatch.setattr(auto_scan, 'Observer', lambda: observer)
    manager = auto_scan.AutoScanner(factory)
    manager.tick(0)
    assert manager.status()['libraries'][0]['mode'] == 'unavailable'
    assert manager.states[lib_id].observer is None


def test_cleanup_preview_pages_without_mutating_rows_or_files(workspace):
    api, factory, lib_id, root, _, _ = workspace
    with factory() as db:
        for idx in range(55):
            path = root / f'ABP-{idx:03d}.part.mp4'
            path.write_bytes(b'partial')
            db.add(MediaItem(library_id=lib_id, path=str(path), filename=path.name))
        db.commit()
    first = api.get(f'/api/libraries/{lib_id}/cleanup-preview').json()
    second = api.get(f"/api/libraries/{lib_id}/cleanup-preview?cursor={first['next_cursor']}").json()
    assert len(first['items']) == 50 and len(second['items']) == 5
    assert second['next_cursor'] is None
    assert len({row['id'] for row in first['items'] + second['items']}) == 55
    with factory() as db:
        assert db.query(MediaItem).count() == 55 and db.query(FileObservation).count() == 0
    assert len(list(root.glob('*.mp4'))) == 55


def test_event_for_same_path_during_enqueue_is_not_lost(workspace, monkeypatch):
    _, factory, lib_id, root, _, _ = workspace
    path = str(root / 'ABP-001.mp4')
    manager = auto_scan.AutoScanner(factory)
    manager.tick(0)
    manager.schedule(lib_id, [path], immediate=True, now=1)
    original = auto_scan.enqueue
    def enqueue_with_new_event(*args, **kwargs):
        queued = original(*args, **kwargs)
        manager.schedule(lib_id, [path], immediate=True, now=2)
        return queued
    monkeypatch.setattr(auto_scan, 'enqueue', enqueue_with_new_event)
    manager.tick(1)
    assert manager.pending[lib_id] == {path} and manager.deadlines[lib_id] == 2


def test_large_incremental_batch_does_not_prune_unrelated_media(workspace):
    from app.services import task_store
    api, factory, lib_id, root, _, settings = workspace
    settings.auto_scrape = False
    changed = add_media(workspace)
    unrelated_missing = add_media(workspace, 'ABP-002', exists=False)
    paths = [str(root / 'ABP-001.mp4')] + [str(root / f'unknown-{idx}.mp4') for idx in range(1100)]
    with factory() as db:
        queued = task_store.enqueue(db, 'scan', db.get(Library, lib_id), inputs={'paths': paths})
        job_id = queued.job_id
    done = run(workspace, {'job_id': job_id})
    assert done['failed'] == 0 and done['scanned'] == 1 and done['removed'] == 0
    with factory() as db:
        assert db.get(MediaItem, changed).recognition_version
        assert db.get(MediaItem, unrelated_missing) is not None


def test_v130_schema_migration_preserves_media_jobs_and_manual_policy(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from app import db as database
    engine = create_engine(f'sqlite:///{tmp_path.as_posix()}/legacy.db')
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        lib = Library(name='Legacy', path=str(tmp_path), auto_scan_enabled=False, scan_interval_seconds=3)
        db.add(lib)
        db.flush()
        db.add(MediaItem(library_id=lib.id, path=str(tmp_path / 'ABP-001.mp4'), filename='ABP-001.mp4', number='ABP-001', title='Saved metadata'))
        db.add(BackgroundJob(job_id='legacy-job', kind='scan', library_id=lib.id, status='interrupted', scanned=3))
        db.commit()
    # Remove exactly the columns and table introduced after v1.3.0.
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE file_observations'))
        for table, columns in {
            'libraries': ('sort_order', 'scan_mode', 'ts_policy', 'full_scan_interval_seconds', 'next_full_scan_at', 'file_settle_seconds', 'parent_fallback_depth', 'ignore_dirs'),
            'media_items': ('number_locked', 'number_source', 'recognition_notes', 'recognition_version', 'file_mtime_ns'),
            'background_jobs': ('waiting', 'scan_manifest_json'),
        }.items():
            for column in columns:
                connection.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    database.init_db()
    with factory() as db:
        lib = db.query(Library).one()
        assert lib.auto_scan_enabled and lib.scan_mode == 'native' and lib.scan_interval_seconds is None and lib.sort_order == 0
        assert db.query(MediaItem).one().title == 'Saved metadata'
        job = db.get(BackgroundJob, 'legacy-job')
        assert job.status == 'interrupted' and job.scanned == 3 and job.waiting == 0
        lib.auto_scan_enabled = False
        db.commit()
    database.init_db()
    with factory() as db:
        assert not db.query(Library).one().auto_scan_enabled
        assert db.query(FileObservation).count() == 0
    engine.dispose()


def test_polling_upgrade_retires_schedules_and_preserves_disabled_libraries(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import db as database

    engine = create_engine(f'sqlite:///{tmp_path.as_posix()}/polling-upgrade.db')
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for enabled in (True, False):
            db.add(Library(name=str(enabled), path=str(tmp_path), auto_scan_enabled=enabled,
                scan_mode='poll', scan_interval_seconds=30, scan_interval_hours=1,
                next_full_scan_at=utcnow() - timedelta(days=1)))
        db.commit()
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    database.init_db()
    database.init_db()
    with factory() as db:
        libraries = db.query(Library).order_by(Library.id).all()
        assert [lib.auto_scan_enabled for lib in libraries] == [True, False]
        assert all(lib.scan_mode == 'native' and lib.scan_interval_seconds is None
            and lib.scan_interval_hours is None and lib.next_full_scan_at is None for lib in libraries)
    engine.dispose()
