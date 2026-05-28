<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-hdd-stack"></i> Copias de seguridad</h2>
      <button class="btn btn-primary" @click="openCreate">
        <i class="bi bi-plus-circle"></i> Nuevo backup
      </button>
    </div>

    <div class="alert alert-info d-flex gap-2 align-items-start mb-3" role="alert">
      <i class="bi bi-info-circle-fill mt-1"></i>
      <div class="small">
        Cada backup respalda lo que selecciones (<strong>web</strong>, <strong>bases de datos</strong> y/o
        <strong>correo</strong>) de un dominio. Las copias <strong>incrementales</strong> solo guardan lo que
        cambió usando enlaces duros, y las bases de datos se comprimen para ocupar poco disco. El destino
        puede ser local (<code>/backups</code>) o un servidor remoto por <strong>SFTP</strong>.
      </div>
    </div>

    <!-- Tabla de jobs -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="jobs.length === 0" class="alert alert-secondary m-3 mb-0">
          No tienes backups configurados todavía.
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Nombre</th>
                <th>Dominio</th>
                <th>Contenido</th>
                <th>Tipo</th>
                <th>Destino</th>
                <th>Última copia</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="job in jobs" :key="job.id" :class="{'table-secondary text-muted': !job.is_active}">
                <td>
                  <div class="fw-semibold">{{ job.name }}</div>
                  <div v-if="job.description" class="text-muted small">{{ job.description }}</div>
                </td>
                <td class="small">{{ domainName(job.domain_id) }}</td>
                <td>
                  <span v-if="job.include_files" class="badge bg-primary me-1" title="Archivos web">Web</span>
                  <span v-if="job.include_databases" class="badge bg-info me-1" title="Bases de datos">BD</span>
                  <span v-if="job.include_mail" class="badge bg-warning text-dark" title="Correo">Correo</span>
                </td>
                <td>
                  <span class="badge" :class="job.backup_type === 'incremental' ? 'bg-success' : 'bg-secondary'">
                    {{ job.backup_type === 'incremental' ? 'Incremental' : 'Completa' }}
                  </span>
                </td>
                <td class="small">
                  <i :class="job.destination_type === 'sftp' ? 'bi bi-hdd-network' : 'bi bi-hdd'"></i>
                  {{ job.destination_type === 'sftp' ? (job.sftp_host || 'SFTP') : 'Local' }}
                </td>
                <td class="small">
                  <span v-if="runningJobId === job.id" class="text-primary">
                    <span class="spinner-border spinner-border-sm me-1"></span> En curso…
                  </span>
                  <template v-else-if="job.last_record_status">
                    <span :class="statusBadge(job.last_record_status)">{{ statusLabel(job.last_record_status) }}</span>
                    <div class="text-muted">
                      {{ formatDate(job.last_run) }}
                      <span v-if="job.last_record_size_mb"> · {{ job.last_record_size_mb }} MB</span>
                    </div>
                  </template>
                  <span v-else class="text-muted">Nunca</span>
                </td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-success" title="Ejecutar ahora"
                            :disabled="runningJobId === job.id || !job.is_active" @click="runJob(job)">
                      <i class="bi bi-play-fill"></i>
                    </button>
                    <button class="btn btn-outline-secondary" title="Historial" @click="openHistory(job)">
                      <i class="bi bi-clock-history"></i>
                    </button>
                    <button class="btn btn-outline-warning" title="Editar" @click="openEdit(job)">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger" title="Eliminar" @click="deleteJob(job)">
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
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">{{ editing ? 'Editar backup' : 'Nuevo backup' }}</h5>
            <button type="button" class="btn-close" @click="closeForm"></button>
          </div>
          <div class="modal-body">
            <div class="row g-3">
              <div class="col-md-6">
                <label class="form-label fw-semibold">Nombre <span class="text-danger">*</span></label>
                <input v-model="form.name" class="form-control" placeholder="Ej: Backup diario tienda" />
              </div>
              <div class="col-md-6">
                <label class="form-label fw-semibold">Dominio <span class="text-danger">*</span></label>
                <select v-model="form.domain_id" class="form-select" :disabled="editing">
                  <option :value="null" disabled>Selecciona un dominio</option>
                  <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.domain_name }}</option>
                </select>
              </div>
              <div class="col-12">
                <label class="form-label">Descripción (opcional)</label>
                <input v-model="form.description" class="form-control" placeholder="Notas sobre este backup" />
              </div>
            </div>

            <hr />

            <!-- Contenido -->
            <label class="form-label fw-semibold d-block">¿Qué respaldar?</label>
            <div class="d-flex flex-wrap gap-4 mb-3">
              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="incFiles" v-model="form.include_files" />
                <label class="form-check-label" for="incFiles"><i class="bi bi-folder"></i> Archivos web</label>
              </div>
              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="incDb" v-model="form.include_databases" />
                <label class="form-check-label" for="incDb"><i class="bi bi-database"></i> Bases de datos</label>
              </div>
              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="incMail" v-model="form.include_mail" />
                <label class="form-check-label" for="incMail"><i class="bi bi-envelope"></i> Correo</label>
              </div>
            </div>

            <div class="row g-3">
              <!-- Tipo -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Tipo de copia</label>
                <select v-model="form.backup_type" class="form-select">
                  <option value="incremental">Incremental (solo cambios, recomendado)</option>
                  <option value="full">Completa (todo cada vez)</option>
                </select>
              </div>
              <!-- Retención -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Copias a conservar</label>
                <input v-model.number="form.retention_copies" type="number" min="1" max="365" class="form-control" />
                <div class="form-text">Se eliminan las más antiguas al superar este número (solo destino local).</div>
              </div>
            </div>

            <hr />

            <!-- Destino -->
            <label class="form-label fw-semibold d-block">Destino</label>
            <div class="d-flex gap-4 mb-3">
              <div class="form-check">
                <input class="form-check-input" type="radio" id="destLocal" value="local" v-model="form.destination_type" />
                <label class="form-check-label" for="destLocal"><i class="bi bi-hdd"></i> Local</label>
              </div>
              <div class="form-check">
                <input class="form-check-input" type="radio" id="destSftp" value="sftp" v-model="form.destination_type" />
                <label class="form-check-label" for="destSftp"><i class="bi bi-hdd-network"></i> Remoto (SFTP)</label>
              </div>
            </div>

            <div v-if="form.destination_type === 'local'" class="mb-2">
              <label class="form-label">Ruta local</label>
              <input v-model="form.local_path" class="form-control font-monospace" placeholder="/backups" />
            </div>

            <div v-else class="row g-3">
              <div class="col-md-8">
                <label class="form-label">Host SFTP <span class="text-danger">*</span></label>
                <input v-model="form.sftp_host" class="form-control" placeholder="backup.midominio.com" />
              </div>
              <div class="col-md-4">
                <label class="form-label">Puerto</label>
                <input v-model.number="form.sftp_port" type="number" class="form-control" placeholder="22" />
              </div>
              <div class="col-md-6">
                <label class="form-label">Usuario <span class="text-danger">*</span></label>
                <input v-model="form.sftp_user" class="form-control" placeholder="backupuser" />
              </div>
              <div class="col-md-6">
                <label class="form-label">Contraseña</label>
                <input v-model="form.sftp_password" type="password" class="form-control"
                       :placeholder="editing ? 'Dejar en blanco para no cambiar' : 'Opcional si usas clave SSH'" />
              </div>
              <div class="col-md-6">
                <label class="form-label">Ruta remota</label>
                <input v-model="form.sftp_path" class="form-control font-monospace" placeholder="/backups" />
              </div>
              <div class="col-md-6">
                <label class="form-label">Clave SSH privada (ruta en el servidor)</label>
                <input v-model="form.sftp_key_path" class="form-control font-monospace" placeholder="/root/.ssh/id_backup" />
              </div>
              <div class="col-12" v-if="editing">
                <button class="btn btn-sm btn-outline-info" :disabled="testingSftp" @click="testSftp">
                  <span v-if="testingSftp" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-plug"></i> Probar conexión
                </button>
                <span v-if="sftpTestMsg" :class="sftpTestOk ? 'text-success ms-2' : 'text-danger ms-2'">
                  {{ sftpTestMsg }}
                </span>
              </div>
            </div>

            <div class="form-check mt-3">
              <input class="form-check-input" type="checkbox" id="jobActive" v-model="form.is_active" />
              <label class="form-check-label" for="jobActive">Backup activo</label>
            </div>

            <div v-if="formError" class="alert alert-danger mt-3 mb-0">{{ formError }}</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="closeForm">Cancelar</button>
            <button class="btn btn-primary" :disabled="saving" @click="submitForm">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              {{ editing ? 'Guardar cambios' : 'Crear backup' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal historial -->
    <div v-if="showHistory" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Historial · {{ historyJob?.name }}</h5>
            <button type="button" class="btn-close" @click="showHistory = false"></button>
          </div>
          <div class="modal-body">
            <div v-if="historyLoading" class="text-center py-4">
              <div class="spinner-border" role="status"></div>
            </div>
            <div v-else-if="records.length === 0" class="alert alert-secondary mb-0">
              Este backup no se ha ejecutado todavía.
            </div>
            <div v-else class="table-responsive">
              <table class="table table-sm align-middle mb-0">
                <thead class="table-light">
                  <tr>
                    <th>Fecha</th>
                    <th>Estado</th>
                    <th>Tipo</th>
                    <th>Tamaño</th>
                    <th>Archivos</th>
                    <th>BD</th>
                    <th>Duración</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="r in records" :key="r.id">
                    <tr>
                      <td class="small">{{ formatDateTime(r.started_at) }}</td>
                      <td><span :class="statusBadge(r.status)">{{ statusLabel(r.status) }}</span></td>
                      <td class="small">{{ r.is_incremental ? 'Incremental' : 'Completa' }}</td>
                      <td class="small">{{ r.size_mb }} MB</td>
                      <td class="small">{{ r.files_transferred }}/{{ r.files_total }}</td>
                      <td class="small">{{ r.db_count }}</td>
                      <td class="small">{{ r.duration_seconds != null ? r.duration_seconds + 's' : '—' }}</td>
                      <td>
                        <button v-if="r.log_output || r.error_message"
                                class="btn btn-sm btn-outline-secondary py-0"
                                @click="expanded === r.id ? expanded = null : expanded = r.id">
                          <i class="bi bi-card-text"></i>
                        </button>
                      </td>
                    </tr>
                    <tr v-if="expanded === r.id">
                      <td colspan="8" class="bg-light">
                        <div v-if="r.error_message" class="text-danger small mb-2">{{ r.error_message }}</div>
                        <pre class="small mb-0" style="max-height:240px;overflow:auto;white-space:pre-wrap">{{ r.log_output || 'Sin log' }}</pre>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showHistory = false">Cerrar</button>
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

function emptyForm() {
  return {
    name: '',
    description: '',
    domain_id: null,
    include_files: true,
    include_databases: true,
    include_mail: false,
    backup_type: 'incremental',
    destination_type: 'local',
    local_path: '/backups',
    sftp_host: '',
    sftp_port: 22,
    sftp_user: '',
    sftp_password: '',
    sftp_path: '/backups',
    sftp_key_path: '',
    retention_copies: 7,
    is_active: true,
  }
}

export default {
  name: 'Backups',
  setup() {
    const store = useMainStore()
    const jobs = ref([])
    const domains = ref([])
    const loading = ref(false)

    const showForm = ref(false)
    const editing = ref(null)
    const form = ref(emptyForm())
    const formError = ref('')
    const saving = ref(false)

    const testingSftp = ref(false)
    const sftpTestMsg = ref('')
    const sftpTestOk = ref(false)

    const runningJobId = ref(null)

    const showHistory = ref(false)
    const historyJob = ref(null)
    const records = ref([])
    const historyLoading = ref(false)
    const expanded = ref(null)

    const domainName = (id) => {
      const d = domains.value.find(x => x.id === id)
      return d ? d.domain_name : '—'
    }

    const statusLabel = (s) => ({
      pending: 'Pendiente', running: 'En curso', success: 'Correcto',
      failed: 'Fallido', cancelled: 'Cancelado',
    }[s] || s)

    const statusBadge = (s) => 'badge ' + ({
      success: 'bg-success', failed: 'bg-danger', running: 'bg-primary',
      pending: 'bg-secondary', cancelled: 'bg-secondary',
    }[s] || 'bg-secondary')

    const loadJobs = async () => {
      loading.value = true
      try {
        jobs.value = await api.getBackupJobs()
      } catch (e) {
        store.showNotification('Error cargando backups: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const loadDomains = async () => {
      try {
        domains.value = await api.getDomains() || []
      } catch (e) {
        domains.value = []
      }
    }

    const openCreate = () => {
      editing.value = null
      form.value = emptyForm()
      formError.value = ''
      sftpTestMsg.value = ''
      showForm.value = true
    }

    const openEdit = (job) => {
      editing.value = job
      form.value = {
        name: job.name,
        description: job.description || '',
        domain_id: job.domain_id,
        include_files: job.include_files,
        include_databases: job.include_databases,
        include_mail: job.include_mail,
        backup_type: job.backup_type,
        destination_type: job.destination_type,
        local_path: job.local_path || '/backups',
        sftp_host: job.sftp_host || '',
        sftp_port: job.sftp_port || 22,
        sftp_user: job.sftp_user || '',
        sftp_password: '',
        sftp_path: job.sftp_path || '/backups',
        sftp_key_path: job.sftp_key_path || '',
        retention_copies: job.retention_copies,
        is_active: job.is_active,
      }
      formError.value = ''
      sftpTestMsg.value = ''
      showForm.value = true
    }

    const closeForm = () => { showForm.value = false }

    const submitForm = async () => {
      formError.value = ''
      if (!form.value.name.trim()) { formError.value = 'El nombre es obligatorio.'; return }
      if (!form.value.domain_id) { formError.value = 'Debes seleccionar un dominio.'; return }
      if (!form.value.include_files && !form.value.include_databases && !form.value.include_mail) {
        formError.value = 'Selecciona al menos un contenido a respaldar.'; return
      }
      if (form.value.destination_type === 'sftp' && (!form.value.sftp_host || !form.value.sftp_user)) {
        formError.value = 'Host y usuario SFTP son obligatorios para destino remoto.'; return
      }
      saving.value = true
      try {
        if (editing.value) {
          await api.updateBackupJob(editing.value.id, form.value)
          store.showNotification('Backup actualizado', 'success')
        } else {
          await api.createBackupJob(form.value)
          store.showNotification('Backup creado', 'success')
        }
        showForm.value = false
        await loadJobs()
      } catch (e) {
        formError.value = e.message
      } finally {
        saving.value = false
      }
    }

    const testSftp = async () => {
      if (!editing.value) return
      testingSftp.value = true
      sftpTestMsg.value = ''
      try {
        const res = await api.testBackupSftp(editing.value.id)
        sftpTestOk.value = res.ok
        sftpTestMsg.value = res.message
      } catch (e) {
        sftpTestOk.value = false
        sftpTestMsg.value = e.message
      } finally {
        testingSftp.value = false
      }
    }

    const pollRecord = async (recordId) => {
      const FINAL = ['success', 'failed', 'cancelled']
      for (let i = 0; i < 600; i++) {   // hasta ~20 min (2s * 600)
        await new Promise(r => setTimeout(r, 2000))
        let rec
        try {
          rec = await api.getBackupRecord(recordId)
        } catch (e) {
          break
        }
        if (FINAL.includes(rec.status)) return rec
      }
      return null
    }

    const runJob = async (job) => {
      runningJobId.value = job.id
      try {
        const rec = await api.runBackupJob(job.id)
        store.showNotification('Backup iniciado…', 'info')
        const final = await pollRecord(rec.id)
        if (final && final.status === 'success') {
          store.showNotification(`Backup "${job.name}" completado (${final.size_mb} MB)`, 'success')
        } else if (final && final.status === 'failed') {
          store.showNotification(`Backup "${job.name}" falló: ${final.error_message || 'error desconocido'}`, 'danger')
        } else {
          store.showNotification('El backup sigue en curso; revisa el historial.', 'warning')
        }
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        runningJobId.value = null
        await loadJobs()
      }
    }

    const openHistory = async (job) => {
      historyJob.value = job
      showHistory.value = true
      expanded.value = null
      historyLoading.value = true
      try {
        records.value = await api.getBackupRecords(job.id)
      } catch (e) {
        store.showNotification('Error cargando historial: ' + e.message, 'danger')
        records.value = []
      } finally {
        historyLoading.value = false
      }
    }

    const deleteJob = async (job) => {
      if (!confirm(`¿Eliminar el backup "${job.name}"? No se borran las copias ya guardadas en disco.`)) return
      try {
        await api.deleteBackupJob(job.id)
        store.showNotification('Backup eliminado', 'success')
        await loadJobs()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    const formatDate = (dt) => {
      if (!dt) return '—'
      return new Date(dt).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    }
    const formatDateTime = (dt) => {
      if (!dt) return '—'
      return new Date(dt).toLocaleString('es-ES', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      })
    }

    onMounted(async () => {
      await Promise.all([loadJobs(), loadDomains()])
    })

    return {
      jobs, domains, loading,
      showForm, editing, form, formError, saving,
      testingSftp, sftpTestMsg, sftpTestOk,
      runningJobId,
      showHistory, historyJob, records, historyLoading, expanded,
      domainName, statusLabel, statusBadge,
      openCreate, openEdit, closeForm, submitForm, testSftp,
      runJob, openHistory, deleteJob,
      formatDate, formatDateTime,
    }
  }
}
</script>
