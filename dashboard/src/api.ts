import type { PlayData, Summary } from './types'

// Rutas relativas SIN diagonal inicial (la app se publica en una subruta).
async function getJson<T>(promise: Promise<Response>): Promise<T> {
  const r = await promise
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as T
}

export const fetchSummary = () => getJson<Summary>(fetch('api/summary'))

export const fetchPlay = (gameId: number, playId: number) =>
  getJson<PlayData>(fetch(`api/play/${gameId}/${playId}`))
