#!/usr/bin/env bash
set -e

ACTION="$1"
TUN_DEV="${2:-tun0}"
SOCKS_PORT="${3:-10808}"
SERVER_IP="${4:-127.0.0.1}"
SERVER_IP_2="${5:-127.0.0.1}"

REAL_USER="${SUDO_USER:-${PKEXEC_UID:-wtdumean}}"
if [ "$REAL_USER" = "0" ] || [ -z "$REAL_USER" ]; then
    REAL_USER="wtdumean"
fi
if [[ "$REAL_USER" =~ ^[0-9]+$ ]]; then
    REAL_USER=$(id -nu "$REAL_USER" 2>/dev/null || echo "wtdumean")
fi

resolve_ip() {
    local target="$1"
    if [[ -z "$target" ]]; then
        return
    fi
    if [[ "$target" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "$target"
    else
        getent ahostsv4 "$target" 2>/dev/null | awk '{print $1}' | head -n1
    fi
}

DEF_GW=$(ip -4 route show default 2>/dev/null | grep -v "$TUN_DEV" | awk '/via/ {print $3}' | head -n1)
DEF_DEV=$(ip -4 route show default 2>/dev/null | grep -v "$TUN_DEV" | awk '/dev/ {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n1)

case "$ACTION" in
    up)
        ALL_SERVERS=("$SERVER_IP" "$SERVER_IP_2")
        for s_host in "${ALL_SERVERS[@]}"; do
            s_ip=$(resolve_ip "$s_host")
            if [ -n "$s_ip" ] && [ -n "$DEF_GW" ] && [ -n "$DEF_DEV" ]; then
                ip route replace "$s_ip/32" via "$DEF_GW" dev "$DEF_DEV" 2>/dev/null || true
            fi
        done

        sysctl -w net.ipv4.conf.all.rp_filter=0 2>/dev/null || true
        sysctl -w net.ipv4.conf.default.rp_filter=0 2>/dev/null || true

        if ! ip link show "$TUN_DEV" &>/dev/null; then
            ip tuntap add dev "$TUN_DEV" mode tun user "$REAL_USER" 2>/dev/null || ip tuntap add dev "$TUN_DEV" mode tun 2>/dev/null || true
        fi

        ip addr replace 198.18.0.1/15 dev "$TUN_DEV" 2>/dev/null || true
        ip link set dev "$TUN_DEV" up mtu 1500
        sysctl -w net.ipv4.conf."$TUN_DEV".rp_filter=0 2>/dev/null || true

        iptables -I INPUT 1 -i "$TUN_DEV" -j ACCEPT 2>/dev/null || true
        iptables -I OUTPUT 1 -o "$TUN_DEV" -j ACCEPT 2>/dev/null || true
        iptables -I FORWARD 1 -i "$TUN_DEV" -j ACCEPT 2>/dev/null || true
        iptables -I FORWARD 1 -o "$TUN_DEV" -j ACCEPT 2>/dev/null || true

        iptables -t mangle -I POSTROUTING 1 -o "$TUN_DEV" -j ACCEPT 2>/dev/null || true
        iptables -t mangle -I PREROUTING 1 -i "$TUN_DEV" -j ACCEPT 2>/dev/null || true

        iptables -t nat -I OUTPUT 1 -p udp --dport 53 ! -d 127.0.0.0/8 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null || true
        iptables -t nat -I OUTPUT 1 -p tcp --dport 53 ! -d 127.0.0.0/8 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null || true

        ip route replace 0.0.0.0/1 dev "$TUN_DEV" metric 0
        ip route replace 128.0.0.0/1 dev "$TUN_DEV" metric 0

        ip route replace 172.29.172.254/32 dev "$TUN_DEV" metric 0 2>/dev/null || true

        if command -v resolvectl &>/dev/null; then
            resolvectl dns "$TUN_DEV" 172.29.172.254 2>/dev/null || true
            resolvectl domain "$TUN_DEV" "~." 2>/dev/null || true
            resolvectl default-route "$TUN_DEV" yes 2>/dev/null || true
        fi

        sysctl -w net.ipv6.conf."$TUN_DEV".disable_ipv6=1 2>/dev/null || true
        while ip6tables -D OUTPUT ! -o lo -j REJECT --reject-with icmp6-port-unreachable 2>/dev/null; do :; done
        ip6tables -I OUTPUT 1 ! -o lo -j REJECT --reject-with icmp6-port-unreachable 2>/dev/null || true
        while ip6tables -D FORWARD ! -o lo -j DROP 2>/dev/null; do :; done
        ip6tables -I FORWARD 1 ! -o lo -j DROP 2>/dev/null || true
        while ip -6 rule del unreachable pref 100 2>/dev/null; do :; done
        ip -6 rule add unreachable pref 100 2>/dev/null || true

        echo "TUN_UP_SUCCESS"
        ;;

    down)
        while ip -6 rule del unreachable pref 100 2>/dev/null; do :; done
        while ip6tables -D OUTPUT ! -o lo -j REJECT --reject-with icmp6-port-unreachable 2>/dev/null; do :; done
        while ip6tables -D FORWARD ! -o lo -j DROP 2>/dev/null; do :; done

        while iptables -t mangle -D POSTROUTING -o "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done
        while iptables -t mangle -D PREROUTING -i "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done
        while iptables -t mangle -D OUTPUT -o "$TUN_DEV" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360 2>/dev/null; do :; done
        while iptables -t mangle -D FORWARD -o "$TUN_DEV" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360 2>/dev/null; do :; done
        while iptables -t nat -D OUTPUT -p udp --dport 53 ! -d 127.0.0.0/8 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null; do :; done
        while iptables -t nat -D OUTPUT -p tcp --dport 53 ! -d 127.0.0.0/8 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null; do :; done
        while iptables -t nat -D OUTPUT -p udp --dport 53 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null; do :; done
        while iptables -t nat -D OUTPUT -p tcp --dport 53 ! -d 172.29.172.254 -j DNAT --to-destination 172.29.172.254:53 2>/dev/null; do :; done
        while iptables -D INPUT -i "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done
        while iptables -D OUTPUT -o "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done
        while iptables -D FORWARD -i "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done
        while iptables -D FORWARD -o "$TUN_DEV" -j ACCEPT 2>/dev/null; do :; done

        if command -v resolvectl &>/dev/null; then
            resolvectl default-route "$TUN_DEV" no 2>/dev/null || true
            resolvectl revert "$TUN_DEV" 2>/dev/null || true
        fi

        ip route del 0.0.0.0/1 dev "$TUN_DEV" 2>/dev/null || true
        ip route del 128.0.0.0/1 dev "$TUN_DEV" 2>/dev/null || true
        ip route del 172.29.172.254/32 dev "$TUN_DEV" 2>/dev/null || true

        if ! ip link show amn0 &>/dev/null; then
            ALL_SERVERS=("$SERVER_IP" "$SERVER_IP_2")
            for s_host in "${ALL_SERVERS[@]}"; do
                s_ip=$(resolve_ip "$s_host")
                if [ -n "$s_ip" ] && [ -n "$DEF_GW" ] && [ -n "$DEF_DEV" ]; then
                    ip route del "$s_ip/32" via "$DEF_GW" dev "$DEF_DEV" 2>/dev/null || true
                fi
            done
        fi

        ip link set dev "$TUN_DEV" down 2>/dev/null || true
        ip tuntap del dev "$TUN_DEV" mode tun 2>/dev/null || true

        sysctl -w net.ipv4.conf.all.rp_filter=2 2>/dev/null || true
        sysctl -w net.ipv4.conf.default.rp_filter=2 2>/dev/null || true

        echo "TUN_DOWN_SUCCESS"
        ;;

    status)
        if ip link show "$TUN_DEV" &>/dev/null; then
            echo "TUN_ACTIVE"
        else
            echo "TUN_INACTIVE"
        fi
        ;;

    *)
        echo "Usage: $0 {up|down|status} [tun_dev] [socks_port] [server_ip1] [server_ip2]"
        exit 1
        ;;
esac
