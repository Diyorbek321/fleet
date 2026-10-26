/**
 * Sharing is switched on once and then kept on: every time the app opens or
 * comes back to the foreground it restarts tracking that the OS, a reboot or
 * a dead session stopped — without asking the driver again.
 */
import { keepTrackingAlive, type TrackingDeps } from '../tracking-keeper';

function deps(overrides: Partial<TrackingDeps> = {}): TrackingDeps & { start: jest.Mock } {
  return {
    backgroundStatus: async () => 'granted',
    foregroundStatus: async () => 'granted',
    isRunning: async () => false,
    sessionDead: async () => false,
    start: jest.fn(async () => {}),
    ...overrides,
  } as TrackingDeps & { start: jest.Mock };
}

describe('keepTrackingAlive', () => {
  it('restarts tracking that stopped while "always" is granted', async () => {
    const d = deps();
    expect(await keepTrackingAlive(d)).toBe('live');
    expect(d.start).toHaveBeenCalledTimes(1);
  });

  it('leaves running tracking alone', async () => {
    const d = deps({ isRunning: async () => true });
    expect(await keepTrackingAlive(d)).toBe('live');
    expect(d.start).not.toHaveBeenCalled();
  });

  it('asks for "always" when only while-in-use was granted', async () => {
    const d = deps({ backgroundStatus: async () => 'denied' });
    expect(await keepTrackingAlive(d)).toBe('needs-always');
    expect(d.start).not.toHaveBeenCalled();
  });

  it('asks the driver to switch it on when nothing was granted', async () => {
    const d = deps({
      backgroundStatus: async () => 'undetermined',
      foregroundStatus: async () => 'undetermined',
    });
    expect(await keepTrackingAlive(d)).toBe('needs-permission');
  });

  it('reports a start the OS refused instead of claiming it is live', async () => {
    const d = deps({ start: jest.fn(async () => { throw new Error('refused'); }) });
    expect(await keepTrackingAlive(d)).toBe('needs-permission');
  });

  it('does not restart tracking on a session the server already refused', async () => {
    // Restarting would draw another 401, another stop and another "sign in
    // again" notification every minute the app stays open.
    const d = deps({ sessionDead: async () => true });
    expect(await keepTrackingAlive(d)).toBe('signed-out');
    expect(d.start).not.toHaveBeenCalled();
  });
});
