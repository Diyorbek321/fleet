import { format } from '@/lib/datetime';
import type { Trip, TripSubscription } from '@/lib/trips';

/** The trip facts printed beside a cargo owner's link. */
export type TripLinkFacts = Pick<Trip, 'reference' | 'originName' | 'destinationName' | 'scheduledEnd'>;

type Translate = (key: string) => string;

/** Where from, where to, and the unloading date — each null when not known. */
export function tripLinkFacts(trip: TripLinkFacts): { from: string | null; to: string | null; unloading: string | null } {
  return {
    from: trip.originName?.trim() || null,
    to: trip.destinationName?.trim() || null,
    unloading: trip.scheduledEnd ? format(trip.scheduledEnd, 'dd.MM.yyyy') : null,
  };
}

/**
 * The block the dispatcher pastes to a cargo owner: the trip in three lines
 * and the links under it, so the message stands on its own in whatever chat
 * it lands in. Lines with nothing to say are left out, not printed as dashes.
 */
export function buildTripLinkText(trip: TripLinkFacts, sub: Pick<TripSubscription, 'deepLink' | 'trackUrl'>, t: Translate): string {
  const { from, to, unloading } = tripLinkFacts(trip);
  const lines = [
    `${t('tripSubscriptions.copyText.trip')}: ${trip.reference}`,
    from && `${t('tripSubscriptions.copyText.from')}: ${from}`,
    to && `${t('tripSubscriptions.copyText.to')}: ${to}`,
    unloading && `${t('tripSubscriptions.copyText.unloading')}: ${unloading}`,
    '',
    sub.trackUrl && `${t('tripSubscriptions.copyText.map')}: ${sub.trackUrl}`,
    `${t('tripSubscriptions.copyText.telegram')}: ${sub.deepLink}`,
  ];
  return lines.filter((line): line is string => typeof line === 'string').join('\n');
}
