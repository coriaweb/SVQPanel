<template>
  <div>
    <!-- Back button + header -->
    <div class="d-flex align-items-center gap-3 mb-4">
      <button class="btn btn-outline-secondary btn-sm" @click="$router.push('/users')">
        <i class="bi bi-arrow-left"></i> Volver
      </button>
      <div v-if="user">
        <h2 class="mb-0">
          <i class="bi bi-person-circle me-2"></i>{{ user.username }}
          <span :class="roleBadgeClass(user.role)" class="badge ms-2 fs-6">{{ roleLabel(user.role) }}</span>
        </h2>
        <small class="text-muted">{{ user.email }}</small>
      </div>
      <div v-else-if="loadingUser" class="spinner-border spinner-border-sm text-secondary"></div>
    </div>

    <div v-if="user" class="row g-4">
      <!-- User Info Card -->
      <div class="col-md-4">
        <div class="card h-100">
          <div class="card-header">
            <i class="bi bi-info-circle me-1"></i> Información de la cuenta
          </div>
          <div class="card-body">
            <dl class="row mb-0">
              <dt class="col-5 text-muted">Usuario</dt>
              <dd class="col-7">{{ user.username }}</dd>

              <dt class="col-5 text-muted">Email</dt>
              <dd class="col-7">{{ user.email }}</dd>

              <dt class="col-5 text-muted">Nombre</dt>
              <dd class="col-7">{{ [user.first_name, user.last_name].filter(Boolean).join(' ') || '—' }}</dd>

              <dt class="col-5 text-muted">Rol</dt>
              <dd class="col-7">
                <span :class="roleBadgeClass(user.role)" class="badge">{{ roleLabel(user.role) }}</span>
              </dd>

              <dt class="col-5 text-muted">Estado</dt>
              <dd class="col-7">
                <span v-if="user.is_active" class="badge bg-success">Activo</span>
                <span v-else class="badge bg-danger">Inactivo</span>
              </dd>

              <dt class="col-5 text-muted">Dominios</dt>
              <dd class="col-7">
                {{ domains.length }} / {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}
              </dd>

              <dt class="col-5 text-muted">Creado</dt>
              <dd class="col-7">{{ formatDate(user.created_at) }}</dd>

              <dt class="col-5 text-muted">Último login</dt>
              <dd class="col-7">{{ user.last_login ? formatDate(user.last_login) : 'Nunca' }}</dd>
            </dl>
          </div>
          <div class="card-footer d-flex gap-2">
            <button class="btn btn-sm btn-outline-warning flex-fill" @click="openEditUser">
              <i class="bi bi-pencil me-1"></i> Editar
            </button>
          </div>
        </div>
      </div>

      <!-- Domains Card -->
      <div class="col-md-8">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-globe2 me-1"></i> Dominios de {{ user.username }}</span>
            <button class="btn btn-sm btn-primary" @click="openAddDomain">
              <i class="bi bi-plus-lg"></i> Añadir dominio
            </button>
          </div>
          <div class="card-body">
            <div v-if="loadingDomains" class="text-center py-3">
              <div class="spinner-border spinner-border-sm"></div>
            </div>
            <div v-else-if="domains.length === 0" class="alert alert-info mb-0">
              <i class="bi bi-info-circle me-1"></i> Este usuario no tiene dominios
            </div>
            <div v-else class="table-responsive">
              <table class="table table-hover align-middle mb-0">
                <thead class="table-light">
                  <tr>
                    <th>Dominio</th>
                    <th>PHP</th>
                    <th>SSL</th>
                    <th>Estado</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="domain in domains" :key="domain.id">
                    <td>
                      <i class="bi bi-globe text-primary me-1"></i>
                      <a :href="'http://' + domain.domain_name" target="_blank" class="text-decoration-none">
                        {{ domain.domain_name }}
                      </a>
                    </td>
                    <td>
                      <span class="badge bg-info text-dark">PHP {{ domain.php_version || '8.2' }}</span>
                    </td>
                    <td>
                      <span v-if="domain.ssl_enabled" class="badge bg-success">
                        <i class="bi bi-lock-fill"></i> SSL
                      </span>
                      <span v-else class="badge bg-secondary">
                        <i class="bi bi-unlock"></i> Sin SSL
                      </span>
                    </td>
                    <td>
                      <span v-if="domain.is_active" class="badge bg-success">Activo</span>
                      <span v-else class="badge bg-danger">Inactivo</span>
                    </td>
                    <td>
                      <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info" @click="openChangePHP(domain)" title="Cambiar PHP">
                          <i class="bi bi-filetype-php"></i>
                        </button>
                        <button class="btn btn-outline-success" @click="openSSL(domain)" title="Gestionar SSL">
                          <i class="bi bi-lock"></i>
                        </button>
                        <button class="btn btn-outline-danger" @click="deleteDomainConfirm(domain)" title="Eliminar">
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
      </div>
    </div>

    <!-- Edit User Modal -->
    <Modal :isOpen="showEditUser" title="Editar Usuario" @close="closeEditUser">
      <UserForm
        :user="user"
        @submit="handleUserUpdated"
        @cancel="closeEditUser"
      />
    </Modal>

    <!-- Add Domain Modal -->
    <Modal :isOpen="showAddDomain" title="Añadir Dominio" @close="showAddDomain = false">
      <form @submit.prevent="handleAddDomain">
        <div class="mb-3">
          <label class="form-label">Nombre de dominio</label>
          <input
            v-model="newDomain.domain_name"
            type="text"
            class="form-control"
            placeholder="ejemplo.com"
            required
          />
        </div>
        <div class="mb-3">
          <label class="form-label">Versión PHP</label>
          <select v-model="newDomain.php_version" class="form-select">
            <option value="8.5">PHP 8.5</option>
            <option value="8.4">PHP 8.4</option>
            <option value="8.3">PHP 8.3</option>
            <option value="8.2" selected>PHP 8.2</option>
            <option value="8.1">PHP 8.1</option>
            <option value="8.0">PHP 8.0</option>
            <option value="7.4">PHP 7.4</option>
          </select>
        </div>
        <div class="d-flex gap-2">
          <button type="submit" class="btn btn-primary" :disabled="addingDomain">
            <span v-if="addingDomain" class="spinner-border spinner-border-sm me-1"></span>
            Crear dominio
          </button>
          <button type="button" class="btn btn-secondary" @click="showAddDomain = false">Cancelar</button>
        </div>
      </form>
    </Modal>

    <!-- Change PHP Modal -->
    <Modal :isOpen="showChangePHP" :title="`Cambiar PHP — ${selectedDomain?.domain_name}`" @close="showChangePHP = false">
      <form @submit.prevent="handleChangePHP">
        <div class="mb-3">
          <label class="form-label">Versión PHP</label>
          <select v-model="phpVersion" class="form-select">
            <option value="8.5">PHP 8.5</option>
            <option value="8.4">PHP 8.4</option>
            <option value="8.3">PHP 8.3</option>
            <option value="8.2">PHP 8.2</option>
            <option value="8.1">PHP 8.1</option>
            <option value="8.0">PHP 8.0</option>
            <option value="7.4">PHP 7.4</option>
          </select>
        </div>
        <div class="d-flex gap-2">
          <button type="submit" class="btn btn-primary" :disabled="changingPHP">
            <span v-if="changingPHP" class="spinner-border spinner-border-sm me-1"></span>
            Cambiar
          </button>
          <button type="button" class="btn btn-secondary" @click="showChangePHP = false">Cancelar</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'

