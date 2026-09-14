#!/bin/sh
# Run as root only after confirming the two reserved subnets are unused.
set -eu
for spec in 'llm-apps 172.30.80.0/24 172.30.80.1 br-llm-apps' 'llm-backend 172.30.81.0/24 172.30.81.1 br-llm-backend'; do
    set -- $spec
    if ! docker network inspect "$1" >/dev/null 2>&1; then
        internal=''
        [ "$1" != llm-backend ] || internal=--internal
        docker network create $internal --subnet "$2" --gateway "$3" -o com.docker.network.bridge.name="$4" "$1"
    fi
done
install -d /usr/local/lib/ailauncher
cat > /usr/local/lib/ailauncher/relay-firewall <<'RULES'
#!/bin/sh
set -eu
iptables -N AILAUNCHER_RELAY 2>/dev/null || true
iptables -F AILAUNCHER_RELAY
iptables -A AILAUNCHER_RELAY -i br-llm-backend -j ACCEPT
iptables -A AILAUNCHER_RELAY -i lo -j ACCEPT
iptables -A AILAUNCHER_RELAY -j REJECT
iptables -C INPUT -d 172.30.81.1 -p tcp --dport 8080 -j AILAUNCHER_RELAY 2>/dev/null || iptables -I INPUT 1 -d 172.30.81.1 -p tcp --dport 8080 -j AILAUNCHER_RELAY
RULES
chmod 755 /usr/local/lib/ailauncher/relay-firewall
cat > /etc/systemd/system/ailauncher-relay.service <<'UNIT'
[Unit]
Description=Private Docker bridge relay to local llama-server
Requires=docker.service
After=docker.service network-online.target
[Service]
ExecStartPre=/usr/local/lib/ailauncher/relay-firewall
ExecStart=/usr/bin/socat TCP4-LISTEN:8080,bind=172.30.81.1,reuseaddr,fork TCP4:127.0.0.1:8080
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ailauncher-relay.service
