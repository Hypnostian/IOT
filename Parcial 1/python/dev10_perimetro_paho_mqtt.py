#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV10 - Perímetro y bodega "Bodega Zenón"
=========================================

Origen de envío : cliente MQTT explícito (paho-mqtt), sin el SDK de Azure
Protocolo       : MQTT 3.1.1 sobre TLS, puerto 8883
Plantilla       : GZ Perímetro y Bodega
Intervalo       : 30 s
Equipo          : portátil del estudiante (nodo de la sustentación en vivo)

Qué hace distinto a este origen
-------------------------------
Habla el protocolo MQTT de IoT Hub "a pelo", con los topics reservados de la
plataforma. No hay abstracción de por medio:

  CONNECT   client_id = <deviceId>
            username  = <hub>/<deviceId>/?api-version=2021-04-12&model-id=<dtmi>
            password  = token SAS generado localmente
  Telemetría  PUBLISH  devices/<deviceId>/messages/events/
  Comandos    SUBSCRIBE $iothub/methods/POST/#
              respuesta $iothub/methods/res/<codigo>/?$rid=<rid>
  Propiedades PUBLISH  $iothub/twin/PATCH/properties/reported/?$rid=<rid>
              SUBSCRIBE $iothub/twin/PATCH/properties/desired/#

Es el origen que mejor evidencia, frente al ingeniero, que IoT Central es un
broker MQTT gestionado: se ve el CONNECT, el topic y el payload exacto.

Uso:
    python dev10_perimetro_paho_mqtt.py
    python dev10_perimetro_paho_mqtt.py --una-vez
