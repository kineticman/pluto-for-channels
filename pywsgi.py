from gevent.pywsgi import WSGIServer
from flask import Flask, redirect, request, Response, send_file
from threading import Thread, Lock
import io, os, importlib, time, uuid, unicodedata, gzip
import xml.etree.ElementTree as ET
import pytz
from datetime import datetime, timedelta

from gevent import monkey
monkey.patch_all()

version     = "2.0"
updated_date = "2026"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
try:
    port = int(os.environ.get("PLUTO_PORT", 7777))
except Exception:
    port = 7777

pluto_username = os.environ.get("PLUTO_USERNAME")
pluto_password = os.environ.get("PLUTO_PASSWORD")

ALLOWED_COUNTRY_CODES = ['local', 'us_east', 'us_west', 'ca', 'uk', 'fr', 'de', 'all']
REGION_LABELS = {
    'local':   '🇺🇸 Local (US)',
    'us_east': '🇺🇸 US East',
    'us_west': '🇺🇸 US West',
    'ca':      '🇨🇦 Canada',
    'uk':      '🇬🇧 United Kingdom',
    'fr':      '🇫🇷 France',
    'de':      '🇩🇪 Germany',
    'all':     '🌍 All Regions',
}

app      = Flask(__name__)
provider = "pluto"
providers = {
    provider: importlib.import_module(provider).Client(pluto_username, pluto_password),
}

# ---------------------------------------------------------------------------
# Lazy EPG cache
# EPG is generated on first request and cached in memory for 2 hours.
# No scheduler, no files on disk, no env-var region lists needed.
# ---------------------------------------------------------------------------
_epg_cache      = {}   # country_code -> {'xml': bytes, 'gz': bytes, 'generated_at': datetime}
_epg_cache_lock = Lock()
EPG_TTL_HOURS   = 2


def _epg_is_fresh(country_code):
    entry = _epg_cache.get(country_code)
    if not entry:
        return False
    age = datetime.now(pytz.utc) - entry['generated_at']
    return age < timedelta(hours=EPG_TTL_HOURS)


def _build_epg_xml(country_code):
    """Generate EPG XML bytes (and gz bytes) for a region, store in cache."""
    client = providers[provider]

    if country_code == 'all':
        # collect every region except 'all' itself
        regions = [c for c in ALLOWED_COUNTRY_CODES if c != 'all']
        station_list, err = client.channels_all()
    else:
        regions = [country_code]
        station_list, err = client.channels(country_code)

    if err:
        raise RuntimeError(err)

    # Fetch EPG data for each region
    for region in regions:
        err = client.update_epg(region)
        if err:
            raise RuntimeError(err)

    # Build XML tree
    root = ET.Element("tv", attrib={"generator-info-name": "kineticman/pluto-for-channels", "generated-ts": ""})

    for station in station_list:
        ch = ET.SubElement(root, "channel", attrib={"id": station["id"]})
        dn = ET.SubElement(ch, "display-name")
        dn.text = client.strip_illegal_characters(station["name"])
        ET.SubElement(ch, "icon", attrib={"src": station["logo"]})

    if country_code == 'all':
        program_data = client.get_all_epg_data(regions)
    else:
        program_data = client.epg_data.get(country_code, [])

    for elem in program_data:
        root = client.read_epg_data(elem, root)

    ET.indent(ET.ElementTree(root), '  ')
    xml_declaration = "<?xml version='1.0' encoding='utf-8'?>"
    doctype         = '<!DOCTYPE tv SYSTEM "xmltv.dtd">'
    xml_str         = (xml_declaration + '\n' + doctype + '\n'
                       + ET.tostring(root, encoding='utf-8').decode('utf-8'))
    xml_bytes = xml_str.encode('utf-8')

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
        gz.write(xml_bytes)
    gz_bytes = buf.getvalue()

    # Clear raw EPG data from client after building (keep memory lean)
    client.epg_data = {}

    with _epg_cache_lock:
        _epg_cache[country_code] = {
            'xml':          xml_bytes,
            'gz':           gz_bytes,
            'generated_at': datetime.now(pytz.utc),
        }

    return xml_bytes, gz_bytes


