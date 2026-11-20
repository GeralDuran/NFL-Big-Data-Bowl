import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchPlay } from '../api'
import { fmt, ordinal } from '../format'
import type { FilmItem, Num, PlayData, PlayerTrack } from '../types'

// Cancha 120 x 53.3 yardas a 10 px por yarda. El ataque avanza siempre hacia la derecha.
const S = 10
const FW = 120
const FH = 53.3
const CW = FW * S
const CH = Math.round(FH * S)
const PRESSURE_RADIUS = 2.5
const FPS = 10

const px = (x: number) => x * S
const py = (y: number) => (FH - y) * S

const OFFENSE = '#3b82f6'
const DEFENSE = '#ef4444'
const BALL = '#d9a441'
const EMERALD = '#34d399'
const RED = '#f87171'

function sample(arr: Num[], pos: number): number | null {
  const n = arr.length
  if (n === 0) return null
  const i0 = Math.max(0, Math.min(n - 1, Math.floor(pos)))
  const i1 = Math.min(n - 1, i0 + 1)
  const a = arr[i0]
  const b = arr[i1]
  if (a == null) return b
  if (b == null) return a
  return a + (b - a) * (pos - i0)
}

const role = (p: PlayerTrack) => (p.role ?? '').toLowerCase()

/** Cancha estática (zonas de anotación, líneas, números, hash marks) en un canvas aparte. */
function buildField(play: PlayData): HTMLCanvasElement {
  const cv = document.createElement('canvas')
  cv.width = CW
  cv.height = CH
  const ctx = cv.getContext('2d')
  if (!ctx) return cv

  ctx.fillStyle = '#0a3324'
  ctx.fillRect(0, 0, CW, CH)
  for (let yd = 10; yd < 110; yd += 10) {
    if (((yd / 10) | 0) % 2 === 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.025)'
      ctx.fillRect(px(yd), 0, px(10), CH)
    }
  }
  // Zonas de anotación
  ctx.fillStyle = '#06241a'
  ctx.fillRect(0, 0, px(10), CH)
  ctx.fillRect(px(110), 0, px(10), CH)
  ctx.fillStyle = 'rgba(255,255,255,0.28)'
  ctx.font = 'bold 30px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.save()
  ctx.translate(px(5), CH / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillText(play.possessionTeam, 0, 0)
  ctx.restore()
  ctx.save()
  ctx.translate(px(115), CH / 2)
  ctx.rotate(Math.PI / 2)
  ctx.fillText(play.defensiveTeam, 0, 0)
  ctx.restore()

  // Líneas cada 5 yardas (finas) y cada 10 (gruesas)
  for (let yd = 10; yd <= 110; yd += 5) {
    ctx.strokeStyle = yd % 10 === 0 ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.22)'
    ctx.lineWidth = yd % 10 === 0 ? 2 : 1
    ctx.beginPath()
    ctx.moveTo(px(yd), 0)
    ctx.lineTo(px(yd), CH)
    ctx.stroke()
  }
  ctx.strokeStyle = 'rgba(255,255,255,0.8)'
  ctx.lineWidth = 3
  for (const yd of [0, 120]) {
    ctx.beginPath()
    ctx.moveTo(px(yd), 0)
    ctx.lineTo(px(yd), CH)
    ctx.stroke()
  }
  ctx.strokeRect(0, 0, CW, CH)

  // Hash marks cada yarda
  ctx.strokeStyle = 'rgba(255,255,255,0.3)'
  ctx.lineWidth = 1
  for (let yd = 11; yd < 110; yd++) {
    for (const hy of [23.6, 29.7]) {
      ctx.beginPath()
      ctx.moveTo(px(yd), py(hy) - 4)
      ctx.lineTo(px(yd), py(hy) + 4)
      ctx.stroke()
    }
  }

  // Números de yarda (10-20-30-40-50-40-30-20-10)
  ctx.font = 'bold 26px system-ui, sans-serif'
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  for (let yd = 20; yd <= 100; yd += 10) {
    const label = String(Math.min(yd - 10, 110 - yd))
    ctx.fillText(label, px(yd), py(8))
    ctx.save()
    ctx.translate(px(yd), py(FH - 8))
    ctx.rotate(Math.PI)
    ctx.fillText(label, 0, 0)
    ctx.restore()
  }
  return cv
}

