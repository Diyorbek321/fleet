import { useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Tooltip, useMap } from 'react-leaflet';
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
// The plate rides above it as a permanent tooltip — see `.truck-plate` in
// index.css for why it is a tooltip and not part of the icon.
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
      {/*
        The z-0 is load-bearing, not decoration. Leaflet gives its own panes
        z-index 200-1000 (tiles 200, markers 600, controls 1000) and leaves
        .leaflet-container itself at z-index:auto — which does *not* open a
        stacking context, so those panes compete directly with this map's
        siblings. The overlays below sit at z-10 and lost every time, which is
        why clicking a truck appeared to do nothing: the popup was rendering
        behind the tiles. An explicit z-index on the positioned container traps
        the panes inside it, and the overlays stack above the map as a whole.
      */}
      <MapContainer
        center={UZBEKISTAN_CENTER}
        zoom={DEFAULT_ZOOM}
        className="absolute inset-0 z-0 rounded-lg overflow-hidden shadow-elevated"
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
          >
            {/* Permanent, because the question the map answers at this zoom is
                "which of these nine dots is Anvar's lorry" — and answering it
                by clicking each one in turn is not answering it. */}
            <Tooltip permanent direction="top" offset={[0, -18]} className="truck-plate">
              {truck.plateNumber || truck.name}
            </Tooltip>
          </Marker>
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
