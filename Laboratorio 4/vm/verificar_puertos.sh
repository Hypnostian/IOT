#!/usr/bin/env bash
# Revisa desde la VM los puertos de IoT Hub usados en el laboratorio 4.
set -u
cd "$(dirname "$0")"
HUB=$(grep '^IOTC_HUB_HOSTNAME=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")

echo "Hub: $HUB"
getent hosts "$HUB"
echo
for puerto in 8883 5671 443; do
  nc -vz -w 10 "$HUB" "$puerto"
done
echo
echo "Saludo TLS en el puerto 5671 (AMQPS):"
openssl s_client -connect "$HUB:5671" -servername "$HUB" </dev/null 2>/dev/null \
  | grep -E "Protocol|Cipher is|Verify return code"
