"""Receptor del webhook de alertas de Grafana.

Es la accion de la alerta: Grafana hace POST a http://receptor-alertas:8080/alerta
y cada notificacion queda en /datos/alertas.jsonl (una linea JSON por envio) y en
el log del contenedor.
"""

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARCHIVO = os.getenv("ARCHIVO_ALERTAS", "/datos/alertas.jsonl")
PUERTO = int(os.getenv("PUERTO_RECEPTOR", "8080"))


class Receptor(BaseHTTPRequestHandler):
    def do_POST(self):
        cuerpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            notificacion = json.loads(cuerpo)
        except ValueError:
            notificacion = {"crudo": cuerpo.decode("utf-8", "replace")}

        recibido = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        with open(ARCHIVO, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps({"recibido_utc": recibido, "ruta": self.path,
                                      "notificacion": notificacion}, ensure_ascii=False) + "\n")

        for alerta in notificacion.get("alerts", []):
            etiquetas = alerta.get("labels", {})
            print(f"{recibido} {alerta.get('status', '?').upper()} {etiquetas.get('alertname')} "
                  f"dispositivo={etiquetas.get('dispositivo', '-')} valores={alerta.get('valueString', '')}",
                  flush=True)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"receptor de alertas activo")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
    print(f"receptor de alertas escuchando en :{PUERTO}, guarda en {ARCHIVO}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PUERTO), Receptor).serve_forever()
