import datetime
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "licenses.json")
TRIAL_DAYS = 60


def load_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("devices", {})
                return data
        except Exception:
            pass
    initial = {
        "admin_config": {
            "user": "laconcha",
            "pass": "quelapario"
        },
        # Cada equipo se registra solo (por su ID de hardware, no por una clave que se
        # pueda copiar/compartir) la primera vez que abre la app, siempre como plan FREE
        # (prueba de 30 días). Un admin lo pasa a plan PAID desde /admin tras validar el pago.
        "devices": {},
        "updates": {
            "latest_version": "1.0.0",
            "download_url": "https://github.com/pedroagv/API_Traductor/releases/latest/download/SubVozPro_Portable.zip",
            "release_notes": "Versión 1.0.0 inicial con soporte multidioma y cambio de modelos.",
        },
    }
    save_db(initial)
    return initial


def evaluate_device(dev: dict) -> dict:
    """Determina si un dispositivo puede ejecutar la app en este momento, según su plan."""
    now = datetime.datetime.now()
    plan = dev.get("plan", "FREE")

    if plan == "PAID":
        expires_at_str = dev.get("expires_at")
        if expires_at_str:
            exp_dt = datetime.datetime.fromisoformat(expires_at_str)
            if now > exp_dt:
                return {
                    "can_run": False, "status": "expired",
                    "message": f"Tu licencia venció el {exp_dt.strftime('%d/%m/%Y')}. Contacta a ventas para renovarla.",
                    "days_remaining": 0,
                }
            return {
                "can_run": True, "status": "active",
                "message": f"Licencia activa hasta el {exp_dt.strftime('%d/%m/%Y')}.",
                "days_remaining": (exp_dt - now).days,
            }
        return {"can_run": True, "status": "active", "message": "Licencia activa (vitalicia).", "days_remaining": 999999}

    # plan FREE: prueba de 30 días contada desde el primer registro en el servidor.
    first_seen_str = dev.get("first_seen") or now.isoformat()
    first_seen = datetime.datetime.fromisoformat(first_seen_str)
    elapsed = (now - first_seen).days
    remaining = max(0, TRIAL_DAYS - elapsed)

    if remaining > 0:
        return {
            "can_run": True, "status": "trial",
            "message": f"Prueba gratuita: {remaining} día(s) restantes.",
            "days_remaining": remaining,
        }

    return {
        "can_run": False, "status": "expired_trial",
        "message": "Tu período de prueba de 30 días terminó. Contacta a ventas para activar tu licencia.",
        "days_remaining": 0,
    }


def save_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_admin_credentials() -> tuple[str, str]:
    db = load_db()
    admin_cfg = db.get("admin_config", {})
    user = admin_cfg.get("user") or os.environ.get("ADMIN_USER", "laconcha")
    password = admin_cfg.get("pass") or os.environ.get("ADMIN_PASS", "quelapario")
    return user, password


def get_admin_token(user: str = None, password: str = None) -> str:
    if not user or not password:
        user, password = get_admin_credentials()
    return hashlib.sha256(f"{user}:{password}:SUBVOZ-ADMIN-SALT".encode()).hexdigest()


def check_auth_token(token: str) -> bool:
    return token and token == get_admin_token()


class LicenseAPIHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_POST(self):
        if self.path == "/register-device":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)

            hw_id = parsed.get("hw_id", [""])[0].strip()
            hostname = parsed.get("hostname", [""])[0].strip()

            if not hw_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "can_run": False, "message": "Falta el ID del equipo."}).encode())
                return

            db = load_db()
            devices = db.setdefault("devices", {})
            now_iso = datetime.datetime.now().isoformat()

            dev = devices.get(hw_id)
            if dev is None:
                dev = {
                    "plan": "FREE",
                    "hostname": hostname,
                    "note": "",
                    "first_seen": now_iso,
                    "last_seen": now_iso,
                    "activated_at": None,
                    "duration_months": 0,
                    "expires_at": None,
                }
                devices[hw_id] = dev
            else:
                dev["last_seen"] = now_iso
                if hostname:
                    dev["hostname"] = hostname
            save_db(db)

            evaluation = evaluate_device(dev)
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "hw_id": hw_id,
                "plan": dev.get("plan", "FREE"),
                "expires_at": dev.get("expires_at"),
                **evaluation,
            }).encode())

        elif self.path == "/admin/api/activate-device":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)

            token = parsed.get("token", [""])[0]
            hw_id = parsed.get("hw_id", [""])[0].strip()
            months = int(parsed.get("months", [1])[0] or 1)
            note = parsed.get("note", [""])[0]

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            if not hw_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "Falta el ID del equipo"}).encode())
                return

            db = load_db()
            devices = db.setdefault("devices", {})
            now = datetime.datetime.now()
            dev = devices.get(hw_id)
            if dev is None:
                dev = {
                    "plan": "FREE", "hostname": "", "note": "",
                    "first_seen": now.isoformat(), "last_seen": now.isoformat(),
                    "activated_at": None, "duration_months": 0, "expires_at": None,
                }
                devices[hw_id] = dev

            dev["plan"] = "PAID"
            dev["activated_at"] = now.isoformat()
            dev["duration_months"] = months
            dev["expires_at"] = (now + datetime.timedelta(days=30 * months)).isoformat()
            if note:
                dev["note"] = note
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "hw_id": hw_id, "expires_at": dev["expires_at"]}).encode())

        elif self.path == "/admin/api/deactivate-device":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            token = parsed.get("token", [""])[0]
            hw_id = parsed.get("hw_id", [""])[0].strip()

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            dev = db.get("devices", {}).get(hw_id)
            if not dev:
                self._set_headers(404)
                self.wfile.write(json.dumps({"success": False, "message": "Dispositivo no encontrado"}).encode())
                return

            dev["plan"] = "FREE"
            dev["activated_at"] = None
            dev["duration_months"] = 0
            dev["expires_at"] = None
            save_db(db)
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "message": "Dispositivo regresado a plan FREE"}).encode())

        elif self.path == "/admin/api/delete-device":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            token = parsed.get("token", [""])[0]
            hw_id = parsed.get("hw_id", [""])[0].strip()

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            if hw_id in db.get("devices", {}):
                del db["devices"][hw_id]
                save_db(db)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": f"Dispositivo {hw_id} eliminado"}).encode())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"success": False, "message": "Dispositivo no encontrado"}).encode())

        elif self.path == "/admin/api/login":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            user = parsed.get("user", [""])[0].strip()
            password = parsed.get("pass", [""])[0].strip()
            valid_user, valid_pass = get_admin_credentials()

            if user == valid_user and password == valid_pass:
                token = get_admin_token(user, password)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "token": token}).encode())
            else:
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "Usuario o clave incorrectos"}).encode())

        elif self.path == "/admin/api/change-credentials":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            token = parsed.get("token", [""])[0]
            new_user = parsed.get("new_user", [""])[0].strip()
            new_pass = parsed.get("new_pass", [""])[0].strip()

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            if not new_user or not new_pass:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "El usuario y contraseña no pueden estar vacíos"}).encode())
                return

            db = load_db()
            db["admin_config"] = {"user": new_user, "pass": new_pass}
            save_db(db)

            new_token = get_admin_token(new_user, new_pass)
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "message": "Credenciales actualizadas exitosamente", "token": new_token}).encode())

        elif self.path == "/submit-ticket":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            
            hw_id = parsed.get("hw_id", [""])[0].strip()
            mac = parsed.get("mac", [""])[0].strip()
            hostname = parsed.get("hostname", [""])[0].strip()
            contact_info = parsed.get("contact_info", [""])[0].strip()
            license_key = parsed.get("license_key", [""])[0].strip().upper()
            subject = parsed.get("subject", ["Soporte Técnico"])[0].strip()
            category = parsed.get("category", ["Soporte Técnico"])[0].strip()
            message = parsed.get("message", [""])[0].strip()
            logs = parsed.get("logs", [""])[0].strip()

            if not message and not subject:
                self._set_headers(400)
                self.wfile.write(json.dumps({"success": False, "message": "El mensaje no puede estar vacío"}).encode())
                return

            db = load_db()
            tickets = db.get("tickets", {})
            
            import random
            ticket_id = f"TCK-{random.randint(1000, 9999)}"
            now_iso = datetime.datetime.now().isoformat()

            ticket_obj = {
                "id": ticket_id,
                "created_at": now_iso,
                "hw_id": hw_id,
                "mac": mac,
                "hostname": hostname,
                "contact_info": contact_info or "Sin contacto especificado",
                "license_key": license_key or "Período de Prueba Gratis",
                "subject": subject,
                "category": category,
                "message": message,
                "logs": logs,
                "status": "Abierto ⏳",
                "admin_reply": "",
                "meeting_url": "",
                "updated_at": now_iso
            }
            tickets[ticket_id] = ticket_obj
            db["tickets"] = tickets
            save_db(db)

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "message": f"¡Ticket {ticket_id} creado con éxito!",
                "ticket_id": ticket_id
            }).encode())

        elif self.path == "/admin/api/reply-ticket":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")
            parsed = urllib.parse.parse_qs(post_body)
            
            token = parsed.get("token", [""])[0]
            ticket_id = parsed.get("ticket_id", [""])[0].strip()
            status = parsed.get("status", ["En Revisión 🛠️"])[0].strip()
            admin_reply = parsed.get("admin_reply", [""])[0].strip()
            meeting_url = parsed.get("meeting_url", [""])[0].strip()

            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            tickets = db.get("tickets", {})
            if ticket_id in tickets:
                tickets[ticket_id]["status"] = status
                tickets[ticket_id]["admin_reply"] = admin_reply
                tickets[ticket_id]["meeting_url"] = meeting_url
                tickets[ticket_id]["updated_at"] = datetime.datetime.now().isoformat()
                save_db(db)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": "Ticket actualizado"}).encode())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"success": False, "message": "Ticket no encontrado"}).encode())

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

        elif path == "/check-tickets":
            mac = query.get("mac", [""])[0].strip()
            hw_id = query.get("hw_id", [""])[0].strip()
            db = load_db()
            tickets = db.get("tickets", {})
            user_tickets = [t for t in tickets.values() if (mac and t.get("mac") == mac) or (hw_id and t.get("hw_id") == hw_id)]
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "tickets": user_tickets}).encode())

        elif path == "/admin/api/devices":
            token = query.get("token", [""])[0]
            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            devices = db.get("devices", {})
            enriched = {}
            for hw_id, dev in devices.items():
                enriched[hw_id] = {**dev, **evaluate_device(dev)}

            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "devices": enriched}).encode())

        elif path == "/admin/api/tickets":
            token = query.get("token", [""])[0]
            if not check_auth_token(token):
                self._set_headers(401)
                self.wfile.write(json.dumps({"success": False, "message": "No autorizado"}).encode())
                return

            db = load_db()
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "tickets": db.get("tickets", {})}).encode())

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
