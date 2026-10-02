"""Cliente HTTPS (API REST de IoT Hub) que publica la telemetria del panel solar en IoT Central.

Uso:
    python https_cliente.py --count 10 --interval 5                 (una conexion reutilizada, keep-alive)
    python https_cliente.py --count 10 --interval 5 --nueva-conexion (TLS nuevo en cada mensaje)
"""

import argparse
import http.client
import ssl
import time
import urllib.parse
import uuid

import certifi

import comun

PUERTO_HTTPS = 443
API_VERSION = "2021-04-12"


def abrir_conexion(contexto):
    t0 = time.perf_counter()
    conexion = http.client.HTTPSConnection(comun.HUB_HOSTNAME, PUERTO_HTTPS, context=contexto, timeout=20)
    conexion.connect()
    ms = (time.perf_counter() - t0) * 1000
    ip = conexion.sock.getpeername()[0]
    return conexion, ms, ip


def main():
    parser = argparse.ArgumentParser(description="Publica la telemetría del panel solar por HTTPS.")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--nueva-conexion", action="store_true",
                        help="abre una conexión TLS nueva para cada mensaje")
    args = parser.parse_args()
    comun.validar_configuracion()

    modo = "https_nueva" if args.nueva_conexion else "https"
    ruta = f"/devices/{urllib.parse.quote(comun.DEVICE_ID)}/messages/events?api-version={API_VERSION}"
    contexto = ssl.create_default_context(cafile=certifi.where())
    sas = comun.generar_sas()
    panel = comun.Panel()
    registro = comun.Registro(modo, args.interval)

    print("=" * 33, "HTTPS", "=" * 34)
    print(f"Hostname: {comun.HUB_HOSTNAME}")
    print(f"Puerto: {PUERTO_HTTPS}")
    print("TLS: Sí, certificado validado con certifi")
    print(f"Endpoint: POST {ruta}")
    print("Autenticación: encabezado Authorization con token SAS")
    print(f"Conexión: {'nueva en cada mensaje' if args.nueva_conexion else 'reutilizada (keep-alive)'}")
    print("Clave: Cargada, no mostrada")
    print("=" * 74)

    conexion = None
    ms_conexiones = []
    bytes_handshake = [0, 0]
    bytes_inicio = (0, 0)
    bytes_mensajes = [0, 0]
    ip = None

    for secuencia in range(args.count):
        if conexion is None:
            conexion, ms, ip = abrir_conexion(contexto)
            ms_conexiones.append(ms)
            bytes_inicio = comun.bytes_tcp(PUERTO_HTTPS, ip)
            bytes_handshake[0] += bytes_inicio[0]
            bytes_handshake[1] += bytes_inicio[1]
            print(f"[TLS] Conexión establecida con {ip}:{PUERTO_HTTPS} en {ms:.2f} ms "
                  f"(bytes TLS: enviados={bytes_inicio[0]} recibidos={bytes_inicio[1]})")

        lectura = panel.lectura()
        datos = comun.a_json(lectura)
        momento = comun.ahora_utc()
        encabezados = {
            "Authorization": sas,
            "Content-Type": "application/json",
            "iothub-contenttype": "application/json",
            "iothub-contentencoding": "utf-8",
            "iothub-messageid": str(uuid.uuid4()),
            "iothub-app-iothub-creation-time-utc": comun.iso(momento),
        }

        t0 = time.perf_counter()
        conexion.request("POST", ruta, body=datos, headers=encabezados)
        respuesta = conexion.getresponse()
        respuesta.read()
        latencia = (time.perf_counter() - t0) * 1000

        antes = bytes_inicio
        bytes_inicio = comun.bytes_tcp(PUERTO_HTTPS, ip)
        bytes_mensajes[0] += bytes_inicio[0] - antes[0]
        bytes_mensajes[1] += bytes_inicio[1] - antes[1]

        print()
        print(f"[POST] secuencia={secuencia}")
        print(f"[POST] payload_bytes= {len(datos)}")
        print(f"[POST] payload= {datos.decode('utf-8')}")
        print(f"[RESPUESTA] HTTP {respuesta.status} {respuesta.reason} tiempo={latencia:.2f} ms")
        resultado = str(respuesta.status)
        registro.envio(secuencia, momento, len(datos), latencia if respuesta.status == 204 else None, resultado)

        if args.nueva_conexion:
            conexion.close()
            conexion = None

        if secuencia < args.count - 1:
            time.sleep(args.interval)

    if conexion is not None:
        conexion.close()

    conexiones = len(ms_conexiones)
    resumen = {
        "puerto": PUERTO_HTTPS,
        "mensajes": args.count,
        "aceptados": len(registro.latencias),
        "ms_conexion": round(sum(ms_conexiones) / conexiones, 2),
        "conexiones_tls": conexiones,
        "bytes_conexion_enviados": round(bytes_handshake[0] / conexiones),
        "bytes_conexion_recibidos": round(bytes_handshake[1] / conexiones),
        "bytes_por_mensaje_enviados": round(bytes_mensajes[0] / args.count, 1),
        "bytes_por_mensaje_recibidos": round(bytes_mensajes[1] / args.count, 1),
        "bytes_por_mensaje_con_tls_enviados": round((bytes_mensajes[0] + bytes_handshake[0]) / args.count, 1),
        "bytes_por_mensaje_con_tls_recibidos": round((bytes_mensajes[1] + bytes_handshake[1]) / args.count, 1),
    }
    print()
    print(f"[FIN] Mensajes enviados: {args.count}, respondidos con 204: {len(registro.latencias)}")
    print(f"[FIN] Conexiones TLS abiertas: {len(ms_conexiones)}")
    print(f"[FIN] Bytes por mensaje (petición y respuesta): enviados={resumen['bytes_por_mensaje_enviados']} "
          f"recibidos={resumen['bytes_por_mensaje_recibidos']}")
    print(f"[FIN] Bytes por mensaje contando el saludo TLS: enviados={resumen['bytes_por_mensaje_con_tls_enviados']} "
          f"recibidos={resumen['bytes_por_mensaje_con_tls_recibidos']}")
    print(f"[FIN] Resumen guardado en {registro.cerrar(resumen).name}")


if __name__ == "__main__":
    main()
