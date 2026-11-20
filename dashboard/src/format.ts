import type { Num } from './types'

export const fmt = (v: Num | undefined, d = 2): string => (v == null ? '—' : v.toFixed(d))
export const fmtInt = (v: number): string => v.toLocaleString('es-MX')
export const ordinal = (n: number): string => ['', '1st', '2nd', '3rd', '4th'][n] ?? `${n}`