interface Live {
  rusherDist: number | null
  maxSep: number | null
}

function draw(ctx: CanvasRenderingContext2D, field: HTMLCanvasElement, play: PlayData, pos: number, now: number): Live {
  ctx.clearRect(0, 0, CW, CH)
  ctx.drawImage(field, 0, 0)

  // Línea de golpeo
  if (play.los_x != null) {
    ctx.strokeStyle = '#facc15'
    ctx.lineWidth = 2.5
    ctx.beginPath()
    ctx.moveTo(px(play.los_x), 0)
    ctx.lineTo(px(play.los_x), CH)
    ctx.stroke()
  }

  type Pt = { p: PlayerTrack; x: number; y: number; o: number | null }
  const pts: Pt[] = []
  for (const p of play.players) {
    const x = sample(p.x, pos)
    const y = sample(p.y, pos)
    if (x == null || y == null) continue
    pts.push({ p, x, y, o: p.o[Math.round(pos)] ?? null })
  }
  const qb = pts.find((t) => role(t.p) === 'pass')
  const rushers = pts.filter((t) => role(t.p) === 'pass rush')
  const routes = pts.filter((t) => role(t.p) === 'pass route')
  const cover = pts.filter((t) => role(t.p) === 'coverage')

  // Círculo de alerta de 2.5 yd alrededor del QB + rusher más cercano
  let rusherDist: number | null = null
  if (qb) {
    let near: Pt | null = null
    for (const r of rushers) {
      const d = Math.hypot(r.x - qb.x, r.y - qb.y)
      if (rusherDist == null || d < rusherDist) {
        rusherDist = d
        near = r
      }
    }
    const collapsed = rusherDist != null && rusherDist < PRESSURE_RADIUS
    const pulse = 0.5 + 0.5 * Math.sin(now / 110)
    ctx.beginPath()
    ctx.arc(px(qb.x), py(qb.y), PRESSURE_RADIUS * S, 0, Math.PI * 2)
    ctx.fillStyle = collapsed ? `rgba(239,68,68,${0.12 + 0.2 * pulse})` : 'rgba(52,211,153,0.10)'
    ctx.fill()
    ctx.lineWidth = collapsed ? 2 + 2 * pulse : 2
    ctx.strokeStyle = collapsed ? RED : EMERALD
    ctx.stroke()
    if (near && rusherDist != null) {
      ctx.setLineDash([4, 4])
      ctx.strokeStyle = collapsed ? RED : 'rgba(251,191,36,0.8)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(px(near.x), py(near.y))
      ctx.lineTo(px(qb.x), py(qb.y))
      ctx.stroke()
      ctx.setLineDash([])
    }
  }

  // Receptor más abierto: línea punteada hacia su defensor más cercano
  let maxSep: number | null = null
  let sepPair: { r: Pt; d: Pt } | null = null
  for (const r of routes) {
    let best: Pt | null = null
    let bd = Infinity
    for (const c of cover) {
      const d = Math.hypot(c.x - r.x, c.y - r.y)
      if (d < bd) {
        bd = d
        best = c
      }
    }
    if (best && (maxSep == null || bd > maxSep)) {
      maxSep = bd
      sepPair = { r, d: best }
    }
  }
  if (sepPair && maxSep != null) {
    const { r, d } = sepPair
    ctx.setLineDash([2, 6])
    ctx.lineCap = 'round'
    ctx.strokeStyle = EMERALD
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.moveTo(px(r.x), py(r.y))
    ctx.lineTo(px(d.x), py(d.y))
    ctx.stroke()
    ctx.setLineDash([])
    ctx.lineCap = 'butt'
    ctx.beginPath()
    ctx.arc(px(r.x), py(r.y), 1.9 * S, 0, Math.PI * 2)
    ctx.strokeStyle = EMERALD
    ctx.lineWidth = 2
    ctx.stroke()
    const mx = (px(r.x) + px(d.x)) / 2
    const my = (py(r.y) + py(d.y)) / 2
    const label = `${maxSep.toFixed(1)} yd`
    ctx.font = 'bold 15px system-ui, sans-serif'
    const w = ctx.measureText(label).width + 12
    ctx.fillStyle = 'rgba(2,6,23,0.85)'
    ctx.fillRect(mx - w / 2, my - 11, w, 22)
    ctx.fillStyle = EMERALD
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, mx, my)
  }

  // Jugadores: círculo + dorsal + flecha de orientación (o)
  const offTeam = play.possessionTeam
  for (const t of pts) {
    const isOff = t.p.team === offTeam
    const cxp = px(t.x)
    const cyp = py(t.y)
    if (t.o != null) {
      const a = (t.o * Math.PI) / 180
      const dx = Math.sin(a)
      const dy = -Math.cos(a)
      const x0 = cxp + dx * 1.25 * S
      const y0 = cyp + dy * 1.25 * S
      const x1 = cxp + dx * 2.5 * S
      const y1 = cyp + dy * 2.5 * S
      ctx.strokeStyle = isOff ? '#93c5fd' : '#fca5a5'
      ctx.fillStyle = ctx.strokeStyle
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(x0, y0)
      ctx.lineTo(x1, y1)
      ctx.stroke()
      const hx = -dy
      const hy = dx
      ctx.beginPath()
      ctx.moveTo(x1 + dx * 5, y1 + dy * 5)
      ctx.lineTo(x1 + hx * 3.5, y1 + hy * 3.5)
      ctx.lineTo(x1 - hx * 3.5, y1 - hy * 3.5)
      ctx.closePath()
      ctx.fill()
    }
    ctx.beginPath()
    ctx.arc(cxp, cyp, 1.25 * S, 0, Math.PI * 2)
    ctx.fillStyle = isOff ? OFFENSE : DEFENSE
    ctx.fill()
    ctx.lineWidth = t === qb ? 3 : 1.5
    ctx.strokeStyle = t === qb ? '#fde68a' : 'rgba(255,255,255,0.85)'
    ctx.stroke()
    if (t.p.jersey != null) {
      ctx.fillStyle = '#fff'
      ctx.font = 'bold 12px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(t.p.jersey), cxp, cyp + 0.5)
    }
  }

  // Balón
  if (play.ball) {
    const bx = sample(play.ball.x, pos)
    const by = sample(play.ball.y, pos)
    if (bx != null && by != null) {
      ctx.beginPath()
      ctx.ellipse(px(bx), py(by), 0.95 * S, 0.6 * S, 0, 0, Math.PI * 2)
      ctx.fillStyle = BALL
      ctx.fill()
      ctx.strokeStyle = '#78350f'
      ctx.lineWidth = 2
      ctx.stroke()
    }
  }
  return { rusherDist, maxSep }
}

