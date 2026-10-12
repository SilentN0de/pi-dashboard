from flask import Flask, render_template_string, jsonify, request
import subprocess
import requests
import re
import json
import os
import sysstats

app = Flask(__name__)

PIHOLE_PASSWORD = os.environ.get("PIHOLE_PASSWORD", "")
PIHOLE_IP = "10.0.0.12"

_pihole_sid = None
_pihole_sid_time = 0
_PIHOLE_SID_TTL = 1200  # re-auth every 20 min (Pi-hole drops idle sessions after 30)


def _ip_sort_key(x):
    ip = x['ip']
    if '.' in ip and ':' not in ip:
        try:
            return (0, list(map(int, ip.split('.'))))
        except ValueError:
            pass
    return (1, ip)


def get_pihole_token():
    """Cached Pi-hole API session. Every /api/auth call takes one of Pi-hole's
    limited API seats, so the dashboard must reuse its session instead of
    logging in on every poll."""
    global _pihole_sid, _pihole_sid_time
    import time as _time
    if _pihole_sid and _time.time() - _pihole_sid_time < _PIHOLE_SID_TTL:
        return _pihole_sid
    if _pihole_sid:
        try:  # give our old seat back before taking a new one
            requests.delete(f'http://{PIHOLE_IP}/api/auth',
                headers={'X-FTL-SID': _pihole_sid}, timeout=5)
        except Exception:
            pass
        _pihole_sid = None
    try:
        auth = requests.post(f'http://{PIHOLE_IP}/api/auth',
            json={'password': PIHOLE_PASSWORD}, timeout=5)
        auth.raise_for_status()
        _pihole_sid = auth.json()['session']['sid']
        _pihole_sid_time = _time.time()
        return _pihole_sid
    except Exception:
        return None


def _pihole_api(path, timeout=10):
    """GET a Pi-hole API path, re-authenticating once if the session died."""
    global _pihole_sid
    for _ in range(2):
        sid = get_pihole_token()
        if not sid:
            return None
        try:
            r = requests.get(f'http://{PIHOLE_IP}{path}',
                headers={'X-FTL-SID': sid}, timeout=timeout)
            if r.status_code == 401:
                _pihole_sid = None
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            return None
    return None


def get_pihole(sid):
    data = _pihole_api('/api/stats/summary', timeout=5)
    try:
        return {
            'queries': data['queries']['total'],
            'blocked': data['queries']['blocked'],
            'percentage': round(data['queries']['percent_blocked'], 1)
        }
    except Exception:
        return {}


def get_devices(sid):
    data = _pihole_api('/api/network/devices', timeout=10)
    try:
        devices = []
        for d in data.get('devices', []):
            for ip_entry in d.get('ips', []):
                devices.append({
                    'ip': ip_entry['ip'],
                    'hostname': ip_entry.get('name') or 'Unknown',
                    'mac': d.get('hwaddr', 'N/A').upper(),
                    'vendor': d.get('macVendor') or 'Unknown'
                })
        devices.sort(key=_ip_sort_key)
        return devices
    except Exception:
        return []


def get_bandwidth():
    try:
        result = subprocess.run(['vnstat', '--oneline', '-i', 'eth0'],
            capture_output=True, text=True)
        parts = result.stdout.strip().split(';')
        if len(parts) > 12:
            # vnstat --oneline fields: 3=day rx, 4=day tx, 8=month rx, 9=month tx
            return {
                'today_rx': parts[3],
                'today_tx': parts[4],
                'month_rx': parts[8],
                'month_tx': parts[9]
            }
        return {}
    except:
        return {}

