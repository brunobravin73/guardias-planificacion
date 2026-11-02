import time
from typing import List, Dict, Tuple, Optional, Any
from ortools.sat.python import cp_model

from app.schemas import (
    Doctor, DayConfig, DoctorRestriction, ScheduleRequest,
    ScheduleResponse, DaySchedule, ShiftAssignment, DoctorStats
)

def solve_schedule(request: ScheduleRequest) -> ScheduleResponse:
    """
    Resuelve el problema de programación de guardias médicas usando Google OR-Tools CP-SAT.
    
    Reglas y restricciones:
    1. Participantes activos (5 a 12).
    2. Carga de guardias: exactamente 7 por participante (o configurable por doctor).
    3. Cobertura diaria: 1 o 2 médicos por día según DayConfig.required_shifts.
    4. Descanso obligatorio post-guardia: x[p, d] + x[p, d+1] <= 1.
    5. Restricciones personales: x[p, d] == 0 si el día está bloqueado.
    6. Equidad de jueves: distribución equilibrada de los turnos de jueves entre los participantes.
    7. Equidad de fines de semana y feriados: reparto justo de turnos no laborables.
    """
    active_doctors = [doc for doc in request.doctors if doc.active]
    num_doctors = len(active_doctors)
    days_config = sorted(request.days_config, key=lambda d: d.day)
    num_days = len(days_config)
    
    # Validaciones iniciales
    if num_doctors < 1:
        return ScheduleResponse(
            success=False,
            status="INVALID_INPUT",
            message="Debe haber al menos un médico activo en el sistema.",
            diagnostics=["No se encontraron médicos activos."]
        )
        
    total_slots_needed = sum(d.required_shifts for d in days_config)
    total_quota_target = sum(d.target_shifts for d in active_doctors)
    
    # Mapa de restricciones
    doctor_blocked_days: Dict[str, set] = {doc.id: set() for doc in active_doctors}
    for r in request.restrictions:
        if r.doctor_id in doctor_blocked_days:
            doctor_blocked_days[r.doctor_id].update(r.blocked_days)
            
    # Chequeo de consistencia aritmética para cuota estricta
    diagnostics: List[str] = []
    
    if request.strict_quota and total_slots_needed != total_quota_target:
        diff = total_slots_needed - total_quota_target
        if diff > 0:
            msg = (
                f"Inconsistencia de cupos: El mes requiere {total_slots_needed} turnos "
                f"({sum(1 for d in days_config if d.required_shifts == 2)} días con guardia doble), "
                f"pero la suma de las cuotas de los {num_doctors} médicos activos es {total_quota_target} "
                f"({total_quota_target // num_doctors} por persona). "
                f"Sobran {diff} cupos de guardia. Reduzca {diff} guardias dobles o desactive la cuota estricta."
            )
        else:
            faltan = abs(diff)
            msg = (
                f"Inconsistencia de cupos: El mes requiere {total_slots_needed} turnos, "
                f"pero para cumplir la cuota estricta de {total_quota_target} guardias "
                f"({num_doctors} médicos con promedio de {round(total_quota_target / num_doctors, 1)} guardias), faltan {faltan} turnos. "
                f"Active {faltan} días con guardia doble (o ajuste las cuotas/active el modo flexible) "
                f"para que la capacidad total sea exactamente igual a {total_quota_target}."
            )
        return ScheduleResponse(
            success=False,
            status="QUOTA_MISMATCH",
            message=msg,
            diagnostics=[
                f"Total turnos requeridos por configuración de días: {total_slots_needed}",
                f"Total turnos meta del personal activo: {total_quota_target}",
                f"Diferencia: {diff} turnos."
            ]
        )

    # Chequeo previo de disponibilidad individual
    for doc in active_doctors:
        blocked = doctor_blocked_days[doc.id]
        available_days = num_days - len(blocked)
        if available_days < doc.target_shifts:
            diagnostics.append(
                f"El profesional '{doc.name}' tiene {len(blocked)} días bloqueados de {num_days}. "
                f"Solo le quedan {available_days} días disponibles, lo cual hace imposible asignarle {doc.target_shifts} guardias."
            )
            
    # Chequeo de disponibilidad por día (si hay suficientes médicos libres cada día)
    for day in days_config:
        req = day.required_shifts
        avail_docs_today = [
            doc for doc in active_doctors if day.day not in doctor_blocked_days[doc.id]
        ]
        if len(avail_docs_today) < req:
            diagnostics.append(
                f"El día {day.day} ({day.weekday_name}) requiere {req} médicos, pero solo {len(avail_docs_today)} "
                f"están disponibles por bloqueos personales."
            )
            
    if diagnostics:
        return ScheduleResponse(
            success=False,
            status="INFEASIBLE_PRECHECK",
            message="Se detectaron conflictos en las restricciones personales que impiden generar la distribución.",
            diagnostics=diagnostics
        )

    # Construcción del Modelo CP-SAT
    model = cp_model.CpModel()
    
    # Variables binarias x[p_id, day_num]
    x = {}
    for doc in active_doctors:
        for day in days_config:
            x[doc.id, day.day] = model.NewBoolVar(f"x_{doc.id}_{day.day}")
            
    # 1. Cobertura diaria estricta: exactamente required_shifts por día
    for day in days_config:
        model.Add(
            sum(x[doc.id, day.day] for doc in active_doctors) == day.required_shifts
        )
        
    # 2. Descanso obligatorio post-guardia (no dos días consecutivos)
    # Si hace guardia el día d, x[p, d+1] debe ser 0.
    for doc in active_doctors:
        for i in range(len(days_config) - 1):
            d1 = days_config[i].day
            d2 = days_config[i+1].day
            # Solo si son días calendario consecutivos
            if d2 == d1 + 1:
                model.Add(x[doc.id, d1] + x[doc.id, d2] <= 1)

    # 2b. Regla opcional: impedir 3 o más guardias en una ventana de 5 días corridos
    day_numbers_set = {d.day for d in days_config}
    max_day_num = max(day_numbers_set) if day_numbers_set else 0
    if request.avoid_three_in_five_days and max_day_num >= 5:
        for doc in active_doctors:
            for start_d in range(1, max_day_num - 3):
                window_vars = [
                    x[doc.id, wd]
                    for wd in range(start_d, start_d + 5)
                    if wd in day_numbers_set
                ]
                if len(window_vars) >= 3:
                    model.Add(sum(window_vars) <= 2)
                
    # 3. Restricciones individuales de indisponibilidad
    for doc in active_doctors:
        for b_day in doctor_blocked_days[doc.id]:
            if (doc.id, b_day) in x:
                model.Add(x[doc.id, b_day] == 0)

    # 4. Cuota de guardias por persona
    # Variables auxiliares para el número de guardias de cada persona
    total_assigned_vars = {}
    quota_diff_vars = []
    
    for doc in active_doctors:
        shifts_for_doc = [x[doc.id, day.day] for day in days_config]
        assigned_sum = model.NewIntVar(0, num_days, f"total_shifts_{doc.id}")
        model.Add(assigned_sum == sum(shifts_for_doc))
        total_assigned_vars[doc.id] = assigned_sum
        
        if request.strict_quota:
            # Cuota exacta obligatoria (ej. 7 guardias)
            model.Add(assigned_sum == doc.target_shifts)
        else:
            # Cuota flexible: penalizar desviación de la meta
            diff_var = model.NewIntVar(-num_days, num_days, f"diff_{doc.id}")
            model.Add(diff_var == assigned_sum - doc.target_shifts)
            abs_diff = model.NewIntVar(0, num_days, f"abs_diff_{doc.id}")
            model.AddAbsEquality(abs_diff, diff_var)
            quota_diff_vars.append(abs_diff)

    total_spread_var = None
    if not request.strict_quota and len(active_doctors) > 1:
        max_total = model.NewIntVar(0, num_days, "max_total")
        min_total = model.NewIntVar(0, num_days, "min_total")
        for doc in active_doctors:
            model.Add(max_total >= total_assigned_vars[doc.id])
            model.Add(min_total <= total_assigned_vars[doc.id])
        total_spread_var = model.NewIntVar(0, num_days, "total_spread")
        model.Add(total_spread_var == max_total - min_total)

    # 5. Equidad de JUEVES (Altamente deseados por generar fin de semana largo)
    thursday_days = [d.day for d in days_config if d.is_thursday]
    thursday_diff_var = None
    th_assigned_vars = {}
    
    if thursday_days and request.prioritize_thursdays:
        for doc in active_doctors:
            th_sum = model.NewIntVar(0, len(thursday_days), f"th_shifts_{doc.id}")
            model.Add(th_sum == sum(x[doc.id, t_day] for t_day in thursday_days))
            th_assigned_vars[doc.id] = th_sum
            
        max_th = model.NewIntVar(0, len(thursday_days), "max_th")
        min_th = model.NewIntVar(0, len(thursday_days), "min_th")
        for doc in active_doctors:
            model.Add(max_th >= th_assigned_vars[doc.id])
            model.Add(min_th <= th_assigned_vars[doc.id])
        thursday_diff_var = model.NewIntVar(0, len(thursday_days), "thursday_spread")
        model.Add(thursday_diff_var == max_th - min_th)
        
    # 6. Equidad de Fines de Semana (Sábados y Domingos)
    weekend_days = [d.day for d in days_config if d.is_weekend]
    weekend_diff_var = None
    wk_assigned_vars = {}
    
    if weekend_days and request.prioritize_weekends:
        for doc in active_doctors:
            wk_sum = model.NewIntVar(0, len(weekend_days), f"wk_shifts_{doc.id}")
            model.Add(wk_sum == sum(x[doc.id, w_day] for w_day in weekend_days))
            wk_assigned_vars[doc.id] = wk_sum
            
        max_wk = model.NewIntVar(0, len(weekend_days), "max_wk")
        min_wk = model.NewIntVar(0, len(weekend_days), "min_wk")
        for doc in active_doctors:
            model.Add(max_wk >= wk_assigned_vars[doc.id])
            model.Add(min_wk <= wk_assigned_vars[doc.id])
        weekend_diff_var = model.NewIntVar(0, len(weekend_days), "weekend_spread")
        model.Add(weekend_diff_var == max_wk - min_wk)

    # 7. Equidad de Feriados
    holiday_days = [d.day for d in days_config if d.is_holiday]
    hol_diff_var = None
    if holiday_days:
        hol_assigned_vars = {}
        for doc in active_doctors:
            hol_sum = model.NewIntVar(0, len(holiday_days), f"hol_shifts_{doc.id}")
            model.Add(hol_sum == sum(x[doc.id, h_day] for h_day in holiday_days))
            hol_assigned_vars[doc.id] = hol_sum
        max_hol = model.NewIntVar(0, len(holiday_days), "max_hol")
        min_hol = model.NewIntVar(0, len(holiday_days), "min_hol")
        for doc in active_doctors:
            model.Add(max_hol >= hol_assigned_vars[doc.id])
            model.Add(min_hol <= hol_assigned_vars[doc.id])
        hol_diff_var = model.NewIntVar(0, len(holiday_days), "holiday_spread")
        model.Add(hol_diff_var == max_hol - min_hol)

    # 8. Espaciado saludable entre guardias (evitar guardias cada 48h continuamente)
    # x[p, d] + x[p, d+2] <= 1 como penalización suave para favorecer descanso más espaciado
    two_day_violations = []
    for doc in active_doctors:
        for i in range(len(days_config) - 2):
            d1 = days_config[i].day
            d3 = days_config[i+2].day
            if d3 == d1 + 2:
                v = model.NewBoolVar(f"two_day_dense_{doc.id}_{d1}")
                # v == 1 si ambas son 1
                model.Add(x[doc.id, d1] + x[doc.id, d3] <= 1 + v)
                two_day_violations.append(v)

    # Función Objetivo: Minimizar disparidades con ponderación
    objective_terms = []
    
    # Si cuota es flexible, penalizar desviación de la meta y dispersión entre médicos
    if quota_diff_vars:
        objective_terms.append(500 * sum(quota_diff_vars))
    if total_spread_var is not None:
        objective_terms.append(2500 * total_spread_var)
        
    # Equidad de jueves: alta prioridad
    if thursday_diff_var is not None:
        objective_terms.append(100 * thursday_diff_var)
        
    # Equidad de fines de semana: prioridad media-alta
    if weekend_diff_var is not None:
        objective_terms.append(40 * weekend_diff_var)
        
    # Equidad de feriados: prioridad media
    if hol_diff_var is not None:
        objective_terms.append(30 * hol_diff_var)
        
    # Espaciado de guardias (suavizado)
    if two_day_violations:
        objective_terms.append(2 * sum(two_day_violations))

    if objective_terms:
        model.Minimize(sum(objective_terms))

    # Ejecución del Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(request.max_solve_time_seconds)
    solver.parameters.num_workers = 4  # Paralelismo
    
    start_time = time.time()
    solve_status = solver.Solve(model)
    elapsed_time = round(time.time() - start_time, 3)

    if solve_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Solución encontrada
        status_name = "OPTIMAL" if solve_status == cp_model.OPTIMAL else "FEASIBLE"
        
        # Mapear doctores por ID para acceso rápido
        doc_map = {doc.id: doc for doc in active_doctors}
        
        # Armar el calendario de salida
        schedule_output: List[DaySchedule] = []
        doctor_th_counts: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        doctor_wk_counts: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        doctor_hol_counts: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        doctor_total_counts: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        doctor_assigned_days: Dict[str, set] = {doc.id: set() for doc in active_doctors}
        consecutive_errors: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        three_in_five_errors: Dict[str, int] = {doc.id: 0 for doc in active_doctors}
        
        # Para verificar descanso de 24h
        prev_day_doctors = set()
        
        for day in days_config:
            assigned: List[ShiftAssignment] = []
            slot_idx = 1
            current_day_doctors = set()
            
            for doc in active_doctors:
                if solver.Value(x[doc.id, day.day]) == 1:
                    assigned.append(ShiftAssignment(
                        doctor_id=doc.id,
                        doctor_name=doc.name,
                        doctor_color=doc.color or "#3B82F6",
                        slot_index=slot_idx
                    ))
                    slot_idx += 1
                    doctor_total_counts[doc.id] += 1
                    doctor_assigned_days[doc.id].add(day.day)
                    current_day_doctors.add(doc.id)
                    
                    if day.is_thursday:
                        doctor_th_counts[doc.id] += 1
                    if day.is_weekend:
                        doctor_wk_counts[doc.id] += 1
                    if day.is_holiday:
                        doctor_hol_counts[doc.id] += 1
                        
            # Verificar si hubo violación consecutiva (debería ser 0 garantizado por el solver)
            for doc_id in current_day_doctors:
                if doc_id in prev_day_doctors:
                    consecutive_errors[doc_id] += 1
            prev_day_doctors = current_day_doctors
            
            schedule_output.append(DaySchedule(
                day=day.day,
                date=day.date,
                weekday_name=day.weekday_name,
                is_thursday=day.is_thursday,
                is_weekend=day.is_weekend,
                is_holiday=day.is_holiday,
                holiday_name=day.holiday_name,
                required_shifts=day.required_shifts,
                assigned_doctors=assigned
            ))

        if max_day_num >= 5:
            for doc in active_doctors:
                assigned_set = doctor_assigned_days[doc.id]
                for start_d in range(1, max_day_num - 3):
                    count_in_window = sum(1 for wd in range(start_d, start_d + 5) if wd in assigned_set)
                    if count_in_window >= 3:
                        three_in_five_errors[doc.id] += 1
            
        # Estadísticas individuales
        stats_output: List[DoctorStats] = []
        for doc in active_doctors:
            stats_output.append(DoctorStats(
                doctor_id=doc.id,
                doctor_name=doc.name,
                doctor_color=doc.color or "#3B82F6",
                total_shifts=doctor_total_counts[doc.id],
                target_shifts=doc.target_shifts,
                thursday_shifts=doctor_th_counts[doc.id],
                weekend_shifts=doctor_wk_counts[doc.id],
                holiday_shifts=doctor_hol_counts[doc.id],
                consecutive_violations=consecutive_errors[doc.id],
                three_in_five_violations=three_in_five_errors[doc.id],
                blocked_days_count=len(doctor_blocked_days[doc.id])
            ))
            
        summary = {
            "total_days": num_days,
            "total_slots": total_slots_needed,
            "active_doctors": num_doctors,
            "elapsed_seconds": elapsed_time,
            "thursdays_in_month": len(thursday_days),
            "double_shift_days": sum(1 for d in days_config if d.required_shifts == 2),
            "perfect_consecutive_rest": sum(consecutive_errors.values()) == 0,
            "avoid_three_in_five_enabled": request.avoid_three_in_five_days,
            "zero_three_in_five_clusters": sum(three_in_five_errors.values()) == 0,
            "strict_quota_met": all(s.total_shifts == s.target_shifts for s in stats_output)
        }
        
        return ScheduleResponse(
            success=True,
            status=status_name,
            message="Planificación de guardias calculada exitosamente cumpliendo todas las reglas.",
            schedule=schedule_output,
            stats=stats_output,
            summary=summary
        )
    else:
        # Infactible o tiempo agotado
        infeasible_diags = [
            "Verifique que los profesionales con muchos días bloqueados tengan margen suficiente para completar su cuota sin días consecutivos.",
            "Revise si los fines de semana o jueves concentran demasiadas restricciones personales que dejan días sin suficientes médicos disponibles.",
            "Considere liberar temporalmente algún bloqueo personal o flexibilizar los días de guardia doble."
        ]
        if request.avoid_three_in_five_days:
            infeasible_diags.insert(
                0,
                "La regla opcional 'Evitar 3 guardias en 5 días' está activa. Si algún profesional tiene muchos días bloqueados en el mes, puede desactivarla para ampliar las combinaciones posibles."
            )
        return ScheduleResponse(
            success=False,
            status="INFEASIBLE",
            message="No existe una combinación posible que cumpla simultáneamente con las cuotas mensuales, el descanso obligatorio de 24h, las reglas de espaciado y los bloqueos personales configurados.",
            diagnostics=infeasible_diags
        )
