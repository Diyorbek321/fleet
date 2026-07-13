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
import { PageLoader } from "@/components/PageLoader";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import LoginPage from "@/pages/LoginPage";

// Lazy-load page routes so heavy dependencies (Leaflet maps, Recharts reports,
// etc.) are split into their own chunks and only fetched on demand. The auth
// and layout shell above stays eager so the app boots fast.
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const TrucksPage = lazy(() => import("@/pages/TrucksPage"));
const TruckDetailPage = lazy(() => import("@/pages/TruckDetailPage"));
const DriverDetailPage = lazy(() => import("@/pages/DriverDetailPage"));
const MapViewPage = lazy(() => import("@/pages/MapViewPage"));
const MaintenancePage = lazy(() => import("@/pages/MaintenancePage"));
const ReportsPage = lazy(() => import("@/pages/ReportsPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const DevicesPage = lazy(() => import("@/pages/DevicesPage"));
const DriversPage = lazy(() => import("@/pages/DriversPage"));
const GeofencesPage = lazy(() => import("@/pages/GeofencesPage"));
const TripsPage = lazy(() => import("@/pages/TripsPage"));
const TripDetailPage = lazy(() => import("@/pages/TripDetailPage"));
const TripReportPrintPage = lazy(() => import("@/pages/TripReportPrintPage"));
const LeakagePage = lazy(() => import("@/pages/LeakagePage"));
const BorderQueuePage = lazy(() => import("@/pages/BorderQueuePage"));
const NotFound = lazy(() => import("./pages/NotFound"));

const queryClient = new QueryClient();

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
                      <Route path="/dashboard" element={<DashboardPage />} />
                      <Route path="/trucks" element={<TrucksPage />} />
                      <Route path="/trucks/:id" element={<TruckDetailPage />} />
                      <Route path="/drivers" element={<DriversPage />} />
                      <Route path="/drivers/:id" element={<DriverDetailPage />} />
                      <Route path="/trips" element={<TripsPage />} />
                      <Route path="/trips/:id" element={<TripDetailPage />} />
                      <Route path="/leakage" element={<LeakagePage />} />
                      <Route path="/map" element={<MapViewPage />} />
                      <Route path="/queue" element={<BorderQueuePage />} />
                      <Route path="/geofences" element={<GeofencesPage />} />
                      <Route path="/maintenance" element={<MaintenancePage />} />
                      <Route path="/devices" element={<DevicesPage />} />
                      <Route path="/reports" element={<ReportsPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
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
