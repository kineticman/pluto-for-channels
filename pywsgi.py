from gevent.pywsgi import WSGIServer
from flask import Flask, redirect, request, Response, send_file
from threading import Thread
import os, sys, importlib, schedule, time, re, uuid, unicodedata
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from datetime import datetime, timedelta

# import flask module
from gevent import monkey
monkey.patch_all()

import requests


version = "1.26"
updated_date = "Mar. 11, 2026"
STARTUP_NETWORK_WAIT_SECONDS = 45
STARTUP_NETWORK_WAIT_INTERVAL = 5

# Retrieve the port number from env variables
# Fallback to default if invalid or unspecified
try:
    port = int(os.environ.get("PLUTO_PORT", 7777))
except:
    port = 7777

try:
    channel_start = int(os.environ.get("PLUTO_START", 0))
except (ValueError, TypeError):
    channel_start = 0

# Get Username and Password from environment variables
pluto_username = os.environ.get("PLUTO_USERNAME")
pluto_password = os.environ.get("PLUTO_PASSWORD")

pluto_country_list = os.environ.get("PLUTO_CODE")
if pluto_country_list:
   pluto_country_list = pluto_country_list.split(',')
else:
   pluto_country_list = ['local', 'us_east', 'us_west', 'ca', 'uk', 'fr', 'de']

ALLOWED_COUNTRY_CODES = ['local', 'us_east', 'us_west', 'ca', 'uk', 'fr', 'de', 'all']
# instance of flask application
app = Flask(__name__)
provider = "pluto"
providers = {
    provider: importlib.import_module(provider).Client(pluto_username, pluto_password),
}

def wait_for_pluto_network():
    deadline = time.time() + STARTUP_NETWORK_WAIT_SECONDS
    attempt = 0
    url = "https://boot.pluto.tv/v4/start"

    while True:
        attempt += 1
        try:
            response = requests.get(url, timeout=5)
            if response.status_code < 500:
                print(f"[INFO] Pluto network ready after attempt {attempt}")
                return
            error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            error = type(exc).__name__

        remaining = int(max(0, deadline - time.time()))
        if remaining <= 0:
            print(f"[WARN] Pluto network not ready after {attempt} attempts; continuing startup")
            return

        print(f"[WARN] Pluto network not ready (attempt {attempt}: {error}); retrying in {STARTUP_NETWORK_WAIT_INTERVAL}s")
        time.sleep(min(STARTUP_NETWORK_WAIT_INTERVAL, remaining))

def remove_non_printable(s):
    return ''.join([char for char in s if not unicodedata.category(char).startswith('C')])

