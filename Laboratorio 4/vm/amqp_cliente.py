"""Cliente AMQP 1.0 (Qpid Proton) que publica la telemetria del panel solar en IoT Central.

Uso:
    python amqp_cliente.py --count 10 --interval 5
    PN_TRACE_FRM=1 python amqp_cliente.py --count 2 --interval 2   (muestra las tramas AMQP)
"""

import argparse
import time
import uuid

import certifi
from proton import Message, SSLDomain
from proton.handlers import MessagingHandler
from proton.reactor import Container

import comun

PUERTO_AMQPS = 5671


class PublicadorAMQP(MessagingHandler):
    def __init__(self, cantidad, intervalo):
        super().__init__()
        self.cantidad = cantidad
        self.intervalo = intervalo
        self.direccion = f"/devices/{comun.DEVICE_ID}/messages/events"
        self.panel = comun.Panel()
        self.registro = comun.Registro("amqp", intervalo)
        self.pendientes = {}
        self.enviados = 0
        self.confirmados = 0
        self.enlace = None
        self.bytes_conexion = (0, 0)
        self.t_inicio = 0.0
        self.ms_conexion = 0.0

    def on_start(self, event):
        dominio = SSLDomain(SSLDomain.MODE_CLIENT)
        dominio.set_trusted_ca_db(certifi.where())
        dominio.set_peer_authentication(SSLDomain.VERIFY_PEER_NAME)
        usuario = f"{comun.DEVICE_ID}@sas.{comun.nombre_hub()}"

        print("=" * 34, "AMQP", "=" * 34)
        print(f"Hostname: {comun.HUB_HOSTNAME}")
        print(f"Puerto: {PUERTO_AMQPS} (amqps)")
        print("TLS: Sí, certificado validado con certifi")
        print("Autenticación: SASL PLAIN con token SAS")
        print(f"Usuario SASL: {usuario}")
        print(f"Destino del enlace: {self.direccion}")
        print("Clave: Cargada, no mostrada")
        print("=" * 74)

        self.t_inicio = time.perf_counter()
        conexion = event.container.connect(
            url=f"amqps://{comun.HUB_HOSTNAME}:{PUERTO_AMQPS}",
            ssl_domain=dominio,
            sasl_enabled=True,
            allowed_mechs="PLAIN",
            user=usuario,
            password=comun.generar_sas(),
            virtual_host=comun.HUB_HOSTNAME,
            reconnect=False,
        )
        self.enlace = event.container.create_sender(conexion, target=self.direccion, name="telemetria-panel")
        print("[CONNECT] Abriendo conexión AMQP, sesión y enlace de envío...")

    def on_connection_opened(self, event):
        print(f"[AMQP] Conexión abierta con {event.connection.remote_hostname or comun.HUB_HOSTNAME}")

    def on_link_opened(self, event):
        if event.link != self.enlace:
            return
        self.ms_conexion = (time.perf_counter() - self.t_inicio) * 1000
        self.bytes_conexion = comun.bytes_tcp(PUERTO_AMQPS)
        print(f"[AMQP] Sesión y enlace listos en {self.ms_conexion:.2f} ms")
        print(f"[AMQP] Bytes de establecimiento (TLS + SASL + open/begin/attach): "
              f"enviados={self.bytes_conexion[0]} recibidos={self.bytes_conexion[1]}")

    def on_sendable(self, event):
        if self.enviados == 0 and not self.pendientes:
            print(f"[FLOW] Crédito concedido por IoT Hub: {event.sender.credit} mensajes")
            self._enviar(event)

    def on_timer_task(self, event):
        self._enviar(event)

    def _enviar(self, event):
        if self.enviados >= self.cantidad:
            return
        if self.enlace.credit <= 0:
            event.container.schedule(0.2, self)
            return

        lectura = self.panel.lectura()
        datos = comun.a_json(lectura)
        momento = comun.ahora_utc()
        mensaje = Message(body=datos, inferred=True)
        mensaje.id = str(uuid.uuid4())
        mensaje.address = self.direccion
        mensaje.content_type = "application/json"
        mensaje.content_encoding = "utf-8"
        mensaje.properties = {"iothub-creation-time-utc": comun.iso(momento)}

        entrega = self.enlace.send(mensaje)
        self.pendientes[entrega.tag] = (self.enviados, momento, len(datos), time.perf_counter())
        print()
        print(f"[TRANSFER] secuencia={self.enviados}")
        print(f"[TRANSFER] destino= {self.direccion}")
        print(f"[TRANSFER] payload_bytes= {len(datos)}")
        print(f"[TRANSFER] payload= {datos.decode('utf-8')}")
        print(f"[TRANSFER] crédito restante= {self.enlace.credit}")
        self.enviados += 1

        if self.enviados < self.cantidad:
            event.container.schedule(self.intervalo, self)

    def on_accepted(self, event):
        secuencia, momento, tam, t0 = self.pendientes.pop(event.delivery.tag)
        latencia = (time.perf_counter() - t0) * 1000
        self.confirmados += 1
        self.registro.envio(secuencia, momento, tam, latencia, "accepted")
        print(f"[DISPOSITION] secuencia={secuencia} estado=accepted tiempo={latencia:.2f} ms")
        self._terminar_si_corresponde(event)

    def on_rejected(self, event):
        secuencia, momento, tam, _ = self.pendientes.pop(event.delivery.tag)
        self.registro.envio(secuencia, momento, tam, None, "rejected")
        print(f"[DISPOSITION] secuencia={secuencia} estado=rejected {event.delivery.remote.condition}")
        self._terminar_si_corresponde(event)

    def on_released(self, event):
        secuencia, momento, tam, _ = self.pendientes.pop(event.delivery.tag)
        self.registro.envio(secuencia, momento, tam, None, "released")
        print(f"[DISPOSITION] secuencia={secuencia} estado=released")
        self._terminar_si_corresponde(event)

    def _terminar_si_corresponde(self, event):
        if self.enviados < self.cantidad or self.pendientes:
            return
        enviados, recibidos = comun.bytes_tcp(PUERTO_AMQPS)
        por_mensaje = (
            (enviados - self.bytes_conexion[0]) / self.enviados,
            (recibidos - self.bytes_conexion[1]) / self.enviados,
        )
        print()
        print(f"[FIN] Mensajes enviados: {self.enviados}, aceptados: {self.confirmados}")
        print(f"[FIN] Bytes por mensaje en el enlace: enviados={por_mensaje[0]:.1f} recibidos={por_mensaje[1]:.1f}")
        destino = self.registro.cerrar({
            "puerto": PUERTO_AMQPS,
            "mensajes": self.enviados,
            "aceptados": self.confirmados,
            "ms_conexion": round(self.ms_conexion, 2),
            "bytes_conexion_enviados": self.bytes_conexion[0],
            "bytes_conexion_recibidos": self.bytes_conexion[1],
            "bytes_por_mensaje_enviados": round(por_mensaje[0], 1),
            "bytes_por_mensaje_recibidos": round(por_mensaje[1], 1),
        })
        print(f"[FIN] Resumen guardado en {destino.name}")
        event.connection.close()

    def on_transport_error(self, event):
        print(f"[ERROR] Transporte: {event.transport.condition}")

    def on_connection_closed(self, event):
        print("[DISCONNECT] Conexión AMQP cerrada")


def main():
    parser = argparse.ArgumentParser(description="Publica la telemetría del panel solar por AMQP.")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    comun.validar_configuracion()
    Container(PublicadorAMQP(args.count, args.interval)).run()


if __name__ == "__main__":
    main()
