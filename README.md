# MedGuard • Planificador Inteligente de Guardias Médicas

Aplicación web Full-Stack multi-usuario para la distribución mensual, equitativa y automatizada de guardias médicas mediante programación por restricciones (**Google OR-Tools CP-SAT**), cuentas de usuario con **Supabase Auth** y persistencia aislada por servicio médico mediante **Postgres Row-Level Security (RLS)**, lista para desplegar en **Vercel**.

---

## Características Principales

- **Gestión de Cuentas Multi-Usuario (Supabase Auth):** Registro, inicio de sesión, recuperación de contraseña y aislamiento estricto por usuario mediante políticas RLS (`TO authenticated` + `auth.uid()`).
- **Plantel Médico Propio y Persistente:** Cada cuenta conserva su propio equipo médico (`doctors`), colores identificatorios, estado activo/inactivo y cuotas mensuales individuales o globales (`0` a `31` guardias).
- **Guardado Automático de Calendarios Mensuales:** Cada mes y año (`monthly_schedules`) guarda automáticamente la cantidad de médicos requeridos por día (`0` a `3`), feriados, bloqueos individuales y el rol calculado.
- **Motor Matemático Exacto (OR-Tools CP-SAT):**
  - Prohibición estricta de días consecutivos (descanso obligatorio post-guardia de 24 horas).
  - Cumplimiento de cuotas mensuales estrictas o flexibles.
  - Optimización equitativa de días jueves, fines de semana y feriados oficiales (`AR`, `ES`, `MX`, `CL`, `CO`, `UY`, `PE`, `US`).
- **Impresión A4 Apaisada y Exportación:** Vista de impresión profesional en una sola hoja A4 horizontal y exportación CSV / JSON.

---

## Configuración de Base de Datos (Supabase)

1. Crea un proyecto en Supabase y ejecuta la migración ubicada en `supabase/migrations/20261101000000_init_medguard.sql`.
2. Copia `.env.example` a `.env.local` y completa las credenciales públicas del proyecto:
   ```env
   SUPABASE_URL=https://tu-proyecto.supabase.co
   SUPABASE_PUBLISHABLE_KEY=sb_publishable_tu_clave
   ```
   *(Nota: Si no defines variables de entorno localmente, la aplicación funciona automáticamente en modo local de demostración).*

---

## Ejecución Local

```bash
pip install -r requirements.txt
python run.py
```

Abre `http://127.0.0.1:8000` en tu navegador.

### Pruebas Automatizadas

```bash
python -m tests.test_solver
python -m tests.test_api
```

---

## Despliegue en Vercel

El proyecto está estructurado para el preset nativo de **FastAPI en Vercel** (`app/main.py` + `vercel.json`):

1. Conecta el repositorio de GitHub en Vercel.
2. Configura las variables de entorno en el proyecto de Vercel (`Production`, `Preview`, `Development`):
   - `SUPABASE_URL`
   - `SUPABASE_PUBLISHABLE_KEY`
3. En el panel de Supabase (**Authentication → URL Configuration**), establece como **Site URL** tu dominio de Vercel (`https://tu-app.vercel.app`) y agrégalo también en **Redirect URLs** (`https://tu-app.vercel.app/**`).
