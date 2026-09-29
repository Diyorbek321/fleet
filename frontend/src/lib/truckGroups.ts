import { api } from '@/lib/api';

/**
 * A truck's Telegram group and the order sheet posted there. Mirrors
 * `app/routers/truck_groups.py`, the order endpoints in `app/routers/trips.py`
 * and the template in `app/routers/org_settings.py`.
 */
export type TruckGroupStatus = 'none' | 'pending' | 'linked' | 'lost';

export interface TruckGroup {
  status: TruckGroupStatus;
  chat_title: string | null;
  activated_at: string | null;
  /** Only while pending: the `startgroup` link that adds the bot to a group. */
  deep_link: string | null;
}

export interface TripOrderText {
  html: string;
  text: string;
  sent_at: string | null;
}

export interface TripOrderTemplate {
  /** null = the built-in list. */
  rules: string | null;
  footer: string | null;
  default_rules: string;
}

export const truckGroupsApi = {
  get: (truckId: string) => api<TruckGroup>(`/api/trucks/${truckId}/telegram-group`),
  link: (truckId: string) =>
    api<TruckGroup>(`/api/trucks/${truckId}/telegram-group`, { method: 'POST' }),
  unlink: (truckId: string) =>
    api<TruckGroup>(`/api/trucks/${truckId}/telegram-group`, { method: 'DELETE' }),

  orderText: (tripId: string) => api<TripOrderText>(`/api/trips/${tripId}/order-text`),
  sendOrder: (tripId: string) =>
    api<{ sent_at: string }>(`/api/trips/${tripId}/send-order`, { method: 'POST' }),

  template: () => api<TripOrderTemplate>('/api/org/trip-order-template'),
  saveTemplate: (input: { rules: string | null; footer: string | null }) =>
    api<TripOrderTemplate>('/api/org/trip-order-template', { method: 'PUT', body: input }),
};
