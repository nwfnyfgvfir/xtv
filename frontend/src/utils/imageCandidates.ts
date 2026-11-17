import type { MediaListItem } from '@/api/types'

type MediaArtwork = Partial<Pick<MediaListItem,
  'cover_url' | 'cover_local_url' | 'thumb_url' | 'thumb_local_url' | 'backdrop_url' | 'backdrop_local_url'>>

export function mediaImageCandidates(item: MediaArtwork | null | undefined) {
  return [item?.cover_url, item?.cover_local_url, item?.thumb_url, item?.thumb_local_url,
    item?.backdrop_url, item?.backdrop_local_url]
}
