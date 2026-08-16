import datetime
import hashlib
import json
import os
import random
import sys
import urllib.parse
import urllib.request
from wsgiref.simple_server import make_server

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "licenses.json")
TRIAL_DAYS = 30

# URL pública de esta misma API, para armar enlaces absolutos (ej. el botón "Descargar
# actualización" del cliente) -- Render expone la URL real del servicio en esta variable.
PUBLIC_BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://api-traductor-tq44.onrender.com").rstrip("/")

DISK_DATA_DIR = "/var/data" if os.path.exists("/var/data") else os.path.dirname(__file__)
DOWNLOADS_DIR = os.path.join(DISK_DATA_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ilzwqheusmcqjppjuxac.supabase.co").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_N8cqypOpe_lTtjBI4UrPnA_IVz8Xyzy")


def stream_file_response(start_response, file_path: str, filename: str):
    file_size = os.path.getsize(file_path)
    status_line = "200 OK"
    headers = [
        ("Content-Type", "application/zip"),
        ("Content-Disposition", f'attachment; filename="{filename}"'),
        ("Content-Length", str(file_size)),
        ("Access-Control-Allow-Origin", "*"),
        ("Accept-Ranges", "bytes"),
    ]
    start_response(status_line, headers)

    def file_iterator():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(512 * 1024)
                if not chunk:
                    break
                yield chunk

    return file_iterator()


