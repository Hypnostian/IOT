"""Compara los resultados de los tres protocolos a partir de los archivos de la carpeta resultados."""

import json

import comun

ORDEN = [
    ("mqtt", "MQTT 8883"),
    ("amqp", "AMQP 5671"),
    ("https", "HTTPS keep-alive"),
    ("https_nueva", "HTTPS conexión nueva"),
]


def main():
    filas = []
    for clave, nombre in ORDEN:
        archivo = comun.CARPETA_RESULTADOS / f"resumen_{clave}.json"
        if not archivo.exists():
            continue
        r = json.loads(archivo.read_text(encoding="utf-8"))
        if clave == "https_nueva":
            envio = r["bytes_por_mensaje_con_tls_enviados"]
            recibo = r["bytes_por_mensaje_con_tls_recibidos"]
        else:
            envio = r["bytes_por_mensaje_enviados"]
            recibo = r["bytes_por_mensaje_recibidos"]
        filas.append((
            nombre,
            f"{r['aceptados']}/{r['mensajes']}",
            f"{r['ms_conexion']:.0f}",
            f"{r.get('bytes_conexion_enviados', 0)}/{r.get('bytes_conexion_recibidos', 0)}",
            f"{envio:.0f}/{recibo:.0f}",
            f"{r['latencia_min_ms']:.0f}/{r['latencia_prom_ms']:.0f}/{r['latencia_max_ms']:.0f}",
        ))

    titulos = ("Protocolo", "OK", "Conexión ms", "Bytes conexión env/rec",
               "Bytes por mensaje env/rec", "Confirmación ms min/prom/max")
    anchos = [max(len(str(f[i])) for f in filas + [titulos]) for i in range(len(titulos))]
    linea = "  ".join(t.ljust(a) for t, a in zip(titulos, anchos))
    print(linea)
    print("-" * len(linea))
    for fila in filas:
        print("  ".join(str(v).ljust(a) for v, a in zip(fila, anchos)))
    print()
    print("Payload JSON en los tres casos: mismas 4 variables, 99 a 101 bytes.")
    print("Bytes medidos con ss (carga TCP, incluye TLS). En HTTPS con conexión nueva el saludo TLS va en cada mensaje.")


if __name__ == "__main__":
    main()
