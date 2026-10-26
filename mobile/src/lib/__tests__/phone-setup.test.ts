/**
 * Xiaomi, Huawei, Oppo and Vivo kill a backgrounded app's location service
 * unless the app is on the maker's own "autostart" list — a screen every maker
 * hides somewhere different. Opening the right one is the whole fix.
 */
import { autostartTargets, needsAutostart } from '../phone-setup';

describe('autostartTargets', () => {
  it('opens MIUI security center on Xiaomi, Redmi and POCO', () => {
    for (const maker of ['Xiaomi', 'Redmi', 'POCO']) {
      expect(autostartTargets(maker)[0].packageName).toBe('com.miui.securitycenter');
    }
  });

  it('knows Huawei and Honor, Oppo and Realme, and Vivo', () => {
    expect(autostartTargets('HUAWEI')[0].packageName).toBe('com.huawei.systemmanager');
    expect(autostartTargets('HONOR')[0].packageName).toBe('com.huawei.systemmanager');
    expect(autostartTargets('OPPO')[0].packageName).toBe('com.coloros.safecenter');
    expect(autostartTargets('realme')[0].packageName).toBe('com.coloros.safecenter');
    expect(autostartTargets('vivo')[0].packageName).toBe('com.vivo.permissionmanager');
  });

  it('has nothing to open on a phone without such a list', () => {
    expect(autostartTargets('Google')).toEqual([]);
    expect(autostartTargets(undefined)).toEqual([]);
  });
});

describe('needsAutostart', () => {
  it('asks only on the makers that need it', () => {
    expect(needsAutostart('Xiaomi')).toBe(true);
    expect(needsAutostart('samsung')).toBe(false);
  });
});