def _get_epg(country_code):
    """Return cached EPG or generate fresh. Thread-safe."""
    with _epg_cache_lock:
        fresh = _epg_is_fresh(country_code)

    if fresh:
        entry = _epg_cache[country_code]
        return entry['xml'], entry['gz'], None

    try:
        xml_bytes, gz_bytes = _build_epg_xml(country_code)
        return xml_bytes, gz_bytes, None
    except Exception as e:
        return None, None, str(e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def remove_non_printable(s):
    return ''.join(c for c in s if not unicodedata.category(c).startswith('C'))


# ---------------------------------------------------------------------------
# Admin / index page
# ---------------------------------------------------------------------------
INDEX_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #0d0d0d;
  --surface:   #141414;
  --border:    #2a2a2a;
  --accent:    #e8ff47;
  --accent2:   #47ffe8;
  --text:      #e8e8e8;
  --muted:     #666;
  --mono:      'IBM Plex Mono', monospace;
  --sans:      'IBM Plex Sans', sans-serif;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-weight: 300;
  min-height: 100vh;
}

header {
  border-bottom: 1px solid var(--border);
  padding: 2rem 3rem;
  display: flex;
  align-items: baseline;
  gap: 1.5rem;
}

.wordmark {
  font-family: var(--mono);
  font-size: 1.3rem;
  font-weight: 600;
  letter-spacing: 0.15em;
  color: var(--accent);
  text-transform: uppercase;
}

.version-tag {
  font-family: var(--mono);
  font-size: 0.8rem;
  color: var(--muted);
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: 2px;
}

.status-dot {
  width: 7px;
  height: 7px;
  background: var(--accent);
  border-radius: 50%;
  display: inline-block;
  margin-left: auto;
  box-shadow: 0 0 8px var(--accent);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 3rem;
}

.section-label {
  font-family: var(--mono);
  font-size: 0.75rem;
  letter-spacing: 0.2em;
  color: var(--muted);
  text-transform: uppercase;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}

.region-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  margin-bottom: 3rem;
}

.region-card {
  background: var(--surface);
  padding: 1.5rem;
}

.region-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.2rem;
}

.region-name {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text);
}

.epg-badge {
  font-family: var(--mono);
  font-size: 0.7rem;
  letter-spacing: 0.1em;
  padding: 2px 7px;
  border-radius: 2px;
  margin-left: auto;
}

