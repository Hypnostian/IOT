#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV04 - Dosel y sombrío "Bosque de Bartolito"
=============================================

Origen de envío : segundo script Python, con un TRANSPORTE distinto al de DEV02
Protocolo       : MQTT sobre WebSocket seguro, puerto 443 (no 8883)
Plantilla       : GZ Nodo de Dosel (dtmi:granjazenon:cacao:NodoDosel;1)
Intervalo       : 60 s
Equipo          : VM de Azure `granjazenon`

¿Por qué cuenta como un origen distinto y no como "el mismo Python"?
--------------------------------------------------------------------
Porque cambia la pila de transporte completa: el CONNECT de MQTT viaja
encapsulado en un WebSocket sobre TLS/443 en lugar de MQTT nativo sobre
TLS/8883. En el predio esto no es un capricho: el enlace 4G/LTE rural sale
por un CGNAT del operador que, en horas pico, descarta las sesiones largas al
puerto 8883. El 443 atraviesa ese camino sin bloqueo y es el modo que se usa
cuando el nodo se cuelga del router de la casa principal.

Uso:
    python dev04_dosel_websocket.py
    python dev04_dosel_websocket.py --una-vez
"""

import sys

from gzcommon import runner, sim

CLAVE = "dev04"

ESTADO = {"umbral_sombra_pct": 35.0, "lecturas_forzadas": 0}


def telemetria():
    return sim.nodo_dosel("dosel")


def cmd_forzar_lectura(payload):
    ESTADO["lecturas_forzadas"] += 1
    datos = telemetria()
    return {"resultado": "lectura forzada", "muestra": datos,
            "total": ESTADO["lecturas_forzadas"]}


def main():
    args = runner.argumentos(__doc__).parse_args()

    nodo = runner.Nodo(
        CLAVE,
        generar_telemetria=telemetria,
        propiedades_iniciales={
            "especieSombrio": "Cordia alliodora y plátano hartón",
            "alturaDoselM": 12.5,
            "umbralSombraPct": ESTADO["umbral_sombra_pct"],
        },
        comandos={"ForzarLecturaDosel": cmd_forzar_lectura},
        # --- la diferencia con DEV02 está aquí ---
        websockets=True,
        intervalo_s=args.intervalo,
        ventanas=args.ventanas,
        una_vez=args.una_vez,
    )
    nodo.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