url = f'<!DOCTYPE html>\
        <html>\
          <head>\
            <meta charset="utf-8">\
            <meta name="viewport" content="width=device-width, initial-scale=1">\
            <title>{provider.capitalize()} Playlist</title>\
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.1/css/bulma.min.css">\
            <style>\
              body {{ \
                min-height: 100vh; \
                background: linear-gradient(180deg, #0f172a 0%, #111827 42%, #1f2937 100%); \
                color: #e5e7eb; \
              }}\
              .section {{ \
                padding: 2.5rem 1.25rem 4rem; \
              }}\
              .shell {{ \
                max-width: 1180px; \
                margin: 0 auto; \
              }}\
              .hero-panel {{ \
                background: rgba(15, 23, 42, 0.82); \
                border: 1px solid rgba(148, 163, 184, 0.18); \
                border-radius: 20px; \
                padding: 1.5rem; \
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25); \
                margin-bottom: 1.25rem; \
              }}\
              .title, .subtitle, .section-title, .label-title {{ \
                color: #f8fafc; \
              }}\
              .hero-meta {{ \
                display: flex; \
                flex-wrap: wrap; \
                gap: 0.75rem; \
                align-items: center; \
                justify-content: space-between; \
              }}\
              .hero-copy {{ \
                color: #cbd5e1; \
                max-width: 46rem; \
                margin-top: 0.75rem; \
              }}\
              .version-tag {{ \
                background: #22c55e; \
                color: #052e16; \
                font-weight: 700; \
                border-radius: 999px; \
                padding: 0.35rem 0.7rem; \
              }}\
              .subtle-tag {{ \
                background: rgba(59, 130, 246, 0.18); \
                color: #bfdbfe; \
                border-radius: 999px; \
                padding: 0.35rem 0.7rem; \
                font-size: 0.9rem; \
              }}\
              .stack {{ \
                display: flex; \
                flex-direction: column; \
                gap: 1rem; \
              }}\
              .panel {{ \
                background: rgba(15, 23, 42, 0.74); \
                border: 1px solid rgba(148, 163, 184, 0.18); \
                border-radius: 18px; \
                padding: 1rem; \
                box-shadow: 0 12px 30px rgba(0, 0, 0, 0.2); \
              }}\
              .panel + .panel {{ \
                margin-top: 1rem; \
              }}\
              .section-title {{ \
                font-size: 1.1rem; \
                font-weight: 700; \
                margin-bottom: 0.85rem; \
                text-align: center; \
              }}\
              .admin-grid {{ \
                display: grid; \
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); \
                gap: 0.75rem; \
              }}\
              .stat-card {{ \
                background: rgba(30, 41, 59, 0.8); \
                border: 1px solid rgba(148, 163, 184, 0.14); \
                border-radius: 14px; \
                padding: 0.85rem 0.95rem; \
              }}\
              .stat-key {{ \
                color: #93c5fd; \
                font-size: 0.78rem; \
                font-weight: 700; \
                letter-spacing: 0.04em; \
                text-transform: uppercase; \
                margin-bottom: 0.3rem; \
              }}\
              .stat-value {{ \
                color: #f8fafc; \
                font-weight: 600; \
                word-break: break-word; \
              }}\
              .link-list {{ \
                display: flex; \
                flex-direction: column; \
                gap: 0.75rem; \
              }}\
              .list-item {{ \
                display: flex; \
                align-items: flex-start; \
                justify-content: space-between; \
                gap: 1rem; \
                padding: 0.95rem 0; \
                border-top: 1px solid rgba(148, 163, 184, 0.12); \
              }}\
              .list-item:first-child {{ \
                border-top: none; \
                padding-top: 0; \
              }}\
              .item-copy {{ \
                flex: 1; \
                min-width: 0; \
              }}\
              .label-title {{ \
                font-weight: 700; \
                margin-bottom: 0.25rem; \
              }}\
              .label-subtitle {{ \
                color: #94a3b8; \
                font-size: 0.92rem; \
                line-height: 1.4; \
              }}\
              a {{ \
                color: #7dd3fc; \
                word-break: break-all; \
                text-decoration: none; \
              }}\
              a:hover {{ \
                color: #bae6fd; \
              }}\
              .copy-button {{ \
                background: #2563eb; \
                color: white; \
                border: none; \
                padding: 0.6rem 0.85rem; \
                border-radius: 10px; \
                cursor: pointer; \
                transition: background-color 0.3s; \
                flex-shrink: 0; \
                font-weight: 600; \
              }}\
              .copy-button:hover {{ \
                background: #3b82f6; \
              }}\
              .empty-state {{ \
                color: #fecaca; \
              }}\
              @media (max-width: 768px) {{ \
                .list-item {{ \
                  flex-direction: column; \
                }}\
                .copy-button {{ \
                  width: 100%; \
                }}\
              }}\
            </style>\
            <script>\
              function copyToClipboard(text) {{\
                const textarea = document.createElement(\'textarea\');\
                textarea.value = text;\
                textarea.style.position = \'fixed\';\
                textarea.style.left = \'-9999px\';\
                document.body.appendChild(textarea);\
                textarea.select();\
                try {{\
                  document.execCommand(\'copy\');\
                }} catch (err) {{\
                  console.error(\'Fallback: Oops, unable to copy\', err);\
                }}\
                document.body.removeChild(textarea);\
              }}\
            </script>\
          </head>\
          <body>\
          <section class="section">\
            <div class="shell">\
              <div class="hero-panel">\
                <div class="hero-meta">\
                  <h1 class="title">\
                    {provider.capitalize()} Playlist\
                  </h1>\
                  <div>\
                    <span class="version-tag">v{version}</span>\
                    <span class="subtle-tag">Updated {updated_date}</span>\
                  </div>\
                </div>\
                <p class="hero-copy">\
                  Status, runtime settings, playlist URLs, and EPG endpoints for this Pluto deployment.\
                </p>\
              </div>\
              '


