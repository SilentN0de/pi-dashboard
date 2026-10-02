# Pi Dashboard

Live home-lab dashboard for the Raspberry Pi 5 (`PI5-TEST`). Single-page Flask app
with a dark/lime UI, a slim navigation rail, and in-place live updates every
5 seconds (no page reloads).

## What it shows

- **KPIs** — CPU temp, 1-min load, memory, system disk, NAS disk, uptime
- **System Details** — per-core CPU bars, frequency, power/throttle status,
  top processes, board model, IPs, swap
- **Services** — live running/down status for `pihole-FTL`, `secplatform`,
  `tailscaled`, `docker`, `mcbot`, `dashboard`
- **Security Platform** — local API health + version (`127.0.0.1:8000`)
- **Pi-hole** — queries today, blocked, blocked %
- **Bandwidth** — down/up today + down this month (`vnstat`, eth0)
- **Tailscale** — tailnet devices with online/offline pills
- **Docker** — running containers
- **Network Devices** — Pi-hole network table (IP, hostname, MAC, vendor)

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: HTML template, `/` page, `/api/stats` JSON endpoint |
| `sysstats.py` | Stdlib-only stat collectors (system, services, Tailscale, Docker) |
| `dashboard.service` | systemd unit (runs on boot, restarts on failure) |

## Install on a Pi

```bash
sudo apt install python3-flask python3-requests vnstat
sudo mkdir -p /home/admin/dashboard
sudo cp app.py sysstats.py /home/admin/dashboard/
sudo cp dashboard.service /etc/systemd/system/
# Pi-hole web password is NOT in the repo — set it:
sudo systemctl edit dashboard   # add: [Service] Environment=PIHOLE_PASSWORD=your-password
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard
```

Then open `http://<pi-ip>:8080` (or `http://<pi-ip>/admin/` via the rail's Pi-hole icon).

## Notes

- The Pi-hole API session is cached and reused (one login per ~20 min) because
  Pi-hole only allows a limited number of concurrent API sessions.
- `sysstats.py` uses only the standard library; `app.py` needs Flask + requests.
- Live updates: the page polls `/api/stats` every 5 seconds and patches the DOM.
