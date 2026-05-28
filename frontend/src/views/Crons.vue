<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-clock-history"></i> Tareas Cron</h2>
      <button class="btn btn-primary" @click="openCreate">
        <i class="bi bi-plus-circle"></i> Nueva tarea
      </button>
    </div>

    <!-- Ayuda rápida -->
    <div class="alert alert-info d-flex gap-2 align-items-start mb-3" role="alert">
      <i class="bi bi-info-circle-fill mt-1"></i>
      <div class="small">
        Las tareas cron se ejecutan con tu usuario del sistema. El formato de tiempo es
        <strong>minuto hora día mes díaDeSemana</strong> (igual que el comando <code>crontab</code>).
        Usa <code>*</code> para «cualquier valor».
      </div>
    </div>

    <!-- Tabla -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="crons.length === 0" class="alert alert-secondary m-3 mb-0">
          No tienes tareas cron configuradas.
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Expresión</th>
                <th>Comando</th>
                <th>Comentario</th>
                <th>Estado</th>
                <th>Creado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="cron in crons" :key="cron.id" :class="{'table-secondary text-muted': !cron.is_active}">
                <td>
                  <code class="small">{{ cron.minute }} {{ cron.hour }} {{ cron.day }} {{ cron.month }} {{ cron.weekday }}</code>
                  <div class="text-muted small">{{ describeCron(cron) }}</div>
                </td>
                <td>
                  <code class="small text-break" style="max-width:300px; display:block">{{ cron.command }}</code>
                </td>
                <td class="small text-muted">{{ cron.comment || '—' }}</td>
                <td>
                  <span v-if="cron.is_active" class="badge bg-success">Activo</span>
                  <span v-else class="badge bg-secondary">Inactivo</span>
                </td>
                <td class="small text-muted">{{ formatDate(cron.created_at) }}</td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button
                      class="btn btn-outline-secondary"
                      :title="cron.is_active ? 'Desactivar' : 'Activar'"
                      @click="toggleCron(cron)"
                    >
                      <i :class="cron.is_active ? 'bi bi-pause' : 'bi bi-play'"></i>
                    </button>
                    <button class="btn btn-outline-warning" title="Editar" @click="openEdit(cron)">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger" title="Eliminar" @click="deleteCron(cron.id)">
                      <i class="bi bi-trash"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal crear/editar -->
    <div v-if="showForm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">{{ editing ? 'Editar tarea cron' : 'Nueva tarea cron' }}</h5>
            <button type="button" class="btn-close" @click="closeForm"></button>
          </div>
          <div class="modal-body">

            <!-- Selector de expresión rápida -->
            <div class="mb-3">
              <label class="form-label fw-semibold">Presets</label>
              <div class="d-flex flex-wrap gap-2">
                <button
                  v-for="p in presets" :key="p.label"
                  type="button"
                  class="btn btn-sm btn-outline-secondary"
                  @click="applyPreset(p)"
                >{{ p.label }}</button>
              </div>
            </div>

            <!-- Campos de tiempo -->
            <div class="row g-2 mb-3">
              <div class="col">
                <label class="form-label small">Minuto</label>
                <input v-model="form.minute" class="form-control form-control-sm font-monospace" placeholder="*" />
              </div>
              <div class="col">
                <label class="form-label small">Hora</label>
                <input v-model="form.hour" class="form-control form-control-sm font-monospace" placeholder="*" />
              </div>
              <div class="col">
                <label class="form-label small">Día</label>
                <input v-model="form.day" class="form-control form-control-sm font-monospace" placeholder="*" />
              </div>
              <div class="col">
                <label class="form-label small">Mes</label>
                <input v-model="form.month" class="form-control form-control-sm font-monospace" placeholder="*" />
              </div>
              <div class="col">
                <label class="form-label small">Día semana</label>
                <input v-model="form.weekday" class="form-control form-control-sm font-monospace" placeholder="*" />
              </div>
            </div>

            <!-- Vista previa expresión -->
            <div class="mb-3">
              <span class="badge bg-dark font-monospace fs-6">
                {{ form.minute }} {{ form.hour }} {{ form.day }} {{ form.month }} {{ form.weekday }}
              </span>
              <span class="ms-2 text-muted small">{{ describeCron(form) }}</span>
            </div>

            <!-- Comando -->
            <div class="mb-3">
              <label class="form-label fw-semibold">Comando <span class="text-danger">*</span></label>
              <input
                v-model="form.command"
                class="form-control font-monospace"
                placeholder="/usr/bin/php /home/usuario/web/dominio.com/public_html/artisan schedule:run"
              />
              <div class="form-text">Ruta absoluta al script o ejecutable. No se permiten <code>;</code> ni <code>&&</code>.</div>
            </div>

            <!-- Comentario -->
            <div class="mb-3">
              <label class="form-label">Comentario (opcional)</label>
              <input v-model="form.comment" class="form-control" placeholder="Ej: Limpieza de sesiones" />
            </div>

            <div v-if="formError" class="alert alert-danger">{{ formError }}</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="closeForm">Cancelar</button>
            <button class="btn btn-primary" :disabled="saving" @click="submitForm">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              {{ editing ? 'Guardar cambios' : 'Crear tarea' }}
            </button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import api from '../services/api.js'
import { useMainStore } from '../stores/useMainStore.js'

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
  return { minute: '*', hour: '*', day: '*', month: '*', weekday: '*', command: '', comment: '' }
}

export default {
  name: 'Crons',
  setup() {
    const store = useMainStore()
    const crons   = ref([])
    const loading = ref(false)
    const showForm = ref(false)
    const editing  = ref(null)   // cron object being edited, or null
    const form     = ref(emptyForm())
    const formError = ref('')
    const saving   = ref(false)

    const loadCrons = async () => {
      loading.value = true
      try {
        crons.value = await api.getCrons()
      } catch (e) {
        store.showNotification('Error cargando crons: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const openCreate = () => {
      editing.value = null
      form.value = emptyForm()
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

    onMounted(loadCrons)

    return {
      crons, loading,
      showForm, editing, form, formError, saving,
      presets: PRESETS,
      openCreate, openEdit, closeForm,
      applyPreset, submitForm,
      toggleCron, deleteCron,
      describeCron, formatDate,
    }
  }
}
</script>
