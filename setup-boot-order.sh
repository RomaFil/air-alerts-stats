#!/bin/bash
# Гарантує, що docker стартує ПІСЛЯ підняття WireGuard-тунелю.
#
# Навіщо: усі три стеки (Aurum, Music Cloud, Air Alerts) публікують порти на
# адресі інтерфейсу wg0 (типово 10.0.0.1). Якщо docker стартує раніше за тунель,
# адреси ще не існує і публікація падає з
#   bind: cannot assign requested address
# Штатно docker і wg-quick обидва впорядковані лише After=network-online.target,
# а між собою порядку не мають — тобто це гонка, яка вирішується випадково.
#
# ЗАПУСКАТИ З sudo. Зачіпає ВСІ docker-стеки на хості, не лише Air Alerts.
#   sudo ~/air-alerts/setup-boot-order.sh            # тільки встановити й перевірити
#   sudo ~/air-alerts/setup-boot-order.sh --reboot   # встановити, перевірити й перезавантажити
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Потрібен sudo: sudo $0 $*"; exit 1; }

DIR=/etc/systemd/system/docker.service.d
CONF="$DIR/10-wireguard-order.conf"

echo "== було =="
echo -n "docker.service After містить wg: "
systemctl show docker.service -p After | tr ' ' '\n' | grep -c wg-quick || true

mkdir -p "$DIR"
cat > "$CONF" <<'CONF'
[Unit]
# Порти сервісів прив'язані до адреси тунельного інтерфейсу wg0.
# Без цього порядку docker може стартувати раніше за тунель і не зможе
# зайняти адресу: bind: cannot assign requested address.
# Wants, а не Requires: якщо тунель раптом не підніметься, docker усе одно
# має стартувати — краще контейнери без публікації, ніж жодних контейнерів.
After=wg-quick@wg0.service
Wants=wg-quick@wg0.service
CONF
chmod 644 "$CONF"
echo "створено $CONF"

systemctl daemon-reload

echo
echo "== перевірка конфігурації =="
if ! systemd-analyze verify docker.service 2>&1 | grep -v '^$' | tee /tmp/verify.out | grep -q .; then
    echo "  systemd-analyze verify: зауважень немає"
else
    echo "  systemd-analyze verify:"; sed 's/^/    /' /tmp/verify.out
fi

echo -n "  docker.service тепер After=wg-quick@wg0: "
if systemctl show docker.service -p After | tr ' ' '\n' | grep -q 'wg-quick@wg0'; then
    echo "ТАК"
else
    echo "НІ — щось пішло не так, перезавантаження скасовано"
    exit 1
fi

if [ "${1:-}" != "--reboot" ]; then
    echo
    echo "Готово. Перезавантаження НЕ виконано (запусти з --reboot, якщо потрібно)."
    exit 0
fi

echo
echo "== перезавантаження через 5 с, Ctrl+C щоб скасувати =="
sleep 5
systemctl reboot
