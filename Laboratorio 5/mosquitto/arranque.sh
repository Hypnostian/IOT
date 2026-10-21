#!/bin/sh
# Crea el archivo de claves de Mosquitto con el usuario y la clave del .env y arranca el broker.
set -e
mkdir -p /mosquitto/auth
mosquitto_passwd -c -b /mosquitto/auth/passwd "$MQTT_USUARIO" "$MQTT_CLAVE"
chown -R mosquitto:mosquitto /mosquitto/auth /mosquitto/data
chmod 0700 /mosquitto/auth
chmod 0600 /mosquitto/auth/passwd
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
