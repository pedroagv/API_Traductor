import argparse
import datetime
import hashlib
import json
import os
import secrets

DATA_FILE = os.path.join(os.path.dirname(__file__), "licenses.json")


def load_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"licenses": {}, "updates": {}}


def save_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_key(seats: int = 1, note: str = "") -> str:
    db = load_db()
    raw = secrets.token_hex(6).upper()
    prefix = f"REUNION-{seats}SEATS-" if seats > 1 else "REUNION-PRO-"
    key = f"{prefix}{raw[:4]}-{raw[4:8]}-{raw[8:]}"

    db["licenses"][key] = {
        "max_seats": seats,
        "registered_devices": [],
        "created_at": datetime.datetime.now().isoformat(),
        "note": note,
    }
    save_db(db)
    return key


def list_keys():
    db = load_db()
    licenses = db.get("licenses", {})
    print(f"\n--- LICENCIAS REGISTRADAS EN LA API ({len(licenses)}) ---")
    for key, data in licenses.items():
        used = len(data.get("registered_devices", []))
        max_s = data.get("max_seats", 1)
        note = data.get("note", "")
        print(f"🔑 Clave: {key}")
        print(f"   Asientos usados: {used} / {max_s}")
        print(f"   Nota: {note}")
        for dev in data.get("registered_devices", []):
            print(f"     -> HWID: {dev.get('hw_id')} | MAC: {dev.get('mac')} | PC: {dev.get('hostname')}")
        print("-" * 50)


def main():
    parser = argparse.ArgumentParser(description="Generador de Claves de Licencia Reunion Pro")
    parser.add_argument("--seats", type=int, default=1, help="Número de equipos permitidos por esta clave")
    parser.add_argument("--note", type=str, default="", help="Nombre del cliente o nota informativa")
    parser.add_argument("--list", action="store_true", help="Listar todas las claves y sus equipos registrados")

    args = parser.parse_args()

    if args.list:
        list_keys()
    else:
        new_key = generate_key(seats=args.seats, note=args.note)
        print(f"\n✅ ¡Clave generada con éxito!")
        print(f"   🔑 Clave: {new_key}")
        print(f"   👥 Asientos/Equipos permitidos: {args.seats}")
        print(f"   📝 Nota: {args.note if args.note else 'Sin nota'}\n")


if __name__ == "__main__":
    main()
