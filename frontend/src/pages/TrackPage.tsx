import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { MapContainer, Marker, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

import { ApiError } from '@/lib/api';
import { trackApi, type Track } from '@/lib/track';
import { Badge } from '@/components/ui/badge';

/**
 * "Where is my cargo" — the page behind the map link in the customer's
 * Telegram card. No sidebar, no login, no fleet: one lorry, its plate, its
 * route and the date it is expected. Everything on it is already in the
 * message; the page exists so the position is a place on a map rather than a
 * pair of decimal degrees.
 */

// Tashkent, as a fallback centre for a trip whose lorry has never reported.
const UZBEKISTAN_CENTER: [number, number] = [41.2995, 69.2401];

/** The lorry: a green dot. Its plate rides above it as a permanent tooltip
 *  (see `.truck-plate` in index.css), so a screenshot of this page still says
 *  which vehicle it was. */
function truckIcon(): L.DivIcon {
  return L.divIcon({
    className: 'track-truck-marker',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
    html: `
      <div style="
        width:34px;height:34px;background:#22c55e;
        border:3px solid rgba(255,255,255,0.95);border-radius:50%;
        display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 10px rgba(0,0,0,0.35);">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
          <path d="M10 17h4V5a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3z"/>
          <path d="M14 9h4l3 3v5a2 2 0 0 1-2 2h-1"/>
          <circle cx="7.5" cy="17.5" r="2.5"/>
          <circle cx="17.5" cy="17.5" r="2.5"/>
        </svg>
      </div>`,
  });
}

function endpointIcon(kind: 'origin' | 'destination'): L.DivIcon {
  const color = kind === 'origin' ? '#64748b' : '#2563eb';
  return L.divIcon({
    className: 'track-endpoint-marker',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};
             border:3px solid #ffffff;box-shadow:0 1px 5px rgba(0,0,0,0.35);"></div>`,
  });
}

type LatLng = [number, number];

function point(p: { latitude: number | null; longitude: number | null }): LatLng | null {
  return p.latitude !== null && p.longitude !== null ? [p.latitude, p.longitude] : null;
}

export default function TrackPage() {
  const { t, i18n } = useTranslation();
  const { token = '' } = useParams<{ token: string }>();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['track', token],
    queryFn: () => trackApi.get(token),
    enabled: !!token,
    // A lorry moves; a customer who leaves this open on a second screen should
    // see it move too, without a reload.
    refetchInterval: 60_000,
    retry: false,
  });

  const geometry = useMemo(() => {
    if (!data) return { points: [] as LatLng[], center: UZBEKISTAN_CENTER, zoom: 6 };
    const here = data.position ? ([data.position.latitude, data.position.longitude] as LatLng) : null;
    const points = [point(data.origin), here, point(data.destination)].filter(
      (p): p is LatLng => p !== null,
    );
    return {
      points,
      center: here ?? points[0] ?? UZBEKISTAN_CENTER,
      zoom: here ? 7 : 5,
    };
  }, [data]);

  if (isLoading) {
    return <Centered>{t('common.loading')}</Centered>;
  }
  if (isError || !data) {
    // 409 is a real link to a trip that has not started: the page keeps polling,
    // so it opens by itself once the lorry is on its way.
    const notStarted = error instanceof ApiError && error.status === 409;
    return (
      <Centered>
        <div className="max-w-sm space-y-2 text-center">
          <p className="text-lg font-semibold">
            {t(notStarted ? 'track.notStartedTitle' : 'track.unavailableTitle')}
          </p>
          <p className="text-sm text-muted-foreground">
            {t(notStarted ? 'track.notStartedBody' : 'track.unavailableBody')}
          </p>
        </div>
      </Centered>
    );
  }

  const fmtDate = (d: Date) => d.toLocaleDateString(i18n.language);
  const fmtDateTime = (d: Date) => d.toLocaleString(i18n.language);
  /** The ETA is a calendar date, not an instant, so it is reordered as text
   *  rather than pushed through Date and a timezone on the way. */
  const fmtIsoDay = (iso: string) => iso.split('-').reverse().join('.');

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-background">
      <MapContainer
        center={geometry.center}
        zoom={geometry.zoom}
        className="absolute inset-0 z-0"
        style={{ background: '#0b1220' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        {/* A straight line between the known points, drawn dashed so it is
            read as "this is the run", not as "this is the road taken". */}
        {geometry.points.length > 1 && (
          <Polyline positions={geometry.points} pathOptions={{ color: '#2563eb', weight: 3, dashArray: '6 8', opacity: 0.7 }} />
        )}

        {point(data.origin) && <Marker position={point(data.origin)!} icon={endpointIcon('origin')} />}
        {point(data.destination) && (
          <Marker position={point(data.destination)!} icon={endpointIcon('destination')} />
        )}
        {data.position && (
          <Marker position={[data.position.latitude, data.position.longitude]} icon={truckIcon()}>
            {data.plate && (
              <Tooltip permanent direction="top" offset={[0, -18]} className="truck-plate">
                {data.plate}
              </Tooltip>
            )}
          </Marker>
        )}
      </MapContainer>

      {/* The card, over the map rather than beside it: on the phone this is
          opened on, a side panel would be the whole screen. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 p-3 sm:p-4">
        <div className="pointer-events-auto mx-auto max-w-md rounded-xl border border-border bg-card/95 p-4 shadow-elevated backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold">{data.orgName}</h1>
              <p className="truncate text-sm text-muted-foreground">
                {(data.origin.name ?? '—')} → {(data.destination.name ?? '—')}
              </p>
            </div>
            {data.plate && <Badge variant="secondary" className="font-mono shrink-0">{data.plate}</Badge>}
          </div>

          <dl className="mt-3 space-y-1.5 text-sm">
            <Row label={t('track.reference')} value={data.reference} />
            {data.cargo && <Row label={t('track.cargo')} value={data.cargo} />}
            {data.loadedAt && <Row label={t('track.loadedAt')} value={fmtDate(data.loadedAt)} />}
            {data.stage && <Row label={t('track.stage')} value={data.stage} />}
            {data.position?.place && <Row label={t('track.where')} value={data.position.place} />}
            {data.etaCustoms && (
              <Row
                label={t('track.eta')}
                value={
                  fmtIsoDay(data.etaCustoms) +
                  (data.etaIsMeasured ? '' : ` ${t('track.etaApprox')}`)
                }
              />
            )}
          </dl>

          {data.position && (
            <p className="mt-3 text-xs text-muted-foreground">
              {t('track.updatedAt', { time: fmtDateTime(data.position.recordedAt) })}
            </p>
          )}
          {!data.position && (
            <p className="mt-3 text-xs text-muted-foreground">{t('track.noPosition')}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right font-medium">{value}</dd>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh w-full items-center justify-center bg-background p-6 text-muted-foreground">
      {children}
    </div>
  );
}
