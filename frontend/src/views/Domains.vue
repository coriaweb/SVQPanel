<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-globe"></i> Dominios</h2>
      <button class="btn btn-primary" @click="openCreateForm">
        <i class="bi bi-plus-circle"></i> Crear Dominio
      </button>
    </div>

    <!-- Filtro por usuario (solo admin/reseller) -->
    <div v-if="isAdminOrReseller" class="mb-3">
      <select v-model="selectedUser" class="form-select" @change="loadDomains">
        <option value="">Todos los usuarios</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }}
        </option>
      </select>
    </div>

    <!-- Tabla de dominios -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="domains.length === 0" class="alert alert-info m-3 mb-0">
          No hay dominios creados aún
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Dominio</th>
                <th v-if="isAdminOrReseller">Usuario</th>
                <th>PHP</th>
                <th>SSL</th>
                <th>IPv6</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="domain in domains" :key="domain.id">
                <td>
                  <i class="bi bi-globe text-primary me-1"></i>
                  <a :href="'http://' + domain.domain_name" target="_blank" class="text-decoration-none fw-semibold">
                    {{ domain.domain_name }}
                  </a>
                </td>
                <td v-if="isAdminOrReseller">{{ getUserName(domain.user_id) }}</td>
                <td>
                  <select
                    class="form-select form-select-sm"
                    style="min-width:100px"
                    @change="changePHP(domain, $event)"
                  >
                    <option
                      v-for="v in phpVersions"
                      :key="v"
                      :value="v"
                      :selected="v === domain.php_version"
                    >PHP {{ v }}</option>
                  </select>
                </td>
                <td>
                  <span v-if="domain.ssl_enabled" class="badge bg-success">
                    <i class="bi bi-lock-fill me-1"></i>SSL
                  </span>
                  <span v-else class="badge bg-light text-secondary border">
                    <i class="bi bi-unlock me-1"></i>No
                  </span>
                </td>
                <td>
                  <span
                    v-if="domain.ipv6"
                    class="badge bg-primary font-monospace"
                    style="font-size:.7rem; cursor:pointer"
                    :title="domain.ipv6"
                    @click="openIPv6Manager(domain)"
                  >
                    <i class="bi bi-diagram-3 me-1"></i>{{ domain.ipv6.slice(-8) }}…
                  </span>
                  <button
                    v-else
                    class="btn btn-outline-secondary btn-sm py-0"
                    style="font-size:.75rem"
                    @click="openIPv6Manager(domain)"
                    title="Asignar IPv6"
                  >
                    <i class="bi bi-plus-circle me-1"></i>IPv6
                  </button>
                </td>
                <td>
                  <span v-if="domain.is_active" class="badge bg-success">Activo</span>
                  <span v-else class="badge bg-danger">Inactivo</span>
                </td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-success" @click="openSSLManager(domain)" title="SSL">
                      <i class="bi bi-lock"></i>
                    </button>
                    <button class="btn btn-outline-primary" @click="openIPv6Manager(domain)" title="IPv6">
                      <i class="bi bi-diagram-3"></i>
                    </button>
                    <button class="btn btn-outline-secondary" @click="openFileManager(domain)" title="Archivos">
                      <i class="bi bi-folder2-open"></i>
                    </button>
                    <button class="btn btn-outline-warning" @click="openEditForm(domain)" title="Editar">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger" @click="deleteDomainConfirm(domain.id)" title="Eliminar">
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

    <!-- Modal: crear/editar dominio -->
    <Modal :isOpen="showDomainForm" :title="editingDomain ? 'Editar Dominio' : 'Crear Dominio'" @close="closeDomainForm">
      <DomainForm
        :domain="editingDomain"
        :phpVersions="phpVersions"
        @submit="handleDomainSubmit"
        @cancel="closeDomainForm"
      />
    </Modal>

    <!-- Modal: SSL -->
    <Modal v-if="selectedDomain" :isOpen="showSSLManager" :title="'SSL — ' + selectedDomain.domain_name" @close="closeSSLManager">
      <SSLManager :domain="selectedDomain" @reload="reloadDomains" />
    </Modal>

    <!-- Modal: IPv6 -->
    <Modal v-if="selectedDomain" :isOpen="showIPv6Manager" :title="'IPv6 — ' + selectedDomain.domain_name" @close="closeIPv6Manager">
      <IPv6Manager :domain="selectedDomain" @reload="reloadDomains" />
    </Modal>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import DomainForm from '../components/DomainForm.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'

