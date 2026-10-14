import { ApiError, api, tokenStorage } from '@/lib/api';
import type { GeneratedReportFile } from '@/lib/reports';
import type { TripStatus } from '@/lib/trips';

/**
 * The fleet board — every truck, where it is, its export and import — and the
 * dispatchers' group it goes to each morning. Mirrors `app/routers/fleet_board.py`.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export interface BoardTrip {
  trip_id: string;
  reference: string;
  route: string;
  /** Tashkent dates, `YYYY-MM-DD`. */
  loading_date: string | null;
  unloading_date: string | null;
  is_loaded: boolean;
  status: TripStatus;
}

export interface BoardRow {
  position: number;
  truck_id: string;
  plate: string;
  /** The town the GPS last saw the truck in. */
  location: string | null;
  location_at: string | null;
  export_trip: BoardTrip | null;
  import_trip: BoardTrip | null;
}

export interface FleetBoard {
  day: string;
  rows: BoardRow[];
}

export type DispatchGroupStatus = 'none' | 'pending' | 'linked' | 'lost';

export interface DispatchGroup {
  status: DispatchGroupStatus;
  chat_title: string | null;
  activated_at: string | null;
  board_sent_on: string | null;
  /** Only while pending: the `startgroup` link that adds the bot to a group. */
  deep_link: string | null;
}

const GROUP = '/api/fleet-board/telegram-group';

export const fleetBoardApi = {
  get: () => api<FleetBoard>('/api/fleet-board'),

  xlsx: async (): Promise<GeneratedReportFile> => {
    const token = tokenStorage.getAccess();
    const res = await fetch(`${BASE_URL}/api/fleet-board.xlsx`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    const disposition = res.headers.get('Content-Disposition') ?? '';
    const filename = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? 'avtopark.xlsx';
    return { filename, blob: await res.blob() };
  },

  group: () => api<DispatchGroup>(GROUP),
  linkGroup: () => api<DispatchGroup>(GROUP, { method: 'POST' }),
  unlinkGroup: () => api<DispatchGroup>(GROUP, { method: 'DELETE' }),
  sendNow: () => api<DispatchGroup>(`${GROUP}/send`, { method: 'POST' }),
};
