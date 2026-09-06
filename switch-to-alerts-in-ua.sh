#!/usr/bin/env bash
# Перемикає джерело даних на alerts.in.ua.
#
# Токен вводиться з клавіатури і нікуди, крім .env, не потрапляє:
# ні в історію команд, ні в аргументи процесів, ні в логи docker.
#
# Спершу токен перевіряється одноразовим контейнером. Якщо він неробочий
# або історія недоступна — нічого не міняється, збирач далі працює на siren.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "немає .env — спершу cp .env.example .env"; exit 1; }

read -rsp 'ALERTS_TOKEN (введення приховане): ' TOKEN
echo
[ -n "$TOKEN" ] || { echo "порожній токен, вихід"; exit 1; }

echo
echo "→ перевіряю токен, нічого не перемикаючи…"
if ! ALERTS_TOKEN="$TOKEN" docker compose run --rm --no-deps -T \
        -e ALERTS_TOKEN web python -m app.checktoken; then
    echo
    echo "✗ токен не пройшов перевірку. Нічого не змінено:"
    echo "  збирач далі працює на siren, історія накопичується."
    exit 1
fi

echo
echo "→ записую токен у .env…"
umask 077
grep -v -e '^ALERTS_TOKEN=' -e '^ALERTS_PROVIDER=' .env > .env.new
{
    echo "ALERTS_PROVIDER=alerts_in_ua"
    printf 'ALERTS_TOKEN=%s\n' "$TOKEN"
} >> .env.new
mv .env.new .env
chmod 600 .env

echo "→ перезапускаю збирач…"
docker compose up -d

echo
echo "Готово. Далі піде backfill: 27 областей × 35 с ≈ 16 хв."
echo "Спостерігати:  docker compose logs -f poller"
