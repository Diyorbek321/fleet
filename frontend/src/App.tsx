import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { MaintenanceProvider } from "@/contexts/MaintenanceContext";
import { TruckProvider } from "@/contexts/TruckContext";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RoleRoute } from "@/components/RoleRoute";
import { PageLoader } from "@/components/PageLoader";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import LoginPage from "@/pages/LoginPage";
import { lazyPages } from "@/routes/lazyPages";

// Lazy-load page routes so heavy dependencies (Leaflet maps, Recharts reports,
// etc.) are split into their own chunks and only fetched on demand. The auth
// and layout shell above stays eager so the app boots fast.
//
// The sidebar's fourteen destinations come from `@/routes/lazyPages`, which
// owns the same loaders the sidebar prefetches on hover — one registry, so a
// route can never be split here and left un-warmable there. The rest are
// detail views reached from inside a page, where there is no link to hover.
const TruckDetailPage = lazy(() => import("@/pages/TruckDetailPage"));
const DriverDetailPage = lazy(() => import("@/pages/DriverDetailPage"));
const TripDetailPage = lazy(() => import("@/pages/TripDetailPage"));
const TripReportPrintPage = lazy(() => import("@/pages/TripReportPrintPage"));
const NotFound = lazy(() => import("./pages/NotFound"));

const LazyDashboardPage = lazyPages["/dashboard"];
const LazyTrucksPage = lazyPages["/trucks"];
const LazyDriversPage = lazyPages["/drivers"];
const LazyTripsPage = lazyPages["/trips"];
const LazyLeakagePage = lazyPages["/leakage"];
const LazyMapViewPage = lazyPages["/map"];
const LazyBorderQueuePage = lazyPages["/queue"];
const LazyGeofencesPage = lazyPages["/geofences"];
const LazyMaintenancePage = lazyPages["/maintenance"];
const LazyDevicesPage = lazyPages["/devices"];
const LazyReportsPage = lazyPages["/reports"];
const LazySettingsPage = lazyPages["/settings"];
const LazyOrganizationsPage = lazyPages["/organizations"];
const LazyUsersPage = lazyPages["/users"];

/**
 * Query defaults, tuned for the link this app is actually used over.
 *
 * The defaults are built for a fast network: `staleTime: 0` refetches every
 * query the moment a component mounts, so every trip between two pages fired
 * the whole page's requests again even though the answers were seconds old.
 * `gcTime: 5min` then threw the answers away, so coming back to a screen after
 * a coffee meant a spinner rather than instant content. And three retries with
 * backoff turned one failed request on a flaky connection into a stall of
 * several seconds before the user was told anything at all.
 *
 * Measured against the droplet's real throughput (~46 KB/s, ~150 ms RTT).
 * Screens that genuinely need live data set their own `refetchInterval`; these
 * are the floor, not a ceiling.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Long enough that moving between screens re-uses what was just fetched,
      // short enough that a dispatcher acting on a number is not acting on
      // something from a different shift.
      staleTime: 30_000,
      // Keep answers around well past staleTime, so a return visit renders
      // instantly from cache and refreshes behind the content rather than
      // replacing it with a loader.
      gcTime: 10 * 60_000,
      // Alt-tabbing back should not re-request every screen at once on a
      // connection this narrow. The pages that must stay live poll explicitly.
      refetchOnWindowFocus: false,
      // One retry absorbs a dropped packet; three only delays the error
      // message the user needs in order to retry themselves.
      retry: 1,
    },
  },
});

const App = () => (
  <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <AuthProvider>
            <TruckProvider>
              <MaintenanceProvider>
                <Suspense fallback={<PageLoader />}>
                  <Routes>
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route element={<ProtectedRoute />}>
                    <Route path="/trips/:id/report/print" element={<TripReportPrintPage />} />
                    <Route element={<DashboardLayout />}>
                      <Route path="/dashboard" element={<LazyDashboardPage />} />
                      <Route path="/trucks" element={<LazyTrucksPage />} />
                      <Route path="/trucks/:id" element={<TruckDetailPage />} />
                      <Route path="/drivers" element={<LazyDriversPage />} />
                      <Route path="/drivers/:id" element={<DriverDetailPage />} />
                      <Route path="/trips" element={<LazyTripsPage />} />
                      <Route path="/trips/:id" element={<TripDetailPage />} />
                      <Route path="/leakage" element={<LazyLeakagePage />} />
                      <Route path="/map" element={<LazyMapViewPage />} />
                      <Route path="/queue" element={<LazyBorderQueuePage />} />
                      <Route path="/geofences" element={<LazyGeofencesPage />} />
                      <Route path="/maintenance" element={<LazyMaintenancePage />} />
                      <Route path="/devices" element={<LazyDevicesPage />} />
                      <Route path="/reports" element={<LazyReportsPage />} />
                      <Route path="/settings" element={<LazySettingsPage />} />
                      {/* Platform console: only we (the vendor) see other companies. */}
                      <Route element={<RoleRoute allow={["superadmin"]} />}>
                        <Route path="/organizations" element={<LazyOrganizationsPage />} />
                      </Route>
                      {/* A company's own admin managing its staff accounts. */}
                      <Route element={<RoleRoute allow={["admin"]} />}>
                        <Route path="/users" element={<LazyUsersPage />} />
                      </Route>
                    </Route>
                  </Route>
                  <Route path="*" element={<NotFound />} />
                  </Routes>
                </Suspense>
              </MaintenanceProvider>
            </TruckProvider>
          </AuthProvider>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </ErrorBoundary>
);

export default App;
