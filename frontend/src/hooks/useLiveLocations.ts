import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchTruckLocations, type LiveLocation, type LocationUpdateMessage } from '@/lib/locations';
import { tokenStorage } from '@/lib/api';

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';

export const LOCATIONS_KEY = ['truck-locations'] as const;

// GPS pings arrive per-truck every few seconds; every truck's ping used to
// call setQueryData individually, which re-renders the whole app (TruckContext
// wraps every route). Buffer incoming updates and flush them onto one shared
// object at most this often, so a 50-truck fleet costs one re-render per
// window instead of dozens of individual ones.
const FLUSH_INTERVAL_MS = 2000;

export function useLiveLocations() {
  const queryClient = useQueryClient();
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(1000);
  const pendingRef = useRef<Record<string, LiveLocation> | null>(null);

  const { data: locations = {} } = useQuery({
    queryKey: LOCATIONS_KEY,
    queryFn: fetchTruckLocations,
    staleTime: Infinity, // WebSocket is the source of truth after seeding
  });

  useEffect(() => {
    let cancelled = false;

    const connect = () => {
      const token = tokenStorage.getAccess();
      if (!token || cancelled) return;

      const ws = new WebSocket(`${WS_URL}/ws?token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        backoffRef.current = 1000;
      };

      ws.onmessage = (evt: MessageEvent<string>) => {
        let msg: LocationUpdateMessage;
        try {
          msg = JSON.parse(evt.data) as LocationUpdateMessage;
        } catch {
          return;
        }
        if (msg.type !== 'truck_location_update') return;

        pendingRef.current = {
          ...pendingRef.current,
          [msg.truck_id]: {
            truckId: msg.truck_id,
            latitude: msg.lat,
            longitude: msg.lng,
            speed: msg.speed,
            heading: msg.heading,
            recordedAt: msg.recorded_at ? new Date(msg.recorded_at) : new Date(),
          },
        };
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        if (cancelled) return;
        const delay = Math.min(backoffRef.current, 30_000);
        backoffRef.current = Math.min(backoffRef.current * 2, 30_000);
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [queryClient]);

  useEffect(() => {
    const flush = setInterval(() => {
      if (!pendingRef.current) return;
      const updates = pendingRef.current;
      pendingRef.current = null;
      queryClient.setQueryData<Record<string, LiveLocation>>(LOCATIONS_KEY, (prev = {}) => ({
        ...prev,
        ...updates,
      }));
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(flush);
  }, [queryClient]);

  return { locations, isConnected };
}
