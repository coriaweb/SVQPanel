<template>
  <div>
    <!-- Back + header -->
    <div class="d-flex align-items-center gap-3 mb-4">
      <button class="btn btn-outline-secondary btn-sm" @click="$router.back()">
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
      <!-- Info card -->
      <div class="col-md-3">
        <div class="card">
          <div class="card-header"><i class="bi bi-info-circle me-1"></i> Información</div>
          <div class="card-body p-0">
            <ul class="list-group list-group-flush">
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Rol</span>
                <span :class="roleBadgeClass(user.role)" class="badge">{{ roleLabel(user.role) }}</span>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Estado</span>
                <span :class="user.is_active ? 'badge bg-success' : 'badge bg-danger'">
                  {{ user.is_active ? 'Activo' : 'Inactivo' }}
                </span>
              </li>
              <li v-if="user.role === 'reseller'" class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Clientes</span>
                <strong>{{ clients.length }}</strong>
              </li>
              <li v-else class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Dominios</span>
                <strong>{{ domains.length }} / {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}</strong>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Creado</span>
                <small>{{ formatDate(user.created_at) }}</small>
              </li>
            </ul>
          </div>
          <div class="card-footer">
            <button class="btn btn-sm btn-outline-warning w-100" @click="showEditUser = true">
              <i class="bi bi-pencil me-1"></i> Editar usuario
            </button>
          </div>
        </div>
      </div>

      <!-- Panel principal: clientes (reseller) o dominios (user) -->
      <div class="col-md-9">

        <!-- ═══ RESELLER: lista de clientes ═══ -->
        <template v-if="user.role === 'reseller'">
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span><i class="bi bi-people me-1"></i> Clientes de {{ user.username }}</span>
              <button class="btn btn-sm btn-primary" @click="showAddClient = true">
                <i class="bi bi-person-plus"></i> Añadir cliente
              </button>
            </div>
            <div class="card-body">
              <div v-if="loadingClients" class="text-center py-3">
                <div class="spinner-border spinner-border-sm"></div>
              </div>
              <div v-else-if="clients.length === 0" class="alert alert-info mb-0">
                <i class="bi bi-info-circle me-1"></i> Este reseller no tiene clientes aún
              </div>
              <div v-else class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Usuario</th>
                      <th>Email</th>
                      <th>Dominios</th>
                      <th>Estado</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="client in clients" :key="client.id">
                      <td><i class="bi bi-person-circle text-secondary me-1"></i><strong>{{ client.username }}</strong></td>
                      <td>{{ client.email }}</td>
                      <td><i class="bi bi-globe2 me-1 text-muted"></i>{{ client.domains_limit === 0 ? '∞' : client.domains_limit }}</td>
                      <td>
                        <span :class="client.is_active ? 'badge bg-success' : 'badge bg-danger'">
                          {{ client.is_active ? 'Activo' : 'Inactivo' }}
                        </span>
                      </td>
                      <td>
                        <div class="btn-group btn-group-sm">
                          <button class="btn btn-outline-primary" @click="$router.push(`/users/${client.id}/account`)" title="Gestionar">
                            <i class="bi bi-box-arrow-in-right"></i> Gestionar
                          </button>
                          <button class="btn btn-outline-danger" @click="deleteClientConfirm(client)" title="Eliminar">
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
        </template>

        <!-- ═══ USER: lista de dominios ═══ -->
        <template v-else>
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span><i class="bi bi-globe2 me-1"></i> Dominios de {{ user.username }}</span>
              <button class="btn btn-sm btn-primary" @click="showAddDomain = true">
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
                      <td><span class="badge bg-info text-dark">PHP {{ domain.php_version || '8.2' }}</span></td>
                      <td>
                        <span v-if="domain.ssl_enabled" class="badge bg-success"><i class="bi bi-lock-fill"></i> SSL</span>
                        <span v-else class="badge bg-secondary"><i class="bi bi-unlock"></i> Sin SSL</span>
                      </td>
                      <td>
                        <span :class="domain.is_active ? 'badge bg-success' : 'badge bg-danger'">
                          {{ domain.is_active ? 'Activo' : 'Inactivo' }}
                        </span>
                      </td>
                      <td>
                        <div class="btn-group btn-group-sm">
                          <button class="btn btn-outline-info" @click="openChangePHP(domain)" title="Cambiar PHP">
                            <i class="bi bi-filetype-php"></i>
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
        </template>
      </div>
    </div>

    <!-- Modal: editar usuario -->
    <Modal :isOpen="showEditUser" title="Editar Usuario" @close="showEditUser = false">
      <UserForm :user="user" @submit="onUserUpdated" @cancel="showEditUser = false" />
    </Modal>

    <!-- Modal: añadir cliente (reseller) -->
    <Modal :isOpen="showAddClient" title="Añadir Cliente" @close="showAddClient = false">
      <UserForm :parentId="user?.id" @submit="onClientAdded" @cancel="showAddClient = false" />
    </Modal>

    <!-- Modal: añadir dominio -->
    <Modal :isOpen="showAddDomain" title="Añadir Dominio" @close="showAddDomain = false">
      <form @submit.prevent="handleAddDomain">
        <div class="mb-3">
          <label class="form-label">Nombre de dominio</label>
          <input v-model="newDomain.domain_name" type="text" class="form-control" placeholder="ejemplo.com" required />
        </div>
        <div class="mb-3">
          <label class="form-label">Versión PHP</label>
          <select v-model="newDomain.php_version" class="form-select">
            <option value="8.5">PHP 8.5</option>
            <option value="8.4">PHP 8.4</option>
            <option value="8.3">PHP 8.3</option>
            <option value="8.2">PHP 8.2 (recomendado)</option>
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

    <!-- Modal: cambiar PHP -->
    <Modal :isOpen="showChangePHP" :title="`PHP — ${selectedDomain?.domain_name}`" @close="showChangePHP = false">
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
    const clients = ref([])
    const domains = ref([])
    const loadingUser = ref(true)
    const loadingClients = ref(false)
    const loadingDomains = ref(false)

    const showEditUser = ref(false)
    const showAddClient = ref(false)
    const showAddDomain = ref(false)
    const showChangePHP = ref(false)
    const selectedDomain = ref(null)
    const phpVersion = ref('8.2')
    const addingDomain = ref(false)
    const changingPHP = ref(false)
    const newDomain = ref({ domain_name: '', php_version: '8.2' })

    const roleLabel = (role) => ({ admin: '🔑 Admin', reseller: '🏪 Reseller', user: '👤 Usuario' }[role] ?? role)
    const roleBadgeClass = (role) => ({ admin: 'bg-danger', reseller: 'bg-warning text-dark', user: 'bg-secondary' }[role] ?? 'bg-secondary')
    const formatDate = (d) => d ? new Date(d).toLocaleDateString('es-ES', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

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

    const loadClients = async () => {
      loadingClients.value = true
      try {
        const data = await api.getUsers(0, 100, null, userId)
        clients.value = Array.isArray(data) ? data : []
      } catch (e) {
        store.showNotification('Error al cargar clientes', 'danger')
      } finally {
        loadingClients.value = false
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

    const onUserUpdated = async () => {
      showEditUser.value = false
      await loadUser()
    }

    const onClientAdded = async () => {
      showAddClient.value = false
      await loadClients()
    }

    const deleteClientConfirm = (client) => {
      if (confirm(`¿Eliminar cliente "${client.username}"?\nEsto eliminará también sus dominios y archivos.`)) {
        api.deleteUser(client.id)
          .then(() => { store.showNotification('Cliente eliminado', 'success'); loadClients() })
          .catch(e => store.showNotification('Error: ' + e.message, 'danger'))
      }
    }

    const handleAddDomain = async () => {
      addingDomain.value = true
      try {
        await api.createDomain({ user_id: userId, domain_name: newDomain.value.domain_name, php_version: newDomain.value.php_version })
        store.showNotification('Dominio creado', 'success')
        showAddDomain.value = false
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
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
        store.showNotification('PHP actualizado', 'success')
        showChangePHP.value = false
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        changingPHP.value = false
      }
    }

    const deleteDomainConfirm = (domain) => {
      if (confirm(`¿Eliminar dominio "${domain.domain_name}"?`)) {
        api.deleteDomain(domain.id)
          .then(() => { store.showNotification('Dominio eliminado', 'success'); loadDomains() })
          .catch(e => store.showNotification('Error: ' + e.message, 'danger'))
      }
    }

    onMounted(async () => {
      await loadUser()
      if (user.value?.role === 'reseller') {
        await loadClients()
      } else {
        await loadDomains()
      }
    })

    return {
      user, clients, domains,
      loadingUser, loadingClients, loadingDomains,
      showEditUser, showAddClient, showAddDomain, showChangePHP,
      selectedDomain, phpVersion, newDomain, addingDomain, changingPHP,
      roleLabel, roleBadgeClass, formatDate,
      onUserUpdated, onClientAdded, deleteClientConfirm,
      handleAddDomain, openChangePHP, handleChangePHP, deleteDomainConfirm
    }
  }
}
</script>
