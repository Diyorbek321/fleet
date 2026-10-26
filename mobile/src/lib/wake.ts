/** Reading the server's data-only "wake" push — see app/services/phone_wake.py. */

export function isWake(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return false;
  const data = (payload as { data?: Record<string, unknown> }).data;
  if (!data) return false;
  if (data.kind === 'wake') return true;
  if (typeof data.dataString !== 'string') return false;
  try {
    return (JSON.parse(data.dataString) as { kind?: unknown }).kind === 'wake';
  } catch {
    return false;
  }
}
