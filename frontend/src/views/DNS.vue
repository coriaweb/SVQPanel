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
      <div class="card-header"><h5 class="mb-0">Zonas DNS</h5></div>
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
              <th>IP</th>
              <th>SOA NS</th>
              <th>Plantilla</th>
              <th>DNSSEC</th>
              <th>Registros</th>
              <th>Serial</th>
              <th class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="zone in zones" :key="zone.id" :class="selectedZone?.id === zone.id ? 'table-primary' : ''">
              <td class="fw-semibold">{{ zone.domain_name }}</td>
              <td class="font-monospace small">{{ zone.ip_address || '—' }}</td>
              <td class="small text-muted">{{ zone.soa_ns || '—' }}</td>
              <td><span class="badge bg-secondary">{{ zone.template || 'default' }}</span></td>
              <td>
                <span v-if="zone.dnssec_enabled" class="badge bg-success"><i class="bi bi-shield-lock me-1"></i>Activo</span>
                <span v-else class="badge bg-light text-muted border">No</span>
              </td>
              <td><span class="badge bg-secondary">{{ zone.record_count }}</span></td>
              <td><code class="text-muted small">{{ zone.serial }}</code></td>
              <td class="text-end">
                <button v-if="isAdmin" class="btn btn-sm btn-outline-secondary me-1" @click="openEditZone(zone)" title="Editar zona">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-primary me-1" @click="openZoneRecords(zone)" title="Ver registros">
                  <i class="bi bi-list-ul"></i>
                </button>
                <button v-if="isAdmin" class="btn btn-sm btn-outline-danger" @click="confirmDeleteZone(zone)" title="Eliminar zona">
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
          <button v-if="isAdmin" class="btn btn-sm btn-outline-warning" @click="confirmRegenerate" :title="'Regenerar registros con plantilla ' + (selectedZone.template || 'default')">
            <i class="bi bi-arrow-repeat me-1"></i> Regenerar plantilla
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
              <td><span :class="typeClass(rec.record_type)" class="badge">{{ rec.record_type }}</span></td>
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
              <td :colspan="isAdmin ? 6 : 5" class="text-center text-muted py-3">Sin registros</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>


    <!-- ═══════════════ Modal: Crear / Editar Zona ═══════════════ -->
    <div v-if="showZoneModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-diagram-3 me-2"></i>
              {{ editingZone ? 'Editar Dominio DNS' : 'Nueva Zona DNS' }}
            </h5>
            <button class="btn-close" @click="showZoneModal = false"></button>
          </div>
          <div class="modal-body">
            <div class="row g-3">

              <!-- Dominio -->
              <div class="col-12">
                <label class="form-label fw-semibold">Dominio</label>
                <input
                  v-model="zoneForm.domain_name"
                  type="text"
                  class="form-control"
                  placeholder="ejemplo.com"
                  :disabled="!!editingZone"
                />
              </div>

              <!-- IP -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Dirección IP</label>
                <input
                  v-model="zoneForm.ip_address"
                  type="text"
                  class="form-control font-monospace"
                  placeholder="185.104.188.53"
                />
                <div class="form-text">IP del servidor para los registros A de la zona.</div>
              </div>

              <!-- Plantilla -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Plantilla</label>
                <select v-model="zoneForm.template" class="form-select">
                  <option value="default">BIND9 (default)</option>
                  <option value="minimal">Mínima (solo NS + A)</option>
                  <option value="mail">Con correo (NS + A + MX + SPF)</option>
                </select>
              </div>

              <!-- SOA NS -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">SOA — Nameserver primario</label>
                <input
                  v-model="zoneForm.soa_ns"
                  type="text"
                  class="form-control font-monospace"
                  placeholder="ns1.svqpanel.local"
                />
                <div class="form-text">Se actualiza también el registro NS primario.</div>
              </div>

              <!-- TTL -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">TTL <small class="text-muted">(segundos)</small></label>
                <select v-model.number="zoneForm.ttl" class="form-select">
                  <option :value="300">300 (5 min — propagación rápida)</option>
                  <option :value="3600">3600 (1 hora)</option>
                  <option :value="14400">14400 (4 horas — recomendado)</option>
                  <option :value="86400">86400 (24 horas)</option>
                </select>
              </div>

              <!-- DNSSEC -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">DNSSEC</label>
                <div class="form-check form-switch mt-1">
                  <input
                    id="dnssecSwitch"
                    v-model="zoneForm.dnssec_enabled"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                  />
                  <label for="dnssecSwitch" class="form-check-label">
                    {{ zoneForm.dnssec_enabled ? 'Habilitado' : 'Deshabilitado' }}
                  </label>
                </div>
                <div class="form-text text-warning small" v-if="zoneForm.dnssec_enabled">
                  <i class="bi bi-exclamation-triangle me-1"></i>
                  Requiere configuración adicional en BIND9.
                </div>
              </div>

              <!-- Fecha expiración -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Fecha de Expiración <small class="text-muted">(DD-MM-AAAA)</small></label>
                <input
                  v-model="zoneForm.expires_at"
                  type="date"
                  class="form-control"
                />
                <div class="form-text">Fecha de renovación del dominio (solo referencia).</div>
              </div>

            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showZoneModal = false">Cancelar</button>
            <button
              class="btn btn-primary"
              :disabled="savingZone || !zoneForm.domain_name"
              @click="saveZone"
            >
              <span v-if="savingZone" class="spinner-border spinner-border-sm me-2"></span>
              {{ editingZone ? 'Guardar cambios' : 'Crear Zona' }}
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════ Modal: Añadir / Editar Registro ═══════════════ -->
    <div v-if="showRecordModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">{{ editingRecord ? 'Editar Registro DNS' : 'Añadir Registro DNS' }}</h5>
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
                <input v-model="recordForm.name" type="text" class="form-control font-monospace" placeholder="@" />
              </div>
            </template>
            <template v-else>
              <div class="mb-3">
                <label class="form-label">Tipo / Nombre <small class="text-muted">(no editable)</small></label>
                <input :value="editingRecord.record_type + ' — ' + editingRecord.name" type="text" class="form-control font-monospace" disabled />
              </div>
            </template>
            <div class="mb-3">
              <label class="form-label">Contenido</label>
              <input v-model="recordForm.content" type="text" class="form-control font-monospace" placeholder="IP, hostname, texto..." />
              <div class="form-text" v-if="recordForm.record_type === 'NS'">
                Recuerda añadir el punto final: <code>ns1.tuservidor.com<strong>.</strong></code>
              </div>
              <div class="form-text" v-if="recordForm.record_type === 'MX'">
                Recuerda añadir el punto final: <code>mail.tudominio.com<strong>.</strong></code>
              </div>
            </div>
            <div class="row g-2">
              <div class="col-6">
                <label class="form-label">TTL</label>
                <select v-model.number="recordForm.ttl" class="form-select">
                  <option :value="300">300</option>
                  <option :value="3600">3600</option>
                  <option :value="14400">14400</option>
                  <option :value="86400">86400</option>
                </select>
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


    <!-- ═══════════════ Modal: Confirmar regenerar plantilla ═══════════════ -->
    <div v-if="showRegenerateConfirm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-warning">
            <h5 class="modal-title"><i class="bi bi-arrow-repeat me-2"></i>Regenerar plantilla DNS</h5>
            <button class="btn-close" @click="showRegenerateConfirm = false"></button>
          </div>
          <div class="modal-body">
            <p>¿Regenerar los registros de <strong>{{ selectedZone?.domain_name }}</strong> con la plantilla <strong>{{ selectedZone?.template || 'default' }}</strong>?</p>
            <p class="text-warning small"><i class="bi bi-exclamation-triangle me-1"></i>Se borrarán todos los registros actuales y se crearán de nuevo con la plantilla Hestia.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showRegenerateConfirm = false">Cancelar</button>
            <button class="btn btn-warning" :disabled="regenerating" @click="regenerateZone">
              <span v-if="regenerating" class="spinner-border spinner-border-sm me-2"></span>
              Regenerar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════ Modal: Confirmar borrado zona ═══════════════ -->
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


    <!-- ═══════════════ Modal: Confirmar borrado registro ═══════════════ -->
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
            → <code>{{ recordToDelete.content }}</code>?
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

