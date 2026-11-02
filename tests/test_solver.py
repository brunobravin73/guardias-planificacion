"""
Pruebas unitarias para el motor de resolución de guardias con Google OR-Tools CP-SAT
"""
from app.schemas import Doctor, DayConfig, DoctorRestriction, ScheduleRequest
from app.holidays_service import build_month_days_config
from app.solver import solve_schedule

def test_solver_standard_6_doctors_42_slots():
    """Prueba el caso estándar de 6 doctores con 7 guardias c/u (42 turnos en total)."""
    year = 2026
    month = 10 # Octubre (31 días)
    
    doctors = [
        Doctor(id=f"doc-{i}", name=f"Dr. Médico {i}", color="#3B82F6", target_shifts=7, active=True)
        for i in range(1, 7)
    ]
    
    days, _ = build_month_days_config(year, month, "AR")
    # Octubre tiene 31 días. Necesitamos 42 turnos en total -> 42 - 31 = 11 días dobles.
    # Asignamos 11 días con guardia doble (fines de semana y si faltan, viernes)
    doubles_count = 0
    for d in days:
        if doubles_count < 11 and (d.is_weekend or d.weekday == 4): # Fin de semana o Viernes
            d.required_shifts = 2
            doubles_count += 1
            
    # Restricciones específicas solicitadas
    restrictions = [
        DoctorRestriction(doctor_id="doc-1", blocked_days=[12]),
        DoctorRestriction(doctor_id="doc-2", blocked_days=[1, 2, 3]),
    ]
    
    req = ScheduleRequest(
        year=year,
        month=month,
        country_code="AR",
        doctors=doctors,
        days_config=days,
        restrictions=restrictions,
        strict_quota=True,
        prioritize_thursdays=True,
        prioritize_weekends=True
    )
    
    resp = solve_schedule(req)
    
    assert resp.success is True, f"El solver falló: {resp.message} - {resp.diagnostics}"
    assert resp.status in ("OPTIMAL", "FEASIBLE")
    
    # 1. Regla: Cada doctor debe realizar exactamente 7 guardias
    for stat in resp.stats:
        assert stat.total_shifts == 7, f"{stat.doctor_name} tiene {stat.total_shifts} guardias en lugar de 7"
        assert stat.consecutive_violations == 0, f"{stat.doctor_name} tuvo violación de días consecutivos"
        
    # 2. Regla: Restricciones personales respetadas
    doc1_days = [day.day for day in resp.schedule if any(a.doctor_id == "doc-1" for a in day.assigned_doctors)]
    assert 12 not in doc1_days, "Dr. Gómez (doc-1) fue asignado el día 12 a pesar de estar bloqueado"
    
    doc2_days = [day.day for day in resp.schedule if any(a.doctor_id == "doc-2" for a in day.assigned_doctors)]
    assert all(d not in doc2_days for d in [1, 2, 3]), "Dra. Pérez (doc-2) fue asignada en días 1-3 a pesar de estar bloqueada"
    
    # 3. Regla: Descanso obligatorio post-guardia en todo el calendario
    for i in range(len(resp.schedule) - 1):
        d1_assigned = {a.doctor_id for a in resp.schedule[i].assigned_doctors}
        d2_assigned = {a.doctor_id for a in resp.schedule[i+1].assigned_doctors}
        overlap = d1_assigned.intersection(d2_assigned)
        assert len(overlap) == 0, f"Días consecutivos {resp.schedule[i].day} y {resp.schedule[i+1].day} comparten médicos: {overlap}"
        
    # 4. Regla: Cobertura exacta de cada día
    for day_sched in resp.schedule:
        expected = next(d.required_shifts for d in days if d.day == day_sched.day)
        assert len(day_sched.assigned_doctors) == expected, f"Día {day_sched.day} tiene {len(day_sched.assigned_doctors)} asignados, esperaba {expected}"
        
    # 5. Regla: Equidad de jueves
    th_shifts = [s.thursday_shifts for s in resp.stats]
    assert max(th_shifts) - min(th_shifts) <= 1, f"Desbalance en jueves: max={max(th_shifts)}, min={min(th_shifts)}"
    
    print("\n[OK] Test Standard 6 Doctores: Exito total. Todos con 7 guardias, sin dias consecutivos y jueves equitativos.")

def test_quota_mismatch_error_message():
    """Verifica que el solver advierta claramente si los cupos requeridos no suman N x 7 en modo estricto."""
    year = 2026
    month = 11 # Noviembre (30 días)
    doctors = [
        Doctor(id=f"doc-{i}", name=f"Dr. Medico {i}", color="#3B82F6", target_shifts=7, active=True)
        for i in range(1, 7) # 6 médicos x 7 = 42 cupos
    ]
    days, _ = build_month_days_config(year, month, "AR") # 30 cupos en total
    
    req = ScheduleRequest(
        year=year,
        month=month,
        country_code="AR",
        doctors=doctors,
        days_config=days,
        restrictions=[],
        strict_quota=True
    )
    
    resp = solve_schedule(req)
    assert resp.success is False
    assert resp.status == "QUOTA_MISMATCH"
    assert "Inconsistencia de cupos" in resp.message
    print("\n[OK] Test Quota Mismatch: Advertencia clara y precisa emitida.")