"""

import json
import ssl
import sys
import time
import urllib.parse

import paho.mqtt.client as mqtt

from gzcommon import config, dps, runner, sas, sim

CLAVE = "dev10"
API_VERSION_HUB = "2021-04-12"

ESTADO = {"alarma_armada": True, "eventos_acceso": 0,
          "ultima_puerta": False, "conectado": False}


VIGENCIA_TOKEN_S = 3600          # IoT Hub cierra la sesion al caducar
RENOVAR_ANTES_S = 300            # se renueva 5 minutos antes


class ClienteMqttCrudo(object):
    """
    Cliente MQTT de IoT Hub escrito a mano sobre paho.

    Leccion aprendida en la primera semana de operacion
    ---------------------------------------------------
    La primera version dejaba activa la reconexion automatica de paho y, al
    detectar una desconexion, creaba un cliente NUEVO sin cerrar el anterior.
    Cuando el token SAS caducaba (a la hora), IoT Hub cerraba la sesion, paho
    reintentaba con el token caducado (CONNACK rc=5, no autorizado) y el
    cliente viejo y el nuevo, con el mismo client_id, se expulsaban
    mutuamente del hub. En 7 dias: ~299 000 conexiones para ~15 000 envios.

    Esta version:
      * desactiva la reconexion automatica de paho (reconnect_on_failure=False):
        solo este codigo decide cuando reconectar, y siempre con token nuevo;
      * cierra el cliente anterior antes de crear otro;
      * descarta los eventos que lleguen de clientes antiguos (generacion);
      * renueva el token 5 minutos antes de que caduque, con una reconexion
        limpia y planificada en lugar de esperar a que el hub corte.
    """

    def __init__(self, dev, log):
        self.dev = dev
        self.log = log
        self.hub = None
        self.cliente = None
        self.rid = 0
        self.generacion = 0
        self.token_caduca = 0.0

    # -- ciclo de vida ------------------------------------------------------
    def provisionar(self):
        resultado = dps.registrar(
            config.ID_SCOPE, self.dev["device_id"], self.dev["device_key"],
            self.dev["model_id"], config.DPS_ENDPOINT, log=self.log.info)
        self.hub = resultado["assignedHub"]

    def conectar(self):
        # Nunca dos clientes con el mismo client_id a la vez.
        self.desconectar()

        device_id = self.dev["device_id"]
        recurso = "{}/devices/{}".format(self.hub, device_id)
        password = sas.generar_token_sas(recurso, self.dev["device_key"],
                                         vigencia_s=VIGENCIA_TOKEN_S)
        self.token_caduca = sas.expiracion_token(password)
        # El model-id en el username es lo que hace que IoT Central asocie
        # este dispositivo a la plantilla correcta.
        username = "{}/{}/?api-version={}&model-id={}".format(
            self.hub, device_id, API_VERSION_HUB,
            urllib.parse.quote(self.dev["model_id"], safe=""))

        self.generacion += 1
        self.cliente = mqtt.Client(client_id=device_id, protocol=mqtt.MQTTv311,
                                   userdata=self.generacion,
                                   reconnect_on_failure=False)
        self.cliente.username_pw_set(username=username, password=password)
        self.cliente.tls_set(cert_reqs=ssl.CERT_REQUIRED,
                             tls_version=ssl.PROTOCOL_TLSv1_2)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_disconnect = self._al_desconectar
        self.cliente.on_message = self._al_mensaje

        self.log.info("CONNECT MQTT -> %s:8883  client_id=%s  (token valido %d min)",
                      self.hub, device_id, VIGENCIA_TOKEN_S // 60)
        self.cliente.connect(self.hub, 8883, keepalive=120)
        self.cliente.loop_start()

        espera = 0
        while not ESTADO["conectado"] and espera < 30:
            time.sleep(0.5)
            espera += 0.5
        if not ESTADO["conectado"]:
            raise RuntimeError("No se completó el CONNACK en 30 s")

    def token_por_caducar(self):
        return time.time() > self.token_caduca - RENOVAR_ANTES_S

    def desconectar(self):
        if self.cliente is not None:
            anterior = self.cliente
            self.cliente = None
            self.generacion += 1        # los eventos del cliente viejo ya no cuentan
            try:
                anterior.disconnect()
                anterior.loop_stop()
            except Exception:  # noqa: BLE001
                pass
        ESTADO["conectado"] = False

    # -- callbacks ----------------------------------------------------------
    def _al_conectar(self, cliente, userdata, flags, rc):
        if userdata != self.generacion:
            return   # evento de un cliente que ya se cerro
        if rc == 0:
            ESTADO["conectado"] = True
            self.log.info("CONNACK correcto (rc=0). Sesión MQTT abierta.")
            cliente.subscribe("$iothub/methods/POST/#", qos=0)
            cliente.subscribe("$iothub/twin/PATCH/properties/desired/#", qos=0)
            self.reportar_propiedades({
                "zona": "Bodega de grano seco y cerramiento norte",
                "capacidadBodegaSacos": 1200,
                "alarmaArmada": ESTADO["alarma_armada"],
            })
        else:
            self.log.error("CONNACK rechazado, rc=%s", rc)

    def _al_desconectar(self, cliente, userdata, rc):
        if userdata != self.generacion:
            return   # desconexion de un cliente viejo: ya se gestiono
        ESTADO["conectado"] = False
        if rc == 0:
            self.log.info("Sesión MQTT cerrada de forma ordenada.")
        else:
            self.log.warning("Desconectado del broker (rc=%s).", rc)

    def _al_mensaje(self, cliente, userdata, mensaje):
        topico = mensaje.topic
        if topico.startswith("$iothub/methods/POST/"):
            self._atender_comando(topico, mensaje.payload)
        elif topico.startswith("$iothub/twin/PATCH/properties/desired"):
            self._atender_propiedad(mensaje.payload)

    def _atender_comando(self, topico, payload):
        # $iothub/methods/POST/<nombre>/?$rid=<rid>
        partes = topico.split("/")
        nombre = partes[3] if len(partes) > 3 else ""
        rid = ""
        if "$rid=" in topico:
            rid = topico.split("$rid=")[1].split("&")[0]
        try:
            cuerpo = json.loads(payload.decode("utf-8") or "{}")
        except ValueError:
            cuerpo = {}
        self.log.info("COMANDO %s recibido (rid=%s) payload=%s",
                      nombre, rid, cuerpo)

        codigo, respuesta = 200, {"resultado": "aceptado"}
        if nombre == "ArmarAlarma":
            armar = cuerpo if isinstance(cuerpo, bool) else bool(
                (cuerpo or {}).get("armar", True))
            ESTADO["alarma_armada"] = armar
            respuesta = {"resultado": "alarma {}".format(
                "armada" if armar else "desarmada")}
            self.reportar_propiedades({"alarmaArmada": armar})
        elif nombre == "ReconocerAlarma":
            respuesta = {"resultado": "alarma reconocida",
                         "en": runner.marca_tiempo()}
        else:
            codigo, respuesta = 404, {"error": "comando no implementado"}

        self.cliente.publish(
            "$iothub/methods/res/{}/?$rid={}".format(codigo, rid),
            json.dumps(respuesta), qos=0)
        self.log.info("Respuesta de comando publicada (código %d).", codigo)

    def _atender_propiedad(self, payload):
        try:
            deseadas = json.loads(payload.decode("utf-8") or "{}")
        except ValueError:
            return
        self.log.info("PROPIEDAD escribible recibida: %s", deseadas)
        version = deseadas.get("$version")
        acuse = {}
        for clave, valor in deseadas.items():
            if clave.startswith("$"):
                continue
            if clave == "alarmaArmada":
                ESTADO["alarma_armada"] = bool(valor)
            acuse[clave] = {"value": valor, "ac": 200, "ad": "aplicado",
                            "av": version}
        if acuse:
            self.reportar_propiedades(acuse)

    # -- publicación --------------------------------------------------------
    def reportar_propiedades(self, propiedades):
        self.rid += 1
        self.cliente.publish(
            "$iothub/twin/PATCH/properties/reported/?$rid={}".format(self.rid),
            json.dumps(propiedades, ensure_ascii=False), qos=0)

    def publicar(self, datos):
        topico = "devices/{}/messages/events/".format(self.dev["device_id"])
        info = self.cliente.publish(
            topico, json.dumps(datos, ensure_ascii=False), qos=1)
        info.wait_for_publish(timeout=15)
        return topico


def telemetria():
    datos = sim.perimetro("perimetro")
    # Recuento acumulado de aperturas: se analiza con sumatoria en el informe.
    if datos["puertaAbierta"] and not ESTADO["ultima_puerta"]:
        ESTADO["eventos_acceso"] += 1
    ESTADO["ultima_puerta"] = datos["puertaAbierta"]
    datos["eventosAcceso"] = ESTADO["eventos_acceso"]
    return datos


def main():
    args = runner.argumentos(__doc__).parse_args()
    dev = config.dispositivo(CLAVE)
    log = runner.configurar_log(dev["device_id"])
    intervalo = args.intervalo or dev["intervalo_s"]
    ventanas = runner.parsear_ventanas(args.ventanas)

    cliente = ClienteMqttCrudo(dev, log)
    cliente.provisionar()

    enviados = 0
    espera_reintento = 5
    try:
        while not runner._PARAR:
            if runner.en_ventana_desconexion(ventanas):
                if ESTADO["conectado"]:
                    log.warning("VENTANA DE DESCONEXIÓN: DISCONNECT voluntario.")
                    cliente.desconectar()
                time.sleep(min(30, intervalo))
                continue

            # Renovacion planificada: antes de que IoT Hub corte por token caducado.
            if ESTADO["conectado"] and cliente.token_por_caducar():
                log.info("Token SAS a punto de caducar: reconexión planificada con token nuevo.")
                cliente.desconectar()

            if not ESTADO["conectado"]:
                try:
                    cliente.conectar()
                    espera_reintento = 5
                except Exception as exc:  # noqa: BLE001
                    log.error("No se pudo conectar: %s. Reintento en %d s.",
                              exc, espera_reintento)
                    cliente.desconectar()
                    time.sleep(espera_reintento)
                    espera_reintento = min(espera_reintento * 2, 60)
                    continue

            try:
                datos = telemetria()
                topico = cliente.publicar(datos)
                enviados += 1
                log.info("TX #%d -> %s  %s", enviados, topico,
                         json.dumps(datos, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                log.error("Fallo publicando: %s", exc)
                cliente.desconectar()
                time.sleep(5)
                continue

            if args.una_vez:
                log.info("Modo --una-vez: prueba de humo correcta.")
                break

            # Espera troceada: si la sesion cae, se reconecta sin esperar al
            # siguiente envio.
            restante = intervalo
            while restante > 0 and not runner._PARAR and ESTADO["conectado"]:
                time.sleep(min(1.0, restante))
                restante -= 1.0
    finally:
        log.info("Cierre del cliente MQTT. Mensajes enviados: %d", enviados)
        cliente.desconectar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
