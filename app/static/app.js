/**
 * MedGuard • Aplicación de Planificación Inteligente de Guardias Médicas
 * Multi-usuario con Supabase Auth + Persistencia en la Nube (RLS) + Google OR-Tools
 */

const PALETTE = [
    "#3B82F6", // Azul
    "#10B981", // Verde esmeralda
    "#F59E0B", // Ámbar / Naranja
    "#EC4899", // Rosa
    "#8B5CF6", // Violeta
    "#06B6D4", // Cian
    "#EF4444", // Rojo
    "#14B8A6", // Turquesa
    "#F97316", // Naranja brillante
    "#6366F1", // Índigo
    "#84CC16", // Lima
    "#A855F7"  // Púrpura
];

const DEFAULT_DOCTOR_NAMES = [
    "Dr. Gómez (Cirugía)",
    "Dra. Pérez (Clínica)",
    "Dr. Rodríguez (Pediatría)",
    "Dra. Martínez (UTI)",
    "Dr. López (Traumatología)",
    "Dra. Fernández (Cardiología)",
    "Dr. Benítez (Neurología)",
    "Dra. Romero (Anestesia)",
    "Dr. Navarro (Guardia)",
    "Dra. Morales (Infectología)",
    "Dr. Castro (Nefrología)",
    "Dra. Ortiz (Ginecología)"
];

// Mantener instancias de SDK y timers fuera del Proxy reactivo de Alpine.js
let supabaseClient = null;
let monthlySaveTimer = null;
const doctorSaveTimers = {};

function translateAuthError(message) {
    if (!message) return "Ocurrió un error inesperado de autenticación.";
    const msg = message.toLowerCase();
    if (msg.includes("invalid login credentials")) return "Correo electrónico o contraseña incorrectos.";
    if (msg.includes("email not confirmed")) return "Tu correo aún no fue confirmado. Revisa tu bandeja de entrada o carpeta de spam.";
    if (msg.includes("user already registered")) return "Ya existe una cuenta registrada con este correo electrónico.";
    if (msg.includes("password should be at least")) return "La contraseña debe tener al menos 6 caracteres.";
    if (msg.includes("rate limit") || msg.includes("security purposes")) return "Demasiados intentos seguidos. Por favor aguarda unos segundos e intenta de nuevo.";
    if (msg.includes("unable to validate email")) return "Ingresa una dirección de correo electrónico válida.";
    return message;
}

