/** First alphanumeric char for poster placeholder. */
export function monogramChar(input: {
  number?: string | null
  title?: string | null
  filename?: string | null
}): string {
  const sources = [input.number, input.title, input.filename]
  for (const s of sources) {
    if (!s) continue
    const m = s.trim().match(/[A-Za-z0-9一-鿿]/)
    if (m) return m[0].toUpperCase()
  }
  return '?'
}

/** Stable hue from string for monogram background variety. */
export function monogramHue(seed: string): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0
  }
  // Bias toward warm amber/cinema tones (20–55) with some cool accents
  const bands = [28, 36, 42, 48, 210, 265]
  return bands[h % bands.length]
}

export function monogramStyle(seed: string): Record<string, string> {
  const hue = monogramHue(seed || '?')
  return {
    '--mono-hue': String(hue),
  }
}
