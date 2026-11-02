from datetime import date
from typing import List
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import os

try:
    from dotenv import load_dotenv
    load_dotenv(".env.local")
    load_dotenv(".env")
except ImportError:
    pass

from app.schemas import (
    MonthInfoResponse, ScheduleRequest, ScheduleResponse, Doctor, DayConfig, DoctorRestriction
)
from app.holidays_service import (
    get_month_info, SUPPORTED_COUNTRIES, build_month_days_config
)
from app.solver import solve_schedule

app = FastAPI(
    title="Planificador Inteligente de Guardias Médicas",
    description="API para distribución mensual, equitativa y automatizada de guardias médicas con Google OR-Tools",
    version="2.0.0"
)

# Permitir CORS para desarrollo o consumo externo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directorio de estáticos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Planificador de Guardias Médicas"}

@app.get("/api/public-config")
def get_public_config():
    """
    Expone únicamente la URL y clave publicable (publishable/anon) de Supabase
    para que el cliente web gestione sesiones de usuario y persistencia protegida por RLS.
    Nunca exponer claves secretas o service_role aquí.
    """
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = (
        os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )
    return {
        "supabase_enabled": bool(supabase_url and supabase_key),
        "supabase_url": supabase_url,
        "supabase_key": supabase_key,
    }

@app.get("/api/countries")
def get_countries():
    """Retorna la lista de países soportados para detección automática de feriados."""
    return SUPPORTED_COUNTRIES

@app.get("/api/month-info", response_model=MonthInfoResponse)
def get_month(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    country_code: str = Query("AR", min_length=2, max_length=2)
):
    """Obtiene la estructura del mes, días de la semana y feriados oficiales detectados."""
    try:
        return get_month_info(year, month, country_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/solve", response_model=ScheduleResponse)
def solve(request: ScheduleRequest):
    """Ejecuta el motor de optimización OR-Tools CP-SAT para generar el rol de guardias."""
    try:
        response = solve_schedule(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el optimizador: {str(e)}")

@app.get("/api/demo-data")
def get_demo_data(country_code: str = "AR"):
    """
    Proporciona un conjunto de datos inicial listo para usar con 6 médicos,
    configuración de mes actual/próximo y balance de cupos 6 x 7 = 42 turnos.
    """
    today = date.today()
    target_year = today.year
    target_month = today.month
    
    # 6 médicos de ejemplo con colores distintivos
    sample_doctors = [
        Doctor(id="doc-1", name="Dr. Gómez (Cirugía)", color="#3B82F6", target_shifts=7, active=True),
        Doctor(id="doc-2", name="Dra. Pérez (Clínica)", color="#10B981", target_shifts=7, active=True),
        Doctor(id="doc-3", name="Dr. Rodríguez (Pediatría)", color="#F59E0B", target_shifts=7, active=True),
        Doctor(id="doc-4", name="Dra. Martínez (UTI)", color="#EC4899", target_shifts=7, active=True),
        Doctor(id="doc-5", name="Dr. López (Traumatología)", color="#8B5CF6", target_shifts=7, active=True),
        Doctor(id="doc-6", name="Dra. Fernández (Cardiología)", color="#06B6D4", target_shifts=7, active=True),
    ]
    
    # Días del mes
    days, _ = build_month_days_config(target_year, target_month, country_code)
    
    # Necesitamos 6 * 7 = 42 turnos en total.
    # Días totales del mes: len(days) (ej. 30 o 31).
    # Turnos base = len(days). Turnos dobles necesarios = 42 - len(days).
    num_days = len(days)
    needed_doubles = max(0, 42 - num_days)
    
    # Asignar guardia doble primero a fines de semana y luego a feriados/jueves hasta llegar a needed_doubles
    doubles_assigned = 0
    # 1. Fines de semana
    for d in days:
        if doubles_assigned < needed_doubles and d.is_weekend:
            d.required_shifts = 2
            doubles_assigned += 1
            
    # 2. Si aún faltan, feriados o viernes
    if doubles_assigned < needed_doubles:
        for d in days:
            if doubles_assigned < needed_doubles and d.required_shifts == 1 and (d.is_holiday or d.weekday == 4): # Viernes
                d.required_shifts = 2
                doubles_assigned += 1
                
    # Restricciones de ejemplo solicitadas en el prompt:
    # "El Dr. Gómez no puede hacer guardia el 12 por congreso"
    # "La Dra. Pérez pide libre del 1 al 3"
    sample_restrictions = [
        DoctorRestriction(doctor_id="doc-1", blocked_days=[12] if 12 <= num_days else [5]),
        DoctorRestriction(doctor_id="doc-2", blocked_days=[1, 2, 3] if 3 <= num_days else [1]),
    ]
    
    return {
        "year": target_year,
        "month": target_month,
        "country_code": country_code,
        "doctors": sample_doctors,
        "days_config": days,
        "restrictions": sample_restrictions,
        "strict_quota": True,
        "avoid_three_in_five_days": True,
        "prioritize_thursdays": True,
        "prioritize_weekends": True
    }

@app.get("/auth/confirm", include_in_schema=False)
def auth_confirm_redirect(request: Request):
    """Redirige enlaces de verificación por correo (PKCE/token_hash) a la aplicación principal."""
    query = request.url.query
    target = f"/?{query}" if query else "/"
    return RedirectResponse(url=target, status_code=307)

# Servir archivos estáticos si existe la carpeta static
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
