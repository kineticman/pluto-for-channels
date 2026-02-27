import uuid, requests, json, pytz, gzip, re
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import threading

# ---------------------------------------------------------------------------
# Multi-stream workaround
# ---------------------------------------------------------------------------
# Pluto TV enforces one active stream per "device" (identified by clientID).
# When a second stream opens with the same clientID it kills the first one.
#
# Fix: maintain a pool of N independent sessions, each with its own
# randomly-generated clientID.  Stream requests round-robin through the pool
# so every concurrent stream appears as a different device to Pluto.
#
# Set STREAM_POOL_SIZE to however many simultaneous streams you need.
# Each slot uses its own HTTP session + auth token so they are truly isolated.
# ---------------------------------------------------------------------------

STREAM_POOL_SIZE = 10   # adjust to taste


class StreamSession:
    """One 'virtual device' – its own clientID, requests.Session and token cache."""

    def __init__(self, username=None, password=None):
        self.session = requests.Session()
        self.client_id = str(uuid.uuid4())          # unique per virtual device
        self.response_list = {}
        self.sessionAt = {}
        self.username = username
        self.password = password

    def boot(self, country_code, x_forward):
        """Authenticate / refresh token for this virtual device."""
        desired_timezone = pytz.timezone('UTC')
        current_date = datetime.now(desired_timezone)

        # Return cached token if still fresh (< 4 h old)
        if (self.response_list.get(country_code) is not None and
                (current_date - self.sessionAt.get(country_code, datetime.min.replace(tzinfo=pytz.utc))) < timedelta(hours=4)):
            return self.response_list[country_code], None

        boot_headers = {
            'authority': 'boot.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
            'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }

        boot_params = {
            'appName': 'web',
            'appVersion': '8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
            'deviceVersion': '122.0.0',
            'deviceModel': 'web',
            'deviceMake': 'chrome',
            'deviceType': 'web',
            'clientID': self.client_id,              # <-- unique per slot!
            'clientModelNumber': '1.0.0',
            'serverSideAds': 'false',
            'drmCapabilities': 'widevine:L3',
            'blockingMode': '',
            'notificationVersion': '1',
            'appLaunchCount': '',
            'lastAppLaunchDate': '',
        }

        if self.username and self.password:
            boot_params['username'] = self.username
            boot_params['password'] = self.password

        if country_code in x_forward:
            boot_headers.update(x_forward[country_code])

        try:
            response = self.session.get(
                'https://boot.pluto.tv/v4/start',
                headers=boot_headers,
                params=boot_params,
            )
        except Exception as e:
            return None, f"Error Exception type: {type(e).__name__}"

        if 200 <= response.status_code <= 201:
            resp = response.json()
        else:
            return None, f"HTTP failure {response.status_code}: {response.text}"

        self.response_list[country_code] = resp
        self.sessionAt[country_code] = current_date
        print(f"[slot {self.client_id[:8]}] New token for {country_code} at "
              f"{current_date.strftime('%Y-%m-%d %H:%M.%S %z')}")
        return resp, None


class Client:
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password

        # ---- stream session pool ----
        self._pool = [
            StreamSession(username=username, password=password)
            for _ in range(STREAM_POOL_SIZE)
        ]
        self._pool_index = 0
        self._pool_lock = threading.Lock()

        # ---- legacy single session (used for EPG / channel metadata only) ----
        self.session = requests.Session()
        self.sessionAt = {}
        self.response_list = {}
        self.epg_data = {}
        self.device = None
        self.all_channels = {}

        self.load_device()
        self.x_forward = {
            "local":    {"X-Forwarded-For": ""},
            "uk":       {"X-Forwarded-For": "178.238.11.6"},
            "ca":       {"X-Forwarded-For": "192.206.151.131"},
            "fr":       {"X-Forwarded-For": "193.169.64.141"},
            "de":       {"X-Forwarded-For": "81.173.176.155"},
            "us_east":  {"X-Forwarded-For": "108.82.206.181"},
            "us_west":  {"X-Forwarded-For": "76.81.9.69"},
        }

    # ------------------------------------------------------------------
    # Pool helpers
    # ------------------------------------------------------------------

    def _next_slot(self) -> StreamSession:
        """Round-robin through the session pool (thread-safe)."""
        with self._pool_lock:
            slot = self._pool[self._pool_index % STREAM_POOL_SIZE]
            self._pool_index += 1
        return slot

    def get_stream_token(self, country_code) -> tuple:
        """
        Return (session_token, slot_session) from the next pool slot.
        Use this when building stream/stitcher URLs so each concurrent
        stream uses a different clientID device identity.
        """
        slot = self._next_slot()
        resp, error = slot.boot(country_code, self.x_forward)
        if error:
            return None, None, error
        token = resp.get('sessionToken')
        return token, slot, None

    # ------------------------------------------------------------------
    # Existing API (unchanged behaviour, uses primary slot for metadata)
    # ------------------------------------------------------------------

    def load_device(self):
        if self.device is None:
            self.device = uuid.uuid1()
        return self.device

    def resp_data(self, country_code):
        """Primary boot session used for channel/EPG metadata (not streams)."""
        desired_timezone = pytz.timezone('UTC')
        current_date = datetime.now(desired_timezone)
        if (self.response_list.get(country_code) is not None and
                (current_date - self.sessionAt.get(country_code, datetime.now())) < timedelta(hours=4)):
            return self.response_list[country_code], None

        # Delegate to pool slot 0 for metadata (keeps original behaviour)
        resp, error = self._pool[0].boot(country_code, self.x_forward)
        if error:
            return None, error
        self.response_list[country_code] = resp
        self.sessionAt[country_code] = current_date
        return resp, None

    def channels(self, country_code):
        if country_code == 'all':
            return self.channels_all()

        resp, error = self.resp_data(country_code)
        if error:
            return None, error

        token = resp.get('sessionToken', None)
        if token is None:
            return None, error

        url = "https://service-channels.clusters.pluto.tv/v2/guide/channels"

        headers = {
            'authority': 'service-channels.clusters.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Bearer {token}',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
        }

        params = {
            'channelIds': '',
            'offset': '0',
            'limit': '1000',
            'sort': 'number:asc',
        }

        if country_code in self.x_forward:
            headers.update(self.x_forward[country_code])

        try:
            response = self.session.get(url, params=params, headers=headers)
        except Exception as e:
            return None, f"Error Exception type: {type(e).__name__}"

        if response.status_code != 200:
            return None, f"HTTP failure {response.status_code}: {response.text}"

        channel_list = response.json().get("data")

        category_url = "https://service-channels.clusters.pluto.tv/v2/guide/categories"

        try:
            response = self.session.get(category_url, params=params, headers=headers)
        except Exception as e:
            return None, f"Error Exception type: {type(e).__name__}"

        if response.status_code != 200:
            return None, f"HTTP failure {response.status_code}: {response.text}"

        categories_data = response.json().get("data")

        categories_list = {}
        for elem in categories_data:
            category = elem.get('name')
            channelIDs = elem.get('channelIDs')
            for channel in channelIDs:
                categories_list[channel] = category

        stations = []
        for elem in channel_list:
            entry = {
                'id':           elem.get('id'),
                'name':         elem.get('name'),
                'slug':         elem.get('slug'),
                'tmsid':        elem.get('tmsid'),
                'summary':      elem.get('summary'),
                'group':        categories_list.get(elem.get('id')),
                'country_code': country_code,
            }

            number = elem.get('number')
            existing_numbers = {ch["number"] for ch in stations}
            while number in existing_numbers:
                number += 1

            color_logo_png = next(
                (image["url"] for image in elem["images"] if image["type"] == "colorLogoPNG"),
                None,
            )
            entry.update({'number': number, 'logo': color_logo_png})
            stations.append(entry)

        sorted_data = sorted(stations, key=lambda x: x["number"])
        self.all_channels[country_code] = sorted_data
        return sorted_data, None

    def channels_all(self):
        all_channel_list = []
        for key, val in self.all_channels.items():
            all_channel_list.extend(val)

        seen = set()
        filter_key = 'id'
        filtered_list = [
            d for d in all_channel_list
            if d[filter_key] not in seen and not seen.add(d[filter_key])
        ]

        seen = set()
        for elem in filtered_list:
            number = elem.get('number')
            match elem.get('country_code', '').lower():
                case 'ca':
                    offset = 6000
                    if number < offset:
                        number += offset
                case 'uk':
                    offset = 7000
                    if number < offset:
                        number += offset
                case 'fr':
                    offset = 8000
                    if number < offset:
                        number += offset
                case 'de':
                    offset = 9000
                    if number < offset:
                        number += offset

            while number in seen:
                number += 1
            seen.add(number)
            if number != elem.get('number'):
                elem['number'] = number

        return filtered_list, None

    # ------------------------------------------------------------------
    # EPG
    # ------------------------------------------------------------------

    def strip_illegal_characters(self, xml_string):
        illegal_char_pattern = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
        return illegal_char_pattern.sub('', xml_string)

    def update_epg(self, country_code, range_count=3):
        resp, error = self.resp_data(country_code)
        if error:
            return None, error

        token = resp.get('sessionToken', None)
        if token is None:
            return None, error

        desired_timezone = pytz.timezone('UTC')
        start_datetime = datetime.now(desired_timezone)
        start_time = start_datetime.strftime("%Y-%m-%dT%H:00:00.000Z")
        end_time = start_time

        url = "https://service-channels.clusters.pluto.tv/v2/guide/timelines"

        epg_headers = {
            'authority': 'service-channels.clusters.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Bearer {token}',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
        }

        epg_params = {
            'start': start_time,
            'channelIds': '',
            'duration': '720',
        }

        if country_code in self.x_forward:
            epg_headers.update(self.x_forward[country_code])

        station_list, error = self.channels(country_code)
        if error:
            return None, error

        id_values = [d['id'] for d in station_list]
        group_size = 100
        grouped_id_values = [id_values[i:i + group_size] for i in range(0, len(id_values), group_size)]
        country_data = []

        for i in range(range_count):
            if end_time != start_time:
                start_time = end_time
                epg_params['start'] = start_time
            print(f'Retrieving {country_code} EPG data for {start_time}')

            for group in grouped_id_values:
                epg_params['channelIds'] = ','.join(map(str, group))
                try:
                    response = self.session.get(url, params=epg_params, headers=epg_headers)
                except Exception as e:
                    return None, f"Error Exception type: {type(e).__name__}"

                if response.status_code != 200:
                    return None, f"HTTP failure {response.status_code}: {response.text}"
                country_data.append(response.json())

            end_time = (
                datetime.strptime(response.json()["meta"]["endDateTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                .replace(tzinfo=pytz.utc)
                .strftime("%Y-%m-%dT%H:00:00.000Z")
            )

        self.epg_data[country_code] = country_data
        return None

    def epg_json(self, country_code):
        error_code = self.update_epg(country_code)
        if error_code:
            print("error")
            return None, error_code
        return self.epg_data, None

    def find_tuples_by_value(self, dictionary, target_value):
        result_list = []
        for key, values in dictionary.items():
            if target_value in values:
                result_list.extend(key)
        return result_list if result_list else [target_value]

    def read_epg_data(self, resp, root):
        seriesGenres = {
            ("Animated",): ["Family Animation", "Cartoons"],
            ("Educational",): ["Education & Guidance", "Instructional & Educational"],
            ("News",): ["News and Information", "General News", "News + Opinion", "General News"],
            ("History",): ["History & Social Studies"],
            ("Politics",): ["Politics"],
            ("Action",): [
                "Action & Adventure", "Action Classics", "Martial Arts", "Crime Action",
                "Family Adventures", "Action Sci-Fi & Fantasy", "Action Thrillers", "African-American Action",
            ],
            ("Adventure",): ["Action & Adventure", "Adventures", "Sci-Fi Adventure"],
            ("Reality",): ["Reality", "Reality Drama", "Courtroom Reality", "Occupational Reality", "Celebrity Reality"],
            ("Documentary",): [
                "Documentaries", "Social & Cultural Documentaries", "Science and Nature Documentaries",
                "Miscellaneous Documentaries", "Crime Documentaries", "Travel & Adventure Documentaries",
                "Sports Documentaries", "Military Documentaries", "Political Documentaries", "Foreign Documentaries",
                "Religion & Mythology Documentaries", "Historical Documentaries", "Biographical Documentaries",
                "Faith & Spirituality Documentaries",
            ],
            ("Biography",): ["Biographical Documentaries", "Inspirational Biographies"],
            ("Science Fiction",): ["Sci-Fi Thrillers", "Sci-Fi Adventure", "Action Sci-Fi & Fantasy"],
            ("Thriller",): ["Sci-Fi Thrillers", "Thrillers", "Crime Thrillers"],
            ("Talk",): ["Talk & Variety", "Talk Show"],
            ("Variety",): ["Sketch Comedies"],
            ("Home Improvement",): ["Art & Design", "DIY & How To", "Home Improvement"],
            ("House/garden",): ["Home & Garden"],
            ("Cooking",): ["Cooking Instruction", "Food & Wine", "Food Stories"],
            ("Travel",): ["Travel & Adventure Documentaries", "Travel"],
            ("Western",): ["Westerns", "Classic Westerns"],
            ("LGBTQ",): ["Gay & Lesbian", "Gay & Lesbian Dramas", "Gay"],
            ("Game show",): ["Game Show"],
            ("Military",): ["Classic War Stories"],
            ("Comedy",): [
                "Cult Comedies", "Spoofs and Satire", "Slapstick", "Classic Comedies", "Stand-Up",
                "Sports Comedies", "African-American Comedies", "Showbiz Comedies", "Sketch Comedies",
                "Teen Comedies", "Latino Comedies", "Family Comedies",
            ],
            ("Crime",): ["Crime Action", "Crime Drama", "Crime Documentaries"],
            ("Sports",): ["Sports", "Sports & Sports Highlights", "Sports Documentaries", "Poker & Gambling"],
            ("Poker & Gambling",): ["Poker & Gambling"],
            ("Crime drama",): ["Crime Drama"],
            ("Drama",): ["Classic Dramas", "Family Drama", "Indie Drama", "Romantic Drama", "Crime Drama"],
            ("Children",): ["Kids", "Children & Family", "Kids' TV", "Cartoons", "Animals", "Family Animation", "Ages 2-4", "Ages 11-12"],
        }

        for entry in resp["data"]:
            for timeline in entry["timelines"]:
                programme = ET.SubElement(root, "programme", attrib={
                    "channel": entry["channelId"],
                    "start": datetime.strptime(timeline["start"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=pytz.utc).strftime("%Y%m%d%H%M%S %z"),
                    "stop":  datetime.strptime(timeline["stop"],  "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=pytz.utc).strftime("%Y%m%d%H%M%S %z"),
                })
                title = ET.SubElement(programme, "title")
                title.text = self.strip_illegal_characters(timeline["title"])

                if timeline["episode"].get("series", {}).get("type", "") == "live":
                    if timeline["episode"]["clip"]["originalReleaseDate"] == timeline["start"]:
                        ET.SubElement(programme, "live")
                    if timeline["episode"].get("season", None):
                        ep = ET.SubElement(programme, "episode-num", attrib={"system": "onscreen"})
                        ep.text = f'S{timeline["episode"]["season"]:02d}E{timeline["episode"]["number"]:02d}'
                        ep2 = ET.SubElement(programme, "episode-num", attrib={"system": "pluto"})
                        ep2.text = timeline["episode"]["_id"]
                elif timeline["episode"].get("series", {}).get("type", "") == "tv":
                    ep = ET.SubElement(programme, "episode-num", attrib={"system": "onscreen"})
                    ep.text = f'S{timeline["episode"]["season"]:02d}E{timeline["episode"]["number"]:02d}'
                    ep2 = ET.SubElement(programme, "episode-num", attrib={"system": "pluto"})
                    ep2.text = timeline["episode"]["_id"]

                air = ET.SubElement(programme, "episode-num", attrib={"system": "original-air-date"})
                air.text = (datetime.strptime(timeline["episode"]["clip"]["originalReleaseDate"], "%Y-%m-%dT%H:%M:%S.%fZ")
                            .replace(tzinfo=pytz.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + 'Z')

                desc = ET.SubElement(programme, "desc")
                desc.text = self.strip_illegal_characters(timeline["episode"]["description"]).replace('&quot;', '"')

                ET.SubElement(programme, "icon", attrib={"src": timeline["episode"]["series"]["tile"]["path"]})

                date = ET.SubElement(programme, "date")
                date.text = datetime.strptime(timeline["episode"]["clip"]["originalReleaseDate"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y%m%d")

                sid = ET.SubElement(programme, "series-id", attrib={"system": "pluto"})
                sid.text = timeline["episode"]["series"]["_id"]

                if timeline["title"].lower() != timeline["episode"]["name"].lower():
                    sub = ET.SubElement(programme, "sub-title")
                    sub.text = self.strip_illegal_characters(timeline["episode"]["name"])

                categories = []
                if timeline["episode"].get("genre"):
                    categories.extend(self.find_tuples_by_value(seriesGenres, timeline["episode"]["genre"]))
                stype = timeline["episode"].get("series", {}).get("type", "")
                if stype == "tv":
                    categories.append("Series")
                if stype == "film":
                    categories.append("Movie")
                if timeline["episode"].get("subGenre"):
                    categories.extend(self.find_tuples_by_value(seriesGenres, timeline["episode"]["subGenre"]))

                unique_list = []
                for item in categories:
                    if item not in unique_list:
                        unique_list.append(item)
                for category in unique_list:
                    cat_elem = ET.SubElement(programme, "category")
                    cat_elem.text = category

        return root

    def get_all_epg_data(self, country_code):
        all_epg_data = []
        channelIds_seen = {}
        range_count = 3

        for country in country_code:
            error_code = self.update_epg(country, range_count)
            if error_code:
                return error_code

            for epg_list in self.epg_data.get(country):
                data_list = epg_list.get('data')
                for entry in data_list[:]:
                    channelId = entry.get('channelId')
                    if channelId in channelIds_seen:
                        if channelIds_seen[channelId] < range_count:
                            channelIds_seen[channelId] += 1
                        else:
                            data_list.remove(entry)
                    else:
                        channelIds_seen[channelId] = 1
                all_epg_data.append({'data': data_list})

        return all_epg_data

    def create_xml_file(self, country_code):
        if isinstance(country_code, str):
            error_code = self.update_epg(country_code)
            if error_code:
                return error_code
            station_list, error = self.channels(country_code)
            if error:
                return None, error
            xml_file_path = f"epg-{country_code}.xml"
        elif isinstance(country_code, list):
            xml_file_path = "epg-all.xml"
            station_list, error = self.channels_all()
        else:
            print("The variable is neither a string nor a list.")
            return None

        compressed_file_path = f"{xml_file_path}.gz"
        root = ET.Element("tv", attrib={"generator-info-name": "jgomez177", "generated-ts": ""})

        for station in station_list:
            channel = ET.SubElement(root, "channel", attrib={"id": station["id"]})
            display_name = ET.SubElement(channel, "display-name")
            display_name.text = self.strip_illegal_characters(station["name"])
            ET.SubElement(channel, "icon", attrib={"src": station["logo"]})

        if isinstance(country_code, str):
            program_data = self.epg_data.get(country_code, [])
        else:
            program_data = self.get_all_epg_data(country_code)

        for elem in program_data:
            root = self.read_epg_data(elem, root)

        tree = ET.ElementTree(root)
        ET.indent(tree, '  ')

        doctype = '<!DOCTYPE tv SYSTEM "xmltv.dtd">'
        xml_declaration = "<?xml version='1.0' encoding='utf-8'?>"
        output_content = xml_declaration + '\n' + doctype + '\n' + ET.tostring(root, encoding='utf-8').decode('utf-8')

        with open(xml_file_path, "w", encoding='utf-8') as f:
            f.write(output_content)

        with open(xml_file_path, 'rb') as file:
            with gzip.open(compressed_file_path, 'wb') as compressed_file:
                compressed_file.writelines(file)

        self.epg_data = {}
        return None