export default {
  name: 'Domains',
  components: { Modal, DomainForm, SSLManager, IPv6Manager },
  setup() {
    const store = useMainStore()
    const router = useRouter()

    const domains      = ref([])
    const users        = ref([])
    const phpVersions  = ref([])
    const selectedUser = ref('')
    const loading      = ref(false)

    const showDomainForm  = ref(false)
    const showSSLManager  = ref(false)
    const showIPv6Manager = ref(false)
    const editingDomain   = ref(null)
    const selectedDomain  = ref(null)

    // Rol del usuario actual
    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    // ─── Carga de datos ───────────────────────────────────────────────────────

    const loadDomains = async () => {
      loading.value = true
      try {
        const data = await api.getDomains(selectedUser.value || null)
        domains.value = Array.isArray(data) ? data : []
      } catch (e) {
        store.showNotification('Error al cargar dominios', 'danger')
      } finally {
        loading.value = false
      }
    }

    const reloadDomains = async () => {
      await loadDomains()
      // Si hay un modal de IPv6 abierto, actualiza el domain seleccionado
      if (selectedDomain.value) {
        const fresh = domains.value.find(d => d.id === selectedDomain.value.id)
        if (fresh) selectedDomain.value = { ...fresh }
      }
    }

    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return   // usuarios normales no necesitan la lista
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch {
        // silencioso — el filtro simplemente no aparece si falla
      }
    }

    const loadPHPVersions = async () => {
      try {
        const data = await api.getPHPVersions()
        phpVersions.value = data?.versions?.length ? data.versions : ['8.2']
      } catch {
        phpVersions.value = ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5']
      }
    }

    const getUserName = (userId) => {
      const user = users.value.find(u => u.id === userId)
      return user ? user.username : `#${userId}`
    }

    // ─── Acciones ─────────────────────────────────────────────────────────────

    const openCreateForm = () => { editingDomain.value = null; showDomainForm.value = true }
    const openEditForm   = (d) => { editingDomain.value = d;    showDomainForm.value = true }
    const closeDomainForm= () => { showDomainForm.value = false; editingDomain.value = null }

    const handleDomainSubmit = async () => { await loadDomains(); closeDomainForm() }

    const openSSLManager  = (d) => { selectedDomain.value = d; showSSLManager.value = true }
    const closeSSLManager = () => { showSSLManager.value = false; selectedDomain.value = null }

    const openIPv6Manager  = (d) => { selectedDomain.value = { ...d }; showIPv6Manager.value = true }
    const closeIPv6Manager = () => { showIPv6Manager.value = false; selectedDomain.value = null }
    const openFileManager = (d) => { router.push({ path: '/files', query: { domain: d.id } }) }

    const deleteDomainConfirm = (domainId) => {
      if (confirm('¿Eliminar este dominio? Se borrarán todos sus archivos.')) {
        api.deleteDomain(domainId)
          .then(() => { store.showNotification('Dominio eliminado', 'success'); loadDomains() })
          .catch(e => store.showNotification('Error al eliminar: ' + e.message, 'danger'))
      }
    }

    const changePHP = async (domain, event) => {
      const version = event.target.value
      try {
        await api.changePHPVersion(domain.id, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'danger')
        await loadDomains()   // revertir el select visualmente
      }
    }

    onMounted(async () => {
      await Promise.all([loadPHPVersions(), loadUsers(), loadDomains()])
    })

    return {
      domains, users, phpVersions, selectedUser, loading,
      isAdminOrReseller,
      showDomainForm, showSSLManager, showIPv6Manager,
      editingDomain, selectedDomain,
      openCreateForm, openEditForm, closeDomainForm, handleDomainSubmit,
      openSSLManager, closeSSLManager,
      openIPv6Manager, closeIPv6Manager,
      openFileManager,
      deleteDomainConfirm, changePHP,
      loadDomains, reloadDomains, getUserName,
    }
  }
}
</script>
