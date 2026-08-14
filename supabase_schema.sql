-- Execute este script en el Editor SQL de Supabase (https://supabase.com/dashboard)

-- 1. Tabla de Dispositivos (Licencias de Equipos)
CREATE TABLE IF NOT EXISTS public.devices (
    hw_id TEXT PRIMARY KEY,
    plan TEXT DEFAULT 'FREE',
    hostname TEXT,
    note TEXT,
    first_seen TEXT,
    last_seen TEXT,
    activated_at TEXT,
    duration_months INT DEFAULT 0,
    expires_at TEXT
);

-- 2. Tabla de Tickets de Soporte
CREATE TABLE IF NOT EXISTS public.tickets (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    hw_id TEXT,
    mac TEXT,
    hostname TEXT,
    contact_info TEXT,
    license_key TEXT,
    subject TEXT,
    category TEXT,
    message TEXT,
    logs TEXT,
    status TEXT DEFAULT 'Abierto ⏳',
    admin_reply TEXT,
    meeting_url TEXT,
    updated_at TEXT
);

-- 3. Tabla de Configuración de la App y Respaldos
CREATE TABLE IF NOT EXISTS public.app_config (
    key TEXT PRIMARY KEY,
    value JSONB
);

-- Desactivar RLS (Row Level Security) para acceso directo mediante API Key desde el servidor backend
ALTER TABLE public.devices DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.tickets DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_config DISABLE ROW LEVEL SECURITY;
