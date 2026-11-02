import calendar
from datetime import date
from typing import List, Dict, Tuple
import holidays
from app.schemas import DayConfig, HolidayItem, MonthInfoResponse

SPANISH_MONTHS = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]

SPANISH_WEEKDAYS = [
    "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"
]

SUPPORTED_COUNTRIES = [
    {"code": "AR", "name": "Argentina"},
    {"code": "ES", "name": "España"},
    {"code": "MX", "name": "México"},
    {"code": "CL", "name": "Chile"},
    {"code": "CO", "name": "Colombia"},
    {"code": "UY", "name": "Uruguay"},
    {"code": "PE", "name": "Perú"},
    {"code": "US", "name": "Estados Unidos"}
]

def get_country_holidays_map(year: int, country_code: str = "AR") -> Dict[date, str]:
    """Obtiene un mapa de fecha -> nombre de feriado para un país y año."""
    try:
        country_code = country_code.upper()
        hols = holidays.country_holidays(country_code, years=year)
        return {d: str(name) for d, name in hols.items()}
    except Exception:
        # Fallback si el código de país no es soportado
        return {}

def build_month_days_config(year: int, month: int, country_code: str = "AR") -> Tuple[List[DayConfig], List[HolidayItem]]:
    """Construye la lista de DayConfig para todos los días del mes dado."""
    _, num_days = calendar.monthrange(year, month)
    holidays_map = get_country_holidays_map(year, country_code)
    
    days: List[DayConfig] = []
    month_holidays: List[HolidayItem] = []
    
    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        wday = d.weekday() # 0 = Lunes, 3 = Jueves, 6 = Domingo
        is_thurs = (wday == 3)
        is_wknd = (wday >= 5) # Sábado (5) o Domingo (6)
        
        is_hol = d in holidays_map
        hol_name = holidays_map.get(d)
        
        # Por defecto, los fines de semana o feriados pueden sugerirse como guardia simple (1),
        # pero el usuario o presets pueden convertirlos en guardia doble (2).
        req_shifts = 1
        
        if is_hol:
            month_holidays.append(HolidayItem(
                day=day_num,
                date=d.isoformat(),
                name=hol_name
            ))
            
        days.append(DayConfig(
            day=day_num,
            date=d.isoformat(),
            weekday=wday,
            weekday_name=SPANISH_WEEKDAYS[wday],
            is_weekend=is_wknd,
            is_thursday=is_thurs,
            is_holiday=is_hol,
            holiday_name=hol_name,
            required_shifts=req_shifts
        ))
        
    return days, month_holidays

def get_month_info(year: int, month: int, country_code: str = "AR") -> MonthInfoResponse:
    """Genera la información estructural completa de un mes para la interfaz."""
    days, month_holidays = build_month_days_config(year, month, country_code)
    _, num_days = calendar.monthrange(year, month)
    
    thursdays_count = sum(1 for d in days if d.is_thursday)
    weekend_days_count = sum(1 for d in days if d.is_weekend)
    
    return MonthInfoResponse(
        year=year,
        month=month,
        month_name=SPANISH_MONTHS[month],
        total_days=num_days,
        thursdays_count=thursdays_count,
        weekend_days_count=weekend_days_count,
        holidays=month_holidays,
        days=days
    )
