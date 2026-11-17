"""One response policy for artwork on every media and performer page."""
from __future__ import annotations

from app.services.image_backups import local_image_urls
from app.services.images import rewrite_image_url

MEDIA_IMAGE_FIELDS = ('cover_url', 'thumb_url', 'backdrop_url')


def media_image_urls(item) -> dict[str, str | None]:
    backups = local_image_urls(item, MEDIA_IMAGE_FIELDS)
    urls = {}
    for field in MEDIA_IMAGE_FIELDS:
        urls[field] = rewrite_image_url(getattr(item, field, None),
            provider=item.provider, provider_id=item.provider_id)
        urls[field.removesuffix('_url') + '_local_url'] = backups[field]
    return urls


def attach_media_images(data, item) -> None:
    for field, url in media_image_urls(item).items():
        setattr(data, field, url)


def actor_image_urls(actor) -> dict[str, str | None]:
    # MetaTube primary requires a movie ID, so portraits use the general URL route.
    return {'image_url': rewrite_image_url(actor.image_url),
        'image_local_url': local_image_urls(actor, ('image_url',))['image_url']}
