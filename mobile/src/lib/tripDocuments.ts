/**
 * Once a trip is delivered its paperwork is what the trip was settled on, so
 * the driver can no longer delete, relabel or retake a photo — only the desk
 * can. Mirrors `_my_editable_document` in backend/app/routers/me/trips.py.
 */
const CLOSED = new Set(['delivered', 'cancelled']);

export function documentsLocked(tripStatus: string): boolean {
  return CLOSED.has(tripStatus);
}
