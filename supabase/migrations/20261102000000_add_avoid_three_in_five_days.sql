-- Agrega la regla opcional por planificación mensual para impedir 3 guardias en 5 días corridos
alter table public.monthly_schedules
    add column if not exists avoid_three_in_five_days boolean not null default true;
