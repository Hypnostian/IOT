"""Ingesta MQTT -> InfluxDB del laboratorio 5.

Se suscribe a lab5/+/telemetria con QoS 1 y sesion persistente, y escribe cada
lectura en InfluxDB con la marca de tiempo que puso el publicador al medir.

El ACK MQTT se envia solo cuando InfluxDB confirma la escritura. Si InfluxDB se
cae, el broker conserva los mensajes sin confirmar y los reenvia al reconectar,
de modo que la toma no pierde puntos (entrega al menos una vez; un duplicado cae
sobre el mismo punto porque tiene la misma marca de tiempo y las mismas etiquetas).
"""

import json
import os
import queue
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

BROKER = os.getenv("MQTT_HOST", "mosquitto")
PUERTO = int(os.getenv("MQTT_PUERTO", "1883"))
TOPICO = "lab5/+/telemetria"
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
BUCKET = os.environ["INFLUX_BUCKET"]
MEDICION = "ambiente"


def punto_desde(mensaje, recibido):
    datos = json.loads(mensaje.payload)
    medido = datetime.fromisoformat(datos["ts"].replace("Z", "+00:00"))
    return (
        Point(MEDICION)
        .tag("dispositivo", str(datos["dispositivo"]))
        .tag("protocolo", "mqtt")
        .field("temperature", float(datos["temperature"]))
        .field("humidity", float(datos["humidity"]))
        .field("illuminance", float(datos["illuminance"]))
        .field("seq", int(datos["seq"]))
        .field("forzado", 1 if datos.get("forzado") else 0)
        .field("retardo_ms", round((recibido - medido).total_seconds() * 1000, 1))
        .time(medido, WritePrecision.MS)
    )


def escritor(cola, cliente_mqtt, escritura):
    escritos = 0
    while True:
        mensaje, recibido = cola.get()
        try:
            punto = punto_desde(mensaje, recibido)
        except (ValueError, KeyError, TypeError) as error:
            print(f"mensaje descartado en {mensaje.topic}: {error}", flush=True)
            cliente_mqtt.ack(mensaje.mid, mensaje.qos)
            continue

        espera = 1
        while True:
            try:
                escritura.write(bucket=BUCKET, record=punto)
                break
            except Exception as error:  # InfluxDB caido o reiniciando
                print(f"InfluxDB no responde ({error.__class__.__name__}); reintento en {espera} s", flush=True)
                time.sleep(espera)
                espera = min(espera * 2, 30)

        cliente_mqtt.ack(mensaje.mid, mensaje.qos)
        escritos += 1
        if escritos % 60 == 1:
            print(f"{escritos} lecturas escritas en InfluxDB; ultima {punto.to_line_protocol()}", flush=True)


def main():
    influx = InfluxDBClient(url=INFLUX_URL, token=os.environ["INFLUX_TOKEN"], org=os.environ["INFLUX_ORG"])
    escritura = influx.write_api(write_options=SYNCHRONOUS)
    cola = queue.Queue()

    cliente = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="ingesta-lab5",
        clean_session=False,  # sesion persistente: el broker guarda lo que llegue mientras no estemos
        manual_ack=True,
    )
    cliente.username_pw_set(os.environ["MQTT_USUARIO"], os.environ["MQTT_CLAVE"])
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    def al_conectar(c, _datos, banderas, codigo, _props):
        print(f"conectado a {BROKER}:{PUERTO} ({codigo}, sesion previa={banderas.session_present}); "
              f"suscrito a {TOPICO}", flush=True)
        c.subscribe(TOPICO, qos=1)

    def al_desconectar(_c, _datos, _banderas, codigo, _props):
        print(f"desconectado del broker ({codigo}); paho reintenta solo", flush=True)

    def al_mensaje(_c, _datos, mensaje):
        cola.put((mensaje, datetime.now(timezone.utc)))

    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar
    cliente.on_message = al_mensaje

    threading.Thread(target=escritor, args=(cola, cliente, escritura), daemon=True).start()
    cliente.connect_async(BROKER, PUERTO, keepalive=60)
    cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
