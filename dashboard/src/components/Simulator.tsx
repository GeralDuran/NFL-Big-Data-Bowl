import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, fmtInt, ordinal } from '../format'
import type { Cube, Summary } from '../types'

const MIN_N = 30 // jugadas mínimas para recomendar
const MIN_CHART_N = 15

interface CubeRow {
  down: number
  distance: string
  coverageType: string
  coverage: string
  pa: number
  dim: string
  n: number
  nt: number
  res: number
  c: number
  s: number
  ttt: number
  pct: number
  twm: number
  twx: number
  ntw: number
  psi: number
  npsi: number
  pr: number
  pa_: number
}

function decode(cube: Cube): CubeRow[] {
  const k = cube.keys.length
  const idx = (name: string) => cube.metrics.indexOf(name) + k
  const I = Object.fromEntries(cube.metrics.map((m) => [m, idx(m)])) as Record<string, number>
  return cube.rows.map((r) => ({
    down: r[0] as number,
    distance: r[1] as string,
    coverageType: r[2] as string,
    coverage: r[3] as string,
    pa: r[4] as number,
    dim: r[5] as string,
    n: r[I.n] as number,
    nt: r[I.nt] as number,
    res: r[I.res] as number,
    c: r[I.c] as number,
    s: r[I.s] as number,
    ttt: r[I.ttt] as number,
    pct: r[I.pct] as number,
    twm: r[I.twm] as number,
    twx: r[I.twx] as number,
    ntw: r[I.ntw] as number,
    psi: r[I.psi] as number,
    npsi: r[I.npsi] as number,
    pr: r[I.pr] as number,
    pa_: r[I.pa] as number,
  }))
}

interface Filters {
  down: number // 0 = todos
  distance: string // '' = todas
  coverageType: string
  coverage: string
  pa: number // -1 = todos
}
const DEFAULT_FILTERS: Filters = { down: 0, distance: '', coverageType: '', coverage: '', pa: -1 }

const matches = (r: CubeRow, f: Filters, skipCoverage = false) =>
  (f.down === 0 || r.down === f.down) &&
  (f.distance === '' || r.distance === f.distance) &&
  (skipCoverage || ((f.coverageType === '' || r.coverageType === f.coverageType) && (f.coverage === '' || r.coverage === f.coverage))) &&
  (f.pa === -1 || r.pa === f.pa)

interface Stats {
  key: string
  n: number
  psi: number | null
  tws: number | null
  complete: number
  result: number
  pct: number | null
  ttt: number | null
  sack: number
  pressure: number | null
}

function aggregate(rows: CubeRow[], by: (r: CubeRow) => string): Stats[] {
  const acc = new Map<string, CubeRow>()
  for (const r of rows) {
    const key = by(r)
    const a = acc.get(key)
    if (!a) {
      acc.set(key, { ...r, dim: key })
      continue
    }
    for (const f of ['n', 'nt', 'res', 'c', 's', 'ttt', 'pct', 'twm', 'twx', 'ntw', 'psi', 'npsi', 'pr', 'pa_'] as const) a[f] += r[f]
  }
  return [...acc.entries()].map(([key, a]) => ({
    key,
    n: a.n,
    psi: a.npsi > 0 ? a.psi / a.npsi : null,
    tws: a.ntw > 0 ? a.twx / a.ntw : null,
    complete: (a.c / a.n) * 100,
    result: a.res / a.n,
    pct: a.nt > 0 ? a.pct / a.nt : null,
    ttt: a.nt > 0 ? a.ttt / a.nt : null,
    sack: (a.s / a.n) * 100,
    pressure: a.nt > 0 ? (a.pr / a.nt) * 100 : null,
  }))
}

/** Ordena por PSI y por yardas esperadas (playResult) y devuelve la suma de posiciones: menor es mejor. */
function rankByPsiAndResult(list: Stats[]): (Stats & { score: number })[] {
  const el = list.filter((s) => s.n >= MIN_N && s.psi != null)
  const rank = (sel: (s: Stats) => number) => {
    const order = [...el].sort((a, b) => sel(b) - sel(a))
    return new Map(order.map((s, i) => [s.key, i]))
  }
  const rp = rank((s) => s.psi ?? 0)
  const rr = rank((s) => s.result)
  return el.map((s) => ({ ...s, score: (rp.get(s.key) ?? 0) + (rr.get(s.key) ?? 0) })).sort((a, b) => a.score - b.score || (b.psi ?? 0) - (a.psi ?? 0))
}