def supabase_request(endpoint: str, method: str = "GET", payload: dict | list = None, prefer: str = None) -> list | dict | None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{endpoint.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read().decode("utf-8")
            if body:
                return json.loads(body)
            return []
    except Exception as exc:
        print(f"[Supabase API Error] {method} {endpoint}: {exc}")
        return None


def load_db_supabase() -> dict | None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    try:
        dev_rows = supabase_request("devices?select=*")
        tick_rows = supabase_request("tickets?select=*")
        cfg_rows = supabase_request("app_config?select=*")

        if dev_rows is not None and tick_rows is not None:
            devices = {r["hw_id"]: r for r in dev_rows if isinstance(r, dict) and "hw_id" in r}
            tickets = {r["id"]: r for r in tick_rows if isinstance(r, dict) and "id" in r}

            admin_cfg = {"user": os.environ.get("ADMIN_USER", "laconcha"), "pass": os.environ.get("ADMIN_PASS", "quelapario")}
            updates = {
                "latest_version": "1.0.0",
                "download_url": "https://github.com/pedroagv/API_Traductor/releases/latest/download/SubVozPro_Portable.zip",
                "release_notes": "Versión 1.0.0 inicial con soporte multidioma y cambio de modelos.",
            }

            if cfg_rows:
                for r in cfg_rows:
                    if isinstance(r, dict):
                        if r.get("key") == "admin_config" and r.get("value"):
                            admin_cfg = r["value"] if isinstance(r["value"], dict) else json.loads(r["value"])
                        elif r.get("key") == "updates" and r.get("value"):
                            updates = r["value"] if isinstance(r["value"], dict) else json.loads(r["value"])

            return {
                "admin_config": admin_cfg,
                "devices": devices,
                "tickets": tickets,
                "updates": updates,
            }

        # Backup: probar la clave 'licenses_db' en 'app_config'
        if cfg_rows:
            for r in cfg_rows:
                if isinstance(r, dict) and r.get("key") == "licenses_db" and r.get("value"):
                    return r["value"] if isinstance(r["value"], dict) else json.loads(r["value"])

    except Exception as exc:
        print(f"Advertencia cargando desde Supabase: {exc}")

    return None


def save_device_supabase(dev: dict):
    if not SUPABASE_URL or not SUPABASE_KEY or not isinstance(dev, dict):
        return
    try:
        supabase_request("devices", method="POST", payload=dev, prefer="resolution=merge-duplicates")
    except Exception as exc:
        print(f"Error guardando dispositivo en Supabase: {exc}")


def delete_device_supabase(hw_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY or not hw_id:
        return
    try:
        supabase_request(f"devices?hw_id=eq.{urllib.parse.quote(hw_id)}", method="DELETE")
    except Exception as exc:
        print(f"Error eliminando dispositivo en Supabase: {exc}")


def save_ticket_supabase(ticket: dict):
    if not SUPABASE_URL or not SUPABASE_KEY or not isinstance(ticket, dict):
        return
    try:
        supabase_request("tickets", method="POST", payload=ticket, prefer="resolution=merge-duplicates")
    except Exception as exc:
        print(f"Error guardando ticket en Supabase: {exc}")


def save_db_supabase(data: dict):
    if not SUPABASE_URL or not SUPABASE_KEY or not isinstance(data, dict):
        return
    try:
        supabase_request("app_config", method="POST", payload={"key": "licenses_db", "value": data}, prefer="resolution=merge-duplicates")

        devices = data.get("devices", {})
        if isinstance(devices, dict):
            for dev in devices.values():
                if isinstance(dev, dict) and "hw_id" in dev:
                    save_device_supabase(dev)

        tickets = data.get("tickets", {})
        if isinstance(tickets, dict):
            for t in tickets.values():
                if isinstance(t, dict) and "id" in t:
                    save_ticket_supabase(t)

        if "admin_config" in data:
            supabase_request("app_config", method="POST", payload={"key": "admin_config", "value": data["admin_config"]}, prefer="resolution=merge-duplicates")
        if "updates" in data:
            supabase_request("app_config", method="POST", payload={"key": "updates", "value": data["updates"]}, prefer="resolution=merge-duplicates")
    except Exception as exc:
        print(f"Error en save_db_supabase: {exc}")


def init_supabase_check():
    print("=" * 60)
    print("[SUPABASE CHECK] Verificando tablas en la nube Supabase...")
    tables = ["devices", "tickets", "app_config"]
    missing = []
    for t in tables:
        res = supabase_request(f"{t}?select=*&limit=1")
        if res is not None:
            print(f"  [OK] Tabla '{t}' detectada y lista.")
        else:
            missing.append(t)
            print(f"  [MISSING] Tabla '{t}' NO EXISTE en el esquema.")

    if missing:
        print("[SUPABASE WARN] Las siguientes tablas faltan en Supabase:")
        for m in missing:
            print(f"   - {m}")
        print("[INSTRUCCION] Ejecute 'supabase_schema.sql' en el SQL Editor de Supabase.")
        print("[FALLBACK] El servidor operara en modo seguro usando 'licenses.json' local.")
    else:
        print("[SUPABASE OK] Sincronizacion en la nube 100% activa y operativa.")
    print("=" * 60)

try:
    init_supabase_check()
except Exception as exc:
    print(f"Error durante diagnóstico inicial de Supabase: {exc}")


def load_db() -> dict:
    sb_data = load_db_supabase()
    if sb_data is not None:
        return sb_data

    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("devices", {})
                data.setdefault("tickets", {})
                return data
        except Exception:
            pass

    initial = {
        "admin_config": {
            "user": os.environ.get("ADMIN_USER", "laconcha"),
            "pass": os.environ.get("ADMIN_PASS", "quelapario")
        },
        "devices": {},
        "tickets": {},
        "updates": {
            "latest_version": "1.0.0",
            "download_url": "https://github.com/pedroagv/API_Traductor/releases/latest/download/SubVozPro_Portable.zip",
            "release_notes": "Versión 1.0.0 inicial con soporte multidioma y cambio de modelos.",
        },
    }
    save_db(initial)
    return initial


def save_db(data: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    save_db_supabase(data)


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


def evaluate_device(dev: dict) -> dict:
    if not isinstance(dev, dict):
        return {"can_run": True, "is_trial": True, "days_left": TRIAL_DAYS, "status_msg": "Período de prueba activo"}

    plan = dev.get("plan", "FREE")
    expires_at_str = dev.get("expires_at")
    first_seen_str = dev.get("first_seen")
    now = datetime.datetime.now()

    if plan == "PAID":
        if expires_at_str:
            try:
                exp_dt = datetime.datetime.fromisoformat(expires_at_str)
                if now < exp_dt:
                    days_remaining = (exp_dt - now).days
                    return {
                        "can_run": True,
                        "is_trial": False,
                        "days_left": max(0, days_remaining),
                        "status_msg": f"Licencia Activa ({days_remaining} días restantes)",
                    }
                else:
                    return {
                        "can_run": False,
                        "is_trial": False,
                        "days_left": 0,
                        "status_msg": "Licencia Expirada",
                    }
            except Exception:
                pass
        return {
            "can_run": True,
            "is_trial": False,
            "days_left": 365,
            "status_msg": "Licencia Activa (Ilimitada)",
        }

    # Plan FREE (Período de Prueba)
    first_seen = now
    if first_seen_str:
        try:
            first_seen = datetime.datetime.fromisoformat(first_seen_str)
        except Exception:
            pass

    days_used = (now - first_seen).days
    days_left = max(0, TRIAL_DAYS - days_used)
    can_run = days_used < TRIAL_DAYS

    if can_run:
        msg = f"Período de prueba gratis ({days_left} días restantes)"
    else:
        msg = "Período de prueba gratis de 30 días finalizado. Requiere licencia."

    return {
        "can_run": can_run,
        "is_trial": True,
        "days_left": days_left,
        "status_msg": msg,
    }


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query_str = environ.get("QUERY_STRING", "")
    query = urllib.parse.parse_qs(query_str)

    def response(status_code: int, body: bytes | str | dict | list, content_type: str = "application/json", headers_extra: list = None):
        status_messages = {
            200: "200 OK",
            302: "302 Found",
            400: "400 Bad Request",
            401: "401 Unauthorized",
            404: "404 Not Found",
            405: "405 Method Not Allowed",
            500: "500 Internal Server Error",
        }
        status_line = status_messages.get(status_code, f"{status_code} Status")
        headers = [
            ("Content-Type", content_type),
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Authorization"),
        ]
        if headers_extra:
            headers.extend(headers_extra)

        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body

        headers.append(("Content-Length", str(len(body_bytes))))
        start_response(status_line, headers)
        return [body_bytes]

    if method == "OPTIONS":
        return response(200, b"", "text/plain")

    # Endpoints binarios: leen el cuerpo (ZIP) directamente de wsgi.input, no deben
    # pasar por el parseo genérico de abajo, que decodifica todo como texto UTF-8
    # y dejaría el stream ya consumido (y los bytes corruptos) para su propio manejo.
    BINARY_UPLOAD_PATHS = ("/admin/api/upload-file", "/admin/api/upload-chunk")

    # Read body for POST requests
    post_params = {}
    if method == "POST" and path not in BINARY_UPLOAD_PATHS:
        content_len = int(environ.get("CONTENT_LENGTH", 0) or 0)
        if content_len > 0 and "wsgi.input" in environ:
            raw_body = environ["wsgi.input"].read(content_len).decode("utf-8", errors="replace")
            content_type = environ.get("CONTENT_TYPE", "")
            if "application/json" in content_type:
                try:
                    post_params = json.loads(raw_body)
                except Exception:
                    post_params = {}
            else:
                parsed = urllib.parse.parse_qs(raw_body)
                post_params = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    def get_param(name: str, default: str = "") -> str:
        val = post_params.get(name) or query.get(name, [""])[0]
        if isinstance(val, list):
            return val[0].strip() if val else default
        return str(val).strip()

    # --- POST Endpoints ---
    if method == "POST":
        if path == "/register-device":
            hw_id = get_param("hw_id")
            hostname = get_param("hostname")

            if not hw_id:
                return response(400, {"success": False, "can_run": False, "message": "Falta el ID del equipo."})

            db = load_db()
            devices = db.setdefault("devices", {})
            now_iso = datetime.datetime.now().isoformat()

            dev = devices.get(hw_id)
            if dev is None:
                dev = {
                    "hw_id": hw_id,
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
                dev["hw_id"] = hw_id
                dev["last_seen"] = now_iso
                if hostname:
                    dev["hostname"] = hostname
            save_db(db)

            evaluation = evaluate_device(dev)
            return response(200, {
                "success": True,
                "hw_id": hw_id,
                "plan": dev.get("plan", "FREE"),
                "expires_at": dev.get("expires_at"),
                **evaluation,
            })

        elif path == "/admin/api/activate-device":
            token = get_param("token")
            hw_id = get_param("hw_id")
            months_raw = get_param("months", "1")
            months = int(months_raw) if months_raw.isdigit() else 1
            note = get_param("note")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            if not hw_id:
                return response(400, {"success": False, "message": "Falta el ID del equipo"})

            db = load_db()
            devices = db.setdefault("devices", {})
            now = datetime.datetime.now()
            dev = devices.get(hw_id)
            if dev is None:
                dev = {
                    "hw_id": hw_id,
                    "plan": "FREE", "hostname": "", "note": "",
                    "first_seen": now.isoformat(), "last_seen": now.isoformat(),
                    "activated_at": None, "duration_months": 0, "expires_at": None,
                }
                devices[hw_id] = dev

            dev["hw_id"] = hw_id

            dev["plan"] = "PAID"
            dev["activated_at"] = now.isoformat()
            dev["duration_months"] = months
            dev["expires_at"] = (now + datetime.timedelta(days=30 * months)).isoformat()
            if note:
                dev["note"] = note
            save_db(db)

            return response(200, {"success": True, "hw_id": hw_id, "expires_at": dev["expires_at"]})

        elif path == "/admin/api/deactivate-device":
            token = get_param("token")
            hw_id = get_param("hw_id")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            dev = db.get("devices", {}).get(hw_id)
            if not dev:
                return response(404, {"success": False, "message": "Dispositivo no encontrado"})

            dev["plan"] = "FREE"
            dev["activated_at"] = None
            dev["duration_months"] = 0
            dev["expires_at"] = None
            save_db(db)
            return response(200, {"success": True, "message": "Dispositivo regresado a plan FREE"})

        elif path == "/admin/api/delete-device":
            token = get_param("token")
            hw_id = get_param("hw_id")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            if hw_id in db.get("devices", {}):
                del db["devices"][hw_id]
                delete_device_supabase(hw_id)
                save_db(db)
                return response(200, {"success": True, "message": f"Dispositivo {hw_id} eliminado"})
            else:
                return response(404, {"success": False, "message": "Dispositivo no encontrado"})

        elif path == "/admin/api/login":
            user = get_param("user")
            password = get_param("pass")
            valid_user, valid_pass = get_admin_credentials()

            if user == valid_user and password == valid_pass:
                token = get_admin_token(user, password)
                return response(200, {"success": True, "token": token})
            else:
                return response(401, {"success": False, "message": "Usuario o clave incorrectos"})

        elif path == "/admin/api/change-credentials":
            token = get_param("token")
            new_user = get_param("new_user")
            new_pass = get_param("new_pass")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            if not new_user or not new_pass:
                return response(400, {"success": False, "message": "El usuario y contraseña no pueden estar vacíos"})

            db = load_db()
            db["admin_config"] = {"user": new_user, "pass": new_pass}
            save_db(db)

            new_token = get_admin_token(new_user, new_pass)
            return response(200, {"success": True, "message": "Credenciales actualizadas exitosamente", "token": new_token})

        elif path == "/submit-ticket":
            hw_id = get_param("hw_id")
            mac = get_param("mac")
            hostname = get_param("hostname")
            contact_info = get_param("contact_info")
            license_key = get_param("license_key").upper()
            subject = get_param("subject", "Soporte Técnico")
            category = get_param("category", "Soporte Técnico")
            message = get_param("message")
            logs = get_param("logs")

            if not message and not subject:
                return response(400, {"success": False, "message": "El mensaje no puede estar vacío"})

            db = load_db()
            tickets = db.setdefault("tickets", {})
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
            save_db(db)

            return response(200, {
                "success": True,
                "message": f"¡Ticket {ticket_id} creado con éxito!",
                "ticket_id": ticket_id
            })

        elif path == "/admin/api/reply-ticket":
            token = get_param("token")
            ticket_id = get_param("ticket_id")
            status = get_param("status", "En Revisión 🛠️")
            admin_reply = get_param("admin_reply")
            meeting_url = get_param("meeting_url")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            tickets = db.get("tickets", {})
            if ticket_id in tickets:
                tickets[ticket_id]["status"] = status
                tickets[ticket_id]["admin_reply"] = admin_reply
                tickets[ticket_id]["meeting_url"] = meeting_url
                tickets[ticket_id]["updated_at"] = datetime.datetime.now().isoformat()
                save_db(db)
                return response(200, {"success": True, "message": "Ticket actualizado"})
            else:
                return response(404, {"success": False, "message": "Ticket no encontrado"})

        elif path == "/admin/api/download-url-to-disk":
            token = get_param("token")
            file_url = get_param("url")
            filename = get_param("filename", "SubVozPro_Internal.zip")

            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            if not file_url:
                return response(400, {"success": False, "message": "Falta la URL del archivo"})

            dest_path = os.path.join(DOWNLOADS_DIR, filename)

            def _bg_download():
                try:
                    print(f"[DISK FETCH] Descargando {filename} desde {file_url} hacia {dest_path}...")
                    req = urllib.request.Request(file_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req) as resp, open(dest_path + ".tmp", "wb") as f:
                        while True:
                            chunk = resp.read(512 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    os.rename(dest_path + ".tmp", dest_path)
                    print(f"[DISK FETCH SUCCESS] Archivo '{filename}' guardado exitosamente en {dest_path}")
                except Exception as exc:
                    print(f"[DISK FETCH ERROR] {exc}")

            import threading
            threading.Thread(target=_bg_download, daemon=True).start()
            return response(200, {"success": True, "message": f"Descarga iniciada para '{filename}'. Estará disponible en minutos en el disco."})

        elif path == "/admin/api/upload-file":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            filename = get_param("filename", "SubVozPro_Internal.zip")
            dest_path = os.path.join(DOWNLOADS_DIR, filename)

            content_length = int(environ.get("CONTENT_LENGTH", 0))
            wsgi_input = environ.get("wsgi.input")

            print(f"[HTTP UPLOAD] Recibiendo {filename} ({content_length / (1024*1024):.2f} MB) via HTTP stream...")

            temp_path = dest_path + ".tmp"
            written = 0
            with open(temp_path, "wb") as f:
                remaining = content_length
                chunk_size = 512 * 1024
                while remaining > 0:
                    to_read = min(remaining, chunk_size)
                    chunk = wsgi_input.read(to_read)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)

            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            os.rename(temp_path, dest_path)

            print(f"[HTTP UPLOAD SUCCESS] {filename} guardado exitosamente ({written / (1024*1024):.2f} MB)")
            return response(200, {"success": True, "message": f"Archivo '{filename}' subido y guardado exitosamente en disco persistente."})

        elif path == "/admin/api/upload-chunk":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            filename = get_param("filename", "SubVozPro_Internal.zip")
            chunk_idx = int(get_param("chunk_index", "0"))
            total_chunks = int(get_param("total_chunks", "1"))
            dest_path = os.path.join(DOWNLOADS_DIR, filename)
            temp_path = dest_path + ".tmp"

            content_length = int(environ.get("CONTENT_LENGTH", 0))
            wsgi_input = environ.get("wsgi.input")

            if chunk_idx == 0 and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            written = 0
            mode = "wb" if chunk_idx == 0 else "ab"
            with open(temp_path, mode) as f:
                remaining = content_length
                chunk_size = 512 * 1024
                while remaining > 0:
                    to_read = min(remaining, chunk_size)
                    chunk_data = wsgi_input.read(to_read)
                    if not chunk_data:
                        break
                    f.write(chunk_data)
                    written += len(chunk_data)
                    remaining -= len(chunk_data)

            print(f"[CHUNK {chunk_idx+1}/{total_chunks}] Recibidos {written/(1024*1024):.1f} MB para {filename}")

            if chunk_idx + 1 == total_chunks:
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                os.rename(temp_path, dest_path)
                final_mb = os.path.getsize(dest_path) / (1024 * 1024)
                print(f"[CHUNK COMPLETE] {filename} ensamblado exitosamente en disco persistente ({final_mb:.2f} MB)")
                return response(200, {"success": True, "completed": True, "message": f"Archivo '{filename}' ensamblado exitosamente en disco ({final_mb:.2f} MB)"})

            return response(200, {"success": True, "completed": False, "chunk_index": chunk_idx})

        elif path in ("/admin/api/delete-file", "/admin/api/delete-disk-file"):
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            filename = get_param("filename", "SubVozPro_Internal.zip")
            dest_path = os.path.join(DOWNLOADS_DIR, filename)

            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                    return response(200, {"success": True, "message": f"Archivo '{filename}' borrado exitosamente del disco persistente de Render."})
                except Exception as exc:
                    return response(500, {"success": False, "message": f"Error al borrar archivo: {exc}"})
            else:
                return response(404, {"success": False, "message": f"Archivo '{filename}' no existe en el disco."})

        elif path == "/admin/api/set-update-version":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            version = get_param("version")
            notes = get_param("notes", "")

            if not version:
                return response(400, {"success": False, "message": "Falta el número de versión (ej. 1.1.0)"})

            db = load_db()
            updates = db.setdefault("updates", {})
            updates["latest_version"] = version
            updates["release_notes"] = notes
            updates["download_url"] = f"{PUBLIC_BASE_URL}/download"
            save_db(db)

            return response(200, {
                "success": True,
                "message": f"Versión publicada: v{version}. Los clientes que abran la app verán el aviso de actualización.",
            })

        else:
            return response(404, {"error": "Endpoint no encontrado"})

    # --- GET Endpoints ---
    if method == "GET":
        if path in ("/check-update", "/updates"):
            db = load_db()
            updates = db.get("updates", {})
            return response(200, {
                "tag_name": updates.get("latest_version", "1.0.0"),
                # Debe ser absoluta: el cliente la abre directo con el navegador del sistema
                # (QDesktopServices / webbrowser), y una ruta relativa como "/download" ahí
                # no resuelve a nada -- intenta abrirla como archivo local y falla en silencio.
                "html_url": updates.get("download_url") or f"{PUBLIC_BASE_URL}/download",
                "notes": updates.get("release_notes", ""),
            })

        elif path in ("/download", "/download/", "/ReunionPro_Portable.zip", "/SubVozPro_Portable.zip") or path.startswith("/downloads/"):
            fname = "SubVozPro_Portable.zip"
            if path.startswith("/downloads/"):
                fname = os.path.basename(path)

            repo_file = os.path.join(os.path.dirname(__file__), "downloads", fname)
            disk_file = os.path.join(DOWNLOADS_DIR, fname)

            target_file = None
            if os.path.exists(repo_file):
                target_file = repo_file
            elif os.path.exists(disk_file):
                target_file = disk_file

            if target_file:
                sz_mb = os.path.getsize(target_file) / (1024 * 1024)
                print(f"[SERVE FLACO] Sirviendo {fname} ({sz_mb:.2f} MB) directamente desde {target_file}")
                return stream_file_response(start_response, target_file, fname)

            target_url = "https://raw.githubusercontent.com/pedroagv/API_Traductor/main/downloads/SubVozPro_Portable.zip"
            return response(302, b"", "text/html", [("Location", target_url)])

        elif path in ("/download-internal", "/download-internal/", "/SubVozPro_Internal.zip"):
            local_file = os.path.join(DOWNLOADS_DIR, "SubVozPro_Internal.zip")
            if os.path.exists(local_file):
                print(f"[DISK SERVE] Sirviendo SubVozPro_Internal.zip desde disco persistente ({os.path.getsize(local_file)/(1024*1024):.1f} MB)")
                return stream_file_response(start_response, local_file, "SubVozPro_Internal.zip")

            target_url = "https://github.com/pedroagv/API_Traductor/releases/download/SubVozPro/SubVozPro_Internal.zip"
            return response(302, b"", "text/html", [("Location", target_url)])

        elif path == "/admin/api/update-info":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            updates = db.get("updates", {})
            return response(200, {
                "success": True,
                "latest_version": updates.get("latest_version", "1.0.0"),
                "release_notes": updates.get("release_notes", ""),
            })

        elif path == "/admin/api/disk-files":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            files_list = []
            if os.path.exists(DOWNLOADS_DIR):
                for fn in os.listdir(DOWNLOADS_DIR):
                    fp = os.path.join(DOWNLOADS_DIR, fn)
                    if os.path.isfile(fp):
                        sz_mb = os.path.getsize(fp) / (1024 * 1024)
                        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
                        files_list.append({
                            "name": fn,
                            "size_mb": round(sz_mb, 2),
                            "size_gb": round(sz_mb / 1024, 2),
                            "modified": mtime,
                            "url": f"/downloads/{fn}"
                        })
            return response(200, {"success": True, "disk_dir": DOWNLOADS_DIR, "files": files_list})

        elif path in ("/admin/api/delete-file", "/admin/api/delete-disk-file"):
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            filename = get_param("filename", "SubVozPro_Internal.zip")
            dest_path = os.path.join(DOWNLOADS_DIR, filename)

            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                    return response(200, {"success": True, "message": f"Archivo '{filename}' borrado exitosamente del disco persistente de Render."})
                except Exception as exc:
                    return response(500, {"success": False, "message": f"Error al borrar archivo: {exc}"})
            else:
                return response(404, {"success": False, "message": f"Archivo '{filename}' no existe en el disco."})

        elif path in ("/admin", "/admin/"):
            admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
            if os.path.exists(admin_path):
                with open(admin_path, "rb") as f:
                    return response(200, f.read(), "text/html; charset=utf-8")
            else:
                return response(404, {"error": "admin.html no encontrado"})

        elif path == "/check-tickets":
            mac = get_param("mac")
            hw_id = get_param("hw_id")
            db = load_db()
            tickets = db.get("tickets", {})
            user_tickets = [t for t in tickets.values() if (mac and t.get("mac") == mac) or (hw_id and t.get("hw_id") == hw_id)]
            return response(200, {"success": True, "tickets": user_tickets})

        elif path == "/admin/api/devices":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            devices = db.get("devices", {})
            enriched = {}
            for hw_id, dev in devices.items():
                enriched[hw_id] = {**dev, **evaluate_device(dev)}

            return response(200, {"success": True, "devices": enriched})

        elif path == "/admin/api/tickets":
            token = get_param("token")
            if not check_auth_token(token):
                return response(401, {"success": False, "message": "No autorizado"})

            db = load_db()
            return response(200, {"success": True, "tickets": db.get("tickets", {})})

        elif path == "/api-status":
            return response(200, {"status": "SubVoz Pro License API Running"})

        else:
            landing_path = os.path.join(os.path.dirname(__file__), "landing.html")
            if os.path.exists(landing_path):
                with open(landing_path, "rb") as f:
                    return response(200, f.read(), "text/html; charset=utf-8")
            else:
                return response(200, {"status": "SubVoz Pro License API Running"})

    return response(405, {"error": "Método no permitido"})


if __name__ == "__main__":
    print(f"🚀 Servidor API de Licencias SubVoz Pro ejecutándose en el puerto {PORT} (WSGI)...")
    httpd = make_server("", PORT, app)
    httpd.serve_forever()
