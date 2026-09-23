import { api } from '@/lib/api';

/**
 * The cargo owner's view of one load — no account, no session.
 *
 * The token in the URL is the whole credential, and it is the same one already
 * in their Telegram deep link. Requests go out with `auth: false` so a
 * dispatcher who happens to be signed in on the same browser does not have
 * their bearer token attached to a public page's calls.
 */

export interface TrackPlace {
  name: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface TrackPosition {
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
  place: string | null;
  recordedAt: Date;
}

export interface Track {
  orgName: string;
  reference: string;
  cargo: string | null;
  plate: string | null;
  stage: string | null;
  loadedAt: Date | null;
  /** An ISO calendar date ("2026-09-24"), kept as text on purpose: parsed into
   *  a Date it becomes UTC midnight, and a viewer behind UTC would be shown the
   *  day before the one the fleet quoted. */
  etaCustoms: string | null;
  etaIsMeasured: boolean;
  origin: TrackPlace;
  destination: TrackPlace;
  position: TrackPosition | null;
}

interface BackendPlace {
  name: string | null;
  latitude: number | null;
  longitude: number | null;
}

interface BackendTrack {
  org_name: string;
  reference: string;
  cargo: string | null;
  plate: string | null;
  stage: string | null;
  loaded_at: string | null;
  eta_customs: string | null;
  eta_is_measured: boolean;
  origin: BackendPlace;
  destination: BackendPlace;
  position: {
    latitude: number;
    longitude: number;
    speed: number;
    heading: number | null;
    place: string | null;
    recorded_at: string;
  } | null;
}

function adapt(d: BackendTrack): Track {
  return {
    orgName: d.org_name,
    reference: d.reference,
    cargo: d.cargo,
    plate: d.plate,
    stage: d.stage,
    loadedAt: d.loaded_at ? new Date(d.loaded_at) : null,
    etaCustoms: d.eta_customs,
    etaIsMeasured: d.eta_is_measured,
    origin: d.origin,
    destination: d.destination,
    position: d.position
      ? {
          latitude: d.position.latitude,
          longitude: d.position.longitude,
          speed: d.position.speed,
          heading: d.position.heading,
          place: d.position.place,
          recordedAt: new Date(d.position.recorded_at),
        }
      : null,
  };
}

export const trackApi = {
  get: async (token: string): Promise<Track> =>
    adapt(await api<BackendTrack>(`/api/track/${encodeURIComponent(token)}`, { auth: false })),
};
