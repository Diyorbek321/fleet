import { api } from '@/lib/api';

/**
 * Messages to a driver's phone. Mirrors `app/routers/driver_messages.py`;
 * snake_case kept for the same reason `ownerAlerts.ts` gives.
 */
export type DriverMessageKind = 'dispatcher' | 'gps_silent';

export interface DriverMessage {
  id: string;
  driver_id: string;
  truck_id: string | null;
  kind: DriverMessageKind;
  title: string;
  body: string;
  /** How many of the driver's phones took the push. 0 = inbox only. */
  devices_delivered: number;
  created_at: string;
  read_at: string | null;
}

export interface DriverMessageInput {
  title?: string;
  body: string;
}

export const driverMessagesApi = {
  list: (driverId: string) => api<DriverMessage[]>(`/api/drivers/${driverId}/messages`),
  send: (driverId: string, input: DriverMessageInput) =>
    api<DriverMessage>(`/api/drivers/${driverId}/messages`, { method: 'POST', body: input }),
};
