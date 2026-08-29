import { apiFetch } from './api';

export type QueueStatusValue =
  | 'in_queue'
  | 'late'
  | 'crossed'
  | 'check_failed'
  | 'revoked'
  | 'none'
  | 'unknown';

export interface QueueStatus {
  plate: string;
  checkpoint: string;
  /** Start and end of the booked slot. The registry books an hour-long window,
   *  so the end is the deadline the driver is actually working against. */
  queue_at: string | null;
  queue_until: string | null;
  status: QueueStatusValue;
  raw_status: string;
}

export interface QueueWatch {
  id: string;
  plate: string;
  checkpoint: string;
  country: string | null;
  active: boolean;
  last_status: string | null;
  last_seen_queue_at: string | null;
  created_at: string;
}

export interface QueueRefresh {
  status: QueueStatus | null;
  changed: boolean;
}

/** Maps to the backend's `/api/me/queue/*` endpoints. */
export const queueApi = {
  status: () => apiFetch<QueueStatus | null>('/api/me/queue/status'),
  getWatch: () => apiFetch<QueueWatch | null>('/api/me/queue/watch'),
  setWatch: (checkpoint: string, country?: string | null) =>
    apiFetch<QueueWatch>('/api/me/queue/watch', {
      method: 'PUT',
      body: JSON.stringify({ checkpoint, country: country || null }),
    }),
  stopWatch: () =>
    apiFetch<{ message: string }>('/api/me/queue/watch', { method: 'DELETE' }),
  refresh: () => apiFetch<QueueRefresh>('/api/me/queue/refresh', { method: 'POST' }),
  handoff: () => apiFetch<{ url: string }>('/api/me/queue/handoff'),
};
