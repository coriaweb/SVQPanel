<template>
  <div>
    <div class="db-head">
      <div>
        <h2><i class="bi bi-database"></i> Bases de Datos</h2>
        <p class="text-muted mb-0">
          {{ databases.length }} {{ databases.length === 1 ? 'base de datos' : 'bases de datos' }} · MariaDB
        </p>
      </div>
      <button class="btn btn-primary" @click="openCreateForm" v-if="!isMariaDBDisabled">
        <i class="bi bi-plus-circle"></i> Crear BD
      </button>
      <button class="btn btn-warning" disabled v-else>
        <i class="bi bi-exclamation-triangle"></i> MariaDB no habilitado
      </button>
    </div>

    <!-- Advertencia si MariaDB no está habilitado -->
    <div v-if="isMariaDBDisabled" class="alert alert-warning" role="alert">
      <i class="bi bi-exclamation-triangle-fill me-2"></i>
      <strong>MariaDB no está habilitado en este servidor.</strong>
      Los clientes no pueden crear bases de datos hasta que el administrador lo configure.
    </div>

    <!-- Filtro por usuario (solo admin/reseller) -->
    <div v-if="isAdminOrReseller" class="mb-3">
      <select v-model="selectedUser" class="form-select" @change="loadDatabases">
        <option value="">Mis bases de datos</option>
        <option value="all">Todas las bases de datos</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }} ({{ user.email }})
        </option>
      </select>
    </div>

    <!-- Tabla de BDs -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="databases.length === 0" class="alert alert-info m-3 mb-0">
          <i class="bi bi-info-circle me-2"></i>
          {{ isMariaDBDisabled ? 'MariaDB no está disponible' : 'No hay bases de datos creadas' }}
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Nombre BD</th>
                <th v-if="isAdminOrReseller">Usuario</th>
                <th>Usuario MariaDB</th>
                <th>Almacenamiento</th>
                <th>Charset</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="db in databases" :key="db.id">
                <td>
                  <i class="bi bi-database text-primary me-1"></i>
                  <code class="fw-semibold">{{ db.db_name }}</code>
                </td>
                <td v-if="isAdminOrReseller" class="small">
                  {{ getUserName(db.user_id) }}
                </td>
                <td>
                  <code class="small">{{ db.db_user }}</code>
                </td>
                <td>
                  <span class="badge bg-info">{{ db.size_mb }} / {{ db.quota_mb }} MB</span>
                </td>
                <td>
                  <span class="badge bg-secondary">{{ db.db_charset }}</span>
                </td>
                <td>
                  <span v-if="db.is_active" class="badge bg-success">
                    <i class="bi bi-check-circle me-1"></i>Activo
                  </span>
                  <span v-else class="badge bg-danger">
                    <i class="bi bi-x-circle me-1"></i>Inactivo
                  </span>
                </td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button
                      class="btn btn-outline-success"
                      @click="openPhpMyAdmin(db)"
                      title="Abrir phpMyAdmin"
                      :disabled="pmaLoading === db.id"
                      v-if="canManage(db)"
                    >
                      <span v-if="pmaLoading === db.id" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-box-arrow-up-right"></i>
                    </button>
                    <button
                      class="btn btn-outline-info"
                      @click="openEditForm(db)"
                      title="Editar"
                      v-if="canManage(db)"
                    >
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button
                      class="btn btn-outline-warning"
                      @click="openPasswordForm(db)"
                      title="Cambiar contraseña"
                      v-if="canManage(db)"
                    >
                      <i class="bi bi-key"></i>
                    </button>
                    <button
                      class="btn btn-outline-danger"
                      @click="confirmDelete(db)"
                      title="Eliminar"
                      v-if="canManage(db)"
                    >
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

    <!-- Modal: Crear/Editar BD -->
    <Modal
      :isOpen="showFormModal"
      :title="editingDatabase ? 'Editar BD' : 'Crear Nueva BD'"
      @close="showFormModal = false"
    >
      <DatabaseForm
        :database="editingDatabase"
        :domains="userDomains"
        @submit="handleFormSubmit"
        @cancel="showFormModal = false"
      />
    </Modal>

    <!-- Modal: Cambiar contraseña -->
    <Modal
      :isOpen="showPasswordModal"
      title="Cambiar Contraseña BD"
      @close="showPasswordModal = false"
    >
      <div>
        <p class="mb-3">
          <strong>BD:</strong> <code>{{ selectedDatabase?.db_name }}</code> <br>
          <strong>Usuario:</strong> <code>{{ selectedDatabase?.db_user }}</code>
        </p>
        <form @submit.prevent="handlePasswordChange">
          <div class="mb-3">
            <label class="form-label">Nueva Contraseña</label>
            <div class="input-group">
              <input
                v-model="newPassword"
                :type="showNewPassword ? 'text' : 'password'"
                class="form-control"
                placeholder="Mínimo 8 caracteres"
                required
              />
              <button
                type="button"
                class="btn btn-outline-secondary"
                @click="showNewPassword = !showNewPassword"
              >
                <i :class="showNewPassword ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
              </button>
            </div>
          </div>
          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-warning" :disabled="passwordLoading">
              <span v-if="passwordLoading" class="spinner-border spinner-border-sm me-2"></span>
              Cambiar Contraseña
            </button>
            <button type="button" class="btn btn-secondary" @click="showPasswordModal = false">
              Cancelar
            </button>
          </div>
        </form>
      </div>
    </Modal>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import databaseService from '../services/databaseService'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import DatabaseForm from '../components/DatabaseForm.vue'

