import { api } from '@/lib/api';

/** Normalized CarGoRuqsat border-queue statuses (see backend app/services/cgr.py). */
export type QueueStatus =
  | 'in_queue'
  | 'late'
  | 'crossed'
  | 'check_failed'
  | 'revoked'
  | 'none'
  | 'unknown';

/** A driver's border-queue watch as shown on the manager panel (camelCase). */
export interface QueueRow {
  watchId: string;
  driverId: string;
  driverName: string;
  plate: string;
  checkpoint: string;
  country: string | null;
  active: boolean;
  lastStatus: QueueStatus | null;
  lastSeenQueueAt: Date | null;
  updatedAt: Date;
}

/** Raw shape returned by the backend (snake_case JSON from OrgQueueRowOut). */
interface BackendQueueRow {
  watch_id: string;
  driver_id: string;
  driver_name: string;
  plate: string;
  checkpoint: string;
  country: string | null;
  active: boolean;
  last_status: string | null;
  last_seen_queue_at: string | null;
  updated_at: string;
}

function adapt(r: BackendQueueRow): QueueRow {
  return {
    watchId: r.watch_id,
    driverId: r.driver_id,
    driverName: r.driver_name,
    plate: r.plate,
    checkpoint: r.checkpoint,
    country: r.country,
    active: r.active,
    lastStatus: (r.last_status as QueueStatus | null) ?? null,
    lastSeenQueueAt: r.last_seen_queue_at ? new Date(r.last_seen_queue_at) : null,
    updatedAt: new Date(r.updated_at),
  };
}

export async function listQueue(): Promise<QueueRow[]> {
  const data = await api<BackendQueueRow[]>('/api/queue');
  return data.map(adapt);
}

export async function refreshQueue(): Promise<QueueRow[]> {
  const data = await api<BackendQueueRow[]>('/api/queue/refresh', { method: 'POST' });
  return data.map(adapt);
}