def render_link_item(title, description, link):
    return (
        f"<div class='list-item'>"
        f"<div class='item-copy'>"
        f"<div class='label-title'>{title}</div>"
        f"<div class='label-subtitle'>{description}</div>"
        f"<a href='{link}'>{link}</a>"
        f"</div>"
        f"<button class='copy-button' onclick=\"copyToClipboard('{link}')\">Copy</button>"
        f"</div>\n"
    )

@app.route("/")
def index():
    host = request.host
    stream_pool_size = len(getattr(providers[provider], "_pool", []))
    admin_items = [
        ("PLUTO_PORT", str(port)),
        ("PLUTO_START", str(channel_start)),
        ("PLUTO_STREAM_POOL_SIZE", str(stream_pool_size)),
        ("PLUTO_CODE", ", ".join(pluto_country_list)),
        ("PLUTO_USERNAME", pluto_username or "(not set)"),
        ("PLUTO_PASSWORD", "configured" if pluto_password else "(not set)"),
    ]

    admin_stats = "<div class='panel'><div class='section-title'>Admin</div><div class='admin-grid'>"
    for key, value in admin_items:
        admin_stats += (
            f"<div class='stat-card'>"
            f"<div class='stat-key'>{key}</div>"
            f"<div class='stat-value'>{value}</div>"
            f"</div>\n"
        )
    admin_stats += "</div></div>\n"

    sections = ""

    if all(item in ALLOWED_COUNTRY_CODES for item in pluto_country_list):
        pl = f"http://{host}/{provider}/all/playlist.m3u"
        all_links = ""
        all_links += render_link_item(
            f"{provider.upper()} ALL playlist",
            f"channel_id_format = \"{provider}-{{slug}}\" (default format)",
            pl,
        )
        pl = f"http://{host}/{provider}/all/playlist.m3u?channel_id_format=id"
        all_links += render_link_item(
            f"{provider.upper()} ALL playlist",
            f"channel_id_format = \"{provider}-{{id}}\" (i.mjh.nz compatibility)",
            pl,
        )
        pl = f"http://{host}/{provider}/all/playlist.m3u?channel_id_format=slug_only"
        all_links += render_link_item(
            f"{provider.upper()} ALL playlist",
            "channel_id_format = \"{slug}\" (maddox compatibility)",
            pl,
        )
        pl = f"http://{host}/{provider}/epg/all/epg-all.xml"
        all_links += render_link_item(f"{provider.upper()} ALL EPG", "XML guide", pl)
        pl = f"http://{host}/{provider}/epg/all/epg-all.xml.gz"
        all_links += render_link_item(f"{provider.upper()} ALL EPG", "Gzip-compressed XML guide", pl)
        sections += f"<div class='panel'><div class='section-title'>ALL</div><div class='link-list'>{all_links}</div></div>\n"

        for code in pluto_country_list:
            country_links = ""
            pl = f"http://{host}/{provider}/{code}/playlist.m3u"
            country_links += render_link_item(
                f"{provider.upper()} {code.upper()} playlist",
                f"channel_id_format = \"{provider}-{{slug}}\" (default format)",
                pl,
            )
            pl = f"http://{host}/{provider}/{code}/playlist.m3u?channel_id_format=id"
            country_links += render_link_item(
                f"{provider.upper()} {code.upper()} playlist",
                f"channel_id_format = \"{provider}-{{id}}\" (i.mjh.nz compatibility)",
                pl,
            )
            pl = f"http://{host}/{provider}/{code}/playlist.m3u?channel_id_format=slug_only"
            country_links += render_link_item(
                f"{provider.upper()} {code.upper()} playlist",
                "channel_id_format = \"{slug}\" (maddox compatibility)",
                pl,
            )
            pl = f"http://{host}/{provider}/epg/{code}/epg-{code}.xml"
            country_links += render_link_item(f"{provider.upper()} {code.upper()} EPG", "XML guide", pl)
            pl = f"http://{host}/{provider}/epg/{code}/epg-{code}.xml.gz"
            country_links += render_link_item(f"{provider.upper()} {code.upper()} EPG", "Gzip-compressed XML guide", pl)
            sections += f"<div class='panel'><div class='section-title'>{code.upper()}</div><div class='link-list'>{country_links}</div></div>\n"
    else:
        sections += (
            f"<div class='panel empty-state'>"
            f"INVALID COUNTRY CODE in \"{', '.join(pluto_country_list).upper()}\""
            f"</div>\n"
        )
    return f"{url}{admin_stats}<div class='stack'>{sections}</div></div></section></body></html>"