.epg-fresh  { background: #1a2e00; color: var(--accent); border: 1px solid var(--accent); }
.epg-stale  { background: #1a1400; color: #ffb347;       border: 1px solid #ffb347; }
.epg-none   { background: #1a0a0a; color: var(--muted);  border: 1px solid var(--border); }

.url-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.url-label {
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--muted);
  min-width: 60px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.url-text {
  font-family: var(--mono);
  font-size: 0.82rem;
  color: var(--accent2);
  background: #0a1a18;
  border: 1px solid #1a3530;
  padding: 5px 10px;
  border-radius: 2px;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-decoration: none;
  display: block;
}

.url-text:hover { background: #0d2420; color: var(--accent2); }

.copy-btn {
  font-family: var(--mono);
  font-size: 0.72rem;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 5px 12px;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.copy-btn:hover  { border-color: var(--accent); color: var(--accent); }
.copy-btn.copied { border-color: var(--accent); color: var(--accent); background: #1a2e00; }

.divider {
  height: 1px;
  background: var(--border);
  margin: 1rem 0;
}

.all-card {
  background: linear-gradient(135deg, #0f1a0f 0%, #0a0a1a 100%);
  border: 1px solid #2a3a2a;
  padding: 1.5rem;
  margin-bottom: 3rem;
}

.all-card .region-name { color: var(--accent); }

footer {
  border-top: 1px solid var(--border);
  padding: 1.5rem 3rem;
  font-family: var(--mono);
  font-size: 0.75rem;
  color: var(--muted);
  display: flex;
  justify-content: space-between;
}
"""

INDEX_JS = """
function copyUrl(btn, url) {
  navigator.clipboard.writeText(url).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = url; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
  btn.textContent = 'COPIED';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = 'COPY'; btn.classList.remove('copied'); }, 1500);
}
"""


def epg_status_badge(country_code):
    entry = _epg_cache.get(country_code)
    if not entry:
        return '<span class="epg-badge epg-none">EPG: NOT CACHED</span>'
    age = datetime.now(pytz.utc) - entry['generated_at']
    mins = int(age.total_seconds() / 60)
    if age < timedelta(hours=EPG_TTL_HOURS):
        return f'<span class="epg-badge epg-fresh">EPG: CACHED {mins}m AGO</span>'
    return f'<span class="epg-badge epg-stale">EPG: STALE {mins}m AGO</span>'


def url_row(label, url):
    return f"""
    <div class="url-row">
      <span class="url-label">{label}</span>
      <a class="url-text" href="{url}" title="{url}">{url}</a>
      <button class="copy-btn" onclick="copyUrl(this, '{url}')">COPY</button>
    </div>"""


def region_card(code, host, card_class="region-card"):
    label  = REGION_LABELS.get(code, code.upper())
    badge  = epg_status_badge(code)
    m3u    = f"http://{host}/{provider}/{code}/playlist.m3u"
    epg    = f"http://{host}/{provider}/epg/{code}/epg-{code}.xml"
    epg_gz = f"http://{host}/{provider}/epg/{code}/epg-{code}.xml.gz"

    rows = (url_row("M3U", m3u)
          + url_row("EPG", epg)
          + url_row("EPG.GZ", epg_gz))

    return f"""
    <div class="{card_class}">
      <div class="region-header">
        <span class="region-name">{label}</span>
        {badge}
      </div>
      {rows}
    </div>"""


@app.route("/")
def index():
    host = request.host
    all_block = region_card('all', host, card_class="all-card")

    region_cards = ""
    for code in [c for c in ALLOWED_COUNTRY_CODES if c != 'all']:
        region_cards += region_card(code, host)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pluto for Channels</title>
  <style>{INDEX_CSS}</style>
</head>
<body>
  <header>
    <span class="wordmark">Pluto for Channels</span>
    <span class="version-tag">v{version}</span>
    <span class="status-dot"></span>
  </header>
  <main>
    <p class="section-label">All Regions — Combined Playlist &amp; EPG</p>
    {all_block}

    <p class="section-label">Individual Regions</p>
    <div class="region-grid">
      {region_cards}
    </div>
  </main>
  <footer>
    <span>EPG is generated on first request · cached {EPG_TTL_HOURS}h · auto-refreshed on next request after expiry</span>
    <span>pluto-for-channels v{version}</span>
  </footer>
  <script>{INDEX_JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/<country_code>/token")
def token(country_code):
    resp, error = providers[provider].resp_data(country_code)
    if error: return f"ERROR: {error}", 400
    return resp.get('sessionToken', '')


@app.route("/<country_code>/resp")
def resp_route(country_code):
    resp, error = providers[provider].resp_data(country_code)
    if error: return f"ERROR: {error}", 400
    return resp


@app.route("/<prov>/<country_code>/channels")
def channels(prov, country_code):
    ch, error = providers[prov].channels(country_code)
    if error: return f"ERROR: {error}", 400
    return ch


@app.get("/<prov>/<country_code>/epg.json")
def epg_json(prov, country_code):
    epg, err = providers[prov].epg_json(country_code)
    if err: return err
    return epg.get(country_code)


@app.get("/<prov>/<country_code>/stitcher.json")
def stitch_json(prov, country_code):
    resp, error = providers[prov].resp_data(country_code)
    if error: return error, 500
    return resp


@app.get("/<prov>/<country_code>/playlist.m3u")
def playlist(prov, country_code):
    if country_code.lower() == 'all':
        stations, err = providers[prov].channels_all()
    elif country_code.lower() in ALLOWED_COUNTRY_CODES:
        stations, err = providers[prov].channels(country_code)
    else:
        return "Invalid country code", 400

    if err: return err, 500

    host = request.host
    channel_id_format = request.args.get('channel_id_format', '').lower()
    stations = sorted(stations, key=lambda i: i.get('number', 0))

    m3u = "#EXTM3U\r\n\r\n"
    for s in stations:
        stream_url = f"http://{host}/{prov}/{country_code}/watch/{s.get('watchId') or s.get('id')}\n\n"

        if channel_id_format == 'id':
            m3u += f'#EXTINF:-1 channel-id="{prov}-{s.get("id")}"'
        elif channel_id_format == 'slug_only':
            m3u += f'#EXTINF:-1 channel-id="{s.get("slug")}"'
        else:
            m3u += f'#EXTINF:-1 channel-id="{prov}-{s.get("slug")}"'

        m3u += f' tvg-id="{s.get("id")}"'
        if s.get('number'):
            m3u += f' tvg-chno="{s.get("number")}"'
        if s.get('group'):
            m3u += f' group-title="{s.get("group")}"'
        if s.get('logo'):
            m3u += f' tvg-logo="{s.get("logo")}"'
        if s.get('tmsid'):
            m3u += f' tvg-name="{s.get("tmsid")}"'
        if s.get('name'):
            m3u += f' tvc-guide-title="{s.get("name")}"'
        if s.get('summary'):
            m3u += f' tvc-guide-description="{remove_non_printable(s.get("summary"))}"'
        if s.get('timeShift'):
            m3u += f' tvg-shift="{s.get("timeShift")}"'

        m3u += f',{s.get("name") or s.get("call_sign")}\n'
        m3u += f'{stream_url}\n'

    return Response(m3u, content_type='audio/x-mpegurl')


@app.route("/<prov>/<country_code>/watch/<id>")
def watch(prov, country_code, id):
    stitcher  = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
    base_path = f"/stitch/hls/channel/{id}/master.m3u8"

    token, slot_session, error = providers[prov].get_stream_token(country_code)
    if error: return error, 500

    resp           = slot_session.response_list.get(country_code, {})
    stitcherParams = resp.get("stitcherParams", '')

    video_url = f'{stitcher}/v2{base_path}?{stitcherParams}&jwt={token}&masterJWTPassthrough=true&includeExtendedEvents=true'
    print(f"[stream] slot={slot_session.client_id[:8]} channel={id} country={country_code}")
    return redirect(video_url)


@app.get("/<prov>/epg/<country_code>/epg-<code>.xml")
def epg_xml(prov, country_code, code):
    if country_code not in ALLOWED_COUNTRY_CODES or country_code != code:
        return "Invalid country code", 400
    xml_bytes, _, err = _get_epg(country_code)
    if err:   return f"EPG generation failed: {err}", 500
    return Response(xml_bytes, content_type='text/xml; charset=utf-8')


@app.get("/<prov>/epg/<country_code>/epg-<code>.xml.gz")
def epg_xml_gz(prov, country_code, code):
    if country_code not in ALLOWED_COUNTRY_CODES or country_code != code:
        return "Invalid country code", 400
    _, gz_bytes, err = _get_epg(country_code)
    if err: return f"EPG generation failed: {err}", 500
    return Response(gz_bytes,
                    content_type='application/gzip',
                    headers={'Content-Disposition': f'attachment; filename="epg-{country_code}.xml.gz"'})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    try:
        print(f"⇨ http server started on [::]:{port}")
        WSGIServer(('', port), app, log=None).serve_forever()
    except OSError as e:
        print(str(e))
