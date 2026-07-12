import { ref, watch } from 'vue'

export type ThemeMode = 'dark' | 'light'

const THEME_KEY = 'tv-theme'
const theme = ref<ThemeMode>('dark')
let bound = false

function apply(mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', mode)
  document.documentElement.style.colorScheme = mode
}

export function useTheme() {
  if (!bound) {
    const saved = (localStorage.getItem(THEME_KEY) as ThemeMode | null) || 'dark'
    theme.value = saved === 'light' ? 'light' : 'dark'
    apply(theme.value)
    watch(theme, (v) => {
      localStorage.setItem(THEME_KEY, v)
      apply(v)
    })
    bound = true
  }

  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  function setTheme(mode: ThemeMode) {
    theme.value = mode
  }

  return { theme, toggle, setTheme }
}