@app.route("/<country_code>/token")
def token(country_code):
    resp, error = providers[provider].resp_data(country_code)
    if error: return f"ERROR: {error}", 400
    token = resp.get('sessionToken', None)
    return(token)

@app.route("/<country_code>/resp")
def resp(country_code):
    resp, error = providers[provider].resp_data(country_code)
    if error: return f"ERROR: {error}", 400
    # token = resp.get('sessionToken', None)
    return(resp)

@app.route("/<provider>/<country_code>/channels")
def channels(provider, country_code):
    # host = request.host
    channels, error = providers[provider].channels(country_code)
    if error: return f"ERROR: {error}", 400
    return(channels)

@app.get("/<provider>/<country_code>/epg.json")
def epg_json(provider, country_code):
        epg, err = providers[provider].epg_json(country_code)
        if err: return err
        return epg.get(country_code)

@app.get("/<provider>/<country_code>/stitcher.json")
def stitch_json(provider, country_code):
    resp, error= providers[provider].resp_data(country_code)
    if error: return error, 500
    return resp

@app.get("/<provider>/<country_code>/playlist.m3u")
def playlist(provider, country_code):
    if country_code.lower() == 'all':
        stations, err = providers[provider].channels_all()
    elif country_code.lower() in ALLOWED_COUNTRY_CODES:
        stations, err = providers[provider].channels(country_code)
    else: # country_code not in ALLOWED_COUNTRY_CODES
        return "Invalid county code", 400

    host = request.host
    channel_id_format = request.args.get('channel_id_format','').lower()
    
    if err is not None:
        return err, 500
    stations = sorted(stations, key = lambda i: i.get('number', 0))

    m3u = "#EXTM3U\r\n\r\n"
    for s in stations:
        url = f"http://{host}/{provider}/{country_code}/watch/{s.get('watchId') or s.get('id')}\n\n"

        if channel_id_format == 'id':
            m3u += f"#EXTINF:-1 channel-id=\"{provider}-{s.get('id')}\""
        elif channel_id_format == 'slug_only':
            m3u += f"#EXTINF:-1 channel-id=\"{s.get('slug')}\""
        else:
            m3u += f"#EXTINF:-1 channel-id=\"{provider}-{s.get('slug')}\""
        m3u += f" tvg-id=\"{s.get('id')}\""
        m3u += f" tvg-chno=\"{''.join(map(str, str(s.get('number', []) + channel_start)))}\"" if s.get('number') else ""
        m3u += f" group-title=\"{''.join(map(str, s.get('group', [])))}\"" if s.get('group') else ""
        m3u += f" tvg-logo=\"{''.join(map(str, s.get('logo', [])))}\"" if s.get('logo') else ""
        m3u += f" tvg-name=\"{''.join(map(str, s.get('tmsid', [])))}\"" if s.get('tmsid') else ""
        m3u += f" tvc-guide-title=\"{''.join(map(str, s.get('name', [])))}\"" if s.get('name') else ""
        m3u += f" tvc-guide-description=\"{remove_non_printable(''.join(map(str, s.get('summary', []))))}\"" if s.get('summary') else ""
        m3u += f" tvg-shift=\"{''.join(map(str, s.get('timeShift', [])))}\"" if s.get('timeShift') else ""
        m3u += f",{s.get('name') or s.get('call_sign')}\n"
        m3u += f"{url}\n"

    response = Response(m3u, content_type='audio/x-mpegurl')
    return (response)

@app.get("/mjh_compatible/<provider>/<country_code>/playlist.m3u")
def playlist_mjh_compatible(provider, country_code):
    host = request.host
    return (redirect(f"http://{host}/{provider}/{country_code}/playlist.m3u?compatibility=id"))

@app.get("/maddox_compatible/<provider>/<country_code>/playlist.m3u")
def playlist_maddox_compatible(provider, country_code):
    host = request.host
    return (redirect(f"http://{host}/{provider}/{country_code}/playlist.m3u?compatibility=slug_only"))

