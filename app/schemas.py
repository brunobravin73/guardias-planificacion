from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Doctor(BaseModel):
    id: str = Field(..., description="Identificador único del médico")
    name: str = Field(..., description="Nombre y apellido del médico")
    color: Optional[str] = Field(default="#3B82F6", description="Color representativo en la UI")
    active: bool = Field(default=True, description="Si el médico participa en la distribución")
    target_shifts: int = Field(default=7, ge=0, le=31, description="Objetivo de guardias en el mes (personalizable)")

class DayConfig(BaseModel):
    day: int = Field(..., ge=1, le=31, description="Día del mes (1-31)")
    date: str = Field(..., description="Fecha en formato ISO YYYY-MM-DD")
    weekday: int = Field(..., ge=0, le=6, description="Día de semana (0=Lunes, 3=Jueves, 6=Domingo)")
    weekday_name: str = Field(..., description="Nombre del día en español")
    is_weekend: bool = Field(default=False, description="Es sábado o domingo")
    is_thursday: bool = Field(default=False, description="Es día jueves")
    is_holiday: bool = Field(default=False, description="Es día festivo")
    holiday_name: Optional[str] = Field(default=None, description="Nombre del festivo")
    required_shifts: int = Field(default=1, ge=0, le=4, description="Número de personas de guardia (0 a 4)")

class DoctorRestriction(BaseModel):
    doctor_id: str
    blocked_days: List[int] = Field(default_factory=list, description="Lista de días del mes en que no puede hacer guardia")

class ScheduleRequest(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    country_code: str = Field(default="AR", description="Código de país para feriados (AR, ES, MX, etc.)")
    doctors: List[Doctor] = Field(..., min_length=1, description="Lista de médicos participantes")
    days_config: List[DayConfig] = Field(..., description="Configuración de cada día del mes")
    restrictions: List[DoctorRestriction] = Field(default_factory=list, description="Días bloqueados por médico")
    strict_quota: bool = Field(default=True, description="Exigir exactamente target_shifts (7) por médico")
    avoid_three_in_five_days: bool = Field(default=True, description="Evitar asignar 3 o más guardias en un lapso de 5 días corridos al mismo médico")
    prioritize_thursdays: bool = Field(default=True, description="Optimizar distribución equitativa de jueves")
    prioritize_weekends: bool = Field(default=True, description="Optimizar distribución equitativa de fines de semana")
    max_solve_time_seconds: int = Field(default=15, ge=1, le=60)

class ShiftAssignment(BaseModel):
    doctor_id: str
    doctor_name: str
    doctor_color: str
    slot_index: int = Field(default=1, description="1 para primer turno, 2 para guardia doble")

class DaySchedule(BaseModel):
    day: int
    date: str
    weekday_name: str
    is_thursday: bool
    is_weekend: bool
    is_holiday: bool
    holiday_name: Optional[str] = None
    required_shifts: int
    assigned_doctors: List[ShiftAssignment] = Field(default_factory=list)

class DoctorStats(BaseModel):
    doctor_id: str
    doctor_name: str
    doctor_color: str
    total_shifts: int
    target_shifts: int
    thursday_shifts: int
    weekend_shifts: int
    holiday_shifts: int
    consecutive_violations: int = 0
    three_in_five_violations: int = 0
    blocked_days_count: int = 0

class ScheduleResponse(BaseModel):
    success: bool
    status: str
    message: str
    diagnostics: Optional[List[str]] = None
    schedule: List[DaySchedule] = Field(default_factory=list)
    stats: List[DoctorStats] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)

class HolidayItem(BaseModel):
    day: int
    date: str
    name: str

class MonthInfoResponse(BaseModel):
    year: int
    month: int
    month_name: str
    total_days: int
    thursdays_count: int
    weekend_days_count: int
    holidays: List[HolidayItem]
    days: List[DayConfig]