export default {
  name: 'Databases',
  components: { Modal, DatabaseForm },
  setup() {
    const store = useMainStore()
    const databases = ref([])
    const users = ref([])
    const loading = ref(false)
    const showFormModal = ref(false)
    const showPasswordModal = ref(false)
    const editingDatabase = ref(null)
    const selectedDatabase = ref(null)
    const selectedUser = ref('')
    const newPassword = ref('')
    const passwordLoading = ref(false)
    const showNewPassword = ref(false)
    const isMariaDBDisabled = ref(false)
    const pmaLoading = ref(null)  // id de la BD cuyo botón phpMyAdmin está en carga

    const currentUser = computed(() => store.currentUser)

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    const userDomains = computed(() => {
      // Para admin/reseller, mostrar dominios del usuario seleccionado
      if (store.currentUser?.is_admin && selectedUser.value && selectedUser.value !== 'all') {
        return [] // Podría loadear dominios del usuario seleccionado
      }
      return []
    })

    const loadDatabases = async () => {
      loading.value = true
      try {
        const userId = selectedUser.value && selectedUser.value !== 'all' ? selectedUser.value : null
        const data = await databaseService.list(userId)
        // La API devuelve { total, items }
        databases.value = data?.items || []
      } catch (error) {
        // api.js lanza errores planos (Error), no Axios. Detectar 503 por texto del mensaje.
        const msg = error.message || ''
        if (msg.includes('503') || msg.toLowerCase().includes('no está habilitado')) {
          isMariaDBDisabled.value = true
          databases.value = []
        } else {
          store.showNotification(`Error cargando bases de datos: ${msg}`, 'error')
        }
      } finally {
        loading.value = false
      }
    }

    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return
      try {
        const response = await api.get('/users?limit=1000')
        users.value = response.data.data || []
      } catch (error) {
        console.error('Error cargando usuarios:', error)
      }
    }

    const openCreateForm = () => {
      editingDatabase.value = null
      showFormModal.value = true
    }

    const openEditForm = (db) => {
      editingDatabase.value = db
      showFormModal.value = true
    }

    const openPasswordForm = (db) => {
      selectedDatabase.value = db
      newPassword.value = ''
      showNewPassword.value = false
      showPasswordModal.value = true
    }

    const handleFormSubmit = async () => {
      showFormModal.value = false
      await loadDatabases()
    }

    const handlePasswordChange = async () => {
      if (newPassword.value.length < 8) {
        store.showNotification('La contraseña debe tener al menos 8 caracteres', 'error')
        return
      }

      passwordLoading.value = true
      try {
        await databaseService.resetPassword(selectedDatabase.value.id, newPassword.value)
        store.showNotification(`⚠️ Nueva contraseña guardada para ${selectedDatabase.value.db_user}`, 'success')
        showPasswordModal.value = false
        await loadDatabases()
      } catch (error) {
        store.showNotification(`Error cambiando contraseña: ${error.message}`, 'error')
      } finally {
        passwordLoading.value = false
      }
    }

    const confirmDelete = async (db) => {
      if (confirm(`¿Eliminar BD "${db.db_name}"? Esta acción no se puede deshacer.`)) {
        try {
          await databaseService.delete(db.id)
          store.showNotification('BD eliminada correctamente', 'success')
          await loadDatabases()
        } catch (error) {
          store.showNotification(`Error eliminando BD: ${error.message}`, 'error')
        }
      }
    }

    const openPhpMyAdmin = async (db) => {
      pmaLoading.value = db.id
      try {
        const data = await databaseService.getPMAToken(db.id)
        if (data?.pma_url) {
          window.open(data.pma_url, '_blank', 'noopener,noreferrer')
        } else {
          store.showNotification('No se pudo obtener el enlace de phpMyAdmin', 'error')
        }
      } catch (error) {
        const msg = error.message || ''
        if (msg.includes('503') || msg.toLowerCase().includes('no está configurado')) {
          store.showNotification('phpMyAdmin no está instalado en este servidor', 'warning')
        } else if (msg.includes('409') || msg.toLowerCase().includes('no hay contraseña')) {
          store.showNotification(
            'Cambia la contraseña de esta BD desde el panel para habilitar phpMyAdmin',
            'warning'
          )
        } else {
          store.showNotification(`Error abriendo phpMyAdmin: ${msg}`, 'error')
        }
      } finally {
        pmaLoading.value = null
      }
    }

    const canManage = (db) => {
      return store.currentUser?.is_admin || db.user_id === store.currentUser?.id
    }

    const getUserName = (userId) => {
      const user = users.value.find(u => u.id === userId)
      return user ? `${user.username} (${user.email})` : `Usuario ${userId}`
    }

    onMounted(() => {
      loadDatabases()
      loadUsers()
    })

    return {
      databases,
      users,
      loading,
      showFormModal,
      showPasswordModal,
      editingDatabase,
      selectedDatabase,
      selectedUser,
      newPassword,
      passwordLoading,
      showNewPassword,
      isMariaDBDisabled,
      currentUser,
      isAdminOrReseller,
      userDomains,
      loadDatabases,
      openCreateForm,
      openEditForm,
      openPasswordForm,
      handleFormSubmit,
      handlePasswordChange,
      confirmDelete,
      canManage,
      getUserName,
      openPhpMyAdmin,
      pmaLoading
    }
  }
}
</script>

<style scoped>
.db-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); margin-bottom: var(--sp-5); flex-wrap: wrap; }
.db-head h2 { margin: 0 0 2px; }
</style>
