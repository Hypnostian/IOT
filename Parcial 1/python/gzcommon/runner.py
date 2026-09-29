# -*- coding: utf-8 -*-
"""
Esqueleto común de los nodos que usan el SDK `azure-iot-device`.

Resuelve, una sola vez y para todos los scripts:
  * aprovisionamiento por DPS con la clave derivada del grupo,
  * anuncio del Model ID para que IoT Central asigne la plantilla correcta,
  * envío periódico de telemetría con el intervalo de cada dispositivo,
  * propiedades reportadas y propiedades escribibles (writable),
  * comandos (direct methods) con respuesta,
  * ventanas de desconexión programadas, que es la evidencia de "hueco en la
    serie + reconexión" que exige el parcial,
  * registro (log) con marca de tiempo para adjuntar como evidencia.

Cada script de dispositivo solo aporta su función de telemetría.
"""

import argparse
import datetime
import logging
import signal
import sys
import time

from azure.iot.device import IoTHubDeviceClient, Message, MethodResponse
from azure.iot.device import ProvisioningDeviceClient

from . import config
from . import sim

_PARAR = False


def _manejar_senal(signum, frame):
    global _PARAR
    _PARAR = True
    logging.getLogger("gz").info(
        "Señal %s recibida: cerrando la conexión de forma ordenada.", signum)


signal.signal(signal.SIGINT, _manejar_senal)
signal.signal(signal.SIGTERM, _manejar_senal)


def configurar_log(device_id, nivel=logging.INFO):
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)s] [" + device_id + "] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # El SDK es muy verboso en DEBUG; se deja en WARNING.
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("paho").setLevel(logging.WARNING)
    return logging.getLogger("gz")


def parsear_ventanas(texto):
    """
    Convierte "02:00-02:25,14:10-14:20" en [(120, 145), (850, 860)] minutos
    desde la medianoche local. Fuera de esas ventanas el nodo publica normal.
    """
    ventanas = []
    if not texto:
        return ventanas
    for tramo in texto.split(","):
        tramo = tramo.strip()
        if not tramo or "-" not in tramo:
            continue
        ini, fin = tramo.split("-", 1)

        def a_min(v):
            hh, _, mm = v.strip().partition(":")
            return int(hh) * 60 + int(mm or 0)

        ventanas.append((a_min(ini), a_min(fin)))
    return ventanas


def en_ventana_desconexion(ventanas, ts=None):
    if not ventanas:
        return False
    minutos = sim.hora_local(ts) * 60.0
    return any(ini <= minutos < fin for ini, fin in ventanas)


