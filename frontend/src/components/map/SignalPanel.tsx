import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, Phone, SatelliteDish } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { formatDistanceToNow } from '@/lib/datetime';
import { fetchTruckSignal, type SignalState, type TruckSignal } from '@/lib/signal';

type Problem = Exclude<SignalState, 'ok'>;

/** Most actionable first, matching the backend's own priority. */
const ORDER: readonly SignalState[] = ['no_driver', 'gps_off', 'never', 'silent'];

const DOT: Record<Problem, string> = {
  no_driver: 'bg-muted-foreground',
  gps_off: 'bg-destructive',
  never: 'bg-destructive',
  silent: 'bg-status-stopped',
};

interface SignalPanelProps {
  /** Called with a truck that has a last position, so the map can fly to it. */
  onSelect: (truckId: string) => void;
}

/**
 * Every truck the map cannot show live, with why.
 *
 * The map draws only trucks that have a position, so a truck whose driver
 * never switched sharing on was simply absent — and an absent truck reads as
 * a complete map. This lists them, plus the ones whose position went stale.
 */
export function SignalPanel({ onSelect }: SignalPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { data = [] } = useQuery({
    queryKey: ['trucks', 'signal'],
    queryFn: fetchTruckSignal,
    refetchInterval: 60_000,
  });

  const problems = data
    .filter((s) => s.state !== 'ok')
    .sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state));

  if (data.length === 0) return null;

  if (problems.length === 0) {
    return (
      <Card className="absolute bottom-4 right-4 z-10 border-border/50 bg-card/90 backdrop-blur-sm shadow-card">
        <CardContent className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
          <SatelliteDish className="h-4 w-4 text-status-moving" />
          {t('map.signal.allOk')}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="absolute bottom-4 right-4 z-10 w-80 max-w-[calc(100%-2rem)] border-border/50 bg-card/95 backdrop-blur-sm shadow-elevated">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 p-3 text-sm font-medium"
      >
        <SatelliteDish className="h-4 w-4 text-destructive" />
        <span className="flex-1 text-left">{t('map.signal.title', { count: problems.length })}</span>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
      </button>
      {open && (
        <ul className="max-h-[50vh] overflow-y-auto border-t border-border/50">
          {problems.map((s) => (
            <SignalRow key={s.truckId} signal={s} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Battery, tracking mode and app version — the likely reason it went quiet. */
function PhoneState({ signal }: { signal: TruckSignal }) {
  const { t } = useTranslation();
  const parts: { text: string; warn: boolean }[] = [];
  if (signal.phoneBattery !== null) {
    const pct = Math.round(signal.phoneBattery * 100);
    parts.push({ text: t('map.signal.battery', { pct }), warn: pct <= 15 });
  }
  if (signal.phoneTracking === 'foreground') {
    parts.push({ text: t('map.signal.foregroundOnly'), warn: true });
  }
  if (signal.phoneAppVersion) parts.push({ text: `v${signal.phoneAppVersion}`, warn: false });
  if (parts.length === 0) return null;
  return (
    <div className="mt-0.5 flex flex-wrap gap-x-2 pl-[18px] text-[11px]">
      {parts.map((p) => (
        <span key={p.text} className={p.warn ? 'text-destructive' : 'text-muted-foreground'}>
          {p.text}
        </span>
      ))}
    </div>
  );
}

function SignalRow({ signal, onSelect }: { signal: TruckSignal; onSelect: (id: string) => void }) {
  const { t } = useTranslation();
  const state = signal.state as Problem;
  const since = signal.gpsDisabledAt ?? signal.lastFixAt;

  return (
    <li className="border-b border-border/30 px-3 py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[state]}`} />
        {signal.lastFixAt ? (
          <button
            type="button"
            onClick={() => onSelect(signal.truckId)}
            className="font-medium hover:underline"
          >
            {signal.plateNumber}
          </button>
        ) : (
          <span className="font-medium">{signal.plateNumber}</span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{t(`map.signal.state.${state}`)}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-2 pl-[18px] text-xs text-muted-foreground">
        {signal.driverName && <span className="truncate">{signal.driverName}</span>}
        {signal.driverPhone && (
          <a href={`tel:${signal.driverPhone}`} className="inline-flex items-center gap-1 text-primary hover:underline">
            <Phone className="h-3 w-3" />
            {signal.driverPhone}
          </a>
        )}
        {since && state !== 'no_driver' && (
          <span className="ml-auto shrink-0">{formatDistanceToNow(since, { addSuffix: true })}</span>
        )}
      </div>
      <PhoneState signal={signal} />
    </li>
  );
}
