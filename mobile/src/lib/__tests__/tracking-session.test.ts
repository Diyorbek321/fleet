import { clearSessionDead, isSessionDead, markSessionDead } from '../tracking-session';

describe('tracking session flag', () => {
  it('is set by a refused ping and cleared by signing in', async () => {
    expect(await isSessionDead()).toBe(false);
    await markSessionDead();
    expect(await isSessionDead()).toBe(true);
    await clearSessionDead();
    expect(await isSessionDead()).toBe(false);
  });
});
