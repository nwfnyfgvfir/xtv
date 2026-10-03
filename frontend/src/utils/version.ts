/** App version injected at build time (git tag in CI, `git describe` in dev). */
export const APP_VERSION: string =
  typeof __APP_VERSION__ === 'string' && __APP_VERSION__ ? __APP_VERSION__ : 'dev'