HTML = '<!DOCTYPE html>\n<html>\n<head>\n  <title>PI5-TEST Dashboard</title>\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <style>\n    :root{\n      --bg:#0a0a0c; --card:#141417; --card2:#1b1b1f; --lime:#c9f24b;\n      --text:#f4f4f5; --muted:#8e8e96; --red:#ff6b6b; --border:#222227;\n    }\n    *{box-sizing:border-box;margin:0;padding:0}\n    body{font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Inter,sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}\n    .rail{width:60px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:1.4rem;padding:1.4rem 0;border-right:1px solid var(--border)}\n    .rail .logo{color:var(--lime);font-size:1.3rem}\n    html{scroll-behavior:smooth}\n    .rail a{font-size:1.15rem;opacity:.5;text-decoration:none;transition:opacity .15s}\n    .rail a:hover{opacity:1}\n    .main{flex:1;padding:1.6rem 2rem;max-width:1440px;margin:0 auto;width:100%}\n    header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.4rem}\n    header h1{font-size:1.35rem;font-weight:700;display:flex;align-items:center;gap:.6rem;letter-spacing:-.3px}\n    .dotlive{width:10px;height:10px;border-radius:50%;background:var(--lime);box-shadow:0 0 10px var(--lime);animation:pulse 2s infinite}\n    @keyframes pulse{50%{opacity:.35}}\n    header .sub{color:var(--muted);font-size:.8rem;margin-top:.25rem}\n    .livepill{background:var(--lime);color:#171503;font-size:.72rem;font-weight:800;letter-spacing:.6px;padding:.42rem .95rem;border-radius:999px}\n    .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.9rem;margin-bottom:1rem}\n    .kpi{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.05rem 1.15rem}\n    .kpi .num{font-size:1.6rem;font-weight:700;letter-spacing:-.5px}\n    .kpi .lbl{color:var(--muted);font-size:.76rem;margin-top:.3rem}\n    .kpi.hot{background:var(--lime);border:none}\n    .kpi.hot .num{color:#151503}\n    .kpi.hot .lbl{color:#4c511f}\n    .bar{height:6px;background:#26262b;border-radius:99px;margin-top:.65rem;overflow:hidden}\n    .bar>div{height:100%;background:var(--lime);border-radius:99px}\n    .kpi.hot .bar{background:rgba(0,0,0,.15)}\n    .kpi.hot .bar>div{background:#151503}\n    .panels{display:grid;grid-template-columns:1fr 1fr;gap:.9rem}\n    @media(max-width:900px){.panels{grid-template-columns:1fr}.rail{display:none}.main{padding:1.2rem}}\n    .panel{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.15rem 1.25rem;overflow:hidden}\n    .panel.wide{grid-column:1/-1}\n    .panel h3{font-size:.92rem;font-weight:600;margin-bottom:.9rem;display:flex;align-items:center;gap:.5rem}\n    .panel h3 .ico{color:var(--lime)}\n    table{width:100%;border-collapse:collapse}\n    th{text-align:left;color:var(--muted);font-size:.7rem;font-weight:500;text-transform:uppercase;letter-spacing:.6px;padding:.45rem .5rem;border-bottom:1px solid var(--border)}\n    td{padding:.55rem .5rem;border-bottom:1px solid #1b1b1f;font-size:.83rem}\n    tr:last-child td{border-bottom:none}\n    .mono{font-family:ui-monospace,Menlo,monospace;font-size:.78rem;color:var(--muted)}\n    .pill{display:inline-block;padding:.22rem .7rem;border-radius:999px;font-size:.72rem;font-weight:600}\n    .pill.on{background:rgba(201,242,75,.13);color:var(--lime)}\n    .pill.off{background:rgba(255,107,107,.13);color:var(--red)}\n    .svc{display:flex;align-items:center;gap:.6rem;padding:.44rem 0;font-size:.85rem;border-bottom:1px solid #1b1b1f}\n    .svc:last-child{border-bottom:none}\n    .svc .nm{flex:1}\n    .dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}\n    .dot.on{background:var(--lime);box-shadow:0 0 8px var(--lime)}\n    .dot.off{background:var(--red);box-shadow:0 0 8px var(--red)}\n    .stat3{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem}\n    .stat3 .s{background:var(--card2);border-radius:12px;padding:.8rem .9rem}\n    .stat3 .s .v{font-size:1.25rem;font-weight:700;color:var(--lime)}\n    .stat3 .s .l{color:var(--muted);font-size:.7rem;margin-top:.25rem}\n    footer{color:#55555c;font-size:.72rem;margin-top:1.6rem;text-align:center}\n    .sysgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.4rem}\n    @media(max-width:900px){.sysgrid{grid-template-columns:1fr}}\n    .sysgrid h4{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:.7rem;font-weight:600}\n    .corerow{display:flex;align-items:center;gap:.6rem;margin-bottom:.45rem}\n    .corerow .bar{flex:1;margin-top:0}\n    .corerow .mono{min-width:52px}\n    .corerow .mono:last-child{text-align:right}\n    .kv{display:flex;justify-content:space-between;gap:1rem;padding:.42rem 0;border-bottom:1px solid #1b1b1f;font-size:.82rem}\n    .kv:last-child{border-bottom:none}\n    .kv span{color:var(--muted);flex-shrink:0}\n    .kv b{font-weight:600;text-align:right;overflow-wrap:anywhere}\n    .logbox{max-height:340px;overflow-y:auto;background:#0c0c0f;border:1px solid var(--border);border-radius:12px;padding:.6rem .8rem;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.74rem;line-height:1.6}\n    .logline{display:flex;gap:.7rem;padding:.12rem 0;border-bottom:1px solid #151518;white-space:nowrap;overflow:hidden}\n    .logline:last-child{border-bottom:none}\n    .lt{color:#55555c;flex-shrink:0}\n    .lc{color:var(--muted);flex-shrink:0;max-width:110px;overflow:hidden;text-overflow:ellipsis}\n    .ld{flex:1;overflow:hidden;text-overflow:ellipsis;color:var(--text)}\n    .lb{flex-shrink:0;font-weight:700}\n    .lb.yes{color:var(--red)}\n    .lb.no{color:var(--lime)}\n    .lsys{color:#b9b9c0;overflow-wrap:anywhere}\n    .tabs{display:flex;gap:.5rem;margin-bottom:.7rem}\n    .tab{background:var(--card2);border:1px solid var(--border);color:var(--muted);font-size:.75rem;font-weight:600;padding:.4rem .9rem;border-radius:999px;cursor:pointer;font-family:inherit}\n    .tab.active{background:var(--lime);border-color:var(--lime);color:#171503}\n    .legend{display:flex;gap:1.1rem;flex-wrap:wrap;margin-bottom:.8rem;font-size:.74rem;color:var(--muted)}\n    .legend span{display:flex;align-items:center;gap:.4rem}\n  </style>\n</head>\n<body>\n  <nav class="rail">\n    <a class="logo" href="#top" title="Top">&#9889;</a>\n    <a href="#top" title="Overview">&#127968;</a>\n    <a href="#system" title="System">&#128421;</a>\n    <a href="#pihole" title="Pi-hole &amp; Bandwidth">&#128202;</a>\n    <a href="#secplatform" title="Security Platform">&#128737;</a>\n    <a href="#tailscale" title="Tailscale">&#127760;</a>\n    <a href="#" onclick="window.open(\'http://\'+location.hostname+\'/admin/\',\'_blank\');return false;" title="Pi-hole Admin">&#128371;</a>\n    <a href="#network" title="Network Activity">&#128246;</a>\n    <a href="#logs" title="Live Logs">&#128196;</a>\n  </nav>\n  <div class="main" id="top">\n    <header>\n      <div>\n        <h1><span class="dotlive"></span> PI5-TEST</h1>\n        <div class="sub">Home lab control center</div>\n      </div>\n      <div class="livepill">&#9679; LIVE</div>\n    </header>\n\n    <div class="kpis" style="scroll-margin-top:1rem">\n      <div class="kpi hot">\n        <div class="num" id="v-temp">{{ system.temp }}</div>\n        <div class="lbl">CPU Temp</div>\n      </div>\n      <div class="kpi">\n        <div class="num" id="v-load">{{ system.load }}</div>\n        <div class="lbl">Load (1 min)</div>\n      </div>\n      <div class="kpi">\n        <div class="num" id="v-mem">{{ system.mem }}</div>\n        <div class="lbl">Memory Used</div>\n        <div class="bar"><div id="v-mem-bar" style="width: {{ system.mem_pct }}%"></div></div>\n      </div>\n      <div class="kpi">\n        <div class="num" id="v-disk-pct">{{ system.disk_pct }}%</div>\n        <div class="lbl">Disk Used &middot; <span id="v-disk">{{ system.disk }}</span></div>\n        <div class="bar"><div id="v-disk-bar" style="width: {{ system.disk_pct }}%"></div></div>\n      </div>\n      <div class="kpi">\n        <div class="num" id="v-nas-pct">{{ nas.nas_pct }}%</div>\n        <div class="lbl">NAS Used &middot; <span id="v-nas">{{ nas.nas }}</span></div>\n        <div class="bar"><div id="v-nas-bar" style="width: {{ nas.nas_pct }}%"></div></div>\n      </div>\n      <div class="kpi">\n        <div class="num" id="v-uptime">{{ system.uptime }}</div>\n        <div class="lbl">Uptime</div>\n      </div>\n    </div>\n\n    <div class="panel wide" id="system" style="scroll-margin-top:1rem;margin-bottom:1rem">\n      <h3><span class="ico">&#128421;</span> System Details</h3>\n      <div class="sysgrid">\n        <div>\n          <h4>CPU</h4>\n          <div id="v-cores">\n          {% for c in sysdetail.cores %}\n          <div class="corerow"><span class="mono">core{{ loop.index0 }}</span><div class="bar"><div style="width: {{ c }}%"></div></div><span class="mono">{{ c }}%</span></div>\n          {% endfor %}\n          </div>\n          <div class="kv"><span>Frequency</span><b id="v-freq">{{ sysdetail.freq }}</b></div>\n          <div class="kv"><span>Power / Throttle</span><b id="v-thr" style="color: {{ \'#c9f24b\' if sysdetail.throttled_ok else \'#ff6b6b\' }}">{{ sysdetail.throttled }}</b></div>\n        </div>\n        <div>\n          <h4>Top Processes</h4>\n          <table>\n            <tr><th>Process</th><th>CPU %</th><th>MEM %</th></tr>\n            <tbody id="v-procs">\n            {% for p in sysdetail.procs %}\n            <tr><td>{{ p.name }}</td><td class="mono">{{ p.cpu }}</td><td class="mono">{{ p.mem }}</td></tr>\n            {% endfor %}\n            </tbody>\n          </table>\n        </div>\n        <div>\n          <h4>Board &amp; Network</h4>\n          <div class="kv"><span>Model</span><b id="v-model">{{ sysdetail.model }}</b></div>\n          <div class="kv"><span>IP Addresses</span><b class="mono" id="v-ips" style="font-size:.72rem">{{ sysdetail.ips }}</b></div>\n          <div class="kv"><span>Swap Used</span><b id="v-swap">{{ sysdetail.swap }}</b></div>\n          <div class="kv"><span>Memory</span><b id="v-mem2">{{ system.mem }}</b></div>\n          <div class="kv"><span>Disk</span><b id="v-disk2">{{ system.disk }} ({{ system.disk_pct }}%)</b></div>\n        </div>\n      </div>\n    </div>\n\n    <div class="panels">\n      <div class="panel">\n        <h3><span class="ico">&#9881;</span> Services</h3>\n        <div id="v-services">\n        {% for s in services %}\n        <div class="svc"><span class="dot {{ \'on\' if s.active else \'off\' }}"></span><span class="nm">{{ s.name }}</span><span class="mono">{{ \'running\' if s.active else \'down\' }}</span></div>\n        {% endfor %}\n        </div>\n      </div>\n\n      <div class="panel" id="secplatform" style="scroll-margin-top:1rem">\n        <h3><span class="ico">&#128737;</span> Security Platform</h3>\n        <div class="stat3">\n          <div class="s"><div class="v" id="v-sp-ver">{{ secplatform.version }}</div><div class="l">Version</div></div>\n          <div class="s"><div class="v"><span class="pill {{ \'on\' if secplatform.ok else \'off\' }}" id="v-sp-pill">{{ \'healthy\' if secplatform.ok else \'down\' }}</span></div><div class="l">API Status</div></div>\n          <div class="s"><div class="v mono" style="font-size:1rem">:8000</div><div class="l">Local Port</div></div>\n        </div>\n      </div>\n\n      <div class="panel" id="pihole" style="scroll-margin-top:1rem">\n        <h3><span class="ico">&#128371;</span> Pi-hole</h3>\n        <div class="stat3">\n          <div class="s"><div class="v" id="v-ph-q">{{ pihole.get(\'queries\', \'N/A\') }}</div><div class="l">Queries Today</div></div>\n          <div class="s"><div class="v" id="v-ph-b">{{ pihole.get(\'blocked\', \'N/A\') }}</div><div class="l">Blocked</div></div>\n          <div class="s"><div class="v" id="v-ph-p">{{ pihole.get(\'percentage\', \'N/A\') }}%</div><div class="l">Blocked %</div></div>\n        </div>\n      </div>\n\n      <div class="panel">\n        <h3><span class="ico">&#128225;</span> Bandwidth (eth0)</h3>\n        <div class="stat3">\n          <div class="s"><div class="v" id="v-bw-rx">{{ bandwidth.get(\'today_rx\', \'N/A\') }}</div><div class="l">Down Today</div></div>\n          <div class="s"><div class="v" id="v-bw-tx">{{ bandwidth.get(\'today_tx\', \'N/A\') }}</div><div class="l">Up Today</div></div>\n          <div class="s"><div class="v" id="v-bw-mrx">{{ bandwidth.get(\'month_rx\', \'N/A\') }}</div><div class="l">Down Month</div></div>\n        </div>\n      </div>\n\n      <div class="panel" id="tailscale" style="scroll-margin-top:1rem">\n        <h3><span class="ico">&#127760;</span> Tailscale <span id="v-ts-count">({{ tailnet|length }})</span></h3>\n        <table>\n          <tr><th>Device</th><th>IP</th><th>Status</th></tr>\n          <tbody id="v-tailnet">\n          {% for d in tailnet %}\n          <tr><td>{{ d.name }}</td><td class="mono">{{ d.ip }}</td><td><span class="pill {{ \'on\' if d.online else \'off\' }}">{{ \'online\' if d.online else \'offline\' }}</span></td></tr>\n          {% endfor %}\n          </tbody>\n        </table>\n      </div>\n\n      <div class="panel">\n        <h3><span class="ico">&#128051;</span> Docker <span id="v-dk-count">({{ containers|length }})</span></h3>\n        <table>\n          <tr><th>Container</th><th>Status</th></tr>\n          <tbody id="v-docker">\n          {% for c in containers %}\n          <tr><td>{{ c.name }}</td><td class="mono">{{ c.status }}</td></tr>\n          {% endfor %}\n          </tbody>\n        </table>\n      </div>\n\n      <div class="panel wide" id="network" style="scroll-margin-top:1rem">\n        <h3><span class="ico">&#128246;</span> Network Activity</h3>\n        <div class="tabs">\n          <button class="tab active" id="tab-devices" onclick="setNetTab(\'devices\')">Devices</button>\n          <button class="tab" id="tab-traffic" onclick="setNetTab(\'traffic\')">Traffic</button>\n          <button class="tab" id="tab-conns" onclick="setNetTab(\'conns\')">Connections</button>\n        </div>\n        <div id="v-net-devices">\n          <table>\n            <tr><th>IP Address</th><th>Hostname</th><th>MAC</th><th>Vendor</th></tr>\n            <tbody id="v-devtab">\n            {% for d in devices %}\n            <tr><td class="mono">{{ d.ip }}</td><td>{{ d.hostname or \'Unknown\' }}</td><td class="mono">{{ d.mac or \'N/A\' }}</td><td>{{ d.vendor or \'Unknown\' }}</td></tr>\n            {% endfor %}\n            </tbody>\n          </table>\n        </div>\n        <div id="v-net-traffic" hidden>\n          <div class="legend"><span><i class="dot" style="background:#c9f24b"></i>Incoming</span><span><i class="dot" style="background:#79c0ff"></i>Outgoing</span><span><i class="dot" style="background:#ff6b6b"></i>Blocked / unwanted</span></div>\n          <div class="stat3" id="v-rates"><div class="lsys">collecting baseline...</div></div>\n          <div id="v-blocked" style="margin-top:.9rem"></div>\n        </div>\n        <div id="v-net-conns" hidden>\n          <table>\n            <tr><th>Proto</th><th>Local</th><th>Remote</th><th>State</th></tr>\n            <tbody id="v-conntab"><tr><td colspan="4" class="mono">loading...</td></tr></tbody>\n          </table>\n        </div>\n      </div>\n    </div>\n\n    <div class="panel wide" id="logs" style="scroll-margin-top:1rem">\n      <h3><span class="ico">&#128196;</span> Live Logs</h3>\n      <div class="tabs">\n        <button class="tab active" id="tab-pihole" onclick="setLogSource(\'pihole\')">Pi-hole queries</button>\n        <button class="tab" id="tab-system" onclick="setLogSource(\'system\')">System journal</button>\n      </div>\n      <div class="logbox" id="v-logs"><div class="lsys">loading...</div></div>\n    </div>\n\n    <footer><span id="v-updated">Live</span> &middot; updating every 5 seconds &middot; PI5-TEST home lab</footer>\n  </div>\n<script>\nconst LIME = \'#c9f24b\', RED = \'#ff6b6b\';\nconst esc = s => String(s).replace(/[&<>"\']/g, c => ({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[c]));\nconst set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };\nconst bar = (id, pct) => { const el = document.getElementById(id); if (el) el.style.width = pct + \'%\'; };\n\nasync function refresh() {\n  try {\n    const r = await fetch(\'api/stats\', {cache: \'no-store\'});\n    if (!r.ok) return;\n    const d = await r.json();\n    set(\'v-temp\', d.system.temp);\n    set(\'v-load\', d.system.load);\n    set(\'v-mem\', d.system.mem); set(\'v-mem2\', d.system.mem); bar(\'v-mem-bar\', d.system.mem_pct);\n    set(\'v-disk-pct\', d.system.disk_pct + \'%\');\n    set(\'v-disk\', d.system.disk);\n    set(\'v-disk2\', d.system.disk + \' (\' + d.system.disk_pct + \'%)\');\n    bar(\'v-disk-bar\', d.system.disk_pct);\n    set(\'v-uptime\', d.system.uptime);\n    set(\'v-nas-pct\', d.nas.nas_pct + \'%\');\n    set(\'v-nas\', d.nas.nas);\n    bar(\'v-nas-bar\', d.nas.nas_pct);\n\n    const cores = document.getElementById(\'v-cores\');\n    if (cores) cores.innerHTML = d.sysdetail.cores.map((c, i) =>\n      \'<div class="corerow"><span class="mono">core\' + i + \'</span><div class="bar"><div style="width:\' + c + \'%"></div></div><span class="mono">\' + c + \'%</span></div>\').join(\'\');\n    set(\'v-freq\', d.sysdetail.freq);\n    const thr = document.getElementById(\'v-thr\');\n    if (thr) { thr.textContent = d.sysdetail.throttled; thr.style.color = d.sysdetail.throttled_ok ? LIME : RED; }\n\n    const procs = document.getElementById(\'v-procs\');\n    if (procs) procs.innerHTML = d.sysdetail.procs.map(p =>\n      \'<tr><td>\' + esc(p.name) + \'</td><td class="mono">\' + p.cpu + \'</td><td class="mono">\' + p.mem + \'</td></tr>\').join(\'\');\n    set(\'v-model\', d.sysdetail.model);\n    set(\'v-ips\', d.sysdetail.ips);\n    set(\'v-swap\', d.sysdetail.swap);\n\n    const svc = document.getElementById(\'v-services\');\n    if (svc) svc.innerHTML = d.services.map(s =>\n      \'<div class="svc"><span class="dot \' + (s.active ? \'on\' : \'off\') + \'"></span><span class="nm">\' + esc(s.name) + \'</span><span class="mono">\' + (s.active ? \'running\' : \'down\') + \'</span></div>\').join(\'\');\n\n    set(\'v-sp-ver\', d.secplatform.version);\n    const pill = document.getElementById(\'v-sp-pill\');\n    if (pill) { pill.textContent = d.secplatform.ok ? \'healthy\' : \'down\'; pill.className = \'pill \' + (d.secplatform.ok ? \'on\' : \'off\'); }\n\n    set(\'v-ph-q\', d.pihole.queries !== undefined ? d.pihole.queries : \'N/A\');\n    set(\'v-ph-b\', d.pihole.blocked !== undefined ? d.pihole.blocked : \'N/A\');\n    set(\'v-ph-p\', (d.pihole.percentage !== undefined ? d.pihole.percentage : \'N/A\') + \'%\');\n    set(\'v-bw-rx\', d.bandwidth.today_rx || \'N/A\');\n    set(\'v-bw-tx\', d.bandwidth.today_tx || \'N/A\');\n    set(\'v-bw-mrx\', d.bandwidth.month_rx || \'N/A\');\n\n    const ts = document.getElementById(\'v-tailnet\');\n    if (ts) ts.innerHTML = d.tailnet.map(t =>\n      \'<tr><td>\' + esc(t.name) + \'</td><td class="mono">\' + esc(t.ip) + \'</td><td><span class="pill \' + (t.online ? \'on\' : \'off\') + \'">\' + (t.online ? \'online\' : \'offline\') + \'</span></td></tr>\').join(\'\');\n    set(\'v-ts-count\', \'(\' + d.tailnet.length + \')\');\n\n    const dk = document.getElementById(\'v-docker\');\n    if (dk) dk.innerHTML = d.containers.map(c =>\n      \'<tr><td>\' + esc(c.name) + \'</td><td class="mono">\' + esc(c.status) + \'</td></tr>\').join(\'\');\n    set(\'v-dk-count\', \'(\' + d.containers.length + \')\');\n\n\n    set(\'v-updated\', \'Updated \' + new Date().toLocaleTimeString());\n  } catch (e) { /* keep last good data */ }\n}\nlet logSource = \'pihole\';\nfunction setLogSource(s){ logSource = s;\n  document.getElementById(\'tab-pihole\').className = \'tab\' + (s===\'pihole\' ? \' active\' : \'\');\n  document.getElementById(\'tab-system\').className = \'tab\' + (s===\'system\' ? \' active\' : \'\');\n  refreshLogs();\n}\nasync function refreshLogs(){\n  const box = document.getElementById(\'v-logs\');\n  if(!box) return;\n  try{\n    const r = await fetch(\'api/logs?source=\' + logSource + \'&limit=30\', {cache: \'no-store\'});\n    if(!r.ok) return;\n    const d = await r.json();\n    if(d.source === \'system\'){\n      box.innerHTML = d.lines.map(l => \'<div class="lsys">\'+esc(l)+\'</div>\').join(\'\');\n    } else {\n      box.innerHTML = d.queries.map(q => {\n        const t = q.time ? new Date(q.time*1000).toLocaleTimeString() : \'\';\n        return \'<div class="logline"><span class="lt">\'+t+\'</span>\'+\n          \'<span class="lc">\'+esc(q.client||\'\')+\'</span>\'+\n          \'<span class="ld">\'+esc(q.domain||\'\')+\'</span>\'+\n          \'<span class="lb \'+(q.blocked?\'yes\':\'no\')+\'">\'+(q.blocked?\'BLOCKED\':\'ok\')+\'</span></div>\';\n      }).join(\'\') || \'<div class="lsys">no queries</div>\';\n    }\n  } catch(e){ }\n}\nlet netTab = \'devices\';\nfunction setNetTab(t){ netTab = t;\n  for (const k of [\'devices\',\'traffic\',\'conns\']) {\n    document.getElementById(\'tab-\'+k).className = \'tab\' + (k===t ? \' active\' : \'\');\n    document.getElementById(\'v-net-\'+k).hidden = (k!==t);\n  }\n  refreshNet();\n}\nconst fmtRate = b => b < 1024 ? b + \' B/s\' : b < 1048576 ? (b/1024).toFixed(1) + \' KB/s\' : (b/1048576).toFixed(2) + \' MB/s\';\nasync function refreshNet(){\n  try{\n    const r = await fetch(\'api/network\', {cache: \'no-store\'});\n    if(!r.ok) return;\n    const d = await r.json();\n    const dev = document.getElementById(\'v-devtab\');\n    if (dev) dev.innerHTML = d.devices.map(x =>\n      \'<tr><td class="mono">\'+esc(x.ip)+\'</td><td>\'+esc(x.hostname||\'Unknown\')+\'</td><td class="mono">\'+esc(x.mac||\'N/A\')+\'</td><td>\'+esc(x.vendor||\'Unknown\')+\'</td></tr>\').join(\'\');\n    const rt = document.getElementById(\'v-rates\');\n    if (rt) rt.innerHTML = d.traffic.length ? d.traffic.map(t =>\n      \'<div class="s"><div class="v" style="font-size:1rem">\'+esc(t.iface)+\'</div><div class="l"><span style="color:#c9f24b">&#8595; \'+fmtRate(t.rx_rate)+\'</span> &middot; <span style="color:#79c0ff">&#8593; \'+fmtRate(t.tx_rate)+\'</span></div></div>\').join(\'\')\n      : \'<div class="lsys">collecting baseline...</div>\';\n    const bl = document.getElementById(\'v-blocked\');\n    if (bl) bl.innerHTML = \'<div class="kv"><span style="color:#ff6b6b">Blocked today (ads / trackers / malware)</span><b style="color:#ff6b6b">\'+(d.blocked?d.blocked.today:0)+\'</b></div>\' +\n      ((d.blocked&&d.blocked.domains)||[]).map(x=>\'<div class="kv"><span class="mono">\'+esc(x.domain)+\'</span><b>\'+x.count+\' blocked</b></div>\').join(\'\');\n    const cn = document.getElementById(\'v-conntab\');\n    if (cn) cn.innerHTML = d.connections.length ? d.connections.map(c =>\n      \'<tr><td class="mono">\'+esc(c.proto)+\'</td><td class="mono">\'+esc(c.local)+\'</td><td class="mono">\'+esc(c.remote)+\'</td><td>\'+esc(c.state)+\'</td></tr>\').join(\'\')\n      : \'<tr><td colspan="4" class="mono">no active connections</td></tr>\';\n  } catch(e){ }\n}\nrefresh();\nrefreshLogs();\nrefreshNet();\nsetInterval(refresh, 5000);\nsetInterval(refreshLogs, 5000);\nsetInterval(refreshNet, 5000);\n</script>\n</body>\n</html>\n'

