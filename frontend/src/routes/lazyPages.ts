import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

/**
 * Route code-splitting, in one place so the chunks can also be *prefetched*.
 *
 * Splitting alone made the first visit to each page worse, not better.
 * Throttled to the ~46 KB/s the droplet actually delivers, the first
 * navigation to a page cost 0.4–1.4 s of blank Suspense fallback while its
 * chunk downloaded — against ~250 ms for a repeat visit — and the cost came
 * back after every deploy, because the filenames are content-hashed.
 *
 * Keeping the loaders in a map lets the sidebar warm a chunk before the user
 * commits to the click, so the navigation they eventually make is instant.
 */
// These are route elements: React Router renders each as `<Page />` with no
// props, so a props type that admits none is the accurate one.
type PageComponent = ComponentType<Record<string, never>>;
type Loader = () => Promise<{ default: PageComponent }>;

const loaders = {
  '/dashboard': () => import('@/pages/DashboardPage'),
  '/leakage': () => import('@/pages/LeakagePage'),
  '/trips': () => import('@/pages/TripsPage'),
  '/trucks': () => import('@/pages/TrucksPage'),
  '/drivers': () => import('@/pages/DriversPage'),
  '/map': () => import('@/pages/MapViewPage'),
  '/queue': () => import('@/pages/BorderQueuePage'),
  '/geofences': () => import('@/pages/GeofencesPage'),
  '/maintenance': () => import('@/pages/MaintenancePage'),
  '/devices': () => import('@/pages/DevicesPage'),
  '/reports': () => import('@/pages/ReportsPage'),
  '/settings': () => import('@/pages/SettingsPage'),
  '/users': () => import('@/pages/UsersPage'),
  '/organizations': () => import('@/pages/OrganizationsPage'),
} as const satisfies Record<string, Loader>;

export type RoutePath = keyof typeof loaders;

/**
 * Chunks already requested. The browser caches a dynamic import itself; this
 * only avoids re-entering the module graph on every hover event.
 */
const warmed = new Set<string>();

/**
 * Start downloading a route's chunk without navigating to it.
 *
 * Called on hover and on focus of a sidebar link. A pointer resting on a link
 * is the earliest honest signal that the user is about to go there, and it
 * buys most of the time the download needs. Focus covers keyboard users, who
 * would otherwise be the only people still waiting.
 *
 * Failures are swallowed on purpose: this is speculative. If the chunk cannot
 * be had now, the real navigation asks for it again and Suspense shows the
 * loader exactly as it does today.
 */
export function prefetchRoute(path: string): void {
  if (warmed.has(path)) return;
  const load = (loaders as Record<string, Loader | undefined>)[path];
  if (!load) return;
  warmed.add(path);
  void load().catch(() => warmed.delete(path));
}

/**
 * Warm the sidebar's routes once the browser is idle.
 *
 * Hover prefetching only helps someone who reaches for the sidebar with a
 * mouse and pauses. This covers the first click of the session — otherwise the
 * slowest one they make — and every click on a touch screen, where there is no
 * hover to hang it on.
 *
 * Sequential, not parallel: firing fourteen requests at once on a ~46 KB/s
 * link would starve the data requests of the page the user is actually
 * looking at, trading a fast second navigation for a slow first screen.
 * Ordered by how likely a dispatcher is to want them.
 *
 * Skipped on a metered or slow connection, where a couple of hundred kilobytes
 * of speculation is a real cost the user did not ask for.
 */
export async function prefetchLikelyRoutes(): Promise<void> {
  const conn = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;
  if (conn?.saveData) return;
  if (conn?.effectiveType && /(^|-)2g$/.test(conn.effectiveType)) return;

  // Dashboard is the landing route and is already loaded by the time this runs.
  const order: RoutePath[] = [
    '/leakage',
    '/trips',
    '/trucks',
    '/drivers',
    '/reports',
    '/maintenance',
    '/queue',
    '/geofences',
    '/devices',
    '/settings',
  ];

  for (const path of order) {
    if (warmed.has(path)) continue;
    warmed.add(path);
    // Awaited so the chunks arrive one at a time. A failure is not worth
    // stopping the queue for: the next route may still be worth warming.
    await (loaders as Record<string, Loader | undefined>)[path]?.().catch(() => {
      warmed.delete(path);
    });
  }
}

/** Kick the queue off when the browser has nothing better to do. */
export function schedulePrefetch(): void {
  const idle = (window as unknown as {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void;
  }).requestIdleCallback;

  const run = () => void prefetchLikelyRoutes();
  // Safari still has no requestIdleCallback; a timeout is close enough for a
  // speculative fetch.
  if (idle) idle(run, { timeout: 4000 });
  else window.setTimeout(run, 2000);
}

export const lazyPages = Object.fromEntries(
  Object.entries(loaders).map(([path, load]) => [path, lazy(load as Loader)]),
) as Record<RoutePath, LazyExoticComponent<PageComponent>>;
