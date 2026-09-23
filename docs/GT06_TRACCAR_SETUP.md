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
with one set of headers, and Fleet Watch authenticates *per device* — the
`(IMEI, api_key)` pair is what binds an incoming position to one customer's
truck. There is no shared gateway key to fall back on: a key that belongs to no
organization leaves ingest with nothing to check the target truck against, which
is exactly why the old `GPS_API_KEYS` list was removed. So the forwarder has to
send each device's own credentials.

### Option A — Per-device forwarding via Traccar's computed attributes (recommended)

1. In the Traccar UI, for each device, set a computed attribute `deviceApiKey` to
   the `api_key` that `POST /api/devices` returned for it (step 1). Fleet Watch
   shows that key exactly once, so store it as you enroll.
2. Template the headers so Traccar substitutes them per device at send time:

```xml
<entry key='forward.url'>http://fleet-backend:8000/api/gps/ingest</entry>
<entry key='forward.headerTemplate'>
X-API-Key: {attributes.deviceApiKey}
X-IMEI: {device.uniqueId}
</entry>
```

`device.uniqueId` is the IMEI Traccar knows the tracker by, and it must match the
`imei` the device was enrolled with — that is the lookup key on our side.

### Option B — Small adapter service (most flexible)

If your Traccar version's templating cannot do the above, run a small service in
front of the API: it receives Traccar's webhook, looks the IMEI up in its own key
map, and re-sends with that device's `X-API-Key`. Keep the map in the adapter's
own secret store, one entry per device, so revoking one tracker stays a
one-device operation.

Whichever you pick, rotating a compromised tracker is
`POST /api/devices/{id}/rotate-key` — the old key stops working on the next
request, not when some cache expires.

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
