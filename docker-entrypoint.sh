#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2024-2026 Hunter-Clipper
#
# Fixes issue #21: Docker creates named volumes root-owned, while the app runs
# as appuser (uid 999). The image's own chown only covers /data/downloads as it
# exists in the image layer, which the mounted volume then shadows — so the
# writability probe in app/main.py fails and downloads silently land in /tmp.
#
# When started as root (see `user: root` in docker-compose.yml) this script
# takes ownership of the download directory and then drops privileges to
# appuser before exec'ing the real command. When started as any other user it
# execs the command unchanged, so `docker run --user 999` still works.
set -e

APP_UID=999
APP_GID=999
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/data/downloads}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DOWNLOAD_DIR"
    chown -R "$APP_UID:$APP_GID" "$DOWNLOAD_DIR"
    # Drop privileges for the application itself. The kernel clears the
    # container's capabilities on the 0 -> non-zero uid transition, so the caps
    # added in docker-compose.yml (CHOWN/SETUID/SETGID) are only usable during
    # this init step and are gone by the time uvicorn runs.
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$@"
fi

exec "$@"