@app.route("/<provider>/<country_code>/watch/<id>")
def watch(provider, country_code, id):
    sid = uuid.uuid4()
    stitcher = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
    base_path = f"/stitch/hls/channel/{id}/master.m3u8"

    # Use a pool slot so each concurrent stream gets its own clientID device identity
    token, slot_session, error = providers[provider].get_stream_token(country_code)
    if error: return error, 500

    # Get stitcherParams from the same slot's cached response
    resp = slot_session.response_list.get(country_code, {})
    stitcherParams = resp.get("stitcherParams", '')

    # Construct the authenticated URL for all streams
    video_url = f'{stitcher}/v2{base_path}?{stitcherParams}&jwt={token}&masterJWTPassthrough=true&includeExtendedEvents=true'

    print(f"[stream] slot={slot_session.client_id[:8]} channel={id} country={country_code}")
    return redirect(video_url)
@app.get("/<provider>/epg/<country_code>/<filename>")
def epg_xml(provider, country_code, filename):

    # Generate ALLOWED_FILENAMES and ALLOWED_GZ_FILENAMES based on ALLOWED_COUNTRY_CODES
    ALLOWED_EPG_FILENAMES = {f'epg-{code}.xml' for code in ALLOWED_COUNTRY_CODES}
    ALLOWED_GZ_FILENAMES = {f'epg-{code}.xml.gz' for code in ALLOWED_COUNTRY_CODES}

    # Specify the file path
    # file_path = 'epg.xml'
    try:
        if country_code not in ALLOWED_COUNTRY_CODES:
            return "Invalid county code", 400

        # Check if the provided filename is allowed in either format
        if filename not in ALLOWED_EPG_FILENAMES and filename not in ALLOWED_GZ_FILENAMES:
        # Check if the provided filename is allowed
        # if filename not in ALLOWED_EPG_FILENAMES:
            return "Invalid filename", 400
        
        # Specify the file path based on the provider and filename
        file_path = f'{filename}'

        # Return the file without explicitly opening it
        if filename in ALLOWED_EPG_FILENAMES: 
            return send_file(file_path, as_attachment=False, download_name=file_path, mimetype='text/plain')
        elif filename in ALLOWED_GZ_FILENAMES:
            return send_file(file_path, as_attachment=True, download_name=file_path)

    except FileNotFoundError:
        # Handle the case where the file is not found
        return "XML file not found", 404
    except Exception as e:
        # Handle other unexpected errors
        return f"An error occurred: {str(e)}", 500


    except Exception as e:
        # Handle other unexpected errors
        return f"An error occurred: {str(e)}", 500

# Define the function you want to execute every four hours
def epg_scheduler():
    print("[INFO] Running EPG Scheduler")
    if all(item in ALLOWED_COUNTRY_CODES for item in pluto_country_list):
        for code in pluto_country_list:
            error = providers[provider].create_xml_file(code)
            if error: print(f"{error}")
        error = providers[provider].create_xml_file(pluto_country_list)
        if error: print(f"{error}")
    print("[INFO] EPG Scheduler Complete")

# Schedule the function to run every two hours
schedule.every(2).hours.do(epg_scheduler)

# Define a function to run the scheduler in a separate thread
def scheduler_thread():
    wait_for_pluto_network()

    # Run the task immediately when the thread starts
    try:
        epg_scheduler()
    except Exception as e:
        print(f"Error running initial task: {e}")

    # Continue as Scheduled
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
             print(f"[ERROR] Error in scheduler thread: {e}")

# Function to monitor and restart the thread if needed
def monitor_thread(thread_func):
    thread = Thread(target=thread_func, daemon=True)
    print("[INFO] Initializing Scheduler")
    thread.start()

    while True:
        if not thread.is_alive():
            print("[ERROR] Scheduler Thread Stopped. Restarting...")
            thread.start()
        time.sleep(15 * 60)  # Check every 15 minutes
        print("[INFO] Checking Scheduler Thread")

if __name__ == '__main__':
    try:
        # Start a monitoring thread
        Thread(target=monitor_thread, args=(scheduler_thread,), daemon=True).start()

        print(f"⇨ http server started on [::]:{port}")
        WSGIServer(('', port), app, log=None).serve_forever()

    except OSError as e:


        print(str(e))