const eventIndex = (events: (string | null)[], names: string[]): number => events.findIndex((e) => e != null && names.includes(e))

export default function FilmRoom({ items }: { items: FilmItem[] }) {
  const [selected, setSelected] = useState(`${items[0].game_id}_${items[0].play_id}`)
  const [play, setPlay] = useState<PlayData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const [pos, setPos] = useState(0)
  const [live, setLive] = useState<Live>({ rusherDist: null, maxSep: null })

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fieldRef = useRef<HTMLCanvasElement | null>(null)
  const playRef = useRef<PlayData | null>(null)
  const posRef = useRef(0)
  const playingRef = useRef(true)
  const speedRef = useRef(1)
  const cache = useRef(new Map<string, PlayData>())

  const groups = useMemo(() => {
    const m = new Map<string, FilmItem[]>()
    for (const it of items) m.set(it.category_label, [...(m.get(it.category_label) ?? []), it])
    return [...m.entries()]
  }, [items])

  useEffect(() => {
    playingRef.current = playing
  }, [playing])
  useEffect(() => {
    speedRef.current = speed
  }, [speed])

  // Carga de la jugada seleccionada
  useEffect(() => {
    let cancelled = false
    const [g, p] = selected.split('_').map(Number)
    setError(null)
    const apply = (d: PlayData) => {
      playRef.current = d
      fieldRef.current = buildField(d)
      posRef.current = 0
      setPos(0)
      setPlay(d)
      setPlaying(true)
    }
    const hit = cache.current.get(selected)
    if (hit) {
      apply(hit)
    } else {
      fetchPlay(g, p)
        .then((d) => {
          if (cancelled) return
          cache.current.set(selected, d)
          apply(d)
        })
        .catch((e: Error) => !cancelled && setError(`No se pudo cargar la jugada (${e.message})`))
    }
    return () => {
      cancelled = true
    }
  }, [selected])

  // Bucle de animación: avanza el tiempo y dibuja
  useEffect(() => {
    let raf = 0
    let last = performance.now()
    const loop = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      const d = playRef.current
      if (d && playingRef.current) {
        const max = d.clock.length - 1
        let p = posRef.current + dt * FPS * speedRef.current
        if (p >= max) {
          p = max
          playingRef.current = false
          setPlaying(false)
        }
        posRef.current = p
        setPos(p)
      }
      const cv = canvasRef.current
      const ctx = cv?.getContext('2d')
      if (d && ctx && fieldRef.current) {
        const l = draw(ctx, fieldRef.current, d, posRef.current, now)
        setLive((prev) =>
          prev.rusherDist === l.rusherDist && prev.maxSep === l.maxSep ? prev : { rusherDist: l.rusherDist, maxSep: l.maxSep },
        )
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const n = play?.clock.length ?? 1
  const t = play ? play.clock[0] + pos / FPS : 0
  const snapIdx = play ? Math.max(0, eventIndex(play.events, ['ball_snap', 'autoevent_ballsnap'])) : 0
  const passIdx = play ? play.pass_index : 0
  const arrivedIdx = play ? eventIndex(play.events, ['pass_arrived']) : -1
  const m = play?.metrics
  const ttt = m?.ttt ?? 0
  const pct = m?.pct ?? 0
  const collapsedNow = live.rusherDist != null && live.rusherDist < PRESSURE_RADIUS
  const pocketPct = ttt > 0 ? Math.min(100, (pct / ttt) * 100) : 100
  const cursorPct = ttt > 0 ? Math.min(100, (t / ttt) * 100) : 0

  const togglePlay = () => {
    if (!play) return
    if (!playing && posRef.current >= n - 1) {
      posRef.current = 0
      setPos(0)
    }
    setPlaying(!playing)
  }
  const reset = () => {
    posRef.current = 0
    setPos(0)
    setPlaying(false)
  }
  const seek = (v: number) => {
    posRef.current = v
    setPos(v)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
        <label htmlFor="play-select" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Jugada destacada
        </label>
        <select
          id="play-select"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="min-w-[320px] flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
        >
          {groups.map(([label, list]) => (
            <optgroup key={label} label={label}>
              {list.map((it) => (
                <option key={`${it.game_id}_${it.play_id}`} value={`${it.game_id}_${it.play_id}`}>
                  {`${it.possessionTeam} vs ${it.defensiveTeam} · ${ordinal(it.down)} & ${it.yardsToGo} · PCT ${fmt(it.metrics.pct, 1)} s · TWS ${fmt(it.metrics.tws_max, 1)} yd · ${it.passResult ?? '—'}`}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {error && <div className="rounded-md border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</div>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
            <canvas ref={canvasRef} width={CW} height={CH} className="block h-auto w-full" aria-label="Cancha 2D de la jugada" />
          </div>

          <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={togglePlay}
                className="w-24 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-bold text-slate-950 hover:bg-emerald-400"
              >
                {playing ? '❚❚ Pause' : '▶ Play'}
              </button>
              <button
                onClick={reset}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
              >
                ↺ Reiniciar
              </button>
              <div className="ml-2 flex overflow-hidden rounded-md border border-slate-700" role="group" aria-label="Velocidad">
                {[0.25, 0.5, 1].map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpeed(s)}
                    className={`px-3 py-1.5 text-sm tabular-nums ${
                      speed === s ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {s}x
                  </button>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
                <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-full" style={{ background: OFFENSE }} /> Ataque</span>
                <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-full" style={{ background: DEFENSE }} /> Defensa</span>
                <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-full" style={{ background: BALL }} /> Balón</span>
              </div>
            </div>

            <div>
              <div className="relative">
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, n - 1)}
                  step={1}
                  value={Math.round(pos)}
                  onChange={(e) => seek(Number(e.target.value))}
                  className="w-full accent-emerald-500"
                  aria-label="frameId"
                />
              </div>
              <div className="flex justify-between text-xs tabular-nums text-slate-500">
                <span>frameId {play ? play.snap_frame : '—'}</span>
                <span className="text-slate-300">frameId {play ? play.snap_frame + Math.round(pos) : '—'}</span>
                <span>frameId {play ? play.snap_frame + n - 1 : '—'}</span>
              </div>
            </div>
          </div>
        </div>

        <aside className="space-y-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-center">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Reloj desde ball_snap</div>
            <div
              className={`font-mono text-7xl font-black tabular-nums leading-none ${collapsedNow ? 'text-red-400' : 'text-emerald-400'}`}
              aria-live="off"
            >
              {t.toFixed(1)}
              <span className="ml-1 text-3xl text-slate-500">s</span>
            </div>
            <div
              className={`mt-2 inline-block rounded px-2 py-0.5 text-xs font-bold ${
                collapsedNow ? 'bg-red-500/20 text-red-300' : 'bg-emerald-500/15 text-emerald-300'
              }`}
            >
              {collapsedNow ? 'BOLSILLO COLAPSADO' : 'BOLSILLO LIMPIO'}
            </div>

            <div className="mt-4 text-left">
              <div className="mb-1 flex justify-between text-xs text-slate-400">
                <span>Reloj de presión</span>
                <span className="tabular-nums">PCT {fmt(m?.pct, 1)} s / TTT {fmt(m?.ttt, 1)} s</span>
              </div>
              <div className="relative h-3 overflow-hidden rounded-full bg-slate-800">
                <div className="absolute inset-y-0 left-0 bg-emerald-500/70" style={{ width: `${pocketPct}%` }} />
                <div className="absolute inset-y-0 right-0 bg-red-500/70" style={{ width: `${100 - pocketPct}%` }} />
                <div className="absolute inset-y-0 w-1 bg-white" style={{ left: `calc(${cursorPct}% - 2px)` }} />
              </div>
              <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wide text-slate-500">
                <span>Snap</span>
                <span>Pase</span>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap justify-center gap-2 text-xs">
              <EventChip label="ball_snap" reached={!!play && pos >= snapIdx} />
              <EventChip label="pass_forward" reached={!!play && pos >= passIdx} />
              <EventChip
                label="pass_arrived"
                reached={arrivedIdx >= 0 && pos >= arrivedIdx}
                missing={!!play && arrivedIdx < 0}
              />
            </div>
            {play && arrivedIdx < 0 && (
              <p className="mt-2 text-[11px] leading-snug text-slate-500">
                El tracking de esta muestra termina poco después de pass_forward, por eso pass_arrived no está registrado.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Stat label="Rusher → QB" value={`${fmt(live.rusherDist, 1)} yd`} tone={collapsedNow ? 'red' : 'emerald'} />
            <Stat label="Máx. separación" value={`${fmt(live.maxSep, 1)} yd`} tone="emerald" />
            <Stat label="TWS máx (pase)" value={`${fmt(m?.tws_max, 1)} yd`} />
            <Stat label="PSI" value={fmt(m?.psi, 1)} tone="emerald" />
          </div>

          {play && (
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-sm">
              <div className="mb-1 flex flex-wrap gap-x-3 text-xs text-slate-400">
                <span>{ordinal(play.down)} &amp; {play.yardsToGo}</span>
                <span>{play.offenseFormation ?? '—'}</span>
                <span>{play.pff_passCoverage ?? '—'} ({play.pff_passCoverageType ?? '—'})</span>
                <span>{play.pff_playAction ? 'Con PA' : 'Sin PA'}</span>
                <span>Resultado: {play.passResult ?? '—'} · {fmt(play.playResult, 0)} yd</span>
              </div>
              <p className="text-xs leading-snug text-slate-300">{play.playDescription}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function EventChip({ label, reached, missing }: { label: string; reached: boolean; missing?: boolean }) {
  const cls = missing
    ? 'border-slate-800 text-slate-600 line-through'
    : reached
      ? 'border-emerald-500 bg-emerald-500/15 text-emerald-300'
      : 'border-slate-700 text-slate-500'
  return <span className={`rounded-full border px-2.5 py-1 font-mono ${cls}`}>{label}</span>
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'emerald' | 'red' }) {
  const color = tone === 'red' ? 'text-red-400' : tone === 'emerald' ? 'text-emerald-400' : 'text-slate-100'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-xl font-bold tabular-nums ${color}`}>{value}</div>
    </div>
  )
}