function schedulerApp() {
    return {
        // Estado de arranque y autenticación
        isBootstrapping: true,
        isLoadingWorkspace: false,
        supabaseEnabled: false,
        user: null,
        authMode: 'login', // 'login' | 'signup' | 'reset'
        authForm: {
            email: '',
            password: '',
            confirmPassword: '',
            newPassword: ''
        },
        showPassword: false,
        authBusy: false,
        authError: '',
        authInfo: '',
        showPasswordUpdateModal: false,

        // Estado de sincronización con Supabase: 'idle' | 'saving' | 'saved' | 'error'
        syncStatus: 'idle',
        lastSyncedAt: null,
        savedMonths: [], // [{ year, month, solved_at }]

        // Pestaña activa: 'calendar' | 'personal' | 'days' | 'matrix' | 'stats'
        activeTab: 'calendar',
        // Vista del calendario en smartphones verticales: 'list' | 'grid'
        mobileCalendarView: 'list',

        // Estado de fecha y país
        year: 2026,
        month: 10,
        countryCode: 'AR',
        supportedCountries: [],

        // Datos principales del usuario activo
        doctors: [],
        days: [],
        monthHolidays: [],
        restrictions: [], // [{ doctor_id: "...", blocked_days: [12] }]

        // Parámetros de optimización
        strictQuota: true,
        avoidThreeInFiveDays: true,
        prioritizeThursdays: true,
        prioritizeWeekends: true,

        // Resultado del solver
        schedule: [],
        stats: [],
        summary: null,
        isSolving: false,
        lastSolvedAt: null,
        solvedAtIso: null,

        // Modales y notificaciones
        showErrorModal: false,
        errorMessage: '',
        diagnostics: [],
        successToast: null,

        // Configuración de cuotas
        defaultTargetShifts: 7,

        // Formularios auxiliares
        newDoctor: {
            name: '',
            color: '#3B82F6',
            target_shifts: 7
        },
        rangeBlock: {
            doctorId: '',
            startDay: 1,
            endDay: 1
        },

        // ==========================================
        // INICIALIZACIÓN Y AUTENTICACIÓN
        // ==========================================
        async init() {
            const now = new Date();
            this.year = now.getFullYear();
            this.month = now.getMonth() + 1;

            try {
                const [_, pubConfig] = await Promise.all([
                    this.fetchCountries(),
                    this.fetchPublicConfig()
                ]);

                if (pubConfig && pubConfig.supabase_enabled && window.supabase) {
                    this.supabaseEnabled = true;
                    supabaseClient = window.supabase.createClient(
                        pubConfig.supabase_url,
                        pubConfig.supabase_key
                    );

                    // Procesar enlaces de confirmación por correo o recuperación (PKCE token_hash)
                    await this.handleUrlAuthTokens();

                    // Escuchar cambios de sesión sin bloquear el callback interno
                    supabaseClient.auth.onAuthStateChange((event, session) => {
                        if (event === 'PASSWORD_RECOVERY') {
                            this.user = session?.user || null;
                            this.showPasswordUpdateModal = true;
                        } else if (event === 'SIGNED_OUT') {
                            this.clearUserWorkspaceState();
                        } else if (session?.user) {
                            const prevId = this.user ? this.user.id : null;
                            this.user = session.user;
                            if (prevId !== session.user.id) {
                                setTimeout(() => {
                                    this.loadUserWorkspace();
                                }, 0);
                            }
                        }
                    });

                    const { data: { session } } = await supabaseClient.auth.getSession();
                    if (session?.user) {
                        this.user = session.user;
                        await this.loadUserWorkspace();
                    }
                } else {
                    // Modo local sin Supabase configurado
                    this.supabaseEnabled = false;
                    await this.loadDemoData(false);
                }
            } catch (e) {
                console.error("Error en inicialización:", e);
            } finally {
                this.isBootstrapping = false;
            }
        },

        async fetchPublicConfig() {
            try {
                const res = await fetch('/api/public-config');
                if (res.ok) {
                    return await res.json();
                }
            } catch (e) {
                console.error("Error al consultar configuración pública:", e);
            }
            return { supabase_enabled: false };
        },

        async handleUrlAuthTokens() {
            if (!supabaseClient) return;
            const params = new URLSearchParams(window.location.search);
            const tokenHash = params.get('token_hash');
            const type = params.get('type');
            if (tokenHash && type) {
                const { error } = await supabaseClient.auth.verifyOtp({
                    token_hash: tokenHash,
                    type: type
                });
                window.history.replaceState({}, document.title, window.location.pathname);
                if (error) {
                    this.authError = translateAuthError(error.message);
                } else if (type === 'recovery') {
                    this.showPasswordUpdateModal = true;
                } else {
                    this.showToast("Correo verificado correctamente. ¡Bienvenido/a!");
                }
            }
        },

        clearUserWorkspaceState() {
            if (monthlySaveTimer) clearTimeout(monthlySaveTimer);
            this.user = null;
            this.doctors = [];
            this.days = [];
            this.restrictions = [];
            this.schedule = [];
            this.stats = [];
            this.summary = null;
            this.lastSolvedAt = null;
            this.solvedAtIso = null;
            this.savedMonths = [];
            this.syncStatus = 'idle';
        },

        switchAuthMode(mode) {
            this.authMode = mode;
            this.authError = '';
            this.authInfo = '';
        },

        async submitAuth() {
            if (!supabaseClient) return;
            this.authError = '';
            this.authInfo = '';

            const email = this.authForm.email.trim();
            const password = this.authForm.password;

            if (!email) {
                this.authError = "Ingresa tu correo electrónico.";
                return;
            }

            this.authBusy = true;
            try {
                if (this.authMode === 'login') {
                    const { data, error } = await supabaseClient.auth.signInWithPassword({
                        email,
                        password
                    });
                    if (error) throw error;
                    if (data?.user) {
                        this.user = data.user;
                        this.authForm.password = '';
                        await this.loadUserWorkspace();
                        this.showToast(`Sesión iniciada como ${data.user.email}`);
                    }
                } else if (this.authMode === 'signup') {
                    if (password.length < 6) {
                        this.authError = "La contraseña debe tener al menos 6 caracteres.";
                        return;
                    }
                    if (password !== this.authForm.confirmPassword) {
                        this.authError = "Las contraseñas ingresadas no coinciden.";
                        return;
                    }
                    const { data, error } = await supabaseClient.auth.signUp({
                        email,
                        password,
                        options: {
                            emailRedirectTo: window.location.origin
                        }
                    });
                    if (error) throw error;

                    if (data?.session && data?.user) {
                        this.user = data.user;
                        this.authForm.password = '';
                        this.authForm.confirmPassword = '';
                        await this.loadUserWorkspace();
                        this.showToast("¡Cuenta creada con éxito! Ya puedes configurar tu plantel.");
                    } else {
                        this.authInfo = "¡Cuenta creada! Te enviamos un enlace de confirmación a tu correo electrónico. Confírmalo para iniciar sesión.";
                        this.authMode = 'login';
                        this.authForm.password = '';
                        this.authForm.confirmPassword = '';
                    }
                } else if (this.authMode === 'reset') {
                    const { error } = await supabaseClient.auth.resetPasswordForEmail(email, {
                        redirectTo: window.location.origin
                    });
                    if (error) throw error;
                    this.authInfo = "Si el correo está registrado, recibirás un enlace para restablecer tu contraseña.";
                }
            } catch (err) {
                this.authError = translateAuthError(err.message);
            } finally {
                this.authBusy = false;
            }
        },

        async updateRecoveredPassword() {
            if (!supabaseClient) return;
            const newPassword = this.authForm.newPassword;
            if (!newPassword || newPassword.length < 6) {
                alert("La nueva contraseña debe tener al menos 6 caracteres.");
                return;
            }
            this.authBusy = true;
            try {
                const { error } = await supabaseClient.auth.updateUser({ password: newPassword });
                if (error) throw error;
                this.showPasswordUpdateModal = false;
                this.authForm.newPassword = '';
                this.showToast("Contraseña actualizada correctamente.");
            } catch (err) {
                alert(translateAuthError(err.message));
            } finally {
                this.authBusy = false;
            }
        },

        async signOut() {
            if (!supabaseClient) return;
            try {
                await this.flushPendingSaves();
                await supabaseClient.auth.signOut();
                this.clearUserWorkspaceState();
                this.showToast("Sesión cerrada correctamente");
            } catch (err) {
                console.error("Error al cerrar sesión:", err);
            }
        },

        // ==========================================
        // CARGA Y PERSISTENCIA EN SUPABASE (RLS)
        // ==========================================
        async loadUserWorkspace() {
            if (!supabaseClient || !this.user || this.isLoadingWorkspace) return;
            this.isLoadingWorkspace = true;
            this.syncStatus = 'saving';
            try {
                const { data: docs, error: docsErr } = await supabaseClient
                    .from('doctors')
                    .select('id, name, color, active, target_shifts, sort_order')
                    .eq('user_id', this.user.id)
                    .order('sort_order', { ascending: true })
                    .order('created_at', { ascending: true });

                if (docsErr) throw docsErr;

                this.doctors = (docs || []).map(d => ({
                    id: d.id,
                    name: d.name,
                    color: d.color || '#3B82F6',
                    active: d.active !== false,
                    target_shifts: Number.isFinite(Number(d.target_shifts)) ? Number(d.target_shifts) : 7,
                    sort_order: d.sort_order ?? 0
                }));

                if (this.doctors.length > 0) {
                    this.rangeBlock.doctorId = this.doctors[0].id;
                    this.newDoctor.color = PALETTE[this.doctors.length % PALETTE.length];
                } else {
                    // Usuario nuevo: mostrar primero la pestaña de personal o bienvenida
                    this.activeTab = 'personal';
                }

                await this.refreshSavedMonthsList();
                await this.loadPeriodData();
                this.syncStatus = 'saved';
                this.lastSyncedAt = new Date().toLocaleTimeString();
            } catch (err) {
                console.error("Error al cargar datos del usuario:", err);
                this.syncStatus = 'error';
            } finally {
                this.isLoadingWorkspace = false;
            }
        },

        async refreshSavedMonthsList() {
            if (!supabaseClient || !this.user) return;
            const { data } = await supabaseClient
                .from('monthly_schedules')
                .select('year, month, solved_at, updated_at')
                .eq('user_id', this.user.id)
                .order('year', { ascending: false })
                .order('month', { ascending: false })
                .limit(24);
            this.savedMonths = data || [];
        },

        async onPeriodChange() {
            if (this.supabaseEnabled && this.user) {
                await this.flushPendingSaves();
                await this.loadPeriodData();
            } else {
                await this.loadMonthInfo(true);
            }
        },

        async onCountryChange() {
            await this.loadMonthInfo(true);
            this.scheduleMonthlySave();
        },

        async loadPeriodData() {
            if (!supabaseClient || !this.user) {
                await this.loadMonthInfo(false);
                return;
            }

            try {
                const { data: plan, error } = await supabaseClient
                    .from('monthly_schedules')
                    .select('*')
                    .eq('user_id', this.user.id)
                    .eq('year', this.year)
                    .eq('month', this.month)
                    .maybeSingle();

                if (error) throw error;

                if (plan) {
                    this.countryCode = plan.country_code || this.countryCode;
                    this.strictQuota = plan.strict_quota !== false;
                    this.avoidThreeInFiveDays = plan.avoid_three_in_five_days !== false;
                    this.prioritizeThursdays = plan.prioritize_thursdays !== false;
                    this.prioritizeWeekends = plan.prioritize_weekends !== false;
                    this.defaultTargetShifts = Number.isFinite(Number(plan.default_target_shifts))
                        ? Number(plan.default_target_shifts)
                        : 7;

                    if (Array.isArray(plan.days_config) && plan.days_config.length > 0) {
                        this.days = plan.days_config;
                        this.monthHolidays = this.days
                            .filter(d => d.is_holiday)
                            .map(d => ({ day: d.day, date: d.date, name: d.holiday_name || 'Feriado' }));
                    } else {
                        await this.loadMonthInfo(false);
                    }

                    const activeDocIds = new Set(this.doctors.map(d => d.id));
                    const loadedRestrictions = Array.isArray(plan.restrictions) ? plan.restrictions : [];
                    this.restrictions = loadedRestrictions.filter(r => activeDocIds.has(r.doctor_id));
                    this.doctors.forEach(d => {
                        if (!this.restrictions.some(r => r.doctor_id === d.id)) {
                            this.restrictions.push({ doctor_id: d.id, blocked_days: [] });
                        }
                    });

                    this.schedule = Array.isArray(plan.schedule) ? plan.schedule : [];
                    this.stats = Array.isArray(plan.stats) ? plan.stats : [];
                    this.summary = plan.summary || null;
                    this.solvedAtIso = plan.solved_at || null;
                    this.lastSolvedAt = plan.solved_at
                        ? new Date(plan.solved_at).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' })
                        : null;

                    this.syncDoctorVisualsInSchedule();
                } else {
                    await this.loadMonthInfo(false);
                    this.restrictions = this.doctors.map(d => ({
                        doctor_id: d.id,
                        blocked_days: []
                    }));
                    this.schedule = [];
                    this.stats = [];
                    this.summary = null;
                    this.solvedAtIso = null;
                    this.lastSolvedAt = null;
                }
            } catch (err) {
                console.error("Error al cargar planificación mensual:", err);
                await this.loadMonthInfo(false);
            }
        },

        scheduleMonthlySave() {
            if (!this.supabaseEnabled || !this.user) return;
            this.syncStatus = 'saving';
            if (monthlySaveTimer) clearTimeout(monthlySaveTimer);
            monthlySaveTimer = setTimeout(() => {
                this.saveMonthlyPlanNow();
            }, 600);
        },

        async saveMonthlyPlanNow() {
            if (!this.supabaseEnabled || !this.user || !supabaseClient) return;
            if (monthlySaveTimer) {
                clearTimeout(monthlySaveTimer);
                monthlySaveTimer = null;
            }
            if (!this.days || this.days.length === 0) return;

            this.syncStatus = 'saving';
            try {
                const payload = {
                    user_id: this.user.id,
                    year: this.year,
                    month: this.month,
                    country_code: this.countryCode,
                    strict_quota: this.strictQuota,
                    avoid_three_in_five_days: this.avoidThreeInFiveDays,
                    prioritize_thursdays: this.prioritizeThursdays,
                    prioritize_weekends: this.prioritizeWeekends,
                    default_target_shifts: this.defaultTargetShifts,
                    days_config: this.days,
                    restrictions: this.restrictions,
                    schedule: this.schedule,
                    stats: this.stats,
                    summary: this.summary,
                    solved_at: this.solvedAtIso
                };

                const { error } = await supabaseClient
                    .from('monthly_schedules')
                    .upsert(payload, { onConflict: 'user_id,year,month' });

                if (error) throw error;

                this.syncStatus = 'saved';
                this.lastSyncedAt = new Date().toLocaleTimeString();
                await this.refreshSavedMonthsList();
            } catch (err) {
                console.error("Error al guardar planificación mensual:", err);
                this.syncStatus = 'error';
            }
        },

        scheduleDoctorSave(doc) {
            this.syncDoctorVisualsInSchedule();
            if (!this.supabaseEnabled || !this.user || !supabaseClient) return;
            this.syncStatus = 'saving';
            if (doctorSaveTimers[doc.id]) clearTimeout(doctorSaveTimers[doc.id]);
            doctorSaveTimers[doc.id] = setTimeout(() => {
                this.saveDoctorNow(doc);
            }, 400);
        },

        async saveDoctorNow(doc) {
            if (!this.supabaseEnabled || !this.user || !supabaseClient) return;
            if (doctorSaveTimers[doc.id]) {
                clearTimeout(doctorSaveTimers[doc.id]);
                delete doctorSaveTimers[doc.id];
            }
            const cleanName = (doc.name || '').trim() || 'Profesional';
            doc.name = cleanName;
            const cleanTarget = Math.max(0, Math.min(31, Number.isFinite(Number(doc.target_shifts)) ? Number(doc.target_shifts) : 7));
            doc.target_shifts = cleanTarget;

            this.syncStatus = 'saving';
            try {
                const { error } = await supabaseClient
                    .from('doctors')
                    .update({
                        name: cleanName,
                        color: doc.color || '#3B82F6',
                        active: !!doc.active,
                        target_shifts: cleanTarget
                    })
                    .eq('id', doc.id)
                    .eq('user_id', this.user.id);

                if (error) throw error;
                this.syncStatus = 'saved';
                this.lastSyncedAt = new Date().toLocaleTimeString();
            } catch (err) {
                console.error("Error al actualizar médico:", err);
                this.syncStatus = 'error';
            }
        },

        async flushPendingSaves() {
            if (!this.supabaseEnabled || !this.user) return;
            const pendingDocIds = Object.keys(doctorSaveTimers);
            for (const docId of pendingDocIds) {
                const doc = this.doctors.find(d => d.id === docId);
                if (doc) await this.saveDoctorNow(doc);
            }
            if (monthlySaveTimer || this.syncStatus === 'error') {
                await this.saveMonthlyPlanNow();
            }
        },

        syncDoctorVisualsInSchedule() {
            const docMap = {};
            this.doctors.forEach(d => { docMap[d.id] = d; });
            if (this.schedule && this.schedule.length > 0) {
                this.schedule.forEach(dayItem => {
                    (dayItem.assigned_doctors || []).forEach(ad => {
                        if (docMap[ad.doctor_id]) {
                            ad.doctor_name = docMap[ad.doctor_id].name;
                            ad.doctor_color = docMap[ad.doctor_id].color;
                        }
                    });
                });
            }
            if (this.stats && this.stats.length > 0) {
                this.stats.forEach(st => {
                    if (docMap[st.doctor_id]) {
                        st.doctor_name = docMap[st.doctor_id].name;
                        st.doctor_color = docMap[st.doctor_id].color;
                    }
                });
            }
        },

        // ==========================================
        // PETICIONES AL BACKEND FASTAPI
        // ==========================================
        async fetchCountries() {
            try {
                const res = await fetch('/api/countries');
                if (res.ok) {
                    this.supportedCountries = await res.json();
                }
            } catch (e) {
                console.error("Error al cargar países:", e);
            }
        },

        async loadMonthInfo(keepCustomShifts = true) {
            try {
                const prevShiftsMap = {};
                if (keepCustomShifts && this.days.length > 0) {
                    this.days.forEach(d => {
                        prevShiftsMap[d.day] = d.required_shifts;
                    });
                }

                const res = await fetch(`/api/month-info?year=${this.year}&month=${this.month}&country_code=${this.countryCode}`);
                if (res.ok) {
                    const data = await res.json();
                    this.days = data.days.map(d => ({
                        ...d,
                        required_shifts: (keepCustomShifts && prevShiftsMap[d.day] !== undefined)
                            ? prevShiftsMap[d.day]
                            : 1
                    }));
                    this.monthHolidays = data.holidays;

                    // Limpiar días bloqueados que excedan el total de días del mes
                    const maxDay = data.total_days;
                    this.restrictions.forEach(r => {
                        r.blocked_days = r.blocked_days.filter(day => day <= maxDay);
                    });
                }
            } catch (e) {
                console.error("Error al cargar mes:", e);
            }
        },

        async loadDemoData(confirmIfNotEmpty = true) {
            if (confirmIfNotEmpty && this.supabaseEnabled && this.user && this.doctors.length > 0) {
                const ok = confirm(
                    "Esto reemplazará tu plantel médico actual y cargará 6 profesionales de ejemplo con bloqueos de prueba. ¿Deseas continuar?"
                );
                if (!ok) return;
            }

            this.isSolving = true;
            try {
                const res = await fetch(`/api/demo-data?country_code=${this.countryCode}`);
                if (res.ok) {
                    const data = await res.json();
                    this.year = data.year;
                    this.month = data.month;
                    this.days = data.days_config;
                    this.strictQuota = data.strict_quota;
                    this.avoidThreeInFiveDays = data.avoid_three_in_five_days !== false;
                    this.prioritizeThursdays = data.prioritize_thursdays;
                    this.prioritizeWeekends = data.prioritize_weekends;

                    if (this.supabaseEnabled && this.user && supabaseClient) {
                        this.syncStatus = 'saving';
                        await supabaseClient
                            .from('doctors')
                            .delete()
                            .eq('user_id', this.user.id);

                        const toInsert = data.doctors.map((d, idx) => ({
                            user_id: this.user.id,
                            name: d.name,
                            color: d.color,
                            active: d.active,
                            target_shifts: d.target_shifts,
                            sort_order: idx
                        }));

                        const { data: insertedDocs, error: insErr } = await supabaseClient
                            .from('doctors')
                            .insert(toInsert)
                            .select('id, name, color, active, target_shifts, sort_order')
                            .order('sort_order', { ascending: true });

                        if (insErr) throw insErr;

                        // Mapear IDs de demo (doc-1, doc-2...) a los UUID reales creados en Supabase
                        const idMap = {};
                        data.doctors.forEach((origDoc, idx) => {
                            if (insertedDocs[idx]) {
                                idMap[origDoc.id] = insertedDocs[idx].id;
                            }
                        });

                        this.doctors = insertedDocs;
                        this.restrictions = data.restrictions
                            .filter(r => idMap[r.doctor_id])
                            .map(r => ({
                                doctor_id: idMap[r.doctor_id],
                                blocked_days: r.blocked_days
                            }));
                        this.doctors.forEach(d => {
                            if (!this.restrictions.some(r => r.doctor_id === d.id)) {
                                this.restrictions.push({ doctor_id: d.id, blocked_days: [] });
                            }
                        });
                    } else {
                        this.doctors = data.doctors;
                        this.restrictions = data.restrictions;
                    }

                    if (this.doctors.length > 0) {
                        this.rangeBlock.doctorId = this.doctors[0].id;
                        this.newDoctor.color = PALETTE[this.doctors.length % PALETTE.length];
                    }

                    await this.generateSchedule();
                }
            } catch (e) {
                console.error("Error al cargar demo:", e);
                this.syncStatus = 'error';
            } finally {
                this.isSolving = false;
            }
        },

        // ==========================================
        // GETTERS COMPUTADOS
        // ==========================================
        get activeDoctors() {
            return this.doctors.filter(d => d.active);
        },

        get activeDoctorsCount() {
            return this.activeDoctors.length;
        },

        get totalCapacity() {
            return this.activeDoctors.reduce((sum, d) => {
                const val = Number(d.target_shifts);
                return sum + (Number.isFinite(val) ? val : 7);
            }, 0);
        },

        get totalSlotsRequired() {
            return this.days.reduce((sum, d) => {
                const val = Number(d.required_shifts);
                return sum + (Number.isFinite(val) ? val : 1);
            }, 0);
        },

        get quotaBalanceDiff() {
            return this.totalSlotsRequired - this.totalCapacity;
        },

        get isBalanceOk() {
            return this.activeDoctorsCount > 0 && this.quotaBalanceDiff === 0;
        },

        get monthName() {
            const months = [
                "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
            ];
            return months[this.month] || '';
        },

        getMonthShortName(m) {
            const months = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
            return months[m] || m;
        },

        // Construcción de la grilla de calendario de 7 columnas (Lunes a Domingo)
        getCalendarGridDays() {
            if (!this.days || this.days.length === 0) return [];

            const firstDayWeekday = this.days[0].weekday;
            const cells = [];
            for (let i = 0; i < firstDayWeekday; i++) {
                cells.push({ empty: true, id: `empty-${i}` });
            }

            const scheduleMap = {};
            if (this.schedule && this.schedule.length > 0) {
                this.schedule.forEach(item => {
                    scheduleMap[item.day] = item;
                });
            }

            this.days.forEach(d => {
                const sched = scheduleMap[d.day] || null;
                cells.push({
                    empty: false,
                    day: d.day,
                    date: d.date,
                    weekday: d.weekday,
                    weekday_name: d.weekday_name,
                    is_thursday: d.is_thursday,
                    is_weekend: d.is_weekend,
                    is_holiday: d.is_holiday,
                    holiday_name: d.holiday_name,
                    required_shifts: d.required_shifts,
                    assigned_doctors: sched ? sched.assigned_doctors : []
                });
            });

            return cells;
        },

        get calendarGridDays() {
            return this.getCalendarGridDays();
        },

        getCalendarListDays() {
            return this.getCalendarGridDays().filter(item => !item.empty);
        },

        // ==========================================
        // GESTIÓN DE PERSONAL MÉDICO (PERSISTENTE)
        // ==========================================
        async addDoctor() {
            const trimmed = this.newDoctor.name.trim();
            if (!trimmed) return;

            if (this.doctors.length >= 12) {
                alert("El sistema admite un máximo recomendado de 12 profesionales.");
                return;
            }

            const color = this.newDoctor.color || PALETTE[this.doctors.length % PALETTE.length];
            const parsedTarget = parseInt(this.newDoctor.target_shifts, 10);
            const target = Number.isFinite(parsedTarget) ? Math.max(0, Math.min(31, parsedTarget)) : (this.defaultTargetShifts || 7);

            if (this.supabaseEnabled && this.user && supabaseClient) {
                this.syncStatus = 'saving';
                try {
                    const { data: inserted, error } = await supabaseClient
                        .from('doctors')
                        .insert({
                            user_id: this.user.id,
                            name: trimmed,
                            color: color,
                            active: true,
                            target_shifts: target,
                            sort_order: this.doctors.length
                        })
                        .select('id, name, color, active, target_shifts, sort_order')
                        .single();

                    if (error) throw error;

                    this.doctors.push(inserted);
                    this.restrictions.push({
                        doctor_id: inserted.id,
                        blocked_days: []
                    });
                    if (!this.rangeBlock.doctorId) {
                        this.rangeBlock.doctorId = inserted.id;
                    }
                    this.syncStatus = 'saved';
                    this.lastSyncedAt = new Date().toLocaleTimeString();
                } catch (err) {
                    console.error("Error al insertar médico:", err);
                    this.syncStatus = 'error';
                    alert("No se pudo guardar el médico en la nube: " + err.message);
                    return;
                }
            } else {
                const nextId = `doc-${Date.now()}`;
                this.doctors.push({
                    id: nextId,
                    name: trimmed,
                    color: color,
                    active: true,
                    target_shifts: target
                });
                this.restrictions.push({
                    doctor_id: nextId,
                    blocked_days: []
                });
                if (!this.rangeBlock.doctorId) {
                    this.rangeBlock.doctorId = nextId;
                }
            }

            this.newDoctor.name = '';
            this.newDoctor.color = PALETTE[this.doctors.length % PALETTE.length];
            this.showToast(`Se agregó a ${trimmed} (${target} guardias)`);
        },

        async applyDefaultTargetToAll() {
            const parsed = parseInt(this.defaultTargetShifts, 10);
            const target = Number.isFinite(parsed) ? Math.max(0, Math.min(31, parsed)) : 7;
            this.defaultTargetShifts = target;

            this.doctors.forEach(d => {
                d.target_shifts = target;
            });

            if (this.supabaseEnabled && this.user && supabaseClient && this.doctors.length > 0) {
                this.syncStatus = 'saving';
                try {
                    const { error } = await supabaseClient
                        .from('doctors')
                        .update({ target_shifts: target })
                        .eq('user_id', this.user.id);
                    if (error) throw error;
                    this.syncStatus = 'saved';
                    this.lastSyncedAt = new Date().toLocaleTimeString();
                } catch (err) {
                    console.error("Error al aplicar cuota global:", err);
                    this.syncStatus = 'error';
                }
            }
            this.scheduleMonthlySave();
            this.showToast(`Cuota de ${target} guardias aplicada a todo el personal`);
        },

        changeDoctorTarget(doc, delta) {
            const current = Number.isFinite(Number(doc.target_shifts)) ? Number(doc.target_shifts) : 7;
            doc.target_shifts = Math.max(0, Math.min(31, current + delta));
            this.scheduleDoctorSave(doc);
        },

        async removeDoctor(id) {
            const doc = this.doctors.find(d => d.id === id);
            const name = doc ? doc.name : 'el profesional';
            if (!confirm(`¿Seguro que deseas eliminar a ${name} de tu plantel médico?`)) {
                return;
            }

            if (this.supabaseEnabled && this.user && supabaseClient) {
                this.syncStatus = 'saving';
                try {
                    const { error } = await supabaseClient
                        .from('doctors')
                        .delete()
                        .eq('id', id)
                        .eq('user_id', this.user.id);
                    if (error) throw error;
                    this.syncStatus = 'saved';
                    this.lastSyncedAt = new Date().toLocaleTimeString();
                } catch (err) {
                    console.error("Error al eliminar médico:", err);
                    this.syncStatus = 'error';
                    alert("No se pudo eliminar el profesional: " + err.message);
                    return;
                }
            }

            this.doctors = this.doctors.filter(d => d.id !== id);
            this.restrictions = this.restrictions.filter(r => r.doctor_id !== id);
            if (this.rangeBlock.doctorId === id) {
                this.rangeBlock.doctorId = this.doctors[0] ? this.doctors[0].id : '';
            }
            this.scheduleMonthlySave();
            this.showToast(`Se eliminó a ${name}`);
        },

        toggleDoctorActive(doc) {
            doc.active = !doc.active;
            this.scheduleDoctorSave(doc);
            this.showToast(`${doc.name} ahora está ${doc.active ? 'activo' : 'inactivo'}`);
        },

        async setDoctorsPreset(count) {
            if (this.doctors.length > 0) {
                const ok = confirm(
                    `¿Deseas reemplazar tu plantel actual (${this.doctors.length} profesionales) por una plantilla de ${count} médicos?`
                );
                if (!ok) return;
            }

            const target = Number.isFinite(Number(this.defaultTargetShifts)) ? Number(this.defaultTargetShifts) : 7;

            if (this.supabaseEnabled && this.user && supabaseClient) {
                this.syncStatus = 'saving';
                try {
                    await supabaseClient
                        .from('doctors')
                        .delete()
                        .eq('user_id', this.user.id);

                    const rows = [];
                    for (let i = 0; i < count; i++) {
                        rows.push({
                            user_id: this.user.id,
                            name: DEFAULT_DOCTOR_NAMES[i] || `Médico ${i + 1}`,
                            color: PALETTE[i % PALETTE.length],
                            active: true,
                            target_shifts: target,
                            sort_order: i
                        });
                    }

                    const { data: inserted, error } = await supabaseClient
                        .from('doctors')
                        .insert(rows)
                        .select('id, name, color, active, target_shifts, sort_order')
                        .order('sort_order', { ascending: true });

                    if (error) throw error;
                    this.doctors = inserted || [];
                    this.syncStatus = 'saved';
                } catch (err) {
                    console.error("Error al crear plantilla de médicos:", err);
                    this.syncStatus = 'error';
                    return;
                }
            } else {
                this.doctors = [];
                for (let i = 0; i < count; i++) {
                    this.doctors.push({
                        id: `doc-${i + 1}`,
                        name: DEFAULT_DOCTOR_NAMES[i] || `Médico ${i + 1}`,
                        color: PALETTE[i % PALETTE.length],
                        active: true,
                        target_shifts: target
                    });
                }
            }

            this.restrictions = this.doctors.map(d => ({
                doctor_id: d.id,
                blocked_days: []
            }));
            if (this.doctors.length > 0) {
                this.rangeBlock.doctorId = this.doctors[0].id;
            }

            this.autoBalanceDoubles();
            this.showToast(`Se cargó plantilla de ${count} médicos (${target} guardias c/u)`);
        },

        // ==========================================
        // CONFIGURACIÓN DE DÍAS Y TURNOS (PERSISTENTE)
        // ==========================================
        setRequiredShifts(dayObj, value) {
            dayObj.required_shifts = parseInt(value, 10);
            this.scheduleMonthlySave();
        },

        setAllWeekendsDouble() {
            this.days.forEach(d => {
                if (d.is_weekend) d.required_shifts = 2;
            });
            this.scheduleMonthlySave();
            this.showToast("Todos los fines de semana configurados con guardia doble (2)");
        },

        setAllHolidaysDouble() {
            this.days.forEach(d => {
                if (d.is_holiday) d.required_shifts = 2;
            });
            this.scheduleMonthlySave();
            this.showToast("Todos los feriados configurados con guardia doble (2)");
        },

        clearAllDoubles() {
            this.days.forEach(d => {
                d.required_shifts = 1;
            });
            this.scheduleMonthlySave();
            this.showToast("Todas las guardias restablecidas a turno simple (1)");
        },

        autoBalanceDoubles() {
            const targetTotal = this.totalCapacity;
            const numDays = this.days.length;

            if (targetTotal <= 0) {
                alert("La capacidad total de guardias es 0. Activa al menos un médico con cuota mayor a 0.");
                return;
            }

            const scoredDays = [...this.days].map(d => {
                let score = 0;
                if (d.is_holiday) score += 50;
                if (d.is_weekend) score += 40;
                if (d.weekday === 4) score += 30; // Viernes
                if (d.weekday === 3) score += 20; // Jueves
                return { day: d, score };
            });
            scoredDays.sort((a, b) => b.score - a.score);

            if (targetTotal < numDays) {
                this.days.forEach(d => d.required_shifts = 0);
                for (let i = 0; i < targetTotal; i++) {
                    scoredDays[i].day.required_shifts = 1;
                }
            } else {
                this.days.forEach(d => d.required_shifts = 1);
                let remaining = targetTotal - numDays;

                for (let i = 0; i < scoredDays.length && remaining > 0; i++) {
                    scoredDays[i].day.required_shifts = 2;
                    remaining--;
                }

                for (let i = 0; i < scoredDays.length && remaining > 0; i++) {
                    scoredDays[i].day.required_shifts = 3;
                    remaining--;
                }
            }

            this.scheduleMonthlySave();
            this.showToast(`Balance perfecto alcanzado: ${this.totalSlotsRequired} cupos para ${targetTotal} guardias requeridas`);
        },

        // ==========================================
        // MATRIZ DE INDISPONIBILIDAD (PERSISTENTE)
        // ==========================================
        isDayBlocked(doctorId, dayNum) {
            const r = this.restrictions.find(x => x.doctor_id === doctorId);
            return r ? r.blocked_days.includes(dayNum) : false;
        },

        toggleBlock(doctorId, dayNum) {
            let r = this.restrictions.find(x => x.doctor_id === doctorId);
            if (!r) {
                r = { doctor_id: doctorId, blocked_days: [] };
                this.restrictions.push(r);
            }

            const idx = r.blocked_days.indexOf(dayNum);
            if (idx > -1) {
                r.blocked_days.splice(idx, 1);
            } else {
                r.blocked_days.push(dayNum);
            }
            this.scheduleMonthlySave();
        },

        getBlockedCount(doctorId) {
            const r = this.restrictions.find(x => x.doctor_id === doctorId);
            return r ? r.blocked_days.length : 0;
        },

        clearDoctorRestrictions(doctorId) {
            const r = this.restrictions.find(x => x.doctor_id === doctorId);
            if (r) r.blocked_days = [];
            this.scheduleMonthlySave();
            this.showToast("Restricciones eliminadas para este profesional");
        },

        applyRangeBlock() {
            const docId = this.rangeBlock.doctorId;
            const start = parseInt(this.rangeBlock.startDay, 10);
            const end = parseInt(this.rangeBlock.endDay, 10);

            if (!docId) {
                alert("Selecciona un médico.");
                return;
            }
            if (start > end || start < 1 || end > this.days.length) {
                alert("Rango de fechas no válido.");
                return;
            }

            let r = this.restrictions.find(x => x.doctor_id === docId);
            if (!r) {
                r = { doctor_id: docId, blocked_days: [] };
                this.restrictions.push(r);
            }

            const setDays = new Set(r.blocked_days);
            for (let d = start; d <= end; d++) {
                setDays.add(d);
            }
            r.blocked_days = Array.from(setDays);

            const doc = this.doctors.find(d => d.id === docId);
            this.scheduleMonthlySave();
            this.showToast(`Bloqueado del día ${start} al ${end} para ${doc ? doc.name : 'el médico'}`);
        },

        // ==========================================
        // OPTIMIZACIÓN OR-TOOLS Y GUARDADO DE ROL
        // ==========================================
        async generateSchedule() {
            if (this.activeDoctorsCount < 1) {
                alert("Debes agregar y activar al menos un médico en la pestaña 'Personal Médico'.");
                this.activeTab = 'personal';
                return;
            }

            if (this.strictQuota && !this.isBalanceOk) {
                const diff = this.quotaBalanceDiff;
                const confirmBalance = confirm(
                    `Inconsistencia de cupos:\n` +
                    `Hay ${this.totalSlotsRequired} cupos de guardia configurados en el mes, pero la suma de las cuotas del personal activo es ${this.totalCapacity} guardias (${this.activeDoctorsCount} médicos).\n\n` +
                    (diff > 0 ? `Sobran ${diff} cupos de guardia.` : `Faltan ${Math.abs(diff)} cupos de guardia.`) +
                    `\n¿Deseas auto-balancear los días automáticamente para que coincida exactamente con las cuotas asignadas?`
                );
                if (confirmBalance) {
                    this.autoBalanceDoubles();
                } else {
                    return;
                }
            }

            this.isSolving = true;
            this.errorMessage = '';
            this.diagnostics = [];

            const payload = {
                year: this.year,
                month: this.month,
                country_code: this.countryCode,
                doctors: this.doctors,
                days_config: this.days,
                restrictions: this.restrictions,
                strict_quota: this.strictQuota,
                avoid_three_in_five_days: this.avoidThreeInFiveDays,
                prioritize_thursdays: this.prioritizeThursdays,
                prioritize_weekends: this.prioritizeWeekends,
                max_solve_time_seconds: 15
            };

            try {
                const res = await fetch('/api/solve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();

                if (data.success) {
                    this.schedule = data.schedule;
                    this.stats = data.stats;
                    this.summary = data.summary;
                    const nowIso = new Date().toISOString();
                    this.solvedAtIso = nowIso;
                    this.lastSolvedAt = new Date(nowIso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
                    this.activeTab = 'calendar';

                    await this.saveMonthlyPlanNow();
                    this.showToast("Calendario generado y guardado automáticamente");
                } else {
                    this.errorMessage = data.message || "No fue posible encontrar una solución válida.";
                    this.diagnostics = data.diagnostics || [];
                    this.showErrorModal = true;
                }
            } catch (err) {
                this.errorMessage = "Error de conexión con el servidor: " + err.message;
                this.showErrorModal = true;
            } finally {
                this.isSolving = false;
            }
        },

        async jumpToSavedMonth(item) {
            if (item.year === this.year && item.month === this.month) return;
            await this.flushPendingSaves();
            this.year = item.year;
            this.month = item.month;
            await this.loadPeriodData();
            this.activeTab = 'calendar';
        },

        async disableThreeInFiveAndRetry() {
            this.avoidThreeInFiveDays = false;
            this.showErrorModal = false;
            this.scheduleMonthlySave();
            await this.generateSchedule();
        },

        // ==========================================
        // EXPORTACIONES Y UTILIDADES
        // ==========================================
        exportCSV() {
            if (this.schedule.length === 0) {
                alert("Primero genera el calendario para poder exportar.");
                return;
            }

            let csv = "Día,Fecha,Día Semana,Tipo Guardia,Feriado,Médico Asignado 1,Médico Asignado 2,Médico Asignado 3\n";
            this.schedule.forEach(d => {
                const m1 = d.assigned_doctors[0] ? d.assigned_doctors[0].doctor_name : "";
                const m2 = d.assigned_doctors[1] ? d.assigned_doctors[1].doctor_name : "";
                const m3 = d.assigned_doctors[2] ? d.assigned_doctors[2].doctor_name : "";
                const labels = { 0: "Libre (0)", 1: "Simple (1)", 2: "Doble (2)", 3: "Triple (3)" };
                const tipo = labels[d.required_shifts] || `${d.required_shifts}`;
                const feriado = d.holiday_name ? `"${d.holiday_name}"` : "No";
                csv += `${d.day},${d.date},${d.weekday_name},${tipo},${feriado},"${m1}","${m2}","${m3}"\n`;
            });

            csv += "\n\nResumen de Estadísticas por Profesional\n";
            csv += "Médico,Total Guardias,Cuota Meta,Jueves,Fines de Semana,Feriados,Violaciones Descanso,Bloques 3-en-5-Días\n";
            this.stats.forEach(s => {
                csv += `"${s.doctor_name}",${s.total_shifts},${s.target_shifts},${s.thursday_shifts},${s.weekend_shifts},${s.holiday_shifts},${s.consecutive_violations},${s.three_in_five_violations || 0}\n`;
            });

            const blob = new Blob(["\uFEFF" + csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `Guardias_${this.monthName}_${this.year}.csv`;
            a.click();
            URL.revokeObjectURL(url);
            this.showToast("Archivo CSV descargado exitosamente");
        },

        printSchedule() {
            this.activeTab = 'calendar';
            setTimeout(() => {
                window.print();
            }, 100);
        },

        exportJSON() {
            const config = {
                year: this.year,
                month: this.month,
                countryCode: this.countryCode,
                doctors: this.doctors,
                days: this.days,
                restrictions: this.restrictions,
                strictQuota: this.strictQuota,
                avoidThreeInFiveDays: this.avoidThreeInFiveDays,
                schedule: this.schedule,
                stats: this.stats,
                summary: this.summary
            };
            const str = JSON.stringify(config, null, 2);
            const blob = new Blob([str], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `Respaldo_Guardias_${this.monthName}_${this.year}.json`;
            a.click();
            URL.revokeObjectURL(url);
        },

        showToast(msg) {
            this.successToast = msg;
            setTimeout(() => {
                if (this.successToast === msg) {
                    this.successToast = null;
                }
            }, 3500);
        }
    };
}
