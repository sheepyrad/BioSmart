#!/bin/sh
# Open the localhost host in a browser when a desktop session is present.
url=http://127.0.0.1:8000
i=0
while [ "$i" -lt 60 ]; do
    if command -v curl >/dev/null 2>&1 && curl -fsS -o /dev/null "$url"; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
fi
printf '%s\n' "$url"
