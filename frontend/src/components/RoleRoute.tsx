import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import type { UserRole } from '@/lib/api';

/**
 * Where a freshly logged-in user belongs. A superadmin owns no trucks, drivers or
 * trips, so the fleet dashboard would greet them with a wall of zeroes — their
 * home is the customer list instead.
 */
export function landingPathFor(role: UserRole | undefined): string {
  return role === 'superadmin' ? '/organizations' : '/dashboard';
}

interface RoleRouteProps {
  /** Roles allowed through. Anyone else is bounced, never shown the page. */
  allow: readonly UserRole[];
}

/**
 * Second gate, nested inside <ProtectedRoute />: that one answers "are you logged
 * in?", this one answers "may *you* be here?".
 *
 * The redirect target is the dashboard rather than a 403 screen because every
 * blocked case here is a user who simply followed a link meant for someone else —
 * the backend is the real authority (these routes 403 server-side regardless), so
 * this is about not rendering a page that would only fill up with errors.
 */
export function RoleRoute({ allow }: RoleRouteProps) {
  const { user } = useAuth();

  if (!user || !allow.includes(user.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}
