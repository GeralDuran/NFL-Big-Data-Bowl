export type Num = number | null

export interface Kpis {
  n_games: number
  n_dropbacks: number
  n_tracked_plays: number
  ttt_mean: number
  ttt_median: number
  pct_mean: number
  pct_median: number
  min_qb_dist_mean: number
  pressure_reached_pct: number
  tws_mean_avg: number
  tws_max_avg: number
  psi_mean: number
  psi_median: number
  psi_cap_p99: number
  pressure_allowed_pct: number
  sack_pct: number
  complete_pct: number
  play_result_mean: number
}

export interface PlayMetrics {
  ttt: Num
  pct: Num
  pressure_reached: boolean | null
  min_qb_dist: Num
  tws_mean: Num
  tws_max: Num
  psi: Num
}

export interface FilmItem {
  game_id: number
  play_id: number
  category: string
  category_label: string
  possessionTeam: string
  defensiveTeam: string
  down: number
  yardsToGo: number
  passResult: string | null
  metrics: PlayMetrics
  playDescription: string
}

export interface GroupRow {
  value: string | number
  n: number
  n_tracked: number
  play_result: Num
  complete_pct: Num
  sack_pct: Num
  pressure_allowed_pct: Num
  pressure_reached_pct: Num
  ttt: Num
  pct: Num
  tws_mean: Num
  tws_max: Num
  psi: Num
}

export interface Cube {
  keys: string[]
  metrics: string[]
  rows: (string | number | null)[][]
}

export interface TeamRank {
  team: string
  n: number
  sack_pct: Num
  pressure_allowed_pct: Num
  pct: Num
  tws_max: Num
  psi: Num
}

export interface PlayerRankBase {
  nflId: number
  name: string | null
  position: string | null
  team: string | null
}

export interface BlockerRank extends PlayerRankBase {
  snaps: number
  pressure_allowed_pct: Num
  beaten_pct: Num
  pct: Num
}

export interface RusherRank extends PlayerRankBase {
  rushes: number
  pct: Num
  reach_pct: Num
  closing_speed: Num
  min_dist: Num
  hits: Num
  hurries: Num
  sacks: Num
}

export interface ReceiverRank extends PlayerRankBase {
  routes: number
  tws: Num
  psi: Num
}

export interface Rankings {
  min_samples: { ol_snaps: number; rushes: number; routes: number }
  teams_offense: TeamRank[]
  blockers: BlockerRank[]
  rushers_by_pct: RusherRank[]
  rushers_by_closing_speed: RusherRank[]
  receivers: ReceiverRank[]
  receivers_wr_te: ReceiverRank[]
}

export interface Summary {
  meta: { project: string; season: number | null; pressure_radius_yd: number; psi_cap_p99: number }
  kpis: Kpis
  rankings: Rankings
  matrix: {
    play_action: GroupRow[]
    coverage_type: GroupRow[]
    cube_formation: Cube
    cube_block: Cube
  } & Record<string, unknown>
  film_room: FilmItem[]
}

export interface PlayerTrack {
  nfl_id: number
  name: string | null
  jersey: number | null
  position: string | null
  role: string | null
  team: string | null
  x: Num[]
  y: Num[]
  o: Num[]
}

export interface PlayData {
  game_id: number
  play_id: number
  category: string
  category_label: string
  possessionTeam: string
  defensiveTeam: string
  down: number
  yardsToGo: number
  quarter: number
  offenseFormation: string | null
  pff_passCoverage: string | null
  pff_passCoverageType: string | null
  pff_playAction: number | null
  passResult: string | null
  playResult: Num
  playDescription: string
  metrics: PlayMetrics
  snap_frame: number
  pass_frame: number
  pass_index: number
  los_x: Num
  clock: number[]
  events: (string | null)[]
  min_rush_qb_dist: Num[]
  max_receiver_separation: Num[]
  players: PlayerTrack[]
  ball: { x: Num[]; y: Num[] } | null
}
