import type { ScrapeSource } from '@/api/types'

export const scrapeSources = {
  metatube: {
    label: 'MetaTube',
    priority: 'metatube_provider_priority',
    credentialSet: 'metatube_token_set',
  },
  stash: {
    label: 'Stash',
    priority: 'stash_scraper_priority',
    credentialSet: 'stash_api_key_set',
  },
  stashscrapers: {
    label: '拾录 / StashScrapers',
    priority: 'stashscrapers_scraper_priority',
    credentialSet: 'stashscrapers_token_set',
  },
} as const

export function normalizeScrapeSource(value: string | undefined): ScrapeSource {
  return value === 'stash' || value === 'stashscrapers' ? value : 'metatube'
}
