import datetime
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "licenses.json")

# Credenciales de Administrador
ADMIN_USER = os.environ.get("ADMIN_USER", "pedroadmin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "SubVozPro2026!")
ADMIN_TOKEN = hashlib.sha256(f"{ADMIN_USER}:{ADMIN_PASS}:SUBVOZ-ADMIN-SALT".encode()).hexdigest()


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
            "download_url": "https://github.com/pedroagv/API_Traductor/releases/latest/download/SubVozPro_Portable.zip",
            "release_notes": "Versión 1.0.0 inicial con soporte multidioma y cambio de modelos.",
        },
    }
    save_db(initial)
    return initial


def save_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def check_auth_token(token: str) -> bool:
    return token and token == ADMIN_TOKEN


class LicenseAPIHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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
            expires_at_str = lic_data.get("expires_at")

            # Comprobar expiración por tiempo (meses)
            if expires_at_str:
                try:
                    exp_dt = datetime.datetime.fromisoformat(expires_at_str)
                    if datetime.datetime.now() > exp_dt:
                        self._set_headers(403)
                        self.wfile.write(json.dumps({
                            "success": False,
                            "message": f"La licencia de esta clave ha expirado el {exp_dt.strftime('%d/%m/%Y')}.",
                            "expired": True,
                        }).encode())
                        return
                except Exception:
                    pass

            # Comprobar si este dispositivo (MAC o HWID) ya está registrado
            device_match = next((d for d in registered if d.get("mac") == mac or d.get("hw_id") == hw_id), None)
            now_iso = datetime.datetime.now().isoformat()

            if device_match:
                device_match["last_seen"] = now_iso
                lic_data["last_activity"] = now_iso
                save_db(db)

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "message": "Dispositivo autorizado.",
                    "seats_used": len(registered),
                    "max_seats": max_seats,
                    "expires_at": expires_at_str,
                }).encode())
                return

            if len(registered) >= max_seats:
                self._set_headers(403)
                self.wfile.write(json.dumps({
                    "success": False,
                    "message": f"Límite de licencias alcanzado ({len(registered)}/{max_seats} equipos activados).",
                }).encode())
                return

            new_device = {
                "hw_id": hw_id,
                "mac": mac,
                "hostname": hostname,
                "activated_at": now_iso,
                "last_seen": now_iso,
            }
            registered.append(new_device)
            lic_data["registered_devices"] = registered
            lic_data["last_activity"] = now_iso
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "message": f"¡Licencia activada con éxito en este equipo! ({len(registered)}/{max_seats} licencias usadas)",
                "seats_used": len(registered),
                "max_seats": max_seats,
                "expires_at": expires_at_str,
            }).encode())

        elif self.path == "/generate-key" or self.path == "/admin/api/generate-key":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            
            token = parsed.get("token", [""])[0]
            key = parsed.get("key", [""])[0].strip().upper()
            seats = int(parsed.get("seats", [1])[0])
            note = parsed.get("note", [""])[0]
            months = int(parsed.get("months", [0])[0])

            if self.path == "/admin/api/generate-key" and not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            if not key:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "Falta parametro key"}).encode())
                return

            expires_at = None
            if months > 0:
                expires_at = (datetime.datetime.now() + datetime.timedelta(days=30 * months)).isoformat()

            db = load_db()
            db["licenses"][key] = {
                "max_seats": seats,
                "registered_devices": [],
                "created_at": datetime.datetime.now().isoformat(),
                "duration_months": months,
                "expires_at": expires_at,
                "note": note,
            }
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "key": key, "seats": seats, "expires_at": expires_at, "note": note}).encode())

        elif self.path == "/admin/api/login":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            user = parsed.get("user", [""])[0].strip()
            password = parsed.get("pass", [""])[0].strip()

            if user == ADMIN_USER and password == ADMIN_PASS:
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "token": ADMIN_TOKEN}).encode())
            else:
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "Usuario o clave incorrectos"}).encode())

        elif self.path == "/admin/api/delete-key":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            token = parsed.get("token", [""])[0]
            key = parsed.get("key", [""])[0].strip().upper()

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            if key in db.get("licenses", {}):
                del db["licenses"][key]
                save_db(db)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": f"Licencia {key} eliminada"}).encode())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"success": False, "message": "Clave no encontrada"}).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint no encontrado"}).encode())

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/check-update" or path == "/updates":
            db = load_db()
            updates = db.get("updates", {})
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "tag_name": updates.get("latest_version", "1.0.0"),
                "html_url": "/download",
                "notes": updates.get("release_notes", ""),
            }).encode())

        elif path in ("/download", "/download/", "/ReunionPro_Portable.zip", "/SubVozPro_Portable.zip") or path.startswith("/downloads/"):
            db = load_db()
            updates = db.get("updates", {})
            download_url = updates.get("download_url", "").strip()

            if download_url and download_url != "/download" and "pedro/reunion" not in download_url:
                self.send_response(302)
                self.send_header("Location", download_url)
                self.end_headers()
                return

            default_rel = "https://github.com/pedroagv/API_Traductor/releases/latest/download/SubVozPro_Portable.zip"
            self.send_response(302)
            self.send_header("Location", default_rel)
            self.end_headers()

        elif path == "/admin" or path == "/admin/":
            admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
            if os.path.exists(admin_path):
                self._set_headers(200, content_type="text/html; charset=utf-8")
                with open(admin_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "admin.html no encontrado"}).encode())

        elif path == "/admin/api/licenses":
            token = query.get("token", [""])[0]
            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "licenses": db.get("licenses", {})}).encode())

        elif path == "/api-status":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "SubVoz Pro License API Running"}).encode())

        else:
            landing_path = os.path.join(os.path.dirname(__file__), "landing.html")
            if os.path.exists(landing_path):
                self._set_headers(200, content_type="text/html; charset=utf-8")
                with open(landing_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "SubVoz Pro License API Running"}).encode())


def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, LicenseAPIHandler)
    print(f"🚀 Servidor API de Licencias SubVoz Pro ejecutándose en el puerto {PORT}...")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
