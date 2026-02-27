# Pluto for Channels

**Version 1.23**

# Changes

 - Version 1.23:
    - **Multi-stream fix:** Replaced single hardcoded `clientID` with a rotating pool of virtual device sessions. Each concurrent stream now uses a unique `clientID`, bypassing Pluto TV's single-stream-per-device limitation. Pool size defaults to 10 simultaneous streams and is configurable via `STREAM_POOL_SIZE` in `pluto.py`.
 - Version 1.22:
    - Added styling to Playlist page and a copy link.
 - Version 1.21b:
    - Added Pluto Germany.
 - Version 1.21:
    - Added support for PLUTO_USERNAME and PLUTO_PASSWORD environment variables.

# Credits

- **[jgomez177](https://github.com/jgomez177/pluto-for-channels)** — Original project. Built the Pluto TV M3U/EPG integration for Channels DVR.
- **[nuken](https://github.com/nuken/pluto-for-channels)** — Added authentication support (PLUTO_USERNAME / PLUTO_PASSWORD) after Pluto TV introduced mandatory account login.
- **[kineticman](https://github.com/kineticman/pluto-for-channels)** — Multi-stream fix. Introduced the rotating `clientID` session pool allowing multiple simultaneous streams without one killing another.

# Running
Use single quotes around the username and password to avoid conflicts.
```
docker run -d --restart unless-stopped --network=host -e PLUTO_PORT=[your_port_number_here] -e PLUTO_USERNAME='your_username' -e PLUTO_PASSWORD='your_password' --name pluto-for-channels kineticman/pluto-for-channels:main
```

or

```
docker run -d --restart unless-stopped -p [your_port_number_here]:7777 -e PLUTO_USERNAME='your_username' -e PLUTO_PASSWORD='your_password' --name pluto-for-channels kineticman/pluto-for-channels:main
```

You can retrieve the playlist and EPG via the status page.

[http://127.0.0.1](http://127.0.0.1):[your_port_number_here]

### **docker-compose.yml**

```yaml
version: '3.8'

services:
  pluto-for-channels:
    image: kineticman/pluto-for-channels:main
    container_name: pluto-for-channels
    restart: unless-stopped
    ports:
      # Map your desired host port to the container's port 7777
      - "7777:7777"
    environment:
      # Your Pluto TV username. Use single quotes if it contains special characters.
      PLUTO_USERNAME: YOUR_USERNAME
      # Your Pluto TV password. Use single quotes if it contains special characters.
      PLUTO_PASSWORD: YOUR_PASSWORD
      # Optional: Customize the country codes.
      # Default: 'local,us_east,us_west,ca,uk,fr,de'
      PLUTO_CODE: local,us_east,us_west,ca,uk,fr,de
```
Run `docker compose up -d` in terminal.

### **How to Use in Portainer**

1.  In Portainer, navigate to **Stacks**.
2.  Click **Add stack**.
3.  Give it a name (e.g., `pluto`).
4.  Choose the **Web editor** option.
5.  Paste the `docker-compose.yml` content from above into the editor.
6.  **Important:** Edit the environment variables for `PLUTO_USERNAME` and `PLUTO_PASSWORD` with your credentials. You can also change the host port if `7777` is already in use on your system.
7.  Click **Deploy the stack**.

Portainer will now pull the image and create the container with all your specified settings.

## Environment Variables

| Environment Variable | Description | Default |
|---|---|---|
| PLUTO\_PORT | Port the API will be served on. You can set this if it conflicts with another service in your environment. | 7777 |
| PLUTO\_USERNAME | Your Pluto TV username. | |
| PLUTO\_PASSWORD | Your Pluto TV password. | |
| PLUTO\_PASSWORD | Your Pluto TV password. | |
| PLUTO\_CODE | What country streams will be hosted. <br>Multiple can be hosted using comma separation<p><p>ALLOWED\_COUNTRY\_CODES:<br>**us\_east** - United States East Coast,<br>**us\_west** - United States West Coast,<br>**local** - Local IP address Geolocation,<br>**ca** - Canada,<br>**uk** - United Kingdom,<br>**fr** - France,<br>**de** - Germany | local,us\_west,us\_east,ca,uk |

## Additional URL Parameters

| Parameter | Description |
|---|---|
| channel\_id\_format | default channel-id is set as "pluto-{slug}".<br>**"id"** will change channel-id to "pluto-{id}".<br>**"slug\_only"** will change channel-id to "{slug}". |

## Multi-Stream Configuration

By default, 10 simultaneous streams are supported. To change this, edit `STREAM_POOL_SIZE` at the top of `pluto.py`:

```python
STREAM_POOL_SIZE = 10   # increase for more concurrent streams
```

Each pool slot authenticates independently as a separate virtual device. Tokens are cached and refreshed every 4 hours, so the overhead of a larger pool is minimal.
