-- =============================================================================
-- MedGuard: Esquema Multi-Usuario con Supabase Auth + Row Level Security (RLS)
-- =============================================================================

-- 1. Función segura para actualizar automáticamente updated_at
create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = pg_catalog.now();
    return new;
end;
$$;

-- 2. Tabla de Plantel Médico por Usuario (persiste entre meses)
create table if not exists public.doctors (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    name text not null check (char_length(trim(name)) between 1 and 120),
    color text not null default '#3B82F6',
    active boolean not null default true,
    target_shifts integer not null default 7 check (target_shifts between 0 and 31),
    sort_order integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_doctors_user_sort
    on public.doctors using btree (user_id, sort_order, created_at);

drop trigger if exists trg_doctors_updated_at on public.doctors;
create trigger trg_doctors_updated_at
    before update on public.doctors
    for each row
    execute function public.set_updated_at();

-- 3. Tabla de Planificaciones y Calendarios Mensuales por Usuario
create table if not exists public.monthly_schedules (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    year integer not null check (year between 2000 and 2100),
    month integer not null check (month between 1 and 12),
    country_code text not null default 'AR' check (char_length(country_code) = 2),
    strict_quota boolean not null default true,
    prioritize_thursdays boolean not null default true,
    prioritize_weekends boolean not null default true,
    default_target_shifts integer not null default 7 check (default_target_shifts between 0 and 31),
    days_config jsonb not null default '[]'::jsonb,
    restrictions jsonb not null default '[]'::jsonb,
    schedule jsonb not null default '[]'::jsonb,
    stats jsonb not null default '[]'::jsonb,
    summary jsonb,
    solved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint monthly_schedules_user_year_month_key unique (user_id, year, month)
);

drop trigger if exists trg_monthly_schedules_updated_at on public.monthly_schedules;
create trigger trg_monthly_schedules_updated_at
    before update on public.monthly_schedules
    for each row
    execute function public.set_updated_at();

-- 4. Privilegios de Mínimo Acceso y Row Level Security (RLS)
revoke all on public.doctors from anon, public;
revoke all on public.monthly_schedules from anon, public;

grant select, insert, update, delete on public.doctors to authenticated;
grant select, insert, update, delete on public.monthly_schedules to authenticated;

grant all on public.doctors to service_role;
grant all on public.monthly_schedules to service_role;

alter table public.doctors enable row level security;
alter table public.monthly_schedules enable row level security;

-- Políticas RLS para public.doctors
drop policy if exists "doctors_select_own" on public.doctors;
create policy "doctors_select_own"
    on public.doctors
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "doctors_insert_own" on public.doctors;
create policy "doctors_insert_own"
    on public.doctors
    for insert
    to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "doctors_update_own" on public.doctors;
create policy "doctors_update_own"
    on public.doctors
    for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "doctors_delete_own" on public.doctors;
create policy "doctors_delete_own"
    on public.doctors
    for delete
    to authenticated
    using ((select auth.uid()) = user_id);

-- Políticas RLS para public.monthly_schedules
drop policy if exists "monthly_schedules_select_own" on public.monthly_schedules;
create policy "monthly_schedules_select_own"
    on public.monthly_schedules
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "monthly_schedules_insert_own" on public.monthly_schedules;
create policy "monthly_schedules_insert_own"
    on public.monthly_schedules
    for insert
    to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "monthly_schedules_update_own" on public.monthly_schedules;
create policy "monthly_schedules_update_own"
    on public.monthly_schedules
    for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "monthly_schedules_delete_own" on public.monthly_schedules;
create policy "monthly_schedules_delete_own"
    on public.monthly_schedules
    for delete
    to authenticated
    using ((select auth.uid()) = user_id);
