#!/bin/bash
set -e
CK=/tmp/ck_loop.txt
rm -f "$CK"
BASE=http://localhost:8080
curl -s -c "$CK" -X POST "$BASE/login" --data-urlencode "username=admin" --data-urlencode "password=admin123" -o /dev/null -w "login: %{http_code}\n"
curl -s -b "$CK" "$BASE/settings" -o /tmp/out_settings.html -w "settings: %{http_code}\n"
echo "-- remaining 'loop' occurrences in rendered settings page --"
grep -c "loop" /tmp/out_settings.html || true
echo "-- DB rows still containing 'Maintenance (loop)' --"
docker compose -f /mnt/d/otopia/app-wa/booking-management-whatsapp/docker-compose.yml exec -T db psql -U booking -d booking -c "SELECT name, after_service FROM service_type;"
rm -f /tmp/out_settings.html "$CK"