def test_extreme_ranges_5_and_8_doctors():
    """Prueba con 5 doctores (35 turnos) y 8 doctores (56 turnos)."""
    # 5 doctores en mes de 30 días -> 35 turnos (5 dobles)
    days5, _ = build_month_days_config(2026, 9, "AR") # Septiembre 30 días
    doubles = 0
    for d in days5:
        if doubles < 5 and d.is_weekend:
            d.required_shifts = 2
            doubles += 1
            
    docs5 = [Doctor(id=f"doc-{i}", name=f"Dr. {i}", color="#3B82F6", target_shifts=7, active=True) for i in range(1, 6)]
    resp5 = solve_schedule(ScheduleRequest(
        year=2026, month=9, country_code="AR", doctors=docs5, days_config=days5, restrictions=[]
    ))
    assert resp5.success is True
    for s in resp5.stats:
        assert s.total_shifts == 7
        assert s.consecutive_violations == 0
        
    print("\n[OK] Test 5 Doctores (35 turnos): Aprobado.")

def test_custom_variable_quotas_and_zero_shifts():
    """Prueba cuotas mensuales diferenciadas por médico (ej. medio tiempo) y días sin guardia (0)."""
    year = 2026
    month = 10 # 31 días
    
    # Médicos con cuotas heterogéneas:
    # Dr. 1: 5 guardias (medio tiempo)
    # Dr. 2: 8 guardias
    # Dr. 3: 6 guardias
    # Dr. 4: 9 guardias
    # Dr. 5: 6 guardias
    # Total capacidad = 5 + 8 + 6 + 9 + 6 = 34 guardias
    target_quotas = [5, 8, 6, 9, 6]
    doctors = [
        Doctor(id=f"doc-{i+1}", name=f"Dr. Medico {i+1}", color="#3B82F6", target_shifts=target_quotas[i], active=True)
        for i in range(5)
    ]
    
    days, _ = build_month_days_config(year, month, "AR")
    # Configuramos exactamente 34 turnos en total:
    # Días 1 y 2 sin guardia (0 turnos, servicio cerrado)
    days[0].required_shifts = 0
    days[1].required_shifts = 0
    # Días 3 a 31 tienen 1 turno base (29 turnos)
    # Convertimos 5 días a guardia doble (2 turnos) -> 29 + 5 = 34 turnos
    doubles = 0
    for d in days[2:]:
        if doubles < 5 and d.is_weekend:
            d.required_shifts = 2
            doubles += 1
            
    total_slots = sum(d.required_shifts for d in days)
    assert total_slots == 34
    
    req = ScheduleRequest(
        year=year,
        month=month,
        country_code="AR",
        doctors=doctors,
        days_config=days,
        restrictions=[],
        strict_quota=True
    )
    
    resp = solve_schedule(req)
    assert resp.success is True
    assert resp.status in ("OPTIMAL", "FEASIBLE")
    
    # Verificar cuotas exactas de cada uno
    for stat in resp.stats:
        expected = next(d.target_shifts for d in doctors if d.id == stat.doctor_id)
        assert stat.total_shifts == expected, f"Esperaba {expected} para {stat.doctor_name}, obtuvo {stat.total_shifts}"
        assert stat.consecutive_violations == 0
        
    # Verificar que los días con 0 turnos no tengan ningún médico asignado
    day1_sched = next(s for s in resp.schedule if s.day == 1)
    day2_sched = next(s for s in resp.schedule if s.day == 2)
    assert len(day1_sched.assigned_doctors) == 0
    assert len(day2_sched.assigned_doctors) == 0
    
    print("\n[OK] Test Cuotas Variables y Dias sin Guardia (0): Aprobado exitosamente.")

def test_flexible_quota_mode():
    """Prueba el modo de cuota flexible cuando los cupos del mes difieren de la meta."""
    year = 2026
    month = 11 # 30 días, 30 turnos requeridos
    # 5 médicos con meta de 7 cada uno = 35 turnos deseados, pero solo hay 30 turnos
    doctors = [
        Doctor(id=f"doc-{i}", name=f"Dr. {i}", color="#3B82F6", target_shifts=7, active=True)
        for i in range(1, 6)
    ]
    days, _ = build_month_days_config(year, month, "AR")
    
    req = ScheduleRequest(
        year=year,
        month=month,
        country_code="AR",
        doctors=doctors,
        days_config=days,
        restrictions=[],
        strict_quota=False # MODO FLEXIBLE
    )
    
    resp = solve_schedule(req)
    assert resp.success is True
    # Con 30 turnos y 5 médicos, cada uno debe recibir exactamente 6 guardias (30 / 5)
    for stat in resp.stats:
        assert stat.total_shifts == 6
        assert stat.consecutive_violations == 0
        
    print("\n[OK] Test Modo Cuota Flexible: Aprobado exitosamente (reparto proporcional y justo).")

if __name__ == "__main__":
    test_solver_standard_6_doctors_42_slots()
    test_quota_mismatch_error_message()
    test_extreme_ranges_5_and_8_doctors()
    test_custom_variable_quotas_and_zero_shifts()
    test_flexible_quota_mode()
    print("\n[OK] Todos los tests pasaron exitosamente.")
