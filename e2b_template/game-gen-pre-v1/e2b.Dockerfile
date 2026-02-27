# GameGen Lite - High Performance (Parallel Downloads)
FROM ubuntu:22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV NODE_ENV=development
ENV NPM_CONFIG_LOGLEVEL=warn

# 1. Install Basics + aria2 + Node.js 20.x LTS (Full Node.js for hot-reload + future npm packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 zip unzip python3 python3-pip supervisor \
    curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && npm install -g live-server \
    && rm -rf /var/lib/apt/lists/*

# 2. Setup Work Directory
RUN mkdir -p /home/user/game/assets/2d \
             /home/user/game/assets/3d \
             /var/log/supervisor
WORKDIR /home/user/game

# 3. Python Deps
RUN pip3 install --no-cache-dir fastapi uvicorn

# 4. PARALLEL ASSET DOWNLOADER
# We create a text file with all URLs and feed it to aria2c.
# aria2c will download ALL of them simultaneously using 16 connections.

RUN echo 'https://kenney.nl/media/pages/assets/tiny-town/5e46f9e551-1735736916/kenney_tiny-town.zip\n\
https://kenney.nl/media/pages/assets/board-game-icons/1a6c93ddc0-1721645690/kenney_board-game-icons.zip\n\
https://kenney.nl/media/pages/assets/pixel-platformer/bef991136c-1696667883/kenney_pixel-platformer.zip\n\
https://kenney.nl/media/pages/assets/tanks/cc79cf83fc-1677579063/kenney_tanks.zip\n\
https://kenney.nl/media/pages/assets/space-shooter-extension/9a8d3c431c-1677693518/kenney_space-shooter-extension.zip\n\
https://kenney.nl/media/pages/assets/blocky-characters/72bdc6be4c-1749547469/kenney_blocky-characters_20.zip\n\
https://kenney.nl/media/pages/assets/fantasy-town-kit/40ed2a2d51-1754222374/kenney_fantasy-town-kit_2.0.zip\n\
https://kenney.nl/media/pages/assets/car-kit/a9b1e99e92-1714554900/kenney_car-kit.zip\n\
https://kenney.nl/media/pages/assets/modular-buildings/b7b9013fa2-1707397411/kenney_modular-buildings.zip' > download_list.txt && \
    \
    # -j16: Download up to 16 files at once
    # -x16: Use 16 connections per file
    # -s16: Split file into 16 parts
    aria2c -i download_list.txt -j16 -x16 -s16 -d /tmp/downloads && \
    \
    # 5. EXTRACT & ORGANIZE (Fast Bash Script)
    # We use a simple loop to unzip and move.
    cd /tmp/downloads && \
    # 2D Packs
    unzip -q -o kenney_tiny-town.zip -d /home/user/game/assets/2d/tiny_town && \
    unzip -q -o kenney_board-game-icons.zip -d /home/user/game/assets/2d/board_icons && \
    unzip -q -o kenney_pixel-platformer.zip -d /home/user/game/assets/2d/pixel_platformer && \
    unzip -q -o kenney_tanks.zip -d /home/user/game/assets/2d/tanks && \
    unzip -q -o kenney_space-shooter-extension.zip -d /home/user/game/assets/2d/space_shooter && \
    # 3D Packs
    unzip -q -o kenney_blocky-characters_20.zip -d /home/user/game/assets/3d/blocky_chars && \
    unzip -q -o kenney_fantasy-town-kit_2.0.zip -d /home/user/game/assets/3d/fantasy_town && \
    unzip -q -o kenney_car-kit.zip -d /home/user/game/assets/3d/car_kit && \
    unzip -q -o kenney_modular-buildings.zip -d /home/user/game/assets/3d/modular_buildings && \
    # Cleanup
    rm -rf /tmp/downloads /home/user/game/download_list.txt

# 6. Create "Skeleton" & Guidelines
RUN cat > README_FOR_AGENT.md << 'EOF'
# AGENT INSTRUCTIONS

## Asset Directory Structure
All assets are located in `/home/user/game/assets/`.

### 2D Packs (`/assets/2d/`)
- **Pixel Platformer**: `/assets/2d/pixel_platformer/` (Great for side-scrollers)
- **Space Shooter**: `/assets/2d/space_shooter/` (Spaceships, lasers)
- **Tanks**: `/assets/2d/tanks/` (Top-down tank sprites)
- **Tiny Town**: `/assets/2d/tiny_town/` (Tilemaps for RPG towns)
- **Board Icons**: `/assets/2d/board_icons/` (UI elements)

### 3D Packs (`/assets/3d/`)
- **Blocky Characters**: `/assets/3d/blocky_chars/` (Humanoids, skins)
- **Fantasy Town**: `/assets/3d/fantasy_town/` (Medieval buildings)
- **Car Kit**: `/assets/3d/car_kit/` (Racing cars, tracks)
- **Modular Buildings**: `/assets/3d/modular_buildings/` (Modern city parts)

## Usage Tip
Most 2D packs have a `Tilemap` folder or `Sprites` folder inside.
Most 3D packs have `Models/GLTF format` inside.
EOF

# 7. Default Index
RUN echo '<!DOCTYPE html><html><body><h1>Sandbox Ready</h1><p>Assets loaded via Aria2 Parallel Downloader</p></body></html>' > index.html

# 8. Supervisor Config (with live-server for hot-reload and autorestart)
RUN cat > /etc/supervisor/conf.d/supervisord.conf << 'EOF'
[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid
childlogdir=/var/log/supervisor

[program:gameserver]
command=live-server --port=3000 --host=0.0.0.0 --no-browser --wait=500
directory=/home/user/game
environment=HOME="/home/user",NODE_ENV="development"
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/gameserver.err.log
stdout_logfile=/var/log/supervisor/gameserver.out.log
stopsignal=TERM
stopwaitsecs=10
stopasgroup=true
killasgroup=true

[program:control_api]
command=uvicorn server:app --host 0.0.0.0 --port 8000
directory=/home/user/game
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/control_api.err.log
stdout_logfile=/var/log/supervisor/control_api.out.log
stopsignal=TERM
stopwaitsecs=10
stopasgroup=true
killasgroup=true
EOF

# 9. Control Server
RUN echo 'from fastapi import FastAPI\nimport os\napp=FastAPI()\n@app.get("/status")\ndef status(): return {"status":"ready", "2d_packs": os.listdir("assets/2d"), "3d_packs": os.listdir("assets/3d")}' > server.py

EXPOSE 3000 8000
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
