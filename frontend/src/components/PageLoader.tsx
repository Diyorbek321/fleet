/**
 * Fallback shown while a lazy-loaded route chunk is being fetched.
 * Matches the spinner used in ProtectedRoute for visual consistency.
 */
export function PageLoader() {
  return (
    <div className="flex h-[60vh] w-full items-center justify-center">
      <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
    </div>
  );
}
