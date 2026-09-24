#!/bin/sh
set -eu
# A separate chain for the new private endpoints; preserve the existing relay.
iptables -N AILAUNCHER_AUX 2>/dev/null || true
iptables -F AILAUNCHER_AUX
iptables -A AILAUNCHER_AUX -i br-llm-backend -j ACCEPT
iptables -A AILAUNCHER_AUX -i lo -j ACCEPT
iptables -A AILAUNCHER_AUX -j REJECT
iptables -C INPUT -d 172.30.81.1 -p tcp -m multiport --dports 8020,8021 -j AILAUNCHER_AUX 2>/dev/null || iptables -I INPUT 1 -d 172.30.81.1 -p tcp -m multiport --dports 8020,8021 -j AILAUNCHER_AUX
