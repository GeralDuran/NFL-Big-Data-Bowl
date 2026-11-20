import { useState, type ReactNode } from 'react'
import { fmt, fmtInt } from '../format'
import type { Num, Rankings as RankingsData } from '../types'

interface Col<T> {
  header: string
  render: (r: T) => ReactNode
  align?: 'right'
}

interface Spec<T> {
  title: string
  note: string
  rows: T[]
  name: (r: T) => ReactNode
  sub: (r: T) => string
  bar: { value: (r: T) => Num; label: (r: T) => string; header: string; color: string }
  cols: Col<T>[]
}

function RankTable<T>({ spec }: { spec: Spec<T> }) {
  const max = Math.max(0.0001, ...spec.rows.map((r) => spec.bar.value(r) ?? 0))
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[11px] uppercase tracking-wider text-slate-400">
            <th className="w-10 px-3 py-2">#</th>
            <th className="px-3 py-2">Nombre</th>
            <th className="min-w-[220px] px-3 py-2">{spec.bar.header}</th>
            {spec.cols.map((c) => (
              <th key={c.header} className={`px-3 py-2 ${c.align === 'right' ? 'text-right' : ''}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((r, i) => {
            const v = spec.bar.value(r) ?? 0
            return (
              <tr key={i} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/40">
                <td className="px-3 py-2 font-bold tabular-nums text-slate-500">{i + 1}</td>
                <td className="px-3 py-2">
                  <div className="font-semibold text-slate-100">{spec.name(r)}</div>
                  <div className="text-xs text-slate-500">{spec.sub(r)}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                      <div className="h-full rounded-full" style={{ width: `${(v / max) * 100}%`, background: spec.bar.color }} />
                    </div>
                    <span className="w-16 text-right font-bold tabular-nums text-slate-100">{spec.bar.label(r)}</span>
                  </div>
                </td>
                {spec.cols.map((c) => (
                  <td key={c.header} className={`px-3 py-2 tabular-nums text-slate-300 ${c.align === 'right' ? 'text-right' : ''}`}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

type Key = 'teams' | 'receivers' | 'blockers' | 'rushers'
const TABS: { key: Key; label: string }[] = [
  { key: 'teams', label: 'Equipos ofensivos' },
  { key: 'receivers', label: 'Receptores WR/TE' },
  { key: 'blockers', label: 'Linieros ofensivos' },
  { key: 'rushers', label: 'Cazamariscales' },
]

export default function Rankings({ data }: { data: RankingsData }) {
  const [key, setKey] = useState<Key>('teams')
  const ms = data.min_samples

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Rankings">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={key === t.key}
            onClick={() => setKey(t.key)}
            className={`rounded-full border px-4 py-1.5 text-sm ${
              key === t.key ? 'border-emerald-500 bg-emerald-500/15 font-bold text-emerald-300' : 'border-slate-700 text-slate-300 hover:bg-slate-800'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {key === 'teams' && (
        <>
          <RankTable
            spec={{
              title: 'Equipos',
              note: '',
              rows: data.teams_offense,
              name: (r) => r.team,
              sub: (r) => `${fmtInt(r.n)} dropbacks`,
              bar: { header: 'PSI (TWS máx ÷ PCT)', value: (r) => r.psi, label: (r) => fmt(r.psi), color: '#34d399' },
              cols: [
                { header: 'PCT (s)', render: (r) => fmt(r.pct), align: 'right' },
                { header: 'TWS máx (yd)', render: (r) => fmt(r.tws_max), align: 'right' },
                { header: 'Presión perm.', render: (r) => `${fmt(r.pressure_allowed_pct, 1)}%`, align: 'right' },
                { header: 'Sacks', render: (r) => `${fmt(r.sack_pct, 1)}%`, align: 'right' },
              ],
            }}
          />
          <Note>Top 15 por PSI medio por dropback (PSI limitado al percentil 99). Presión permitida según PFF.</Note>
        </>
      )}

      {key === 'receivers' && (
        <>
          <RankTable
            spec={{
              title: 'Receptores',
              note: '',
              rows: data.receivers_wr_te,
              name: (r) => r.name ?? `#${r.nflId}`,
              sub: (r) => `${r.position ?? '—'} · ${r.team ?? '—'} · ${r.routes} rutas`,
              bar: { header: 'TWS medio (yd)', value: (r) => r.tws, label: (r) => fmt(r.tws), color: '#34d399' },
              cols: [{ header: 'PSI', render: (r) => fmt(r.psi), align: 'right' }],
            }}
          />
          <Note>
            Solo WR y TE con al menos {ms.routes} rutas. Orden por suma de posiciones en TWS y PSI. Los corredores quedan fuera porque suelen
            enfrentar linebackers y distancias mayores, lo que infla su separación.
          </Note>
        </>
      )}

      {key === 'blockers' && (
        <>
          <RankTable
            spec={{
              title: 'Linieros',
              note: '',
              rows: data.blockers,
              name: (r) => r.name ?? `#${r.nflId}`,
              sub: (r) => `${r.position ?? '—'} · ${r.team ?? '—'} · ${r.snaps} snaps`,
              bar: { header: 'PCT medio (s)', value: (r) => r.pct, label: (r) => fmt(r.pct), color: '#34d399' },
              cols: [
                { header: 'Presión permitida', render: (r) => `${fmt(r.pressure_allowed_pct, 1)}%`, align: 'right' },
                { header: 'Vencido', render: (r) => `${fmt(r.beaten_pct, 1)}%`, align: 'right' },
              ],
            }}
          />
          <Note>
            Al menos {ms.ol_snaps} snaps. Orden por la suma de posiciones en menor presión permitida (PFF) y mayor PCT de las jugadas en que
            jugó.
          </Note>
        </>
      )}

      {key === 'rushers' && (
        <>
          <RankTable
            spec={{
              title: 'Cazamariscales',
              note: '',
              rows: data.rushers_by_closing_speed,
              name: (r) => r.name ?? `#${r.nflId}`,
              sub: (r) => `${r.position ?? '—'} · ${r.team ?? '—'} · ${r.rushes} rushes`,
              bar: { header: 'Velocidad de cierre (yd/s)', value: (r) => r.closing_speed, label: (r) => fmt(r.closing_speed), color: '#f87171' },
              cols: [
                { header: 'PCT (s)', render: (r) => fmt(r.pct), align: 'right' },
                { header: 'Llega < 2.5 yd', render: (r) => `${fmt(r.reach_pct, 0)}%`, align: 'right' },
                { header: 'Hits / Hurries / Sacks', render: (r) => `${fmt(r.hits, 0)} / ${fmt(r.hurries, 0)} / ${fmt(r.sacks, 0)}`, align: 'right' },
              ],
            }}
          />
          <Note>
            Al menos {ms.rushes} rushes. Velocidad de cierre = (distancia al QB en el snap − distancia mínima) ÷ tiempo hasta ese mínimo. Se
            ordena por esta métrica porque el PCT individual favorece a los tackles interiores, que se alinean más cerca del QB.
          </Note>
        </>
      )}
    </div>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>
}