@app.route('/')
def index():
    sid = get_pihole_token()
    return render_template_string(HTML,
        devices=get_devices(sid),
        bandwidth=get_bandwidth(),
        pihole=get_pihole(sid),
        system=sysstats.get_system(),
        services=sysstats.get_services(),
        secplatform=sysstats.get_secplatform(),
        tailnet=sysstats.get_tailscale(),
        containers=sysstats.get_docker(),
        sysdetail=sysstats.get_system_detail(),
        nas=sysstats.get_nas()
    )

@app.route('/api/stats')
def api_stats():
    sid = get_pihole_token()
    return jsonify(
        system=sysstats.get_system(),
        services=sysstats.get_services(),
        secplatform=sysstats.get_secplatform(),
        tailnet=sysstats.get_tailscale(),
        containers=sysstats.get_docker(),
        sysdetail=sysstats.get_system_detail(),
        pihole=get_pihole(sid),
        bandwidth=get_bandwidth(),
        devices=get_devices(sid),
        nas=sysstats.get_nas(),
    )



def get_pihole_queries(limit=30):
    data = _pihole_api("/api/queries?per_page=%d" % limit, timeout=8)
    try:
        out = []
        for q in data.get("queries", [])[:limit]:
            st = q.get("status", "")
            out.append({
                "time": q.get("time"),
                "domain": q.get("domain", ""),
                "client": q.get("client", ""),
                "type": q.get("type", ""),
                "blocked": st in ("GRAVITY", "GRAVITY_CNAME", "DENYLIST",
                                  "DENYLIST_CNAME", "REGEX", "REGEX_CNAME"),
            })
        return out
    except Exception:
        return []


