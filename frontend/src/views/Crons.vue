<template>
  <div class="sv-view">
    <!-- Cabecera page-head -->
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Tareas Cron</h1>
        <p class="page-head__sub">
          {{ crons.length }} {{ crons.length === 1 ? 'tarea programada' : 'tareas programadas' }}
          · cada tarea se ejecuta bajo el usuario de su propietario (aislada)
        </p>
      </div>
      <div class="cr-head-actions">
        <select v-if="isAdminOrReseller" class="svq-input cr-filter"
                v-model.number="filterUserId" @change="loadCrons">
          <option :value="null">Todos los usuarios</option>
          <option v-for="u in clientUsers" :key="u.id" :value="u.id">{{ u.username }}</option>
        </select>
        <BaseButton variant="primary" size="sm" @click="openCreate">
          <i class="bi bi-plus-circle"></i> Nueva tarea
        </BaseButton>
      </div>
    </div>

    <BaseCard title="Tareas programadas" icon="clock-history" flush>
      <div v-if="loading" class="cr-center"><div class="spinner-border spinner-border-sm"></div></div>

      <EmptyState v-else-if="crons.length === 0" icon="clock-history"
                  title="Sin tareas cron"
                  :description="isAdminOrReseller && filterUserId ? 'Este usuario no tiene tareas cron.' : 'No hay tareas cron configuradas. Crea la primera con «Nueva tarea».'" />

      <div v-else class="cr-table-wrap">
        <table class="cr-table">
          <thead>
            <tr>
              <th v-if="isAdminOrReseller">Usuario</th>
              <th>Expresión</th>
              <th>Comando</th>
              <th>Comentario</th>
              <th>Estado</th>
              <th>Creado</th>
              <th class="cr-right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="cron in crons" :key="cron.id" :class="{ 'cr-row--off': !cron.is_active }">
              <td v-if="isAdminOrReseller">
                <span class="cr-userbadge"><i class="bi bi-person"></i> {{ cron.username || '—' }}</span>
              </td>
              <td>
                <code class="cr-code">{{ cron.minute }} {{ cron.hour }} {{ cron.day }} {{ cron.month }} {{ cron.weekday }}</code>
                <div class="cr-muted">{{ describeCron(cron) }}</div>
              </td>
              <td><code class="cr-code cr-cmd">{{ cron.command }}</code></td>
              <td class="cr-muted">{{ cron.comment || '—' }}</td>
              <td>
                <span class="cr-status" :class="cron.is_active ? 'cr-status--on' : 'cr-status--off'">
                  {{ cron.is_active ? 'Activo' : 'Inactivo' }}
                </span>
              </td>
              <td class="cr-muted">{{ formatDate(cron.created_at) }}</td>
              <td class="cr-right">
                <div class="cr-actions">
                  <button class="cr-iconbtn" :title="cron.is_active ? 'Desactivar' : 'Activar'" @click="toggleCron(cron)">
                    <i :class="cron.is_active ? 'bi bi-pause' : 'bi bi-play'"></i>
                  </button>
                  <button class="cr-iconbtn" title="Editar" @click="openEdit(cron)">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button class="cr-iconbtn cr-iconbtn--danger" title="Eliminar" @click="deleteCron(cron.id)">
                    <i class="bi bi-trash"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <!-- Modal crear/editar -->
    <div v-if="showForm" class="cr-modal" @click.self="closeForm">
      <div class="cr-modal__dialog">
        <div class="cr-modal__head">
          <h5 class="cr-modal__title">
            <i class="bi" :class="editing ? 'bi-pencil' : 'bi-plus-circle'"></i>
            {{ editing ? 'Editar tarea cron' : 'Nueva tarea cron' }}
          </h5>
          <button type="button" class="cr-modal__close" @click="closeForm"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="cr-modal__body">

          <!-- Usuario propietario (admin/reseller, solo al crear) -->
          <div v-if="isAdminOrReseller && !editing" class="cr-field">
            <label>Usuario propietario</label>
            <select v-model.number="form.user_id" class="svq-input">
              <option :value="null">Yo (administrador — se ejecuta como root)</option>
              <option v-for="u in clientUsers" :key="u.id" :value="u.id">
                {{ u.username }} ({{ u.email }})
              </option>
            </select>
            <small class="cr-muted">
              Si eliges un cliente, la tarea se ejecuta <strong>bajo su usuario</strong> del sistema (aislada), no como root.
            </small>
          </div>

          <!-- Presets -->
          <div class="cr-field">
            <label>Presets</label>
            <div class="cr-presets">
              <button v-for="p in presets" :key="p.label" type="button"
                      class="cr-preset" @click="applyPreset(p)">{{ p.label }}</button>
            </div>
          </div>

          <!-- Campos de tiempo -->
          <div class="cr-timegrid">
            <div class="cr-field">
              <label>Minuto</label>
              <input v-model="form.minute" class="svq-input mono" placeholder="*" />
            </div>
            <div class="cr-field">
              <label>Hora</label>
              <input v-model="form.hour" class="svq-input mono" placeholder="*" />
            </div>
            <div class="cr-field">
              <label>Día</label>
              <input v-model="form.day" class="svq-input mono" placeholder="*" />
            </div>
            <div class="cr-field">
              <label>Mes</label>
              <input v-model="form.month" class="svq-input mono" placeholder="*" />
            </div>
            <div class="cr-field">
              <label>Día semana</label>
              <input v-model="form.weekday" class="svq-input mono" placeholder="*" />
            </div>
          </div>

          <!-- Vista previa expresión -->
          <div class="cr-preview">
            <code class="cr-preview__expr">{{ form.minute }} {{ form.hour }} {{ form.day }} {{ form.month }} {{ form.weekday }}</code>
            <span class="cr-muted">{{ describeCron(form) }}</span>
          </div>

          <!-- Comando -->
          <div class="cr-field">
            <label>Comando <span class="cr-req">*</span></label>
            <input v-model="form.command" class="svq-input mono"
                   placeholder="/usr/bin/php /home/usuario/web/dominio.com/public_html/artisan schedule:run" />
            <small class="cr-muted">Ruta absoluta al script o ejecutable. No se permiten <code>;</code> ni <code>&amp;&amp;</code>.</small>
          </div>

          <!-- Comentario -->
          <div class="cr-field">
            <label>Comentario (opcional)</label>
            <input v-model="form.comment" class="svq-input" placeholder="Ej: Limpieza de sesiones" />
          </div>

          <div v-if="formError" class="cr-alert-error">{{ formError }}</div>
        </div>
        <div class="cr-modal__foot">
          <BaseButton variant="ghost" size="sm" @click="closeForm">Cancelar</BaseButton>
          <BaseButton variant="primary" size="sm" :loading="saving" @click="submitForm">
            {{ editing ? 'Guardar cambios' : 'Crear tarea' }}
          </BaseButton>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api.js'
