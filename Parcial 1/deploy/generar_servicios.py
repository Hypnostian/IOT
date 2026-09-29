#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera las unidades systemd de la flota que corre en la VM de Azure.

Cada nodo es un servicio independiente: si uno se cae, los demas siguen
publicando. Eso es justamente lo que permite mostrar en IoT Central que la
flota es asincrona y que una desconexion afecta a un solo dispositivo.

Uso:
    python deploy/generar_servicios.py
"""

import os

DIR = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(DIR, "systemd")
BASE = "/opt/granjazenon"

# clave -> (script, descripcion, argumentos extra)
SERVICIOS = [
    ("dev02", "dev02_lote2_dps_mqtt.py",
     "Lote de cultivo 2 (Python SDK, DPS + MQTT 8883, 15 s)", ""),
    ("dev04", "dev04_dosel_websocket.py",
     "Dosel y sombrio (Python SDK, MQTT sobre WebSocket 443, 60 s)", ""),
    ("dev05", "dev05_estacion_replay_csv.py",
     "Estacion de campo (replay de CSV historico, 60 s)",
     "--ventanas 01:00-02:30,13:00-13:40"),
    ("dev06", "dev06_meteo_atlas_weather.py",
     "Meteorologia del predio (Atlas Weather / Azure Maps, 300 s)", ""),
    ("dev07", "dev07_aire_openmeteo.py",
     "Calidad de aire rural (API publica Open-Meteo, 600 s)", ""),
    ("dev09", "dev09_riego_http_rest.py",
     "Reservorio y riego (puente HTTP/REST, 120 s)", ""),
    ("dev10", "dev10_perimetro_paho_mqtt.py",
     "Perimetro y bodega (MQTT crudo con paho-mqtt, 30 s)", ""),
]

PLANTILLA = """[Unit]
Description=Granja Zenon - {descripcion}
Documentation=file://{base}/README.md
After=network-online.target chrony.service
Wants=network-online.target

[Service]
Type=simple
User=zenon
Group=zenon
WorkingDirectory={base}
ExecStart={base}/.venv/bin/python {base}/{script}{args}
Restart=always
RestartSec=20
# La VM tiene menos de 1 GiB: se acota cada nodo para que un pico no
# se lleve por delante al resto de la flota.
MemoryMax=180M
StandardOutput=append:{base}/logs/{clave}.log
StandardError=append:{base}/logs/{clave}.log
SyslogIdentifier=gz-{clave}

[Install]
WantedBy=multi-user.target
"""


def main():
    os.makedirs(SALIDA, exist_ok=True)
    generados = []
    for clave, script, descripcion, args in SERVICIOS:
        contenido = PLANTILLA.format(
            base=BASE, script=script, descripcion=descripcion, clave=clave,
            args=(" " + args) if args else "")
        nombre = "granjazenon-{}.service".format(clave)
        with open(os.path.join(SALIDA, nombre), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(contenido)
        generados.append(nombre)
        print("{:34s} -> {}".format(nombre, script))
    print("-" * 70)
    print("{} unidades generadas en {}".format(len(generados), SALIDA))


if __name__ == "__main__":
    main()
