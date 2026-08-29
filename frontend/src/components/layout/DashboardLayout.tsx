import React, { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopNavbar } from './TopNavbar';
import { cn } from '@/lib/utils';
import { ChangePasswordDialog } from '@/components/ChangePasswordDialog';
import { SupportSessionBanner } from '@/components/SupportSessionBanner';
import { useAuth } from '@/contexts/AuthContext';
import { schedulePrefetch } from '@/routes/lazyPages';

export function DashboardLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { user } = useAuth();

  // Mounted at the layout, not on one page: an account still on an admin-set
  // password must be stopped wherever it lands after signing in, not only if
  // it happens to visit Settings.
  const mustChangePassword = !!user?.must_change_password;

  // Warm the money screens once the browser is idle. Hover prefetching only
  // helps a user who reaches for the sidebar; this covers the first click of
  // the session, which is otherwise the slowest one they make.
  useEffect(() => {
    schedulePrefetch();
  }, []);

  return (
    <>
      <ChangePasswordDialog open={mustChangePassword} onOpenChange={() => {}} forced />
      {/* Above everything, on every screen: what is behind it belongs to
          somebody else. */}
      <SupportSessionBanner />
      <div className="min-h-screen bg-background">
        {/* Sidebar - hidden on mobile */}
        <div className="hidden lg:block">
          <Sidebar
            collapsed={sidebarCollapsed}
            onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
          />
        </div>

        {/* Mobile sidebar overlay */}
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileMenuOpen(false)}
          >
            <div className="fixed inset-y-0 left-0 w-64" onClick={(e) => e.stopPropagation()}>
              <Sidebar collapsed={false} onToggle={() => setMobileMenuOpen(false)} />
            </div>
          </div>
        )}

        {/* Main content */}
        <div
          className={cn(
            'min-h-screen transition-all duration-300',
            sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
          )}
        >
          <TopNavbar onMenuClick={() => setMobileMenuOpen(true)} />
          <main className="p-4 lg:p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </>
  );
}
