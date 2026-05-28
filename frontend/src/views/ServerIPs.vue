<template>
  <div>
    <h2 class="mb-4">
      <i class="bi bi-hdd-network"></i> Gestión de IPs del Servidor
    </h2>

    <!-- Barra superior -->
    <div class="d-flex gap-2 mb-3 flex-wrap align-items-center">
      <button class="btn btn-primary" @click="openCreate">
        <i class="bi bi-plus-lg me-1"></i> Añadir IP
      </button>
      <button class="btn btn-outline-secondary" @click="scanSystem" :disabled="scanning">
        <span v-if="scanning" class="spinner-border spinner-border-sm me-1"></span>
        <i v-else class="bi bi-search me-1"></i>
        Escanear sistema
      </button>
      <span class="text-muted small ms-auto">
        {{ ips.length }} IP{{ ips.length !== 1 ? 's' : '' }} registrada{{ ips.length !== 1 ? 's' : '' }}
      </span>
    </div>

    <!-- IPs detectadas en el sistema no registradas -->
    <div v-if="unregisteredSystemIPs.length > 0" class="alert alert-info d-flex align-items-start gap-2 mb-3">
      <i class="bi bi-info-circle-fill fs-5 mt-1"></i>
      <div>
        <strong>IPs detectadas en el sistema sin registrar:</strong>
        <div class="mt-1 d-flex flex-wrap gap-2">
          <button
            v-for="sip in unregisteredSystemIPs"
            :key="sip.address"
            class="btn btn-sm btn-outline-info font-monospace"
            @click="quickRegister(sip)"
          >
            <i class="bi bi-plus me-1"></i>{{ sip.address }}{{ sip.netmask }} ({{ sip.interface }})
          </button>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="text-center py-5">
      <div class="spinner-border"></div>
    </div>

    <!-- Tabla -->
    <div v-else class="card">
      <div class="card-body p-0">
        <div class="table-responsive">
          <table class="table table-hover mb-0 align-middle">
            <thead class="table-light">
              <tr>
                <th>Dirección IP</th>
                <th>Máscara</th>
                <th>Interfaz</th>
                <th>Tipo</th>
                <th>Dominios</th>
                <th>Dueño</th>
                <th>Estado</th>
                <th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="ips.length === 0">
                <td colspan="8" class="text-center text-muted py-4">
                  <i class="bi bi-hdd-network fs-2 d-block mb-2"></i>
                  No hay IPs registradas. Añade una o usa "Escanear sistema".
                </td>
              </tr>
              <tr v-for="ip in ips" :key="ip.id">
                <td>
                  <div class="d-flex align-items-center gap-2">
                    <i
                      :class="ip.is_ipv6 ? 'bi bi-diagram-3 text-info' : 'bi bi-globe text-primary'"
                    ></i>
                    <span class="font-monospace fw-bold">{{ ip.address }}</span>
                    <span v-if="ip.nat_ip" class="badge bg-secondary font-monospace small" :title="`NAT: ${ip.nat_ip}`">
                      NAT
                    </span>
                  </div>
                  <div v-if="ip.note" class="text-muted small">{{ ip.note }}</div>
                </td>
                <td class="font-monospace small text-muted">{{ ip.netmask || '—' }}</td>
                <td class="font-monospace small">{{ ip.interface }}</td>
                <td>
                  <span :class="ip.ip_type === 'dedicated' ? 'badge bg-warning text-dark' : 'badge bg-info text-dark'">
                    {{ ip.ip_type === 'dedicated' ? 'Dedicada' : 'Compartida' }}
                  </span>
                </td>
                <td>
                  <span
                    :class="ip.domains_count > 0 ? 'badge bg-primary' : 'badge bg-secondary'"
                  >{{ ip.domains_count }}</span>
                </td>
                <td class="small">{{ ip.owner_username || 'admin' }}</td>
                <td>
                  <span v-if="ip.is_active" class="badge bg-success">Activa</span>
                  <span v-else class="badge bg-secondary">Inactiva</span>
                </td>
                <td class="text-end">
                  <button class="btn btn-sm btn-outline-secondary me-1" @click="openEdit(ip)" title="Editar">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button
                    class="btn btn-sm btn-outline-danger"
                    @click="confirmDelete(ip)"
                    :disabled="ip.domains_count > 0"
                    :title="ip.domains_count > 0 ? 'Tiene dominios asignados' : 'Eliminar'"
                  >
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal crear / editar -->
    <div v-if="showModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-hdd-network me-2"></i>
              {{ editing ? 'Editar IP' : 'Añadir IP' }}
            </h5>
            <button class="btn-close" @click="closeModal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3" v-if="!editing">
              <label class="form-label fw-bold">Dirección IP <span class="text-danger">*</span></label>
              <input v-model="form.address" type="text" class="form-control font-monospace"
                placeholder="185.104.188.71 o 2a01:db8::1" />
              <div class="form-text">IPv4 o IPv6.</div>
            </div>

            <div class="row g-3">
              <div class="col-6">
                <label class="form-label">Máscara de red</label>
                <input v-model="form.netmask" type="text" class="form-control font-monospace"
                  placeholder="255.255.255.0 o /24" />
              </div>
              <div class="col-6">
                <label class="form-label">Interfaz</label>
                <input v-model="form.interface" type="text" class="form-control font-monospace"
                  placeholder="eth0" />
              </div>
            </div>

            <div class="mt-3">
              <label class="form-label fw-bold">Tipo</label>
              <select v-model="form.ip_type" class="form-select">
                <option value="shared">Compartida — múltiples dominios pueden usarla</option>
                <option value="dedicated">Dedicada — un único dominio</option>
              </select>
            </div>

            <div class="mt-3">
              <label class="form-label">IP NAT interna <span class="text-muted small">(opcional)</span></label>
              <input v-model="form.nat_ip" type="text" class="form-control font-monospace"
                placeholder="10.0.0.1 — solo si el servidor está detrás de NAT" />
            </div>

            <div class="mt-3">
              <label class="form-label">Nota <span class="text-muted small">(opcional)</span></label>
              <input v-model="form.note" type="text" class="form-control"
                placeholder="Ej: IP para clientes premium" maxlength="255" />
            </div>

            <div class="form-check form-switch mt-3">
              <input id="ip_active" v-model="form.is_active" type="checkbox" role="switch"
                class="form-check-input" />
              <label for="ip_active" class="form-check-label">IP activa</label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="closeModal">Cancelar</button>
            <button class="btn btn-primary" @click="saveIP" :disabled="saving">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-floppy me-1"></i>
              {{ editing ? 'Guardar cambios' : 'Registrar IP' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal confirmar borrado -->
    <div v-if="ipToDelete" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-trash me-2"></i> Eliminar IP</h5>
            <button class="btn-close btn-close-white" @click="ipToDelete = null"></button>
          </div>
          <div class="modal-body">
            <p>¿Eliminar la IP <strong class="font-monospace">{{ ipToDelete.address }}</strong>?</p>
            <p class="text-muted small mb-0">Esta acción solo la borra del registro del panel, no del sistema operativo.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="ipToDelete = null">Cancelar</button>
            <button class="btn btn-danger" @click="deleteIP" :disabled="saving">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              Eliminar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast" class="position-fixed bottom-0 end-0 p-3" style="z-index:9999">
      <div :class="`alert alert-${toast.type} d-flex align-items-center gap-2 shadow`">
        <i :class="toast.type === 'success' ? 'bi bi-check-circle-fill' : 'bi bi-exclamation-triangle-fill'"></i>
        {{ toast.msg }}
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api.js'

const emptyForm = () => ({
  address: '',
  netmask: '',
  interface: 'eth0',
  ip_type: 'shared',
  nat_ip: '',
  note: '',
  is_active: true,
})

export default {
  name: 'ServerIPs',
  setup() {
    const ips        = ref([])
    const systemIPs  = ref([])
    const loading    = ref(false)
    const scanning   = ref(false)
    const saving     = ref(false)
    const showModal  = ref(false)
    const editing    = ref(null)   // ServerIP object when editing
    const ipToDelete = ref(null)
    const form       = ref(emptyForm())
    const toast      = ref(null)

    const unregisteredSystemIPs = computed(() =>
      systemIPs.value.filter(s => !s.registered)
    )

    function showToast(msg, type = 'success') {
      toast.value = { msg, type }
      setTimeout(() => { toast.value = null }, 4000)
    }

    async function loadIPs() {
      loading.value = true
      try {
        ips.value = await api.get('/api/server-ips')
      } catch (e) {
        showToast('Error al cargar IPs', 'danger')
      } finally {
        loading.value = false
      }
    }

    async function scanSystem() {
      scanning.value = true
      try {
        const data = await api.get('/api/server-ips/system')
        systemIPs.value = data
        if (data.length === 0) showToast('No se detectaron IPs en el sistema', 'warning')
        else showToast(`${data.length} IP(s) detectadas en el sistema`)
      } catch (e) {
        showToast('Error al escanear el sistema', 'danger')
      } finally {
        scanning.value = false
      }
    }

    function openCreate() {
      editing.value = null
      form.value = emptyForm()
      showModal.value = true
    }

    function openEdit(ip) {
      editing.value = ip
      form.value = {
        address:   ip.address,
        netmask:   ip.netmask || '',
        interface: ip.interface,
        ip_type:   ip.ip_type,
        nat_ip:    ip.nat_ip || '',
        note:      ip.note || '',
        is_active: ip.is_active,
      }
      showModal.value = true
    }

    function closeModal() {
      showModal.value = false
      editing.value = null
    }

    function quickRegister(sip) {
      form.value = {
        address:   sip.address,
        netmask:   sip.netmask || '',
        interface: sip.interface,
        ip_type:   'shared',
        nat_ip:    '',
        note:      '',
        is_active: true,
      }
      editing.value = null
      showModal.value = true
    }

    async function saveIP() {
      saving.value = true
      try {
        const payload = {
          netmask:   form.value.netmask   || null,
          interface: form.value.interface,
          ip_type:   form.value.ip_type,
          nat_ip:    form.value.nat_ip    || null,
          note:      form.value.note      || null,
          is_active: form.value.is_active,
        }
        if (editing.value) {
          await api.put(`/api/server-ips/${editing.value.id}`, payload)
          showToast('IP actualizada correctamente')
        } else {
          payload.address = form.value.address
          await api.post('/api/server-ips', payload)
          showToast('IP registrada correctamente')
        }
        closeModal()
        await loadIPs()
        // Actualizar registro en systemIPs
        systemIPs.value = systemIPs.value.map(s =>
          s.address === (editing.value?.address || payload.address)
            ? { ...s, registered: true }
            : s
        )
      } catch (e) {
        const msg = e.response?.data?.detail || 'Error al guardar'
        showToast(msg, 'danger')
      } finally {
        saving.value = false
      }
    }

    function confirmDelete(ip) {
      ipToDelete.value = ip
    }

    async function deleteIP() {
      saving.value = true
      try {
        await api.delete(`/api/server-ips/${ipToDelete.value.id}`)
        showToast('IP eliminada')
        ipToDelete.value = null
        await loadIPs()
      } catch (e) {
        const msg = e.response?.data?.detail || 'Error al eliminar'
        showToast(msg, 'danger')
      } finally {
        saving.value = false
      }
    }

    onMounted(() => {
      loadIPs()
      scanSystem()
    })

    return {
      ips, systemIPs, unregisteredSystemIPs,
      loading, scanning, saving,
      showModal, editing, form,
      ipToDelete, toast,
      openCreate, openEdit, closeModal, quickRegister,
      saveIP, confirmDelete, deleteIP, scanSystem,
    }
  }
}
</script>