import { useMainStore } from '../stores/useMainStore.js'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import EmptyState from '../components/ui/EmptyState.vue'

const PRESETS = [
  { label: 'Cada minuto',   minute: '*',  hour: '*', day: '*', month: '*', weekday: '*' },
  { label: 'Cada hora',     minute: '0',  hour: '*', day: '*', month: '*', weekday: '*' },
  { label: 'Diario 02:00',  minute: '0',  hour: '2', day: '*', month: '*', weekday: '*' },
  { label: 'Semanal (dom)', minute: '0',  hour: '3', day: '*', month: '*', weekday: '0' },
  { label: 'Mensual (1º)',  minute: '0',  hour: '4', day: '1', month: '*', weekday: '*' },
  { label: 'Cada 5 min',    minute: '*/5',hour: '*', day: '*', month: '*', weekday: '*' },
  { label: 'Cada 15 min',   minute: '*/15',hour:'*', day: '*', month: '*', weekday: '*' },
  { label: 'Cada 30 min',   minute: '*/30',hour:'*', day: '*', month: '*', weekday: '*' },
]

function describeCron(c) {
  const { minute, hour, day, month, weekday } = c
  if (minute === '*' && hour === '*' && day === '*' && month === '*' && weekday === '*')
    return 'Cada minuto'
  if (minute === '0' && hour === '*') return 'Cada hora'
  if (minute === '0' && day === '*' && month === '*' && weekday === '*') return `Diario a las ${hour}:00`
  if (minute === '0' && day === '1') return `Mensual (día 1 a las ${hour}:00)`
  if (minute?.startsWith('*/')) return `Cada ${minute.slice(2)} minutos`
  return `${minute} ${hour} ${day} ${month} ${weekday}`
}

