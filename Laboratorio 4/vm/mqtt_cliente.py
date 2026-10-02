"""Cliente MQTT (paho) usado como linea base del Laboratorio 4, medido igual que AMQP y HTTPS.

Uso:
    python mqtt_cliente.py --count 10 --interval 5
"""

import argparse
import ssl
import threading
import time
import urllib.parse

import certifi
import paho.mqtt.client as mqtt

import comun

PUERTO_MQTTS = 8883


def crear_cliente():
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=comun.DEVICE_ID, protocol=mqtt.MQTTv311)
    except AttributeError:
        return mqtt.Client(client_id=comun.DEVICE_ID, protocol=mqtt.MQTTv311)


def main():
    parser = argparse.ArgumentParser(description="Publica la telemetría del panel solar por MQTT.")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    comun.validar_configuracion()

    topic_base = f"devices/{comun.DEVICE_ID}/messages/events/"
    usuario = f"{comun.HUB_HOSTNAME}/{comun.DEVICE_ID}/?api-version=2021-04-12"
    panel = comun.Panel()
    registro = comun.Registro("mqtt", args.interval)
    conectado = threading.Event()
    pendientes = {}
    confirmados = threading.Semaphore(0)

    cliente = crear_cliente()
    cliente.username_pw_set(usuario, comun.generar_sas())
    cliente.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLS_CLIENT)

    def al_conectar(_cliente, _datos, _banderas, codigo, *_):
        print(f"[CONNECT] Código de respuesta: {codigo}")
        conectado.set()

    def al_publicar(_cliente, _datos, mid, *_):
        secuencia, momento, tam, t0 = pendientes.pop(mid)
        latencia = (time.perf_counter() - t0) * 1000
        registro.envio(secuencia, momento, tam, latencia, "puback")
        print(f"[PUBACK] secuencia={secuencia} mid={mid} tiempo={latencia:.2f} ms")
        confirmados.release()

    cliente.on_connect = al_conectar
    cliente.on_publish = al_publicar

    print("=" * 34, "MQTT", "=" * 34)
    print(f"Hostname: {comun.HUB_HOSTNAME}")
    print(f"Puerto: {PUERTO_MQTTS} (mqtts)")
    print("TLS: Sí, certificado validado con certifi")
    print(f"Username: {usuario}")
    print(f"Topic: {topic_base}")
    print("QoS: 1")
    print("Clave: Cargada, no mostrada")
    print("=" * 74)

    t0 = time.perf_counter()
    cliente.connect(comun.HUB_HOSTNAME, PUERTO_MQTTS, keepalive=60)
    cliente.loop_start()
    if not conectado.wait(20):
        print("[ERROR] No llegó CONNACK")
        return
    ms_conexion = (time.perf_counter() - t0) * 1000
    ip = cliente.socket().getpeername()[0]
    bytes_conexion = comun.bytes_tcp(PUERTO_MQTTS, ip)
    print(f"[CONNECT] Sesión MQTT lista en {ms_conexion:.2f} ms "
          f"(bytes TLS + CONNECT: enviados={bytes_conexion[0]} recibidos={bytes_conexion[1]})")

    for secuencia in range(args.count):
        lectura = panel.lectura()
        datos = comun.a_json(lectura)
        momento = comun.ahora_utc()
        propiedades = "$.ct=application%2Fjson&$.ce=utf-8&iothub-creation-time-utc=" + \
            urllib.parse.quote(comun.iso(momento), safe="")
        topic = topic_base + propiedades
        inicio = time.perf_counter()
        info = cliente.publish(topic, datos, qos=1)
        pendientes[info.mid] = (secuencia, momento, len(datos), inicio)
        print()
        print(f"[PUBLISH] secuencia={secuencia}")
        print(f"[PUBLISH] payload_bytes= {len(datos)}")
        print(f"[PUBLISH] payload= {datos.decode('utf-8')}")
        confirmados.acquire(timeout=20)
        if secuencia < args.count - 1:
            time.sleep(args.interval)

    enviados, recibidos = comun.bytes_tcp(PUERTO_MQTTS, ip)
    por_mensaje = ((enviados - bytes_conexion[0]) / args.count, (recibidos - bytes_conexion[1]) / args.count)
    cliente.disconnect()
    cliente.loop_stop()

    resumen = {
        "puerto": PUERTO_MQTTS,
        "mensajes": args.count,
        "aceptados": len(registro.latencias),
        "ms_conexion": round(ms_conexion, 2),
        "bytes_conexion_enviados": bytes_conexion[0],
        "bytes_conexion_recibidos": bytes_conexion[1],
        "bytes_por_mensaje_enviados": round(por_mensaje[0], 1),
        "bytes_por_mensaje_recibidos": round(por_mensaje[1], 1),
    }
    print()
    print(f"[FIN] Mensajes enviados: {args.count}, confirmados con PUBACK: {len(registro.latencias)}")
    print(f"[FIN] Bytes por mensaje: enviados={por_mensaje[0]:.1f} recibidos={por_mensaje[1]:.1f}")
    print(f"[FIN] Resumen guardado en {registro.cerrar(resumen).name}")


if __name__ == "__main__":
    main()
