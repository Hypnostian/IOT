"""Publicador MQTT de la estacion ambiental del laboratorio 5.

Simula los sensores de la estacion que esta junto al panel solar (temperatura,
humedad e iluminancia) con un ciclo diario segun la hora de Colombia, y publica
una lectura cada INTERVALO_S segundos en lab5/<dispositivo>/telemetria con QoS 1.

Tambien escucha lab5/<dispositivo>/control: una orden ahi fuerza el valor de una
variable durante unos minutos. Asi se dispara la alerta de umbral desde el propio
publicador (ver forzar.py).
"""

import json
import math
import os
import random
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_HOST", "mosquitto")
PUERTO = int(os.getenv("MQTT_PUERTO", "1883"))
USUARIO = os.environ["MQTT_USUARIO"]
CLAVE = os.environ["MQTT_CLAVE"]
DISPOSITIVO = os.getenv("DISPOSITIVO_ID", "estacion-01")
INTERVALO = float(os.getenv("INTERVALO_S", "10"))

TOPICO_DATOS = f"lab5/{DISPOSITIVO}/telemetria"
TOPICO_CONTROL = f"lab5/{DISPOSITIVO}/control"
HORA_COLOMBIA = timezone(timedelta(hours=-5))
VARIABLES = ("temperature", "humidity", "illuminance")


class Estacion:
    """Lecturas con ciclo diario: sol de 6:00 a 18:00 y temperatura maxima hacia las 15:00."""

    def __init__(self):
        self.paso_de_luz = 0.85  # fraccion de luz que dejan pasar las nubes; cambia despacio
        self.forzados = {}  # variable -> (valor, vence_en)
        self.candado = threading.Lock()

    def forzar(self, variable, valor, duracion_s):
        with self.candado:
            self.forzados[variable] = (valor, time.time() + duracion_s)

    def lectura(self, ahora):
        local = ahora.astimezone(HORA_COLOMBIA)
        hora = local.hour + local.minute / 60 + local.second / 3600
        sol = math.sin(math.pi * (hora - 6) / 12) if 6 <= hora <= 18 else 0.0
        self.paso_de_luz = min(1.0, max(0.35, self.paso_de_luz + random.gauss(0, 0.02)))

        temperatura = (23.5 + 5.5 * math.sin(2 * math.pi * (hora - 9) / 24)
                       + 1.2 * sol * self.paso_de_luz + random.gauss(0, 0.15))
        humedad = min(99.0, max(30.0, 93 - 2.4 * (temperatura - 18) + random.gauss(0, 0.6)))
        iluminancia = 95000 * sol * self.paso_de_luz + random.uniform(0, 3)

        valores = {
            "temperature": round(temperatura, 2),
            "humidity": round(humedad, 1),
            "illuminance": round(iluminancia, 1),
        }
        forzadas = []
        with self.candado:
            for variable, (valor, vence) in list(self.forzados.items()):
                if time.time() < vence:
                    valores[variable] = valor
                    forzadas.append(variable)
                else:
                    del self.forzados[variable]
                    print(f"fin del forzado de {variable}", flush=True)
        return valores, forzadas


def main():
    estacion = Estacion()
    detener = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: detener.set())
    signal.signal(signal.SIGINT, lambda *_: detener.set())

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pub-{DISPOSITIVO}")
    cliente.username_pw_set(USUARIO, CLAVE)
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    conectado = threading.Event()

    def al_conectar(c, _datos, _banderas, codigo, _props):
        print(f"conectado a {BROKER}:{PUERTO} ({codigo}); publicando en {TOPICO_DATOS} cada {INTERVALO:g} s",
              flush=True)
        c.subscribe(TOPICO_CONTROL, qos=1)
        conectado.set()

    def al_desconectar(_c, _datos, _banderas, codigo, _props):
        print(f"desconectado del broker ({codigo}); paho reintenta solo", flush=True)

    def al_mensaje(_c, _datos, msg):
        try:
            orden = json.loads(msg.payload)
            variable = orden["variable"]
            if variable not in VARIABLES:
                raise ValueError(f"variable desconocida {variable!r}")
            valor = float(orden["valor"])
            duracion = float(orden.get("duracion_s", 300))
        except (ValueError, KeyError, TypeError) as error:
            print(f"orden de control invalida {msg.payload!r}: {error}", flush=True)
            return
        estacion.forzar(variable, valor, duracion)
        print(f"FORZADO {variable}={valor:g} durante {duracion:.0f} s", flush=True)

    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar
    cliente.on_message = al_mensaje
    cliente.connect_async(BROKER, PUERTO, keepalive=60)
    cliente.loop_start()
    # La primera lectura sale cuando el broker ya acepto la conexion; antes se perderia.
    while not conectado.wait(5) and not detener.is_set():
        print("esperando al broker MQTT...", flush=True)

    secuencia = 0
    siguiente = time.monotonic()
    while not detener.is_set():
        ahora = datetime.now(timezone.utc)
        valores, forzadas = estacion.lectura(ahora)
        secuencia += 1
        mensaje = {
            "dispositivo": DISPOSITIVO,
            "seq": secuencia,
            "ts": ahora.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            **valores,
            "forzado": forzadas,
        }
        # Con QoS 1 paho guarda el mensaje aunque el broker no este, y lo envia al reconectar.
        cliente.publish(TOPICO_DATOS, json.dumps(mensaje, separators=(",", ":")), qos=1)
        if secuencia % 30 == 1 or forzadas:
            print(f"seq={secuencia} {valores}" + (f" forzado={forzadas}" if forzadas else ""), flush=True)

        siguiente += INTERVALO
        detener.wait(max(0.0, siguiente - time.monotonic()))

    cliente.loop_stop()
    cliente.disconnect()
    print("publicador detenido", flush=True)


if __name__ == "__main__":
    main()
