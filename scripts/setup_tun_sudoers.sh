#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER_PATH="$SCRIPT_DIR/bin/tun_helper.sh"
CURRENT_USER="$(id -un)"

echo "=== Настройка беспарольного запуска TUN режима StealthProxy ==="
echo "Пользователь: $CURRENT_USER"
echo "Скрипт helper: $HELPER_PATH"

chmod +x "$HELPER_PATH"

# Install symlink to eliminate space issues in sudoers
ln -sf "$HELPER_PATH" /usr/local/bin/stealthproxy_tun_helper 2>/dev/null || sudo ln -sf "$HELPER_PATH" /usr/local/bin/stealthproxy_tun_helper 2>/dev/null || true

RULE_USER="$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/local/bin/stealthproxy_tun_helper, $HELPER_PATH"
TMP_FILE="/tmp/stealthproxy_tun_sudoers"

cat <<EOF > "$TMP_FILE"
$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/local/bin/stealthproxy_tun_helper
$CURRENT_USER ALL=(ALL) NOPASSWD: ${HELPER_PATH// /\\ }
EOF
chmod 0440 "$TMP_FILE"

if command -v pkexec &>/dev/null; then
    pkexec bash -c "cp '$TMP_FILE' /etc/sudoers.d/zz_stealthproxy_tun && chmod 0440 /etc/sudoers.d/zz_stealthproxy_tun && chmod 0440 /etc/sudoers.d/* 2>/dev/null || true"
else
    sudo cp "$TMP_FILE" /etc/sudoers.d/zz_stealthproxy_tun
    sudo chmod 0440 /etc/sudoers.d/zz_stealthproxy_tun
fi

rm -f "$TMP_FILE"
echo "✅ Готово! Теперь TUN-режим будет включаться мгновенно без запроса пароля root."