class Nodo(object):
    """Un dispositivo de la flota conectado con el SDK azure-iot-device."""

    def __init__(self, clave_catalogo, generar_telemetria,
                 propiedades_iniciales=None, comandos=None,
                 websockets=False, intervalo_s=None, ventanas="",
                 una_vez=False):
        self.dev = config.dispositivo(clave_catalogo)
        self.device_id = self.dev["device_id"]
        self.model_id = self.dev["model_id"]
        self.intervalo = intervalo_s or self.dev["intervalo_s"]
        self.websockets = websockets
        self.generar_telemetria = generar_telemetria
        self.propiedades_iniciales = propiedades_iniciales or {}
        self.comandos = comandos or {}
        self.ventanas = parsear_ventanas(ventanas)
        self.una_vez = una_vez
        self.log = configurar_log(self.device_id)
        self.cliente = None
        self.enviados = 0
        self.hub = None

    # -- conexión -----------------------------------------------------------
    def _provisionar(self):
        self.log.info("Provisionando en DPS (ámbito %s)...", config.ID_SCOPE)
        pc = ProvisioningDeviceClient.create_from_symmetric_key(
            provisioning_host=config.DPS_ENDPOINT,
            registration_id=self.device_id,
            id_scope=config.ID_SCOPE,
            symmetric_key=self.dev["device_key"],
            websockets=self.websockets,
        )
        # IoT Central usa este payload para asignar la plantilla del modelo.
        pc.provisioning_payload = {"modelId": self.model_id}
        resultado = pc.register()
        if resultado.status != "assigned":
            raise RuntimeError("DPS devolvió estado {}".format(resultado.status))
        self.hub = resultado.registration_state.assigned_hub
        self.log.info("Asignado al IoT Hub %s", self.hub)
        return resultado

    def conectar(self):
        resultado = self._provisionar()
        self.cliente = IoTHubDeviceClient.create_from_symmetric_key(
            symmetric_key=self.dev["device_key"],
            hostname=self.hub,
            device_id=resultado.registration_state.device_id,
            # product_info es como el SDK de Python anuncia el Model ID de PnP.
            product_info=self.model_id,
            websockets=self.websockets,
        )
        self.cliente.on_method_request_received = self._al_recibir_comando
        self.cliente.on_twin_desired_properties_patch_received = \
            self._al_recibir_propiedad
        transporte = "MQTT sobre WebSocket (443)" if self.websockets \
            else "MQTT sobre TLS (8883)"
        self.log.info("Conectando por %s ...", transporte)
        self.cliente.connect()
        self.log.info("CONECTADO. Origen: %s", self.dev["origen"])

        if self.propiedades_iniciales:
            self.cliente.patch_twin_reported_properties(
                self.propiedades_iniciales)
            self.log.info("Propiedades reportadas: %s",
                          self.propiedades_iniciales)

    def desconectar(self):
        if self.cliente is not None:
            try:
                self.cliente.shutdown()
            except Exception as exc:  # noqa: BLE001 - cierre best effort
                self.log.warning("Error cerrando el cliente: %s", exc)
            self.cliente = None

    # -- callbacks ----------------------------------------------------------
    def _al_recibir_comando(self, peticion):
        self.log.info("COMANDO recibido: %s  payload=%s",
                      peticion.name, peticion.payload)
        manejador = self.comandos.get(peticion.name)
        estado, respuesta = 200, {"resultado": "aceptado"}
        if manejador is not None:
            try:
                respuesta = manejador(peticion.payload) or respuesta
            except Exception as exc:  # noqa: BLE001
                self.log.error("El comando %s falló: %s", peticion.name, exc)
                estado, respuesta = 500, {"error": str(exc)}
        else:
            estado, respuesta = 404, {"error": "comando no implementado"}
            self.log.warning("Comando no implementado: %s", peticion.name)

        self.cliente.send_method_response(
            MethodResponse.create_from_method_request(
                peticion, estado, respuesta))

    def _al_recibir_propiedad(self, parche):
        version = parche.get("$version")
        self.log.info("PROPIEDAD escribible recibida: %s", parche)
        acuse = {}
        for clave, valor in parche.items():
            if clave.startswith("$"):
                continue
            # Formato de acuse que IoT Central espera para writable properties.
            acuse[clave] = {"value": valor, "ac": 200, "ad": "aplicado",
                            "av": version}
            if clave == "intervaloTelemetriaSeg":
                try:
                    self.intervalo = max(5, int(valor))
                    self.log.info("Nuevo intervalo de telemetría: %s s",
                                  self.intervalo)
                except (TypeError, ValueError):
                    pass
        if acuse:
            self.cliente.patch_twin_reported_properties(acuse)

    # -- bucle principal ----------------------------------------------------
    def enviar(self, datos):
        mensaje = Message(_a_json(datos))
        mensaje.content_encoding = "utf-8"
        mensaje.content_type = "application/json"
        self.cliente.send_message(mensaje)
        self.enviados += 1
        self.log.info("TX #%d -> %s", self.enviados, _a_json(datos))

    def ejecutar(self):
        if self.ventanas:
            self.log.info("Ventanas de desconexión programadas (hora local): %s",
                          ", ".join("{:02d}:{:02d}-{:02d}:{:02d}".format(
                              a // 60, a % 60, b // 60, b % 60)
                              for a, b in self.ventanas))
        conectado = False
        try:
            while not _PARAR:
                if en_ventana_desconexion(self.ventanas):
                    if conectado:
                        self.log.warning(
                            "VENTANA DE DESCONEXIÓN: se corta el enlace a "
                            "propósito (hueco documentado en la serie).")
                        self.desconectar()
                        conectado = False
                    time.sleep(min(30, self.intervalo))
                    continue

                if not conectado:
                    try:
                        self.conectar()
                        conectado = True
                    except Exception as exc:  # noqa: BLE001
                        self.log.error("Fallo al conectar: %s. Reintento en 30 s.",
                                       exc)
                        time.sleep(30)
                        continue

                try:
                    self.enviar(self.generar_telemetria())
                except Exception as exc:  # noqa: BLE001
                    self.log.error("Fallo enviando telemetría: %s", exc)
                    self.desconectar()
                    conectado = False
                    time.sleep(15)
                    continue

                if self.una_vez:
                    self.log.info("Modo --una-vez: prueba de humo correcta.")
                    break

                # Espera troceada para reaccionar rápido a SIGTERM.
                restante = self.intervalo
                while restante > 0 and not _PARAR:
                    paso = min(1.0, restante)
                    time.sleep(paso)
                    restante -= paso
        finally:
            self.log.info("Cerrando. Mensajes enviados en esta sesión: %d",
                          self.enviados)
            self.desconectar()


def _a_json(datos):
    import json
    return json.dumps(datos, ensure_ascii=False)


def argumentos(descripcion):
    """Argumentos comunes a todos los scripts de dispositivo."""
    p = argparse.ArgumentParser(description=descripcion)
    p.add_argument("--intervalo", type=int, default=None,
                   help="Intervalo de muestreo en segundos (sobrescribe el "
                        "del catálogo).")
    p.add_argument("--ventanas", default="",
                   help="Ventanas de desconexión, p. ej. "
                        "\"02:00-02:25,14:10-14:20\" en hora local del predio.")
    p.add_argument("--una-vez", action="store_true",
                   help="Envía una sola muestra y termina (prueba de humo).")
    return p


def marca_tiempo():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
