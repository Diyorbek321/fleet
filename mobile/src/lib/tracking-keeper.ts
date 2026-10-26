/**
 * Keeping location sharing on once the driver has switched it on.
 *
 * Sharing used to be a switch the driver could flip off — and the OS, a
 * reboot or a dead session could stop it too, with nothing turning it back
 * on. On the Angren TEK pilot most of the fleet went dark that way within a
 * week. Now there is no off switch: every time the app opens or returns to
 * the foreground this restarts tracking whenever "always" is granted.
 *
 * The OS calls are passed in so the decision can be tested without native
 * modules; the screen wires them to expo-location.
 */
export type TrackingState = 'live' | 'needs-always' | 'needs-permission' | 'signed-out';

export interface TrackingDeps {
  backgroundStatus: () => Promise<string>;
  foregroundStatus: () => Promise<string>;
  isRunning: () => Promise<boolean>;
  /** The server refused the session; restarting would only draw another 401. */
  sessionDead: () => Promise<boolean>;
  start: () => Promise<void>;
}

export async function keepTrackingAlive(deps: TrackingDeps): Promise<TrackingState> {
  if (await deps.sessionDead()) return 'signed-out';
  if ((await deps.backgroundStatus()) === 'granted') {
    try {
      if (!(await deps.isRunning())) await deps.start();
      return 'live';
    } catch {
      // The OS refused the start; say so rather than show a green card.
      return 'needs-permission';
    }
  }
  return (await deps.foregroundStatus()) === 'granted' ? 'needs-always' : 'needs-permission';
}