export default {
  name: 'UserAccount',
  components: { Modal, UserForm },
  setup() {
    const route = useRoute()
    const store = useMainStore()
    const userId = parseInt(route.params.id)

    const user = ref(null)
    const domains = ref([])
    const loadingUser = ref(true)
    const loadingDomains = ref(true)

    const showEditUser = ref(false)
    const showAddDomain = ref(false)
    const showChangePHP = ref(false)
    const selectedDomain = ref(null)
    const phpVersion = ref('8.2')
    const addingDomain = ref(false)
    const changingPHP = ref(false)

    const newDomain = ref({ domain_name: '', php_version: '8.2' })

    const roleLabel = (role) => {
      switch (role) {
        case 'admin': return '🔑 Admin'
        case 'reseller': return '🏪 Reseller'
        default: return '👤 Usuario'
      }
    }

    const roleBadgeClass = (role) => {
      switch (role) {
        case 'admin': return 'bg-danger'
        case 'reseller': return 'bg-warning text-dark'
        default: return 'bg-secondary'
      }
    }

    const formatDate = (dateStr) => {
      if (!dateStr) return '—'
      return new Date(dateStr).toLocaleDateString('es-ES', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    }

    const loadUser = async () => {
      loadingUser.value = true
      try {
        user.value = await api.getUser(userId)
      } catch (e) {
        store.showNotification('Error al cargar usuario', 'danger')
      } finally {
        loadingUser.value = false
      }
    }

    const loadDomains = async () => {
      loadingDomains.value = true
      try {
        const data = await api.getDomains(userId, 0, 100)
        domains.value = Array.isArray(data) ? data : []
      } catch (e) {
        store.showNotification('Error al cargar dominios', 'danger')
      } finally {
        loadingDomains.value = false
      }
    }

    const openEditUser = () => { showEditUser.value = true }
    const closeEditUser = () => { showEditUser.value = false }
    const handleUserUpdated = async () => {
      await loadUser()
      closeEditUser()
      store.showNotification('Usuario actualizado', 'success')
    }

    const openAddDomain = () => {
      newDomain.value = { domain_name: '', php_version: '8.2' }
      showAddDomain.value = true
    }

    const handleAddDomain = async () => {
      addingDomain.value = true
      try {
        await api.createDomain({
          user_id: userId,
          domain_name: newDomain.value.domain_name,
          php_version: newDomain.value.php_version
        })
        store.showNotification('Dominio creado correctamente', 'success')
        showAddDomain.value = false
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al crear dominio: ' + e.message, 'danger')
      } finally {
        addingDomain.value = false
      }
    }

    const openChangePHP = (domain) => {
      selectedDomain.value = domain
      phpVersion.value = domain.php_version || '8.2'
      showChangePHP.value = true
    }

    const handleChangePHP = async () => {
      changingPHP.value = true
      try {
        await api.changePHPVersion(selectedDomain.value.id, phpVersion.value)
        store.showNotification('Versión PHP cambiada', 'success')
        showChangePHP.value = false
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al cambiar PHP: ' + e.message, 'danger')
      } finally {
        changingPHP.value = false
      }
    }

    const openSSL = (domain) => {
      store.showNotification('Gestión SSL — próximamente disponible', 'info')
    }

    const deleteDomainConfirm = (domain) => {
      if (confirm(`¿Eliminar dominio "${domain.domain_name}"?\n\nEsto eliminará la configuración de Nginx y los archivos del dominio.`)) {
        deleteDomain(domain.id)
      }
    }

    const deleteDomain = async (domainId) => {
      try {
        await api.deleteDomain(domainId)
        store.showNotification('Dominio eliminado', 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al eliminar dominio: ' + e.message, 'danger')
      }
    }

    onMounted(async () => {
      await loadUser()
      await loadDomains()
    })

    return {
      user,
      domains,
      loadingUser,
      loadingDomains,
      showEditUser,
      showAddDomain,
      showChangePHP,
      selectedDomain,
      phpVersion,
      newDomain,
      addingDomain,
      changingPHP,
      roleLabel,
      roleBadgeClass,
      formatDate,
      openEditUser,
      closeEditUser,
      handleUserUpdated,
      openAddDomain,
      handleAddDomain,
      openChangePHP,
      handleChangePHP,
      openSSL,
      deleteDomainConfirm
    }
  }
}
</script>
