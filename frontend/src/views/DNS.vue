<template>
  <div class="container-fluid py-4">
    <!-- Cabecera -->
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1"><i class="bi bi-diagram-3 me-2"></i>DNS</h2>
        <p class="text-muted mb-0">Gestión de zonas y registros DNS (BIND9)</p>
      </div>
      <button v-if="isAdmin" class="btn btn-primary" @click="openCreateZone">
        <i class="bi bi-plus-lg me-1"></i> Nueva Zona
      </button>
    </div>

    <!-- Lista de zonas -->
    <div class="card shadow-sm mb-4">
      <div class="card-header">
        <h5 class="mb-0">Zonas DNS</h5>
      </div>
      <div class="card-body p-0">
        <div v-if="loadingZones" class="text-center py-5">
          <div class="spinner-border text-primary"></div>
        </div>
        <div v-else-if="!zones.length" class="text-center py-5 text-muted">
          <i class="bi bi-diagram-3 display-4"></i>
          <p class="mt-2">No hay zonas DNS configuradas.</p>
          <button v-if="isAdmin" class="btn btn-outline-primary btn-sm" @click="openCreateZone">
            Crear primera zona
          </button>
        </div>
        <table v-else class="table table-hover mb-0">
          <thead class="table-light">
            <tr>
              <th>Dominio</th>
              <th>Serial</th>
              <th>Registros</th>
              <th>Estado</th>
              <th>Creada</th>
              <th class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="zone in zones" :key="zone.id">
              <td class="fw-semibold">{{ zone.domain_name }}</td>
              <td><code class="text-muted small">{{ zone.serial }}</code></td>
              <td>
                <span class="badge bg-secondary">{{ zone.record_count }} registros</span>
              </td>
              <td>
                <span :class="zone.is_active ? 'badge bg-success' : 'badge bg-warning text-dark'">
                  {{ zone.is_active ? 'Activa' : 'Inactiva' }}
                </span>
              </td>
              <td class="text-muted small">{{ formatDate(zone.created_at) }}</td>
              <td class="text-end">
                <button class="btn btn-sm btn-outline-primary me-1" @click="openZone(zone)">
                  <i class="bi bi-pencil"></i> Editar
                </button>
                <button v-if="isAdmin" class="btn btn-sm btn-outline-danger" @click="confirmDeleteZone(zone)">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Panel de registros de la zona seleccionada -->
    <div v-if="selectedZone" class="card shadow-sm">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">
          <i class="bi bi-list-ul me-2"></i>
          Registros de <strong>{{ selectedZone.domain_name }}</strong>
          <code class="ms-2 small text-muted">serial {{ selectedZone.serial }}</code>
        </h5>
        <div class="d-flex gap-2">
          <button v-if="isAdmin" class="btn btn-sm btn-success" @click="openAddRecord">
            <i class="bi bi-plus-lg me-1"></i> Añadir Registro
          </button>
          <button class="btn btn-sm btn-outline-secondary" @click="selectedZone = null">
            <i class="bi bi-x"></i> Cerrar
          </button>
        </div>
      </div>
      <div class="card-body p-0">
        <div v-if="loadingRecords" class="text-center py-4">
          <div class="spinner-border spinner-border-sm text-primary"></div>
        </div>
        <table v-else class="table table-sm table-hover mb-0 font-monospace">
          <thead class="table-light">
            <tr>
              <th>Nombre</th>
              <th>Tipo</th>
              <th>Contenido</th>
              <th>TTL</th>
              <th>Prio</th>
              <th v-if="isAdmin" class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rec in records" :key="rec.id">
              <td>{{ rec.name }}</td>
              <td>
                <span :class="typeClass(rec.record_type)" class="badge">{{ rec.record_type }}</span>
              </td>
              <td class="text-break" style="max-width:280px;">{{ rec.content }}</td>
              <td class="text-muted">{{ rec.ttl }}</td>
              <td class="text-muted">{{ rec.priority || '—' }}</td>
              <td v-if="isAdmin" class="text-end">
                <button class="btn btn-sm btn-outline-secondary me-1" @click="openEditRecord(rec)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteRecord(rec)">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
            <tr v-if="!records.length">
              <td :colspan="isAdmin ? 6 : 5" class="text-center text-muted py-3">
                Sin registros
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ──────── Modal: Crear Zona ──────── -->
    <div v-if="showCreateZoneModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-plus-circle me-2"></i>Nueva Zona DNS</h5>
            <button class="btn-close" @click="showCreateZoneModal = false"></button>
          </div>
          <div class="modal-body">
            <label class="form-label">Nombre de dominio</label>
            <input v-model="newZoneName" type="text" class="form-control" placeholder="ejemplo.com" />
            <small class="text-muted">Se creará una zona con registros por defecto (NS, A, MX, SPF).</small>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showCreateZoneModal = false">Cancelar</button>
            <button class="btn btn-primary" :disabled="savingZone || !newZoneName" @click="createZone">
              <span v-if="savingZone" class="spinner-border spinner-border-sm me-2"></span>
              Crear Zona
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ──────── Modal: Añadir / Editar Registro ──────── -->
    <div v-if="showRecordModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              {{ editingRecord ? 'Editar Registro' : 'Añadir Registro' }}
            </h5>
            <button class="btn-close" @click="showRecordModal = false"></button>
          </div>
          <div class="modal-body">
            <template v-if="!editingRecord">
              <div class="mb-3">
                <label class="form-label">Tipo</label>
                <select v-model="recordForm.record_type" class="form-select">
                  <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Nombre <small class="text-muted">(@ para raíz, o subdominio)</small></label>
                <input v-model="recordForm.name" type="text" class="form-control" placeholder="@" />
              </div>
            </template>
            <div class="mb-3">
              <label class="form-label">Contenido</label>
              <input v-model="recordForm.content" type="text" class="form-control" placeholder="IP, hostname, texto..." />
            </div>
            <div class="row g-2">
              <div class="col-6">
                <label class="form-label">TTL</label>
                <input v-model.number="recordForm.ttl" type="number" class="form-control" min="60" max="86400" />
              </div>
              <div v-if="['MX','SRV'].includes(recordForm.record_type)" class="col-6">
                <label class="form-label">Prioridad</label>
                <input v-model.number="recordForm.priority" type="number" class="form-control" min="0" />
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showRecordModal = false">Cancelar</button>
            <button class="btn btn-primary" :disabled="savingRecord" @click="saveRecord">
              <span v-if="savingRecord" class="spinner-border spinner-border-sm me-2"></span>
              {{ editingRecord ? 'Guardar' : 'Añadir' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ──────── Modal: Confirmar borrado zona ──────── -->
    <div v-if="zoneToDelete" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2"></i>Eliminar Zona DNS</h5>
            <button class="btn-close btn-close-white" @click="zoneToDelete = null"></button>
          </div>
          <div class="modal-body">
            <p>¿Seguro que quieres eliminar la zona <strong>{{ zoneToDelete.domain_name }}</strong>?</p>
            <p class="text-danger small">Se eliminarán todos los registros DNS y el fichero de zona de BIND9.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="zoneToDelete = null">Cancelar</button>
            <button class="btn btn-danger" :disabled="deletingZone" @click="deleteZone">
              <span v-if="deletingZone" class="spinner-border spinner-border-sm me-2"></span>
              Eliminar Zona
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ──────── Modal: Confirmar borrado registro ──────── -->
    <div v-if="recordToDelete" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Eliminar Registro DNS</h5>
            <button class="btn-close" @click="recordToDelete = null"></button>
          </div>
          <div class="modal-body">
            ¿Eliminar el registro
            <strong>{{ recordToDelete.record_type }} {{ recordToDelete.name }}</strong>
            → {{ recordToDelete.content }}?
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="recordToDelete = null">Cancelar</button>
            <button class="btn btn-danger" :disabled="deletingRecord" @click="deleteRecord">
              <span v-if="deletingRecord" class="spinner-border spinner-border-sm me-2"></span>
              Eliminar
            </button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA']

const TYPE_CLASSES = {
  A:     'bg-primary',
  AAAA:  'bg-info text-dark',
  CNAME: 'bg-secondary',
  MX:    'bg-warning text-dark',
  TXT:   'bg-light text-dark border',
  NS:    'bg-dark',
  SRV:   'bg-purple',
  CAA:   'bg-danger',
}

export default {
  name: 'DNS',
  setup() {
    const store = useMainStore()
    const isAdmin = computed(() => store.currentUser?.role === 'admin')

    // Zones list
    const zones        = ref([])
    const loadingZones = ref(false)

    // Selected zone + records
    const selectedZone   = ref(null)
    const records        = ref([])
    const loadingRecords = ref(false)

    // Create zone modal
    const showCreateZoneModal = ref(false)
    const newZoneName         = ref('')
    const savingZone          = ref(false)

    // Record modal
    const showRecordModal = ref(false)
    const editingRecord   = ref(null)
    const savingRecord    = ref(false)
    const recordForm      = ref({ record_type: 'A', name: '@', content: '', ttl: 14400, priority: 0 })

    // Delete zone
    const zoneToDelete  = ref(null)
    const deletingZone  = ref(false)

    // Delete record
    const recordToDelete  = ref(null)
    const deletingRecord  = ref(false)

    const recordTypes = RECORD_TYPES

    // ─── helpers ──────────────────────────────────────────────────────────────

    const typeClass = (t) => TYPE_CLASSES[t] || 'bg-secondary'

    const formatDate = (d) => {
      if (!d) return '—'
      return new Date(d).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    }

    // ─── Load zones ───────────────────────────────────────────────────────────

    const loadZones = async () => {
      loadingZones.value = true
      try {
        zones.value = await api.getDnsZones()
      } catch (e) {
        store.showNotification('Error al cargar zonas DNS: ' + e.message, 'danger')
      } finally {
        loadingZones.value = false
      }
    }

    // ─── Load records ─────────────────────────────────────────────────────────

    const loadRecords = async (zoneId) => {
      loadingRecords.value = true
      records.value = []
      try {
        records.value = await api.getDnsRecords(zoneId)
      } catch (e) {
        store.showNotification('Error al cargar registros: ' + e.message, 'danger')
      } finally {
        loadingRecords.value = false
      }
    }

    // ─── Open zone detail ─────────────────────────────────────────────────────

    const openZone = async (zone) => {
      selectedZone.value = zone
      await loadRecords(zone.id)
    }

    // ─── Create zone ──────────────────────────────────────────────────────────

    const openCreateZone = () => {
      newZoneName.value = ''
      showCreateZoneModal.value = true
    }

    const createZone = async () => {
      if (!newZoneName.value.trim()) return
      savingZone.value = true
      try {
        const zone = await api.createDnsZone({ domain_name: newZoneName.value.trim() })
        store.showNotification(`Zona ${zone.domain_name} creada`, 'success')
        showCreateZoneModal.value = false
        await loadZones()
        await openZone(zone)
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingZone.value = false
      }
    }

    // ─── Delete zone ──────────────────────────────────────────────────────────

    const confirmDeleteZone = (zone) => { zoneToDelete.value = zone }

    const deleteZone = async () => {
      if (!zoneToDelete.value) return
      deletingZone.value = true
      try {
        await api.deleteDnsZone(zoneToDelete.value.id)
        store.showNotification(`Zona ${zoneToDelete.value.domain_name} eliminada`, 'success')
        if (selectedZone.value?.id === zoneToDelete.value.id) selectedZone.value = null
        zoneToDelete.value = null
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        deletingZone.value = false
      }
    }

    // ─── Add record ───────────────────────────────────────────────────────────

    const openAddRecord = () => {
      editingRecord.value = null
      recordForm.value = { record_type: 'A', name: '@', content: '', ttl: 14400, priority: 0 }
      showRecordModal.value = true
    }

    const openEditRecord = (rec) => {
      editingRecord.value = rec
      recordForm.value = {
        record_type: rec.record_type,
        name:        rec.name,
        content:     rec.content,
        ttl:         rec.ttl,
        priority:    rec.priority,
      }
      showRecordModal.value = true
    }

    const saveRecord = async () => {
      if (!selectedZone.value) return
      savingRecord.value = true
      try {
        if (editingRecord.value) {
          await api.updateDnsRecord(selectedZone.value.id, editingRecord.value.id, {
            content:  recordForm.value.content,
            ttl:      recordForm.value.ttl,
            priority: recordForm.value.priority,
          })
          store.showNotification('Registro actualizado', 'success')
        } else {
          await api.addDnsRecord(selectedZone.value.id, recordForm.value)
          store.showNotification('Registro añadido', 'success')
        }
        showRecordModal.value = false
        // Refresh zone (serial updated) + records
        const updatedZone = await api.getDnsZone(selectedZone.value.id)
        selectedZone.value = { ...selectedZone.value, serial: updatedZone.serial }
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingRecord.value = false
      }
    }

    // ─── Delete record ────────────────────────────────────────────────────────

    const confirmDeleteRecord = (rec) => { recordToDelete.value = rec }

    const deleteRecord = async () => {
      if (!recordToDelete.value || !selectedZone.value) return
      deletingRecord.value = true
      try {
        await api.deleteDnsRecord(selectedZone.value.id, recordToDelete.value.id)
        store.showNotification('Registro eliminado', 'success')
        recordToDelete.value = null
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        deletingRecord.value = false
      }
    }

    onMounted(loadZones)

    return {
      isAdmin,
      zones, loadingZones,
      selectedZone, records, loadingRecords,
      showCreateZoneModal, newZoneName, savingZone,
      showRecordModal, editingRecord, savingRecord, recordForm, recordTypes,
      zoneToDelete, deletingZone,
      recordToDelete, deletingRecord,
      typeClass, formatDate,
      openZone, openCreateZone, createZone, confirmDeleteZone, deleteZone,
      openAddRecord, openEditRecord, saveRecord, confirmDeleteRecord, deleteRecord,
    }
  }
}
</script>
