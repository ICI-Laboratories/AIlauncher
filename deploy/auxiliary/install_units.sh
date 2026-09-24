#!/bin/bash
set -euo pipefail
# Run as root after copying artifacts to /tmp. Does not start model services.
ss -ltn | awk '{print $4}' | grep -E ':(8020|8021)$' && { echo 'Auxiliary port already occupied'; exit 1; }
install -d -m 755 /usr/local/lib/ailauncher-auxiliary
install -m 644 /tmp/gpu_guard.py /usr/local/lib/ailauncher-auxiliary/gpu_guard.py
install -m 644 /tmp/wait_backend.py /usr/local/lib/ailauncher-auxiliary/wait_backend.py
install -m 755 /tmp/aux_network.sh /usr/local/lib/ailauncher-auxiliary/aux_network.sh
for unit in ailauncher-aux-network ailauncher-aux-guard ailauncher-ocr ailauncher-embeddings; do
    test ! -f "/etc/systemd/system/$unit.service"
done
for unit in ailauncher-aux-network ailauncher-aux-guard ailauncher-ocr ailauncher-embeddings; do
    install -m 644 "/tmp/$unit.service" "/etc/systemd/system/$unit.service"
done
systemd-analyze verify /etc/systemd/system/ailauncher-aux-network.service /etc/systemd/system/ailauncher-aux-guard.service /etc/systemd/system/ailauncher-ocr.service /etc/systemd/system/ailauncher-embeddings.service
systemctl daemon-reload
systemctl start ailauncher-aux-network.service ailauncher-aux-guard.service