function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className="flex flex-wrap overflow-hidden rounded-md border border-slate-700" role="group" aria-label={label}>
        {options.map((o) => (
          <button
            key={String(o.value)}
            onClick={() => onChange(o.value)}
            className={`px-3 py-1.5 text-sm ${value === o.value ? 'bg-emerald-500 font-bold text-slate-950' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'emerald' | 'amber' | 'red' }) {
  const color = tone === 'emerald' ? 'text-emerald-400' : tone === 'amber' ? 'text-amber-400' : tone === 'red' ? 'text-red-400' : 'text-slate-100'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
    </div>
  )
}

function Rec({ title, best, others, label }: { title: string; best: Stats | undefined; others: Stats[]; label: (k: string) => string }) {
  return (
    <div className="rounded-lg border border-emerald-500/40 bg-gradient-to-br from-emerald-950/60 to-slate-900 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">{title}</div>
      {best ? (
        <>
          <div className="mt-1 text-2xl font-black text-white">{label(best.key)}</div>
          <div className="mt-1 text-sm tabular-nums text-slate-300">
            PSI <b className="text-emerald-400">{fmt(best.psi)}</b> · {fmt(best.result)} yd/jugada · TWS máx {fmt(best.tws, 1)} yd ·{' '}
            {fmt(best.complete, 1)}% completos · n={fmtInt(best.n)}
          </div>
          {others.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-slate-800 pt-2 text-xs text-slate-400">
              {others.map((o) => (
                <li key={o.key} className="flex justify-between tabular-nums">
                  <span>{label(o.key)}</span>
                  <span>
                    PSI {fmt(o.psi)} · {fmt(o.result)} yd
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <div className="mt-2 text-sm text-slate-400">Muestra insuficiente (menos de {MIN_N} jugadas). Relaja algún filtro.</div>
      )}
    </div>
  )
}

const BLOCK_NAMES: Record<string, string> = {
  PP: 'PP · Pass Protection',
  PA: 'PA · Play Action Protection',
  PT: 'PT · Post Block',
  SW: 'SW · Switch Block',
  CL: 'CL · Second Level',
  CH: 'CH · Chip Block',
  NB: 'NB · No Block',
  PU: 'PU · Backfield Pickup',
  SR: 'SR · Set & Release',
  BH: 'BH · Backfield Help',
  UP: 'UP · Pull Pass Protection',
  PR: 'PR · Pocket Roll',
}

function ChartPanel({ title, data }: { title: string; data: { name: string; PSI: number; 'TWS máx (yd)': number; '% Completos': number }[] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-200">{title}</h3>
      {data.length === 0 ? (
        <div className="flex h-[300px] items-center justify-center text-sm text-slate-500">Sin datos suficientes para este escenario</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} interval={0} />
            <YAxis yAxisId="a" tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <YAxis yAxisId="b" orientation="right" domain={[0, 100]} tick={{ fill: '#fbbf24', fontSize: 11 }} unit="%" />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              cursor={{ fill: 'rgba(148,163,184,0.08)' }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar isAnimationActive={false} yAxisId="a" dataKey="PSI" fill="#34d399" radius={[3, 3, 0, 0]} />
            <Bar isAnimationActive={false} yAxisId="a" dataKey="TWS máx (yd)" fill="#38bdf8" radius={[3, 3, 0, 0]} />
            <Bar isAnimationActive={false} yAxisId="b" dataKey="% Completos" fill="#fbbf24" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default function Simulator({ summary }: { summary: Summary }) {
  const [f, setF] = useState<Filters>(DEFAULT_FILTERS)
  const formation = useMemo(() => decode(summary.matrix.cube_formation), [summary])
  const blocks = useMemo(() => decode(summary.matrix.cube_block), [summary])

  const distances = useMemo(() => [...new Set(formation.map((r) => r.distance))].sort(), [formation])
  const distOrder = ['Corto: 1-3', 'Medio: 4-7', 'Largo: 8+']
  const covTypes = useMemo(() => ['Man', 'Zone', 'Other'].filter((t) => formation.some((r) => r.coverageType === t)), [formation])
  const coverages = useMemo(() => {
    const tot = new Map<string, number>()
    for (const r of formation) if (f.coverageType === '' || r.coverageType === f.coverageType) tot.set(r.coverage, (tot.get(r.coverage) ?? 0) + r.n)
    return [...tot.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c)
  }, [formation, f.coverageType])

  const set = (patch: Partial<Filters>) => setF((p) => ({ ...p, ...patch }))

  const scenarioRows = useMemo(() => formation.filter((r) => matches(r, f)), [formation, f])
  const scenario = useMemo(() => aggregate(scenarioRows, () => 'all')[0], [scenarioRows])
  const byFormation = useMemo(() => aggregate(scenarioRows, (r) => r.dim), [scenarioRows])
  const byBlock = useMemo(() => aggregate(blocks.filter((r) => matches(r, f)), (r) => r.dim), [blocks, f])
  const byCoverage = useMemo(() => aggregate(formation.filter((r) => matches(r, f, true)), (r) => r.coverage), [formation, f])

  const recFormation = useMemo(() => rankByPsiAndResult(byFormation), [byFormation])
  const recBlock = useMemo(() => rankByPsiAndResult(byBlock), [byBlock])

  const toChart = (list: Stats[]) =>
    list
      .filter((s) => s.n >= MIN_CHART_N && s.psi != null)
      .sort((a, b) => b.n - a.n)
      .slice(0, 8)
      .map((s) => ({ name: s.key, PSI: Number((s.psi ?? 0).toFixed(2)), 'TWS máx (yd)': Number((s.tws ?? 0).toFixed(2)), '% Completos': Number(s.complete.toFixed(1)) }))

  const covOptions = [
    { value: '', label: 'Todos' },
    ...coverages.map((c) => ({ value: c, label: c })),
  ]

  return (
    <div className="space-y-4">
      <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <Segmented
            label="Down"
            value={f.down}
            options={[{ value: 0, label: 'Todos' }, ...[1, 2, 3, 4].map((d) => ({ value: d, label: ordinal(d) }))]}
            onChange={(v) => set({ down: v })}
          />
          <Segmented
            label="Distancia"
            value={f.distance}
            options={[{ value: '', label: 'Todas' }, ...distOrder.filter((d) => distances.includes(d)).map((d) => ({ value: d, label: d }))]}
            onChange={(v) => set({ distance: v })}
          />
          <Segmented
            label="Cobertura"
            value={f.coverageType}
            options={[{ value: '', label: 'Todas' }, ...covTypes.map((t) => ({ value: t, label: t }))]}
            onChange={(v) => set({ coverageType: v, coverage: '' })}
          />
          <Segmented
            label="Play Action"
            value={f.pa}
            options={[
              { value: -1, label: 'Todos' },
              { value: 1, label: 'Con PA' },
              { value: 0, label: 'Sin PA' },
            ]}
            onChange={(v) => set({ pa: v })}
          />
        </div>
        <Segmented label="Esquema de cobertura" value={f.coverage} options={covOptions} onChange={(v) => set({ coverage: v })} />
        <button onClick={() => setF(DEFAULT_FILTERS)} className="text-xs text-slate-400 underline hover:text-slate-200">
          Limpiar filtros
        </button>
      </div>

      {scenario ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <Tile label="Jugadas" value={fmtInt(scenario.n)} />
          <Tile label="PSI" value={fmt(scenario.psi)} tone="emerald" />
          <Tile label="TWS máx" value={`${fmt(scenario.tws, 1)} yd`} tone="emerald" />
          <Tile label="PCT" value={`${fmt(scenario.pct)} s`} tone="amber" />
          <Tile label="% Completos" value={`${fmt(scenario.complete, 1)}%`} />
          <Tile label="Yardas / jugada" value={fmt(scenario.result)} />
          <Tile label="% Sacks" value={`${fmt(scenario.sack, 1)}%`} tone="red" />
        </div>
      ) : (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">Ninguna jugada cumple esta combinación de filtros.</div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Rec title="Recomendación táctica · Formación" best={recFormation[0]} others={recFormation.slice(1, 3)} label={(k) => k} />
        <Rec title="Recomendación táctica · Tipo de bloqueo" best={recBlock[0]} others={recBlock.slice(1, 3)} label={(k) => BLOCK_NAMES[k] ?? k} />
      </div>
      <p className="text-xs text-slate-500">
        El sistema ordena por PSI y por yardas esperadas (playResult) y recomienda la opción con mejor suma de posiciones, con al menos {MIN_N}{' '}
        jugadas. El tipo de bloqueo cuenta una jugada por cada tipo presente en ella. Es una asociación histórica, no causal.
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartPanel title="PSI, TWS y % completos por formación (8 más usadas)" data={toChart(byFormation)} />
        <ChartPanel title="PSI, TWS y % completos por cobertura (8 más usadas)" data={toChart(byCoverage)} />
      </div>
    </div>
  )
}
