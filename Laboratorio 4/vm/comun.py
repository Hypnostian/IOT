"""Funciones compartidas por los clientes del Laboratorio 4 (MQTT, AMQP y HTTPS)."""

import base64
import csv
import hashlib
import hmac
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

HUB_HOSTNAME = os.getenv("IOTC_HUB_HOSTNAME", "").strip()
DEVICE_ID = os.getenv("IOTC_DEVICE_ID", "").strip()
DEVICE_KEY = os.getenv("IOTC_DEVICE_KEY", "").strip()

CARPETA_RESULTADOS = BASE_DIR / os.getenv("LAB4_RESULTADOS", "resultados")


def validar_configuracion():
    faltantes = [nombre for nombre, valor in (
        ("IOTC_HUB_HOSTNAME", HUB_HOSTNAME),
        ("IOTC_DEVICE_ID", DEVICE_ID),
        ("IOTC_DEVICE_KEY", DEVICE_KEY),
    ) if not valor]
    if faltantes:
        print("Faltan variables en .env:", ", ".join(faltantes))
        sys.exit(1)


def nombre_hub():
    return HUB_HOSTNAME.split(".")[0]


def generar_sas(minutos=60):
    """Token SAS del dispositivo: HMAC-SHA256 de '<recurso>\\n<expiracion>' con la clave en Base64."""
    expiracion = int(time.time()) + minutos * 60
    recurso = urllib.parse.quote(f"{HUB_HOSTNAME}/devices/{DEVICE_ID}", safe="")
    firma = hmac.new(
        base64.b64decode(DEVICE_KEY),
        f"{recurso}\n{expiracion}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    firma = urllib.parse.quote(base64.b64encode(firma).decode("utf-8"), safe="")
    return f"SharedAccessSignature sr={recurso}&sig={firma}&se={expiracion}"


def ahora_utc():
    return datetime.now(timezone.utc)


def iso(momento):
    return momento.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Panel:
    """Genera lecturas del panel solar con una curva de sol que sube y baja."""

    def __init__(self, periodo_s=240):
        self.inicio = time.time()
        self.periodo = periodo_s

    def lectura(self):
        fase = ((time.time() - self.inicio) % self.periodo) / self.periodo
        sol = 0.5 - 0.5 * math.cos(2 * math.pi * fase)
        corriente = round(1.0 + 5.0 * sol + random.uniform(-0.05, 0.05), 2)
        voltaje = round(18.0 + 2.8 * sol + random.uniform(-0.1, 0.1), 1)
        return {
            "PotenciaGenerada": round(voltaje * corriente, 1),
            "TemperaturaDelPanel": round(26.5 + 12.5 * sol + random.uniform(-0.3, 0.3), 1),
            "VoltajeDeSalida": voltaje,
            "CorrienteDeSalida": corriente,
        }


def a_json(lectura):
    return json.dumps(lectura, separators=(",", ":")).encode("utf-8")


def bytes_tcp(puerto, ip=None):
    """Bytes de carga TCP (incluye TLS) de las conexiones establecidas hacia el puerto, segun ss."""
    filtro = ["ss", "-tinH", "state", "established"]
    if ip:
        filtro += ["dst", ip]
    filtro += ["dport", "=", f":{puerto}"]
    salida = subprocess.run(filtro, capture_output=True, text=True).stdout
    enviados = sum(int(x) for x in re.findall(r"bytes_acked:(\d+)", salida))
    recibidos = sum(int(x) for x in re.findall(r"bytes_received:(\d+)", salida))
    return enviados, recibidos


class Registro:
    """Guarda cada envio en un CSV y el resumen de la corrida en un JSON."""

    CAMPOS = ["protocolo", "secuencia", "fecha_utc", "payload_bytes", "latencia_ms",
              "intervalo_configurado_s", "resultado"]

    def __init__(self, protocolo, intervalo):
        CARPETA_RESULTADOS.mkdir(exist_ok=True)
        self.protocolo = protocolo
        self.intervalo = intervalo
        self.archivo = CARPETA_RESULTADOS / f"mediciones_{protocolo}.csv"
        nuevo = not self.archivo.exists()
        self._csv = open(self.archivo, "a", newline="", encoding="utf-8")
        self._escritor = csv.DictWriter(self._csv, fieldnames=self.CAMPOS)
        if nuevo:
            self._escritor.writeheader()
        self.latencias = []

    def envio(self, secuencia, fecha, payload_bytes, latencia_ms, resultado):
        if latencia_ms is not None:
            self.latencias.append(latencia_ms)
        self._escritor.writerow({
            "protocolo": self.protocolo,
            "secuencia": secuencia,
            "fecha_utc": iso(fecha),
            "payload_bytes": payload_bytes,
            "latencia_ms": "" if latencia_ms is None else f"{latencia_ms:.2f}",
            "intervalo_configurado_s": self.intervalo,
            "resultado": resultado,
        })
        self._csv.flush()

    def cerrar(self, resumen):
        self._csv.close()
        if self.latencias:
            resumen["latencia_min_ms"] = round(min(self.latencias), 2)
            resumen["latencia_prom_ms"] = round(sum(self.latencias) / len(self.latencias), 2)
            resumen["latencia_max_ms"] = round(max(self.latencias), 2)
        resumen["protocolo"] = self.protocolo
        resumen["fecha_utc"] = iso(ahora_utc())
        destino = CARPETA_RESULTADOS / f"resumen_{self.protocolo}.json"
        destino.write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
        return destino
