from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from datetime import timedelta

import httpx
from sqlalchemy import event, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, object_session

from app.db import SessionLocal
from app.models import Actor, ImageBackup, MediaItem, utcnow
from app.services.images import (
    MAX_IMAGE_BYTES, fetch_image, image_content_type, original_image_url, rewrite_image_url,
    scraped_image_path, site_image_path, site_image_url, store_image_bytes, validate_proxy_url,
)

logger = logging.getLogger(__name__)


def image_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def queue_images(db, urls, *, provider=None, provider_id=None):
    rows = {}
    for value in urls:
        if not value:
            continue
        url = original_image_url(value)
        if url and url.startswith(('http://', 'https://')):
            key = image_key(url)
            rows[key] = dict(url_hash=key, url=url, provider=provider, provider_id=provider_id,
                status='pending', attempts=0, retry_at=utcnow(), updated_at=utcnow())
    if rows:
        db.execute(insert(ImageBackup).values(list(rows.values())).on_conflict_do_nothing(index_elements=['url_hash']))
        db.info['queued_image_backups'] = True


@event.listens_for(Session, 'after_commit')
def notify_committed_backups(db):
    if db.info.pop('queued_image_backups', False):
        worker.notify()


@event.listens_for(Session, 'after_rollback')
def discard_rolled_back_notification(db):
    db.info.pop('queued_image_backups', None)


def local_image_urls(item, fields):
    """Resolve all available backups for one ORM item in a single indexed query."""
    values = {field: original_image_url(getattr(item, field, None)) for field in fields}
    db = object_session(item)
    keys = {image_key(url) for url in values.values() if url and url.startswith(('http://', 'https://'))}
    backups = {}
    if db is not None and keys:
        backups = {row.url_hash: '/api/images/scraped/' + row.local_name for row in
            db.query(ImageBackup).filter(ImageBackup.url_hash.in_(keys), ImageBackup.status == 'done', ImageBackup.local_name.isnot(None))}
    return {field: site_image_url(url if url and url.startswith('/api/images/scraped/') else backups.get(image_key(url)) if url else None)
        for field, url in values.items()}


def read_saved_image(db: Session, url: str) -> tuple[str, bytes] | None:
    """Let the site proxy reuse the same permanent backup as the browser fallback."""
    try:
        row = db.get(ImageBackup, image_key(url))
        if not row or row.status != 'done' or not row.local_name:
            return None
        path = scraped_image_path(row.local_name)
        if path is None:
            return None
        with path.open('rb') as file:
            body = file.read(MAX_IMAGE_BYTES + 1)
        content_type = image_content_type(body)
        if content_type and len(body) <= MAX_IMAGE_BYTES:
            return content_type, body
    except OSError:
        pass
    except SQLAlchemyError:
        db.rollback()
        logger.warning('Could not read the image backup record')
    return None


def save_queued_image(db: Session, url: str, body: bytes) -> None:
    """Persist proxy responses for known library artwork, never arbitrary proxy URLs."""
    try:
        row = db.get(ImageBackup, image_key(url))
        if row is None:
            return
        local = store_image_bytes(body)
        if not local:
            return
        row.status, row.local_name = 'done', local.rsplit('/', 1)[-1]
        row.updated_at = utcnow()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning('Could not record the image backup')


def backup_status(db):
    counts = dict(db.query(ImageBackup.status, func.count(ImageBackup.url_hash)).group_by(ImageBackup.status).all())
    return {'saved': counts.get('done', 0), 'pending': counts.get('pending', 0), 'running': counts.get('running', 0)}


async def download_image(url, *, provider=None, provider_id=None):
    original = validate_proxy_url(url)
    target = rewrite_image_url(original, provider=provider, provider_id=provider_id)
    if not target:
        raise ValueError('Image proxy configuration is invalid')
    if target.startswith('/') or site_image_path(target) is not None:
        target = original
    _, body = await fetch_image(target, referer_url=original)
    local = store_image_bytes(body)
    if not local:
        raise ValueError('Response is not a supported raster image')
    return local.rsplit('/', 1)[-1]


class ImageBackupWorker:
    def __init__(self, factory=SessionLocal, can_run=None):
        self.factory, self.can_run = factory, can_run
        self.thread = None
        self.loop = None
        self.event = None
        self.tasks = []
        self.stopped = threading.Event()

    def notify(self):
        if self.loop and self.event and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.event.set)
            except RuntimeError:
                pass  # The persisted queue remains available after shutdown.

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, name='image-backups', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.loop and not self.loop.is_closed():
            for task in self.tasks:
                try:
                    self.loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    break
        if self.thread:
            self.thread.join(timeout=5)

    def backfill(self):
        with self.factory() as db:
            db.query(ImageBackup).filter_by(status='running').update({'status': 'pending'})
            db.commit()
        for model, fields in ((MediaItem, ('cover_url', 'thumb_url', 'backdrop_url')), (Actor, ('image_url',))):
            cursor = 0
            while not self.stopped.is_set():
                with self.factory() as db:
                    rows = db.query(model).filter(model.id > cursor).order_by(model.id).limit(200).all()
                    if not rows:
                        break
                    for item in rows:
                        queue_images(db, [getattr(item, field) for field in fields],
                            provider=item.provider if model is MediaItem else None,
                            provider_id=item.provider_id if model is MediaItem else None)
                    cursor = rows[-1].id
                    db.commit()

    def claim(self):
        with self.factory() as db:
            row = db.query(ImageBackup).filter(ImageBackup.status == 'pending', ImageBackup.retry_at <= utcnow()).order_by(ImageBackup.retry_at).first()
            if row is None:
                return None
            result = (row.url_hash, row.url, row.provider, row.provider_id)
            row.status = 'running'
            db.commit()
            return result

    async def process(self, entry):
        key, url, provider, provider_id = entry
        local = None
        try:
            local = await download_image(url, provider=provider, provider_id=provider_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                reason = f'HTTP {exc.response.status_code}'
            elif isinstance(exc, ValueError) and str(exc) in {
                'Image exceeds the size limit', 'Response is not a supported raster image', 'Response is not a supported image',
                'Image proxy configuration is invalid', 'Too many image redirects',
                'blocked ip', 'blocked host',
            }:
                reason = str(exc)
            logger.warning('Image backup failed (%s); retry scheduled for image=%s', reason, key)
        finally:
            with self.factory() as db:
                row = db.get(ImageBackup, key)
                # A simultaneous site-proxy request may already have saved a valid copy.
                if row and (local or row.status != 'done'):
                    row.status = 'done' if local else 'pending'
                    if local:
                        row.local_name = local
                    elif not self.stopped.is_set():
                        row.attempts += 1
                        row.retry_at = utcnow() + timedelta(seconds=min(60 * 2 ** min(row.attempts - 1, 6), 3600))
                    row.updated_at = utcnow()
                    db.commit()

    async def consume(self):
        while not self.stopped.is_set():
            entry = self.claim()
            if entry:
                await self.process(entry)
            else:
                self.event.clear()
                try:
                    await asyncio.wait_for(self.event.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.event = asyncio.Event()
        self.tasks = [asyncio.create_task(self.consume()) for _ in range(2)]
        await asyncio.gather(*self.tasks)

    def _run(self):
        from app.services.task_runner import runner
        can_run = self.can_run or runner.is_owner.is_set
        while not self.stopped.is_set() and not can_run():
            self.stopped.wait(1)
        if self.stopped.is_set():
            return
        try:
            self.backfill()
            asyncio.run(self.serve())
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception('Image backup worker stopped unexpectedly')


worker = ImageBackupWorker()