const emptyZoneForm = () => ({
  domain_name:    '',
  ip_address:     '',
  soa_ns:         'ns1.svqpanel.local',
  ttl:            14400,
  template:       'default',
  dnssec_enabled: false,
  expires_at:     '',
})

export default {
  name: 'DNS',
  setup() {
    const store   = useMainStore()
    // Doble check: por role (nuevo) o por is_admin (por si el localStorage es antiguo)
    const isAdmin = computed(() =>
      store.currentUser?.role === 'admin' || store.currentUser?.is_admin === true
    )

    // Zones
    const zones        = ref([])
    const loadingZones = ref(false)

    // Selected zone + records
    const selectedZone   = ref(null)
    const records        = ref([])
    const loadingRecords = ref(false)

    // Zone modal (create + edit)
    const showZoneModal = ref(false)
    const editingZone   = ref(null)   // null = crear, object = editar
    const zoneForm      = ref(emptyZoneForm())
    const savingZone    = ref(false)

    // Record modal
    const showRecordModal = ref(false)
    const editingRecord   = ref(null)
    const savingRecord    = ref(false)
    const recordForm      = ref({ record_type: 'A', name: '@', content: '', ttl: 14400, priority: 0 })

    // Regenerate zone
    const showRegenerateConfirm = ref(false)
    const regenerating          = ref(false)

    // Delete zone
    const zoneToDelete  = ref(null)
    const deletingZone  = ref(false)

    // Delete record
    const recordToDelete  = ref(null)
    const deletingRecord  = ref(false)

    const recordTypes = RECORD_TYPES

    // ─── helpers ──────────────────────────────────────────────────────────────

    const typeClass = (t) => TYPE_CLASSES[t] || 'bg-secondary'

    // ─── Load ─────────────────────────────────────────────────────────────────

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

    // ─── Zone records panel ───────────────────────────────────────────────────

    const openZoneRecords = async (zone) => {
      selectedZone.value = zone
      await loadRecords(zone.id)
    }

    // ─── Create zone ──────────────────────────────────────────────────────────

    const openCreateZone = () => {
      editingZone.value = null
      zoneForm.value = emptyZoneForm()
      showZoneModal.value = true
    }

    // ─── Edit zone ────────────────────────────────────────────────────────────

    const openEditZone = (zone) => {
      editingZone.value = zone
      zoneForm.value = {
        domain_name:    zone.domain_name,
        ip_address:     zone.ip_address   || '',
        soa_ns:         zone.soa_ns       || 'ns1.svqpanel.local',
        ttl:            zone.ttl          || 14400,
        template:       zone.template     || 'default',
        dnssec_enabled: zone.dnssec_enabled || false,
        expires_at:     zone.expires_at   || '',
      }
      showZoneModal.value = true
    }

    const saveZone = async () => {
      savingZone.value = true
      try {
        const payload = {
          ip_address:     zoneForm.value.ip_address     || null,
          soa_ns:         zoneForm.value.soa_ns         || null,
          ttl:            zoneForm.value.ttl,
          template:       zoneForm.value.template,
          dnssec_enabled: zoneForm.value.dnssec_enabled,
          expires_at:     zoneForm.value.expires_at     || null,
        }

        if (editingZone.value) {
          // PUT /dns/{id}
          const updated = await api.updateDnsZone(editingZone.value.id, payload)
          store.showNotification(`Zona ${updated.domain_name} actualizada`, 'success')
          // Refrescar zona seleccionada si está abierta
          if (selectedZone.value?.id === editingZone.value.id) {
            selectedZone.value = { ...selectedZone.value, ...updated }
          }
        } else {
          // POST /dns
          const zone = await api.createDnsZone({ domain_name: zoneForm.value.domain_name, ...payload })
          store.showNotification(`Zona ${zone.domain_name} creada`, 'success')
          await openZoneRecords(zone)
        }

        showZoneModal.value = false
        await loadZones()
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

    // ─── Records ──────────────────────────────────────────────────────────────

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

    // ─── Regenerate zone ──────────────────────────────────────────────────────

    const confirmRegenerate = () => { showRegenerateConfirm.value = true }

    const regenerateZone = async () => {
      if (!selectedZone.value) return
      regenerating.value = true
      try {
        const updated = await api.regenerateDnsZone(selectedZone.value.id)
        store.showNotification(`Registros de ${selectedZone.value.domain_name} regenerados`, 'success')
        showRegenerateConfirm.value = false
        selectedZone.value = { ...selectedZone.value, serial: updated.serial }
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        regenerating.value = false
      }
    }

    onMounted(loadZones)

    return {
      isAdmin,
      zones, loadingZones,
      selectedZone, records, loadingRecords,
      showZoneModal, editingZone, zoneForm, savingZone,
      showRecordModal, editingRecord, savingRecord, recordForm, recordTypes,
      showRegenerateConfirm, regenerating,
      zoneToDelete, deletingZone,
      recordToDelete, deletingRecord,
      typeClass,
      openZoneRecords, openCreateZone, openEditZone, saveZone, confirmDeleteZone, deleteZone,
      openAddRecord, openEditRecord, saveRecord, confirmDeleteRecord, deleteRecord,
      confirmRegenerate, regenerateZone,
    }
  }
}
</script>
