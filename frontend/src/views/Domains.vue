<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-globe"></i> Dominios</h2>
      <button class="btn btn-primary" @click="openCreateForm">
        <i class="bi bi-plus-circle"></i> Crear Dominio
      </button>
    </div>

    <!-- Filter by User -->
    <div class="mb-3">
      <select v-model="selectedUser" class="form-select" @change="loadDomains">
        <option value="">Todos los usuarios</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }}
        </option>
      </select>
    </div>

    <!-- Domains Table -->
    <div class="card">
      <div class="card-body">
        <div v-if="loading" class="loading">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="domains.length === 0" class="alert alert-info">
          No hay dominios creados aún
        </div>
        <table v-else class="table table-hover">
          <thead>
            <tr>
              <th>Dominio</th>
              <th>Usuario</th>
              <th>PHP</th>
              <th>SSL</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="domain in domains" :key="domain.id">
              <td>
                <i class="bi bi-globe"></i> {{ domain.domain_name }}
              </td>
              <td>{{ getUserName(domain.user_id) }}</td>
              <td>
                <select class="form-select form-select-sm" @change="changePHP(domain, $event)">
                  <option v-for="v in phpVersions" :key="v" :value="v" :selected="v === domain.php_version">
                    {{ v }}
                  </option>
                </select>
              </td>
              <td>
                <span v-if="domain.ssl_enabled" class="badge bg-success">
                  <i class="bi bi-shield-lock"></i> Activo
                </span>
                <span v-else class="badge bg-secondary">
                  <i class="bi bi-shield-x"></i> Inactivo
                </span>
              </td>
              <td>
                <span v-if="domain.is_active" class="badge bg-success">Activo</span>
                <span v-else class="badge bg-danger">Inactivo</span>
              </td>
              <td>
                <button class="btn btn-sm btn-info me-2" @click="openSSLManager(domain)" title="Configurar SSL">
                  <i class="bi bi-lock"></i>
                </button>
                <button class="btn btn-sm btn-primary me-2" @click="openIPv6Manager(domain)" title="Asignar IPv6">
                  <i class="bi bi-shuffle"></i>
                </button>
                <button class="btn btn-sm btn-warning me-2" @click="openEditForm(domain)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-danger" @click="deleteDomainConfirm(domain.id)">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Domain Form Modal -->
    <Modal :isOpen="showDomainForm" :title="editingDomain ? 'Editar Dominio' : 'Crear Dominio'" @close="closeDomainForm">
      <DomainForm
        :domain="editingDomain"
        @submit="handleDomainSubmit"
        @cancel="closeDomainForm"
      />
    </Modal>

    <!-- SSL Manager Modal -->
    <Modal v-if="selectedDomain" :isOpen="showSSLManager" :title="'Certificado SSL: ' + selectedDomain.domain_name" @close="closeSSLManager">
      <SSLManager
        :domain="selectedDomain"
        @reload="reloadDomains"
      />
    </Modal>

    <!-- IPv6 Manager Modal -->
    <Modal v-if="selectedDomain" :isOpen="showIPv6Manager" :title="'IPv6: ' + selectedDomain.domain_name" @close="closeIPv6Manager">
      <IPv6Manager
        :domain="selectedDomain"
        @reload="reloadDomains"
      />
    </Modal>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import DomainForm from '../components/DomainForm.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'

export default {
  name: 'Domains',
  components: {
    Modal,
    DomainForm,
    SSLManager,
    IPv6Manager
  },
  setup() {
    const store = useMainStore()
    const domains = ref([])
    const users = ref([])
    const phpVersions = ref(['7.4', '8.0', '8.1', '8.2', '8.3'])
    const selectedUser = ref('')
    const loading = ref(false)
    const showDomainForm = ref(false)
    const showSSLManager = ref(false)
    const showIPv6Manager = ref(false)
    const editingDomain = ref(null)
    const selectedDomain = ref(null)

    const loadDomains = async () => {
      loading.value = true
      try {
        const data = await api.getDomains(selectedUser.value || null)
        domains.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar dominios', 'danger')
      } finally {
        loading.value = false
      }
    }

    const reloadDomains = async () => {
      await loadDomains()
    }

    const loadUsers = async () => {
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar usuarios', 'danger')
      }
    }

    const getUserName = (userId) => {
      const user = users.value.find(u => u.id === userId)
      return user ? user.username : 'Desconocido'
    }

    const openCreateForm = () => {
      editingDomain.value = null
      showDomainForm.value = true
    }

    const openEditForm = (domain) => {
      editingDomain.value = domain
      showDomainForm.value = true
    }

    const closeDomainForm = () => {
      showDomainForm.value = false
      editingDomain.value = null
    }

    const handleDomainSubmit = async () => {
      await loadDomains()
      closeDomainForm()
    }

    const openSSLManager = (domain) => {
      selectedDomain.value = domain
      showSSLManager.value = true
    }

    const closeSSLManager = () => {
      showSSLManager.value = false
      selectedDomain.value = null
    }

    const openIPv6Manager = (domain) => {
      selectedDomain.value = domain
      showIPv6Manager.value = true
    }

    const closeIPv6Manager = () => {
      showIPv6Manager.value = false
      selectedDomain.value = null
    }

    const deleteDomainConfirm = (domainId) => {
      if (confirm('¿Estás seguro de que deseas eliminar este dominio?')) {
        deleteDomain(domainId)
      }
    }

    const deleteDomain = async (domainId) => {
      try {
        await api.deleteDomain(domainId)
        store.showNotification('Dominio eliminado', 'success')
        loadDomains()
      } catch (error) {
        store.showNotification('Error al eliminar dominio', 'danger')
      }
    }

    const changePHP = async (domain, event) => {
      const version = event.target.value
      try {
        await api.changePHPVersion(domain.id, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await loadDomains()
      } catch (error) {
        store.showNotification(`Error al cambiar PHP: ${error.message}`, 'danger')
        await loadDomains()
      }
    }

    onMounted(() => {
      loadUsers()
      loadDomains()
    })

    return {
      domains,
      users,
      phpVersions,
      selectedUser,
      loading,
      showDomainForm,
      showSSLManager,
      showIPv6Manager,
      editingDomain,
      selectedDomain,
      openCreateForm,
      openEditForm,
      closeDomainForm,
      handleDomainSubmit,
      openSSLManager,
      closeSSLManager,
      openIPv6Manager,
      closeIPv6Manager,
      deleteDomainConfirm,
      changePHP,
      loadDomains,
      reloadDomains,
      getUserName
    }
  }
}
</script>
