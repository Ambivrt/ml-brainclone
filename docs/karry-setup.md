# Karry Setup (Location Agent)

Karry is the ecosystem's spatial awareness agent. It tracks position from multiple sources, evaluates geo-fences, and provides place intelligence via MCP tools.

## Architecture

Karry is a **hybrid daemon + MCP server**:

- **Daemon** (`karry_service.py`): Runs 24/7, polls the brains-bus for location updates, evaluates geo-fences, emits position events. Also polls the calendar for meeting locations.
- **MCP server** (`karry-mcp-server.py`): Provides 5 tools for Larry to query location, search nearby places, calculate routes, geocode addresses, and manage geo-fences.

```
Position sources          Karry daemon              Consumers
─────────────────         ──────────────            ─────────
Telegram live loc  ──┐                              
Calendar events    ──┼──► bus inbox ──► geo-fence   ──► bus broadcast
Apple Shortcuts    ──┤    evaluation       │        ──► Telegram notify
Vibesensor app     ──┘                     │        ──► Home Assistant
                                           ▼
                                      state file
                                    (_private/)
```

## Prerequisites

| Component | Required? | Notes |
|-----------|-----------|-------|
| Google Maps API key | Optional | For Places, Directions, Geocoding MCP tools |
| Telegram bot | Optional | Receives live location shares |
| Home Assistant | Optional | Geo-fence triggers |
| GWS CLI | Optional | Calendar polling for meeting locations |

## Installation

### 1. Create project directory

```bash
mkdir -p 03-projects/karry/tests
```

### 2. Geo library

Create `03-projects/karry/karry_geo.py` with:

- `Position` dataclass (lat, lon, source, ts, accuracy_m)
- `GeoFence` dataclass (label, lat, lon, radius_m, on_enter, on_exit)
- `haversine_m(lat1, lon1, lat2, lon2)` -- WGS84 distance in meters
- `is_inside(lat, lon, fence)` -- point-in-fence check
- `GeoState` class -- tracks which fences you're inside, detects enter/exit events, save/load to JSON

### 3. Configuration

Create `agents/karry-config.json`:

```json
{
  "poll_seconds": 30,
  "heartbeat_every": 15,
  "calendar_poll_minutes": 10,
  "google_maps_api_key_env": "GOOGLE_MAPS_API_KEY",
  "home_assistant_url": "",
  "home_assistant_token_env": "HA_TOKEN",
  "home_location": {
    "lat": 0.0,
    "lon": 0.0,
    "address": "{{YOUR_HOME_ADDRESS}}"
  },
  "geofences": [
    {
      "label": "Home",
      "lat": 0.0,
      "lon": 0.0,
      "radius_m": 150,
      "on_enter": ["bus-event", "ha-trigger"],
      "on_exit": ["bus-event"]
    }
  ]
}
```

### 4. Daemon service

Create `agents/karry_service.py` following the daemon pattern (see [daemon-stability.md](daemon-stability.md)):

- Singleton via `lib/daemon_singleton.py`
- Bus polling every `poll_seconds`
- Calendar polling every `calendar_poll_minutes`
- Heartbeat file for health monitoring
- Geo-fence evaluation on every position update
- Actions per fence event: bus-event, telegram-notify, ha-trigger

### 5. MCP server

Create `03-projects/karry/karry-mcp-server.py` with 5 tools:

| Tool | Description |
|------|-------------|
| `karry_locate` | Last known position + geo-fence status |
| `karry_nearby` | Search nearby places (Google Places API) |
| `karry_route` | Calculate route + ETA (Google Directions API) |
| `karry_geocode` | Forward/reverse geocoding |
| `karry_geofence` | List/add/remove geo-fence zones |

### 6. Register

Add to `.mcp.json`:

```json
"karry": {
  "command": "python",
  "args": ["-X", "utf8", "{{VAULT_PATH}}/03-projects/karry/karry-mcp-server.py"]
}
```

Add to daemon registry in your start script.

### 7. Telegram location handler

If using the Telegram bot listener, add a handler for `location` and `venue` message types that posts `karry-location-update` events to the bus.

## Bus Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `karry-location-update` | Inbound | `{lat, lon, source, accuracy_m}` |
| `karry-position-update` | Outbound | `{lat, lon, source, inside, ts}` |
| `karry-geofence-enter` | Outbound | `{fence, lat, lon, source, ts}` |
| `karry-geofence-exit` | Outbound | `{fence, lat, lon, source, ts}` |
| `karry-request` | Inbound | `{type: "status"}` |
| `karry-response` | Outbound | `{type: "status", last_position, inside}` |

## Privacy

Position data is sensitive. The state file (`karry-state.json`) belongs in `_private/` (gitignored). Position data should never appear in external output, Git commits, or public files. Internal bus events between agents are fine.

## Google Maps API

Set the `GOOGLE_MAPS_API_KEY` environment variable. Required APIs:

- Places API (nearby search)
- Directions API (routes + ETA)
- Geocoding API (address lookup)

The daemon itself does not require Google Maps -- it uses Nominatim (OpenStreetMap) for calendar location geocoding. Google Maps is only needed for the MCP server's place intelligence tools.
