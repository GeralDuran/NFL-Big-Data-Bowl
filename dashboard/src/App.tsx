import { useEffect, useState, type ReactNode } from 'react'
import { fetchSummary } from './api'
import FilmRoom from './components/FilmRoom'
import Rankings from './components/Rankings'
import Simulator from './components/Simulator'
import { fmt, fmtInt } from './format'
import type { Summary } from './types'

type Tab = 'film' | 'sim' | 'rank'
const TABS: { key: Tab; label: string }[] = [
  { key: 'film', label: 'Film Room 2D' },
  { key: 'sim', label: 'Simulador Play-Caller' },
  { key: 'rank', label: 'Rankings Top 15' },
]

function KpiCard({ title, value, unit, detail, accent }: { title: string; value: string; unit: string; detail: ReactNode; accent: string }) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} />
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-4xl font-black tabular-nums text-white">{value}</span>
        <span className="text-lg text-slate-400">{unit}</span>
      </div>
      <div className="mt-1 text-xs text-slate-400">{detail}</div>
    </div>
  )
}

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [error, setError] = useState<string | null>(null)
  // ?tab=sim|rank|film permite abrir un módulo directamente
  const [tab, setTab] = useState<Tab>(() => {
    const q = new URLSearchParams(window.location.search).get('tab')
    return TABS.some((t) => t.key === q) ? (q as Tab) : 'film'
  })

  useEffect(() => {
    fetchSummary()
      .then(setSummary)
      .catch((e: Error) => setError(e.message))
  }, [])

  const k = summary?.kpis
  const pa = summary?.matrix.play_action
  const withPa = pa?.find((r) => Number(r.value) === 1)
  const withoutPa = pa?.find((r) => Number(r.value) === 0)
  const paEffect = withPa?.play_result != null && withoutPa?.play_result != null ? withPa.play_result - withoutPa.play_result : null
  const season = summary?.meta.season

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 antialiased">
      <header className="border-b border-slate-800 bg-gradient-to-b from-slate-900 to-slate-950">
        <div className="mx-auto max-w-[1500px] px-4 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-3xl font-black tracking-tight sm:text-4xl">
                Pocket<span className="text-emerald-400">Clock</span> AI
              </h1>
              <p className="mt-1 max-w-3xl text-sm italic text-slate-400">
                Sincronía entre Colapso del Bolsillo y Ventana de Pase (Temporada NFL {season ?? '—'} • {k?.n_games ?? '—'} Partidos)
              </p>
            </div>
            <span className="rounded-full border border-amber-400/50 bg-amber-400/10 px-3 py-1 text-xs font-bold uppercase tracking-wider text-amber-300">
              Perfil: Coach / Coordinador Ofensivo
            </span>
          </div>

          {k ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard
                title="Time to Throw (TTT)"
                value={fmt(k.ttt_mean)}
                unit="s"
                accent="#38bdf8"
                detail={`Mediana ${fmt(k.ttt_median)} s · ${fmtInt(k.n_tracked_plays)} pases con tracking`}
              />
              <KpiCard
                title="Pocket Collapse Time (PCT)"
                value={fmt(k.pct_mean)}
                unit="s"
                accent="#f87171"
                detail={<span className="text-amber-300">{fmt(k.pressure_reached_pct, 1)}% de jugadas bajo presión antes del pase</span>}
              />
              <KpiCard
                title="Target Window Separation (TWS)"
                value={fmt(k.tws_max_avg)}
                unit="yd"
                accent="#34d399"
                detail={`Ventana máxima promedio · separación media de receptores ${fmt(k.tws_mean_avg)} yd`}
              />
              <KpiCard
                title="Índice PSI (Sincronía)"
                value={fmt(k.psi_mean)}
                unit="yd/s"
                accent="#34d399"
                detail={
                  <>
                    TWS máx ÷ PCT ·{' '}
                    <span className="text-emerald-300">
                      Play Action {paEffect != null ? `${paEffect >= 0 ? '+' : ''}${fmt(paEffect)}` : '—'} yd/jugada
                    </span>
                  </>
                }
              />
            </div>
          ) : (
            <div className="mt-5 h-[110px] animate-pulse rounded-lg bg-slate-900" />
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-5">
        <nav className="mb-4 flex gap-1 border-b border-slate-800" role="tablist" aria-label="Módulos">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold ${
                tab === t.key ? 'border-emerald-400 text-emerald-300' : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        {error && (
          <div className="rounded-md border border-red-800 bg-red-950/50 p-4 text-sm text-red-300">
            No se pudo cargar api/summary ({error}). Verifica que el backend esté corriendo y que exista backend/data_summary.json.
          </div>
        )}
        {!summary && !error && <div className="text-sm text-slate-400">Cargando datos…</div>}
        {summary && tab === 'film' && <FilmRoom items={summary.film_room} />}
        {summary && tab === 'sim' && <Simulator summary={summary} />}
        {summary && tab === 'rank' && <Rankings data={summary.rankings} />}
      </main>

      <footer className="mx-auto max-w-[1500px] px-4 pb-8 text-xs text-slate-600">
        PSI = TWS máx ÷ PCT. PCT: segundos desde ball_snap hasta que un Pass Rush queda a menos de 2.5 yd del QB (si no ocurre, TTT). Datos: NFL Next Gen
        Stats y PFF, Big Data Bowl.
      </footer>
    </div>
  )
}
