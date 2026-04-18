export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

function trimTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value
}

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path
  }

  const base = trimTrailingSlash(API_BASE_URL)

  if (!base) {
    return path
  }

  if (path.startsWith(`${base}/`) || path === base) {
    return path
  }

  return `${base}${path.startsWith("/") ? path : `/${path}`}`
}
