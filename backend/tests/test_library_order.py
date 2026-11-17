from app.models import BackgroundJob, Library, MediaItem
from test_persistent_tasks import workspace, add_media


def test_library_order_persists_without_changing_selection_data_or_jobs(workspace):
    api, factory, first, root, _, _ = workspace
    media_id = add_media(workspace, scraped=True)
    second = api.post('/api/libraries', json={'name': 'Second', 'path': str(root)}).json()['id']
    third = api.post('/api/libraries', json={'name': 'Third', 'path': str(root)}).json()['id']
    with factory() as db:
        db.get(Library, second).auto_scan_enabled = False
        db.add(BackgroundJob(job_id='active-order-test', kind='scan', library_id=first, status='running'))
        db.commit()
    ordered = [third, first, second]
    response = api.put('/api/libraries/order', json={'ids': ordered})
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == ordered
    assert [row['sort_order'] for row in response.json()] == [0, 1, 2]
    assert [row['id'] for row in api.get('/api/libraries').json()] == ordered
    with factory() as db:
        assert db.get(MediaItem, media_id).library_id == first
        assert db.get(MediaItem, media_id).scraped_at is not None
        assert db.get(BackgroundJob, 'active-order-test').status == 'running'
        assert db.get(BackgroundJob, 'active-order-test').library_id == first
        assert not db.get(Library, second).auto_scan_enabled


def test_invalid_or_stale_library_order_does_not_partially_update(workspace):
    api, factory, first, root, _, _ = workspace
    second = api.post('/api/libraries', json={'name': 'Second', 'path': str(root)}).json()['id']
    for ids, status in (([second, second], 422), ([second], 409), ([second, first, 99999], 409)):
        assert api.put('/api/libraries/order', json={'ids': ids}).status_code == status
        assert [row['id'] for row in api.get('/api/libraries').json()] == [first, second]


def test_new_library_is_appended_after_saved_order(workspace):
    api, _, first, root, _, _ = workspace
    second = api.post('/api/libraries', json={'name': 'Second', 'path': str(root)}).json()['id']
    api.put('/api/libraries/order', json={'ids': [second, first]}).raise_for_status()
    third = api.post('/api/libraries', json={'name': 'Third', 'path': str(root)}).json()['id']
    assert [row['id'] for row in api.get('/api/libraries').json()] == [second, first, third]
