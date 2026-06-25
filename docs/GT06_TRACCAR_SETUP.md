# Connecting Concox GT06 trackers

GT06 speaks a binary TCP protocol on ports **5023 / 5093 / 5211** (model-dependent).
Your Fleet Watch Pro backend exposes HTTP `POST /api/gps/ingest`, which GT06 can't
produce directly. The recommended pipeline is:

```
[GT06 in truck] --TCP/binary--> [Traccar] --HTTP POST--> /api/gps/ingest --> WebSocket --> map
```

Traccar is a mature open-source protocol translator. It handles GT06, Teltonika,
Queclink, and ~200 more device models out of the box.

---

## 1. Enroll the device in your backend

Before a device can post data, it needs a `Device` row (IMEI + bcrypt-hashed API key):

1. Log in as **admin**.
2. Go to **Devices → Enroll device**.
3. Paste the IMEI (printed on the GT06, usually 15 digits) and pick an assigned truck.
4. Copy the `api_key` — it's shown once.

Or via curl:

```bash
curl -X POST http://api.yourdomain.com/api/devices \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"imei":"353451044103001","name":"Truck Alpha","truck_id":"<uuid>"}'
```

Save the returned `api_key`. You cannot retrieve it later — only rotate.

---

## 2. Run Traccar (Docker)

```bash
docker run -d --name traccar \
  --restart unless-stopped \
  -p 8082:8082 \
  -p 5023:5023 \
  traccar/traccar:latest
```

- **8082** — Traccar admin UI (default login `admin` / `admin` — change immediately)
- **5023** — GT06 listener port (open this publicly so the truck's SIM card can reach it)

For multiple device models at once, also publish:
- `5027` (Teltonika)
- `5001` (GPS103)
- `5093` (Concox Jimi)
- See `traccar.xml` in the container for the full list.

---

## 3. Point the GT06 at your server

GT06 is configured via SMS commands. Insert the SIM, power on, send these to the SIM's phone number:

```
SERVER,1,YOUR_PUBLIC_IP,5023,0#
```

(replace `YOUR_PUBLIC_IP` with the server running Traccar — no trailing slash, no port in Traccar's path)

Some models also want:

```
APN,operator_apn,,#        # set carrier APN
TIMER,10,10#               # report every 10 s when moving, every 10 s stopped
GPRSON,1#                  # enable GPRS
```

Reboot the device and it should appear in Traccar's UI under **Devices** once it
successfully connects. If it doesn't, check:
- SIM has data plan enabled and sufficient balance
- APN is correct for your carrier
- Port 5023 is reachable from outside (test with `nc -vz YOUR_IP 5023` from a phone tether)

---

## 4. Forward positions from Traccar to Fleet Watch Pro

In Traccar's `conf/traccar.xml` (inside the container, or mounted as a volume):

```xml
<entry key='forward.enable'>true</entry>
<entry key='forward.json'>true</entry>
<entry key='forward.url'>http://fleet-backend:8000/api/gps/ingest</entry>
<entry key='forward.header'>X-API-Key: YOUR_DEVICE_API_KEY
X-IMEI: YOUR_DEVICE_IMEI</entry>
```

**Problem with the single-URL approach**: Traccar forwards all devices to one URL
with one set of headers. For multiple devices with different API keys, you need
one of:

### Option A — One global "gateway" API key (simpler, less granular)

Set a single entry in `GPS_API_KEYS` in your backend `.env`:

```env
GPS_API_KEYS=traccar-forwarder-shared-key
```

Traccar forwards everything with that one key. Backend falls back to the legacy
global-key path when no IMEI matches the per-device table. **Downside:** if the
key leaks, you can't revoke one device without revoking all.

### Option B — Per-device forwarding via Traccar's "Computed Attribute" + webhook (recommended)

1. In Traccar UI, for each device, set a computed attribute `deviceApiKey` = the
   API key from step 1.
2. Use Traccar's `forward.urlVariables` feature to inject it:

```xml
<entry key='forward.url'>http://fleet-backend:8000/api/gps/ingest</entry>
<entry key='forward.headerTemplate'>
X-API-Key: {attributes.deviceApiKey}
X-IMEI: {device.uniqueId}
</entry>
```

Traccar substitutes each attribute per-device at send time.

### Option C — Small adapter script (most flexible)

If Traccar's templating doesn't cut it, run a 40-line Python FastAPI app that
receives Traccar webhooks and re-signs them with the correct per-IMEI key looked
up from your DB. This is what production deployments usually do.

---

## 5. Verify

1. Watch `/tmp/uv.log` on the backend — you should see `POST /api/gps/ingest` hits.
2. Open `http://localhost:8080/devices` — the device's **Status** badge should go
   green within 60 s of the first valid POST.
3. Open `/map` — the truck marker should start moving.

Dev simulation without real hardware:

```bash
# simulate a moving truck (adjust TID, API_KEY, IMEI)
while true; do
  LAT=$(awk -v s=$RANDOM 'BEGIN{srand(s); print 41.3+(rand()-0.5)*0.02}')
  LNG=$(awk -v s=$RANDOM 'BEGIN{srand(s); print 69.2+(rand()-0.5)*0.02}')
  curl -s -X POST http://localhost:8000/api/gps/ingest \
    -H "X-API-Key: $API_KEY" -H "X-IMEI: $IMEI" \
    -H 'Content-Type: application/json' \
    -d "{\"points\":[{\"latitude\":$LAT,\"longitude\":$LNG,\"speed\":15.0}]}" >/dev/null
  sleep 2
done
```

---

## Scaling notes (50+ trucks)

- **Database**: move off SQLite. `TruckLocationHistory` grows at ~8 KB/row × 1 row
  every 10 s × 50 trucks × 8 h/day = ~11 M rows/month. Postgres handles this
  easily with a composite index on `(truck_id, recorded_at DESC)`. Consider
  **TimescaleDB** extension if you go over 100 trucks.
- **Traccar**: default config handles thousands of devices on a modest VPS. Just
  give it 2 GB RAM minimum and persistent storage for its own DB.
- **Retention**: decide now. Typical fleet SaaS keeps:
  - raw GPS history: 90 days
  - aggregated daily summaries: forever
  Add a cron job that archives `truck_location_history` older than 90 d to S3,
  then `DELETE FROM truck_location_history WHERE recorded_at < NOW() - INTERVAL '90 days'`.