def get_system_log(limit=40):
    try:
        r = subprocess.run(["journalctl", "-n", str(limit), "--no-pager", "-o", "short"],
                           capture_output=True, text=True, timeout=8)
        return [l[:220] for l in r.stdout.strip().split("\n") if l.strip()]
    except Exception as e:
        return ["log unavailable: %s" % e]


def get_blocked(limit=8):
    """Unwanted traffic: today's blocked count + top blocked domains (Pi-hole)."""
    try:
        data = _pihole_api('/api/stats/top_domains?blocked=true&count=%d' % limit, timeout=8)
        domains = [{'domain': d.get('domain', ''), 'count': d.get('count', 0)}
                   for d in (data.get('domains', []) if data else [])[:limit]]
        summary = _pihole_api('/api/stats/summary', timeout=5)
        today = summary.get('queries', {}).get('blocked', 0) if summary else 0
        return {'today': today, 'domains': domains}
    except Exception:
        return {'today': 0, 'domains': []}


_net_last = None


def get_traffic_rates():
    """Live per-interface rx/tx bytes/sec, from /proc/net/dev deltas."""
    global _net_last
    import time as _time
    cur = {}
    try:
        with open('/proc/net/dev') as f:
            for line in f:
                if ':' not in line:
                    continue
                iface, data = line.split(':', 1)
                iface = iface.strip()
                if iface == 'lo':
                    continue
                parts = data.split()
                cur[iface] = (int(parts[0]), int(parts[8]))
    except Exception:
        return []
    now = _time.time()
    out = []
    if _net_last:
        dt = max(now - _net_last[0], 0.001)
        for iface, (rx, tx) in cur.items():
            if iface in _net_last[1]:
                prx, ptx = _net_last[1][iface]
                out.append({
                    'iface': iface,
                    'rx_rate': max(int((rx - prx) / dt), 0),
                    'tx_rate': max(int((tx - ptx) / dt), 0),
                })
    _net_last = (now, cur)
    out.sort(key=lambda x: x['iface'])
    return out


def get_connections(limit=40):
    """Active connections (ss -tun): lightweight conversations view."""
    try:
        r = subprocess.run(['ss', '-tun'], capture_output=True, text=True, timeout=8)
        conns = []
        for line in r.stdout.strip().split(chr(10))[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            conns.append({
                'proto': parts[0],
                'state': parts[1],
                'local': parts[4],
                'remote': parts[5],
            })
            if len(conns) >= limit:
                break
        return conns
    except Exception:
        return []


@app.route("/api/logs")
def api_logs():
    source = request.args.get("source", "pihole")
    try:
        limit = min(int(request.args.get("limit", 30)), 100)
    except ValueError:
        limit = 30
    if source == "system":
        return jsonify(source="system", lines=get_system_log(limit))
    return jsonify(source="pihole", queries=get_pihole_queries(limit))


@app.route("/api/network")
def api_network():
    sid = get_pihole_token()
    return jsonify(
        devices=get_devices(sid),
        traffic=get_traffic_rates(),
        connections=get_connections(),
        blocked=get_blocked(),
    )


@app.route('/portfolio')
def portfolio():
    try:
        with open('/home/admin/dashboard/portfolio.json', 'r') as f:
            return jsonify(json.load(f))
    except:
        return jsonify({})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)