function emptyForm() {
  return { minute: '*', hour: '*', day: '*', month: '*', weekday: '*', command: '', comment: '', user_id: null }
}

export default {
  name: 'Crons',
  components: { BaseCard, BaseButton, EmptyState },
  setup() {
    const store = useMainStore()
    const crons   = ref([])
    const loading = ref(false)
    const showForm = ref(false)
    const editing  = ref(null)   // cron object being edited, or null
    const form     = ref(emptyForm())
    const formError = ref('')
    const saving   = ref(false)

    // Usuarios (para asignar propietario y filtrar — solo admin/reseller)
    const users = ref([])
    const filterUserId = ref(null)
    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role) || store.currentUser?.is_admin
    )
    const clientUsers = computed(() =>
      users.value.filter(u => u.role !== 'admin' && !u.is_admin)
    )
    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return
      try {
        const data = await api.getUsers(0, 1000)
        users.value = Array.isArray(data) ? data : []
      } catch (e) { /* no bloqueante */ }
    }

    const loadCrons = async () => {
      loading.value = true
      try {
        crons.value = await api.getCrons(filterUserId.value || null)
      } catch (e) {
        store.showNotification('Error cargando crons: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const openCreate = () => {
      editing.value = null
      form.value = emptyForm()
      // Si hay un usuario filtrado, preasignarlo como propietario por comodidad
      if (filterUserId.value) form.value.user_id = filterUserId.value
      formError.value = ''
      showForm.value = true
    }

    const openEdit = (cron) => {
      editing.value = cron
      form.value = {
        minute:  cron.minute,
        hour:    cron.hour,
        day:     cron.day,
        month:   cron.month,
        weekday: cron.weekday,
        command: cron.command,
        comment: cron.comment || '',
      }
      formError.value = ''
      showForm.value = true
    }

    const closeForm = () => { showForm.value = false }

    const applyPreset = (p) => {
      form.value.minute  = p.minute
      form.value.hour    = p.hour
      form.value.day     = p.day
      form.value.month   = p.month
      form.value.weekday = p.weekday
    }

    const submitForm = async () => {
      formError.value = ''
      if (!form.value.command.trim()) {
        formError.value = 'El comando es obligatorio.'
        return
      }
      saving.value = true
      try {
        if (editing.value) {
          await api.updateCron(editing.value.id, form.value)
          store.showNotification('Tarea cron actualizada', 'success')
        } else {
          await api.createCron(form.value)
          store.showNotification('Tarea cron creada', 'success')
        }
        showForm.value = false
        await loadCrons()
      } catch (e) {
        formError.value = e.message
      } finally {
        saving.value = false
      }
    }

    const toggleCron = async (cron) => {
      try {
        await api.toggleCron(cron.id)
        store.showNotification(
          cron.is_active ? 'Tarea desactivada' : 'Tarea activada',
          cron.is_active ? 'warning' : 'success'
        )
        await loadCrons()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    const deleteCron = async (cronId) => {
      if (!confirm('¿Eliminar esta tarea cron?')) return
      try {
        await api.deleteCron(cronId)
        store.showNotification('Tarea eliminada', 'success')
        await loadCrons()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    const formatDate = (dt) => {
      if (!dt) return '—'
      return new Date(dt).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    }

    onMounted(() => { loadCrons(); loadUsers() })

    return {
      crons, loading,
      showForm, editing, form, formError, saving,
      isAdminOrReseller, clientUsers, filterUserId,
      presets: PRESETS,
      openCreate, openEdit, closeForm,
      applyPreset, submitForm,
      toggleCron, deleteCron,
      describeCron, formatDate,
    }
  }
}
</script>

<style scoped>
/* Cabecera */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: var(--sp-5); flex-wrap: wrap; }
.page-head__title { font-size: 1.5rem; font-weight: var(--fw-bold, 700); margin: 0; letter-spacing: -.01em; }
.page-head__sub { color: var(--text-muted); margin: .25rem 0 0; font-size: var(--fs-sm); }
.cr-head-actions { display: flex; align-items: center; gap: var(--sp-2); }
.cr-filter { width: auto; min-width: 180px; }

.cr-center { display: flex; justify-content: center; padding: var(--sp-6) 0; color: var(--text-muted); }
.cr-muted { color: var(--text-muted); font-size: var(--fs-sm); }

/* Tabla */
.cr-table-wrap { overflow-x: auto; }
.cr-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.cr-table thead th {
  text-align: left; padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .04em;
  color: var(--text-muted); font-weight: var(--fw-semibold);
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.cr-table tbody td { padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); vertical-align: middle; }
.cr-table tbody tr:last-child td { border-bottom: none; }
.cr-table tbody tr:hover { background: var(--surface-inset); }
.cr-row--off { opacity: .55; }
.cr-right { text-align: right; }
.cr-code { font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-secondary); }
.cr-cmd { display: block; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cr-userbadge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: var(--fs-xs); padding: 2px 8px; border-radius: var(--r-pill);
  background: var(--surface-inset); border: 1px solid var(--border); color: var(--text-secondary);
}
.cr-status { display: inline-block; font-size: var(--fs-xs); font-weight: var(--fw-semibold); padding: 2px 9px; border-radius: var(--r-pill); }
.cr-status--on  { background: var(--success-bg); color: var(--success); }
.cr-status--off { background: var(--surface-inset); color: var(--text-muted); }

/* Botones de acción */
.cr-actions { display: inline-flex; gap: 4px; }
.cr-iconbtn {
  width: 30px; height: 30px; display: inline-grid; place-items: center;
  border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary);
  border-radius: var(--r-sm); cursor: pointer; transition: all .12s;
}
.cr-iconbtn:hover { background: var(--surface-inset); color: var(--text); border-color: var(--border-strong); }
.cr-iconbtn--danger:hover { color: var(--danger); border-color: var(--danger); }

/* Modal */
.cr-modal { position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,.5); display: flex; align-items: flex-start; justify-content: center; padding: 4vh 1rem; overflow-y: auto; }
.cr-modal__dialog { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-lg, 0 20px 60px rgba(0,0,0,.3)); width: 100%; max-width: 640px; }
.cr-modal__head { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-4) var(--sp-5); border-bottom: 1px solid var(--border); background: var(--surface-inset); border-radius: var(--r-lg) var(--r-lg) 0 0; }
.cr-modal__title { margin: 0; font-size: var(--fs-md); font-weight: var(--fw-semibold); display: flex; align-items: center; gap: .5rem; }
.cr-modal__title .bi { color: var(--svq-orange); }
.cr-modal__close { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.1rem; padding: 4px; border-radius: var(--r-sm); }
.cr-modal__close:hover { background: var(--surface); color: var(--text); }
.cr-modal__body { padding: var(--sp-5); display: flex; flex-direction: column; gap: var(--sp-4); }
.cr-modal__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); padding: var(--sp-4) var(--sp-5); border-top: 1px solid var(--border); }

/* Campos */
.cr-field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.cr-field > label { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); }
/* Los inputs no deben desbordar su contenedor (grid/flex) */
.cr-field .svq-input { width: 100%; box-sizing: border-box; min-width: 0; }
.cr-req { color: var(--danger); }
.cr-timegrid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--sp-2); }
@media (max-width: 560px) { .cr-timegrid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.cr-presets { display: flex; flex-wrap: wrap; gap: 6px; }
.cr-preset {
  font-size: var(--fs-xs); padding: 4px 10px; border-radius: var(--r-pill);
  border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary); cursor: pointer; transition: all .12s;
}
.cr-preset:hover { border-color: var(--svq-orange); color: var(--svq-orange); }

.cr-preview { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); background: var(--surface-inset); border-radius: var(--r-md); flex-wrap: wrap; }
.cr-preview__expr { font-family: var(--font-mono); font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); }

.cr-alert-error { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger-border); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md); font-size: var(--fs-sm); }
</style>
