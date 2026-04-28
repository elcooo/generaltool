export interface TimelineItem {
  timecode: number;
  clock: string;
  action: string;
  label: string;
  detail?: string;
  template_name?: string;
  template_name_human?: string;
  upgrade_name?: string;
  upgrade_name_human?: string;
  science_name?: string;
  science_name_human?: string;
  power_name?: string;
  power_name_human?: string;
  icon_url?: string | null;
}

export interface TopOrder {
  order: string;
  count: number;
}

export interface PlayerReport {
  player_number: number;
  player_name: string;
  meaningful_actions: number;
  effective_apm: number;
  macro_actions: number;
  micro_actions: number;
  economy_actions: number;
  top_meaningful_orders: TopOrder[];
  timeline: TimelineItem[];
}

export interface ReplayMeta {
  start_time_utc?: string;
  end_time_utc?: string;
  duration_seconds_estimate?: number;
  map_file?: string;
  total_actions?: number;
  meaningful_actions_total?: number;
}

export interface AnalyzeReport {
  filename: string;
  replay: ReplayMeta;
  players: PlayerReport[];
  top_meaningful_orders_overall: TopOrder[];
  id_resolution?: {
    unresolved_template_ids?: { template_id: number; count: number }[];
    lookup_file?: string;
  };
}
