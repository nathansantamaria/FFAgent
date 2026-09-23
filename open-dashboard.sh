#!/usr/bin/env bash
# Same as open-dashboard.bat, for mac/linux.
cd "$(dirname "$0")"
( sleep 1; open "http://localhost:8765/dashboard.html" 2>/dev/null || \
  xdg-open "http://localhost:8765/dashboard.html" 2>/dev/null ) &
echo "Dashboard: http://localhost:8765/dashboard.html   (ctrl-C to stop)"
python3 -m http.server 8765
