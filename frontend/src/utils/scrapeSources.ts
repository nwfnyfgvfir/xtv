import type { ScrapeSource } from '@/api/types'

export const scrapeSources = {
  metatube: {
    label: 'MetaTube',
    priority: 'metatube_provider_priority',
    provider: 'metatube_provider',
    fallback: 'metatube_fallback',
    credentialSet: 'metatube_token_set',
  },
  stash: {
    label: 'Stash',
    priority: 'stash_scraper_priority',
    provider: 'stash_scraper',
    fallback: 'stash_fallback',
    credentialSet: 'stash_api_key_set',
  },
  stashscrapers: {
    label: '拾录 / StashScrapers',
    priority: 'stashscrapers_scraper_priority',
    provider: 'stashscrapers_scraper',
    fallback: 'stashscrapers_fallback',
    credentialSet: 'stashscrapers_token_set',
  },
} as const

export function normalizeScrapeSource(value: string | undefined): ScrapeSource {
  return value === 'stash' || value === 'stashscrapers' ? value : 'metatube'
}
