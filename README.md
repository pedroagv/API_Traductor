# Reunion AI Pro - API de Licenciamiento y Servidor de Actualizaciones

Servidor REST ligero en Python para la gestión de licencias multiusuario, registro de direcciones MAC y verificación de actualizaciones de **Reunion AI Pro**.

---

## 🚀 Cómo Ejecutar el Servidor API

### 1. Iniciar el Servidor API (Puerto 8000 por defecto)
```powershell
python server.py
```

El servidor quedará escuchando en `http://localhost:8000`.

---

## 🔑 Cómo Generar Claves para Clientes

Puedes generar claves monousuario o multiusuario usando la herramienta CLI:

### Generar Licencia Monousuario (1 equipo):
```powershell
python cli_generator.py --seats 1 --note "Venta Cliente Juan Perez"
```

### Generar Licencia Multiusuario (Ej. Empresa con 5 equipos):
```powershell
python cli_generator.py --seats 5 --note "Licencia Corporativa Abogados XYZ"
```

### Listar todas las claves y sus equipos registrados:
```powershell
python cli_generator.py --list
```

---

## 📡 Endpoints de la API

* **`POST /verify-license`**: Recibe `key`, `hw_id`, `mac`, `hostname`. Valida si la clave existe y si aún hay licencias disponibles. Si se aprueba, registra la MAC del equipo y autoriza la ejecución.
* **`GET /check-update`**: Retorna información JSON sobre la última versión disponible del software.
