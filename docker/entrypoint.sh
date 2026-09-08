#!/bin/sh
set -eu

if [ "${HEADLESS:-true}" = "false" ]; then
    export DISPLAY="${DISPLAY:-:99}"
    XVFB_SCREEN="${XVFB_SCREEN:-1440x1000x24}"
    rm -f /app/browser/booking_browser_profile/SingletonCookie \
        /app/browser/booking_browser_profile/SingletonLock \
        /app/browser/booking_browser_profile/SingletonSocket
    echo "Starting Booking visible browser..."
    Xvfb "$DISPLAY" -screen 0 "$XVFB_SCREEN" -ac >/tmp/xvfb.log 2>&1 &
    fluxbox >/tmp/fluxbox.log 2>&1 &

    if [ -n "${VNC_PASSWORD:-}" ]; then
        x11vnc -storepasswd "$VNC_PASSWORD" /tmp/x11vnc.pass >/tmp/x11vnc-pass.log 2>&1
        x11vnc -display "$DISPLAY" -forever -shared -rfbauth /tmp/x11vnc.pass -listen 0.0.0.0 -xkb -bg >/tmp/x11vnc.log 2>&1
    else
        x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -xkb -bg >/tmp/x11vnc.log 2>&1
    fi

    websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
    attempts=0
    until curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 50 ]; then
            echo "noVNC failed to start:" >&2
            cat /tmp/novnc.log >&2 || true
            exit 1
        fi
    done
    echo "Browser UI: http://localhost:6080/vnc.html"
fi

if [ -n "${PGHOST:-}" ]; then
    until pg_isready -h "$PGHOST" -p "${PGPORT:-5432}" -U "${PGUSER:-postgres}" -d "${PGDATABASE:-postgres}" >/dev/null 2>&1; do
        sleep 2
    done
    echo "PostgreSQL: READY"
fi

exec "$@"
