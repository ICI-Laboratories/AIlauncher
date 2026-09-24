"""Wait until production chat / preceding OCR is loaded before allocating VRAM."""
import json
import sys
import time
import urllib.error
import urllib.request

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline=time.monotonic()+240
while time.monotonic()<deadline:
    try:
        with opener.open(sys.argv[1],timeout=3) as response:
            if json.load(response).get('status')=='ok':
                raise SystemExit(0)
    except (OSError, ValueError, urllib.error.URLError):
        pass
    time.sleep(2)
raise SystemExit('Preceding inference service is not ready; refusing auxiliary startup')
