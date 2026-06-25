import { useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

import { useTrucks } from '@/contexts/TruckContext';
import { MapControls } from '@/components/map/MapControls';
import { MapLegend } from '@/components/map/MapLegend';
import { TruckPopup } from '@/components/map/TruckPopup';
import { Truck } from '@/types';

// Default view: Tashkent, Uzbekistan. (Mapbox used to hard-code New York.)
const UZBEKISTAN_CENTER: [number, number] = [41.2995, 69.2401];
const DEFAULT_ZOOM = 6;

function statusColor(status: Truck['status']): string {
  switch (status) {
    case 'moving':
      return '#22c55e';
    case 'stopped':
      return '#f97316';
    case 'offline':
    default:
      return '#64748b';
  }
}

// A divIcon mirrors the old custom Mapbox marker (colored circle + truck glyph).
function truckIcon(truck: Truck): L.DivIcon {
  return L.divIcon({
    className: 'truck-marker',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    html: `
      <div style="
        width:32px;height:32px;background:${statusColor(truck.status)};
        border:3px solid rgba(255,255,255,0.9);border-radius:50%;
        display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 8px rgba(0,0,0,0.3);">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
          <path d="M10 17h4V5a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3z"/>
          <path d="M14 9h4l3 3v5a2 2 0 0 1-2 2h-1"/>
          <circle cx="7.5" cy="17.5" r="2.5"/>
          <circle cx="17.5" cy="17.5" r="2.5"/>
        </svg>
      </div>`,
  });
}

/** Pans/zooms the map when a truck is selected elsewhere (list, controls). */
function FlyToSelected({ truck }: { truck: Truck | null }) {
  const map = useMap();
  useEffect(() => {
    if (truck && truck.latitude && truck.longitude) {
      map.flyTo([truck.latitude, truck.longitude], 13, { duration: 1 });
    }
  }, [truck, map]);
  return null;
}

/** Fits the map to all truck markers on first load so trucks are visible. */
function FitToTrucks({ trucks }: { trucks: Truck[] }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    const pts = trucks
      .filter((t) => t.isEnabled && t.latitude && t.longitude)
      .map((t) => [t.latitude, t.longitude] as [number, number]);
    if (pts.length > 0) {
      map.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 12 });
      done.current = true;
    }
  }, [trucks, map]);
  return null;
}

export default function MapViewPage() {
  const { trucks, selectedTruck, setSelectedTruck, isLoading } = useTrucks();

  const visibleTrucks = useMemo(
    () => trucks.filter((t) => t.isEnabled && t.latitude && t.longitude),
    [trucks],
  );

  return (
    <div className="h-[calc(100vh-8rem)] relative animate-fade-in">
      <MapContainer
        center={UZBEKISTAN_CENTER}
        zoom={DEFAULT_ZOOM}
        className="absolute inset-0 rounded-lg overflow-hidden shadow-elevated"
        style={{ background: '#0b1220' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        {visibleTrucks.map((truck) => (
          <Marker
            key={truck.id}
            position={[truck.latitude, truck.longitude]}
            icon={truckIcon(truck)}
            eventHandlers={{ click: () => setSelectedTruck(truck) }}
          />
        ))}

        <FitToTrucks trucks={visibleTrucks} />
        <FlyToSelected truck={selectedTruck} />
      </MapContainer>

      {/* Overlays (unchanged) */}
      <MapControls trucks={trucks} />
      <MapLegend />

      {selectedTruck && (
        <TruckPopup truck={selectedTruck} onClose={() => setSelectedTruck(null)} />
      )}

      {isLoading && (
        <div className="absolute inset-0 z-[1000] bg-background/50 backdrop-blur-sm flex items-center justify-center">
          <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      )}
    </div>
  );
}
