from pathlib import Path

import pytest

from app.models import Library, MediaItem, FileObservation, BackgroundJob
from app.services import auto_scan, task_runner, task_store
from app.services import file_readiness as ready
from test_persistent_tasks import workspace, run


@pytest.mark.parametrize('name', ['Temp', '.temp', '_tmp', 'downloads_temp', '临时目录', 'tmp-202611170102'])
def test_temporary_subdirectories_are_pruned_even_with_old_saved_rules(workspace, name):
    api, factory, lib_id, root, calls, _ = workspace
    temp = root / name
    temp.mkdir()
    (temp / '000001.ts').write_bytes(b'fragment')
    (root / 'ABP-001.ts').write_bytes(b'complete')
    # v1.4.0 users may have explicitly saved the old default list.
    api.patch(f'/api/libraries/{lib_id}', json={'ignore_dirs': '.incomplete,.cache'}).raise_for_status()
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['scanned'] == done['created'] == done['scraped'] == 1
    with factory() as db:
        assert db.query(MediaItem).one().filename == 'ABP-001.ts'
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['temporary', 'playlist', 'suspect'])
def test_two_thousand_fragments_do_not_get_per_file_stat_or_tasks(workspace, monkeypatch, kind):
    api, factory, lib_id, root, calls, _ = workspace
    folder = root / ('Temp' if kind == 'temporary' else 'SSIS-001')
    folder.mkdir()
    for index in range(2000):
        (folder / f'{index:06d}.ts').write_bytes(b'fragment')
    if kind == 'playlist':
        (folder / 'index.m3u8').write_text('#EXTM3U\n' + ''.join(f'#EXTINF:6,\n{index:06d}.ts\n' for index in range(2000)) + '#EXT-X-ENDLIST\n', encoding='utf-8')
    complete = folder / 'ABP-002.ts' if kind != 'temporary' else root / 'ABP-002.ts'
    complete.write_bytes(b'complete transport stream')
    stat = Path.stat
    def no_fragment_stat(path, *args, **kwargs):
        if path.parent == folder and path.suffix == '.ts' and path.stem.isdecimal():
            raise AssertionError('Download fragments must not be statted individually')
        return stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', no_fragment_stat)
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['failed'] == 0 and done['scanned'] == done['created'] == done['scraped'] == 1, done
    with factory() as db:
        assert db.query(MediaItem).count() == 1
        assert db.query(FileObservation).count() == (2 if kind == 'suspect' else 1)
        assert len(auto_scan.AutoScanner(factory).snapshot(db.get(Library, lib_id))) == 1
    waiting = api.get(f'/api/libraries/{lib_id}/waiting').json()
    assert waiting['total'] == (1 if kind == 'suspect' else 0)
    if kind == 'suspect':
        assert '2000' in waiting['items'][0]['reason']
    assert len(calls) == 1


def test_numbered_complete_recordings_can_be_confirmed_without_allowing_playlist_segments(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    for index in range(10):
        (root / f'{index:06d}.ts').write_bytes(b'full recording')
    first = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert first['created'] == 0 and first['waiting'] == 1
    api.patch(f'/api/libraries/{lib_id}', json={'ts_policy': 'complete'}).raise_for_status()
    (root / 'index.m3u8').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\n000000.ts\n#EXTINF:6,\n000001.ts\n', encoding='utf-8')
    second = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert second['created'] == 8 and second['removed'] == 0
    with factory() as db:
        assert db.query(MediaItem).count() == 8
    assert len(list(root.glob('*.ts'))) == 10
    assert api.get(f'/api/libraries/{lib_id}/waiting').json()['total'] == 0


def test_legacy_fragment_record_is_only_previewed_and_never_removed_or_rescraped(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    folder = root / 'Temp'
    folder.mkdir()
    path = folder / '000001.ts'
    path.write_bytes(b'fragment')
    with factory() as db:
        media = MediaItem(library_id=lib_id, path=str(path), filename=path.name, number='ABP-001', number_locked=True)
        db.add(media)
        db.commit()
        media_id = media.id
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['removed'] == 0
    for url in (f'/api/libraries/{lib_id}/rescrape-pending', f'/api/media/{media_id}/rescrape-task'):
        result = run(workspace, api.post(url, json={}).json())
        assert result['scraped'] == 0 and result['skipped'] == 1
    preview = api.get(f'/api/libraries/{lib_id}/cleanup-preview').json()
    assert preview['read_only'] and preview['items'][0]['id'] == media_id
    assert '临时目录' in preview['items'][0]['reason']
    assert path.read_bytes() == b'fragment' and not calls
    with factory() as db:
        assert db.get(MediaItem, media_id) is not None


def test_queued_index_manifest_cannot_bypass_download_filter(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    folder = root / 'Temp'
    folder.mkdir()
    path = folder / '000001.ts'
    path.write_bytes(b'fragment')
    queued = api.post(f'/api/libraries/{lib_id}/scan').json()
    with factory() as db:
        job = db.get(BackgroundJob, queued['job_id'])
        job.manifest_ready = True
        task_store.add_item(db, job, 'index', 'index:' + str(path), path.name, path=str(path))
        db.commit()
    done = run(workspace, queued)
    assert done['created'] == done['scraped'] == 0 and not calls


def test_complete_ts_with_parent_code_is_kept(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    folder = root / 'SSIS-001'
    folder.mkdir()
    (folder / 'recording.ts').write_bytes(b'complete recording')
    done = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert done['created'] == done['scraped'] == 1
    with factory() as db:
        item = db.query(MediaItem).one()
        assert item.number == 'SSIS-001' and item.number_source == 'parent'


def test_ordinary_m3u8_playlist_does_not_turn_full_ts_movies_into_hls_segments(workspace):
    api, factory, lib_id, root, calls, _ = workspace
    for code in ('ABP-001', 'ABP-002'):
        (root / f'{code}.ts').write_bytes(b'complete movie')
    (root / 'movies.m3u8').write_text('#EXTM3U\n#EXTINF:6000,Movie one\nABP-001.ts\n#EXTINF:7000,Movie two\nABP-002.ts\n', encoding='utf-8')
    result = run(workspace, api.post(f'/api/libraries/{lib_id}/scan').json())
    assert result['created'] == result['scraped'] == 2 and len(calls) == 2


def test_native_fragment_burst_is_filtered_before_individual_path_stat(workspace, monkeypatch):
    api, factory, lib_id, root, calls, _ = workspace
    folder = root / 'SSIS-001'
    folder.mkdir()
    paths = []
    for index in range(2000):
        path = folder / f'{index:06d}.ts'
        path.write_bytes(b'fragment')
        paths.append(str(path))
    (root / 'ABP-002.mp4').write_bytes(b'unrelated full movie')
    stat = Path.stat
    def no_fragment_stat(path, *args, **kwargs):
        if path.suffix == '.ts':
            raise AssertionError('A native event burst must not stat fragment paths')
        return stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', no_fragment_stat)
    with factory() as db:
        task = task_store.enqueue(db, 'scan', db.get(Library, lib_id), inputs={'paths': paths})
        job_id = task.job_id
    result = run(workspace, {'job_id': job_id})
    assert result['scanned'] == result['created'] == 0 and result['waiting'] == 1 and not calls
    with factory() as db:
        assert db.query(MediaItem).count() == 0 and db.query(FileObservation).count() == 1
