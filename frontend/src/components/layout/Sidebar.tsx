import React from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Truck,
  Map,
  FileText,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Wrench,
  Radio,
  Users,
  MapPin,
  Package,
  TrendingDown,
  ListChecks,
  Building2,
  UserCog
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import type { UserRole } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

// `roles` narrows an entry to specific roles; entries without it are for everyone.
// This only hides links — the routes and the API enforce the same rules for real.
interface NavItem {
  icon: typeof LayoutDashboard;
  labelKey: string;
  path: string;
  roles?: readonly UserRole[];
}

const navItems: readonly NavItem[] = [
  { icon: LayoutDashboard, labelKey: 'nav.dashboard', path: '/dashboard' },
  { icon: TrendingDown, labelKey: 'nav.leakage', path: '/leakage' },
  { icon: Package, labelKey: 'nav.trips', path: '/trips' },
  { icon: Truck, labelKey: 'nav.trucks', path: '/trucks' },
  { icon: Users, labelKey: 'nav.drivers', path: '/drivers' },
  { icon: Map, labelKey: 'nav.map', path: '/map' },
  { icon: ListChecks, labelKey: 'nav.queue', path: '/queue' },
  { icon: MapPin, labelKey: 'nav.geofences', path: '/geofences' },
  { icon: Wrench, labelKey: 'nav.maintenance', path: '/maintenance' },
  { icon: Radio, labelKey: 'nav.devices', path: '/devices' },
  { icon: FileText, labelKey: 'nav.reports', path: '/reports' },
  { icon: Settings, labelKey: 'nav.settings', path: '/settings' },
  { icon: UserCog, labelKey: 'nav.users', path: '/users', roles: ['admin'] },
  { icon: Building2, labelKey: 'nav.organizations', path: '/organizations', roles: ['superadmin'] },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const location = useLocation();
  const visibleItems = navItems.filter((item) => !item.roles || (user && item.roles.includes(user.role)));

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-screen bg-sidebar border-r border-sidebar-border transition-all duration-300',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex h-16 items-center justify-between border-b border-sidebar-border px-4">
          {!collapsed && (
            <div className="flex items-center gap-2 animate-fade-in">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
                <Truck className="h-5 w-5 text-primary-foreground" />
              </div>
              <span className="font-semibold text-sidebar-foreground">{t('app.name')}</span>
            </div>
          )}
          {collapsed && (
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary mx-auto">
              <Truck className="h-5 w-5 text-primary-foreground" />
            </div>
          )}
        </div>

        {/* Toggle button */}
        <Button
          variant="ghost"
          size="icon"
          className="absolute -right-3 top-20 z-50 h-6 w-6 rounded-full border border-sidebar-border bg-sidebar hover:bg-sidebar-accent"
          onClick={onToggle}
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3 text-sidebar-foreground" />
          ) : (
            <ChevronLeft className="h-3 w-3 text-sidebar-foreground" />
          )}
        </Button>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-3">
          {visibleItems.map((item) => {
            const isActive = location.pathname === item.path;
            const linkContent = (
              <NavLink
                key={item.path}
                to={item.path}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-sidebar-accent text-sidebar-primary shadow-sm'
                    : 'text-sidebar-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground',
                  collapsed && 'justify-center px-2'
                )}
              >
                <item.icon className={cn('h-5 w-5 shrink-0', isActive && 'text-sidebar-primary')} />
                {!collapsed && <span>{t(item.labelKey)}</span>}
              </NavLink>
            );

            if (collapsed) {
              return (
                <Tooltip key={item.path} delayDuration={0}>
                  <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                  <TooltipContent side="right" className="bg-popover text-popover-foreground">
                    {t(item.labelKey)}
                  </TooltipContent>
                </Tooltip>
              );
            }

            return linkContent;
          })}
        </nav>

        {/* Logout */}
        <div className="border-t border-sidebar-border p-3">
          {collapsed ? (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-full text-sidebar-foreground hover:bg-destructive/10 hover:text-destructive"
                  onClick={logout}
                >
                  <LogOut className="h-5 w-5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" className="bg-popover text-popover-foreground">
                {t('nav.logout')}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              className="w-full justify-start gap-3 text-sidebar-foreground hover:bg-destructive/10 hover:text-destructive"
              onClick={logout}
            >
              <LogOut className="h-5 w-5" />
              <span>{t('nav.logout')}</span>
            </Button>
          )}
        </div>
      </div>
    </aside>
  );
}
