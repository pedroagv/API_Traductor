import datetime
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "licenses.json")


def load_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    initial = {
        "licenses": {
            "DEMO-SINGLE-KEY": {
                "max_seats": 1,
                "registered_devices": [],
                "created_at": datetime.datetime.now().isoformat(),
                "note": "Clave demo monousuario",
            },
            "EMPRESA-5SEATS-KEY": {
                "max_seats": 5,
                "registered_devices": [],
                "created_at": datetime.datetime.now().isoformat(),
                "note": "Clave multiusuario 5 licencias",
            },
        },
        "updates": {
            "latest_version": "1.0.0",
            "download_url": "https://github.com/pedro/reunion/releases/latest",
            "release_notes": "Versión 1.0.0 inicial con soporte multidioma y cambio de modelos.",
        },
    }
    save_db(initial)
    return initial


def save_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class LicenseAPIHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_POST(self):
        if self.path == "/verify-license":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")

            parsed = urllib.parse.parse_qs(post_body)
            key = parsed.get("key", [""])[0].strip().upper()
            hw_id = parsed.get("hw_id", [""])[0].strip()
            mac = parsed.get("mac", [""])[0].strip()
            hostname = parsed.get("hostname", [""])[0].strip()

            db = load_db()
            licenses = db.get("licenses", {})

            if key not in licenses:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "Clave de licencia no encontrada."}).encode())
                return

            lic_data = licenses[key]
            max_seats = lic_data.get("max_seats", 1)
            registered = lic_data.get("registered_devices", [])

            # Comprobar si este dispositivo (MAC o HWID) ya está registrado
            device_match = next((d for d in registered if d.get("mac") == mac or d.get("hw_id") == hw_id), None)

            if device_match:
                # Dispositivo previamente autorizado
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "message": "Dispositivo autorizado.",
                    "seats_used": len(registered),
                    "max_seats": max_seats,
                }).encode())
                return

            # Si es una nueva máquina, verificar límite de licencias/asientos
            if len(registered) >= max_seats:
                self._set_headers(403)
                self.wfile.write(json.dumps({
                    "success": False,
                    "message": f"Límite de licencias alcanzado ({len(registered)}/{max_seats} equipos activados).",
                }).encode())
                return

            # Registrar la nueva máquina
            new_device = {
                "hw_id": hw_id,
                "mac": mac,
                "hostname": hostname,
                "activated_at": datetime.datetime.now().isoformat(),
            }
            registered.append(new_device)
            lic_data["registered_devices"] = registered
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "message": f"¡Licencia activada con éxito en este equipo! ({len(registered)}/{max_seats} licencias usadas)",
                "seats_used": len(registered),
                "max_seats": max_seats,
            }).encode())

        elif self.path == "/generate-key":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            key = parsed.get("key", [""])[0].strip().upper()
            seats = int(parsed.get("seats", [1])[0])
            note = parsed.get("note", [""])[0]

            if not key:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "Falta parametro key"}).encode())
                return

            db = load_db()
            db["licenses"][key] = {
                "max_seats": seats,
                "registered_devices": [],
                "created_at": datetime.datetime.now().isoformat(),
                "note": note,
            }
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "key": key, "seats": seats}).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint no encontrado"}).encode())

    def do_GET(self):
        if self.path == "/check-update" or self.path == "/updates":
            db = load_db()
            updates = db.get("updates", {})
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "tag_name": updates.get("latest_version", "1.0.0"),
                "html_url": "/download",
                "notes": updates.get("release_notes", ""),
            }).encode())
        elif self.path in ("/download", "/download/", "/ReunionPro_Portable.zip") or self.path.startswith("/downloads/"):
            downloads_dir = os.path.join(os.path.dirname(__file__), "downloads")
            zip_path = os.path.join(downloads_dir, "ReunionPro_Portable.zip")
            if not os.path.exists(zip_path):
                # Si aún no existe la subcarpeta downloads, buscar en la raíz de API
                zip_path = os.path.join(os.path.dirname(__file__), "ReunionPro_Portable.zip")

            if os.path.exists(zip_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="ReunionPro_Portable.zip"')
                self.send_header("Content-Length", str(os.path.getsize(zip_path)))
                self.end_headers()
                with open(zip_path, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "El archivo portable aún no ha sido subido al servidor."}).encode())
        elif self.path == "/api-status":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "Reunion Pro License API Running"}).encode())
        else:
            # Servir la Landing Page HTML
            landing_path = os.path.join(os.path.dirname(__file__), "landing.html")
            if os.path.exists(landing_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(landing_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "Reunion Pro License API Running"}).encode())


def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, LicenseAPIHandler)
    print(f"🚀 Servidor API de Licencias Reunion AI Pro ejecutándose en el puerto {PORT}...")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
