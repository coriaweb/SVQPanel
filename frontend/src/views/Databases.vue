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
                      class="btn btn-outline-secondary"
                      @click="openUsersModal(db)"
                      title="Gestionar usuarios"
                      v-if="canManage(db)"
                    >
                      <i class="bi bi-people"></i>
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
        :users="users"
        :owner-username="currentUser?.username || ''"
        @submit="handleFormSubmit"
        @cancel="showFormModal = false"
      />
    </Modal>

    <!-- Modal: Usuarios adicionales de BD -->
    <Modal
      :isOpen="showUsersModal"
      :title="`Usuarios de BD: ${selectedDatabase?.db_name || ''}`"
      @close="showUsersModal = false"
    >
      <div>
        <!-- Info BD -->
        <p class="text-muted small mb-3">
          <i class="bi bi-info-circle me-1"></i>
          Usuario principal: <code>{{ selectedDatabase?.db_user }}</code> (gestionado desde Editar / Cambiar contraseña).
          Aquí puedes añadir usuarios adicionales con permisos limitados.
        </p>

        <!-- Tabla de usuarios existentes -->
        <div v-if="dbUsersLoading" class="text-center py-3">
          <div class="spinner-border spinner-border-sm" role="status"></div>
        </div>
        <div v-else-if="dbUsers.length === 0" class="alert alert-info mb-3">
          <i class="bi bi-info-circle me-1"></i>No hay usuarios adicionales.
        </div>
        <div v-else class="mb-4">
          <div v-for="u in dbUsers" :key="u.id" class="border rounded mb-2 p-2">

            <!-- Fila normal -->
            <div v-if="editingDbUser?.id !== u.id" class="d-flex align-items-center gap-2 flex-wrap">
              <code class="small flex-shrink-0">{{ u.username }}</code>
              <div class="flex-fill d-flex flex-wrap gap-1">
                <span v-for="p in parsePerms(u.permissions)" :key="p" class="badge bg-secondary">{{ p }}</span>
              </div>
              <span v-if="u.is_active" class="badge bg-success">Activo</span>
              <span v-else class="badge bg-secondary">Inactivo</span>
              <div class="d-flex gap-1 ms-auto">
                <button class="btn btn-outline-primary btn-sm" @click="startEditDbUser(u)" title="Editar permisos / contraseña">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-outline-danger btn-sm" @click="confirmDeleteDbUser(u)" title="Eliminar">
                  <i class="bi bi-trash"></i>
                </button>
              </div>
            </div>

            <!-- Formulario de edición inline -->
            <div v-else>
              <div class="fw-semibold small mb-2"><code>{{ u.username }}</code></div>

              <!-- Permisos -->
              <div class="mb-2">
                <label class="form-label small mb-1">Permisos</label>
                <div class="d-flex flex-wrap gap-2">
                  <div v-for="perm in availablePermissions" :key="perm" class="form-check form-check-inline">
                    <input class="form-check-input" type="checkbox" :id="`edit-perm-${u.id}-${perm}`"
                      :value="perm" v-model="editDbUserForm.permissions" />
                    <label class="form-check-label small" :for="`edit-perm-${u.id}-${perm}`">{{ perm }}</label>
                  </div>
                </div>
              </div>

              <!-- Nueva contraseña (opcional) -->
              <div class="mb-2">
                <label class="form-label small mb-1">Nueva contraseña <span class="text-muted">(dejar vacío para no cambiar)</span></label>
                <div class="input-group input-group-sm">
                  <input v-model="editDbUserForm.new_password"
                    :type="editDbUserForm.showPassword ? 'text' : 'password'"
                    class="form-control" placeholder="Mínimo 8 caracteres" />
                  <button type="button" class="btn btn-outline-secondary"
                    @click="editDbUserForm.showPassword = !editDbUserForm.showPassword">
                    <i :class="editDbUserForm.showPassword ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
                  </button>
                </div>
              </div>

              <div class="d-flex gap-2">
                <button class="btn btn-primary btn-sm" @click="saveEditDbUser" :disabled="editDbUserLoading">
                  <span v-if="editDbUserLoading" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-check-lg me-1"></i>Guardar
                </button>
                <button class="btn btn-outline-secondary btn-sm" @click="cancelEditDbUser">Cancelar</button>
              </div>
            </div>

          </div>
        </div>

        <!-- Formulario: añadir usuario -->
        <h6 class="fw-semibold mb-2"><i class="bi bi-person-plus me-1"></i>Añadir usuario</h6>
        <form @submit.prevent="handleCreateDbUser">
          <div class="row g-2 mb-2">
            <div class="col-sm-5">
              <label class="form-label small mb-1">Sufijo de usuario <span class="text-muted">(a-z, 0-9, _)</span></label>
              <input
                v-model="newDbUser.suffix"
                type="text"
                class="form-control form-control-sm"
                placeholder="ej: readonly"
                maxlength="16"
                pattern="[a-z0-9_]+"
                required
              />
              <div class="form-text">Nombre resultante: <code>{{ dbUserPreviewName }}</code></div>
            </div>
            <div class="col-sm-7">
              <label class="form-label small mb-1">Contraseña</label>
              <div class="input-group input-group-sm">
                <input
                  v-model="newDbUser.password"
                  :type="showDbUserPassword ? 'text' : 'password'"
                  class="form-control"
                  placeholder="Mínimo 8 caracteres"
                  required
                />
                <button
                  type="button"
                  class="btn btn-outline-secondary"
                  @click="showDbUserPassword = !showDbUserPassword"
                >
                  <i :class="showDbUserPassword ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
                </button>
              </div>
            </div>
          </div>

          <!-- Permisos (checkboxes) -->
          <div class="mb-3">
            <label class="form-label small mb-1">Permisos</label>
            <div class="d-flex flex-wrap gap-2">
              <div
                v-for="perm in availablePermissions"
                :key="perm"
                class="form-check form-check-inline"
              >
                <input
                  class="form-check-input"
                  type="checkbox"
                  :id="`perm-${perm}`"
                  :value="perm"
                  v-model="newDbUser.permissions"
                />
                <label class="form-check-label small" :for="`perm-${perm}`">{{ perm }}</label>
              </div>
            </div>
          </div>

          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary btn-sm" :disabled="dbUserCreateLoading">
              <span v-if="dbUserCreateLoading" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-person-plus me-1"></i>Añadir usuario
            </button>
          </div>
        </form>
      </div>
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

    // ── Estado: usuarios adicionales de BD ──────────────────────────────────
    const showUsersModal     = ref(false)
    const dbUsers            = ref([])
    const dbUsersLoading     = ref(false)
    const dbUserCreateLoading = ref(false)
    const showDbUserPassword = ref(false)
    const newDbUser = ref({ suffix: '', password: '', permissions: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'] })

    const availablePermissions = [
      'SELECT', 'INSERT', 'UPDATE', 'DELETE',
      'CREATE', 'DROP', 'INDEX', 'ALTER',
    ]

    const dbUserPreviewName = computed(() => {
      if (!selectedDatabase.value || !newDbUser.value.suffix) return '—'
      const ownerUser = users.value.find(u => u.id === selectedDatabase.value?.user_id)
      const ownerUsername = ownerUser?.username || store.currentUser?.username || ''
      const prefix = ownerUsername.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 10)
      return `${prefix}_${newDbUser.value.suffix}`
    })

    const currentUser = computed(() => store.currentUser)

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    const allDomains = ref([])

    const userDomains = computed(() => {
      if (!selectedUser.value || selectedUser.value === 'all') return allDomains.value
      return allDomains.value.filter(d => d.user_id === Number(selectedUser.value))
    })

    const loadDomains = async () => {
      try {
        const data = await api.getDomains()
        allDomains.value = Array.isArray(data) ? data : (data?.items || [])
      } catch { allDomains.value = [] }
    }

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
        const data = await api.getUsers(0, 1000)
        users.value = Array.isArray(data) ? data : []
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

    // ── Lógica: usuarios adicionales de BD ──────────────────────────────────

    const openUsersModal = async (db) => {
      selectedDatabase.value = db
      dbUsers.value = []
      newDbUser.value = { suffix: '', password: '', permissions: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'] }
      showDbUserPassword.value = false
      showUsersModal.value = true
      await loadDbUsers(db.id)
    }

    const loadDbUsers = async (dbId) => {
      dbUsersLoading.value = true
      try {
        const data = await api.getDbUsers(dbId)
        dbUsers.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification(`Error cargando usuarios de BD: ${error.message}`, 'error')
      } finally {
        dbUsersLoading.value = false
      }
    }

    const handleCreateDbUser = async () => {
      if (!newDbUser.value.suffix.match(/^[a-z0-9_]+$/)) {
        store.showNotification('El sufijo solo puede contener letras minúsculas, números y _', 'error')
        return
      }
      if (newDbUser.value.password.length < 8) {
        store.showNotification('La contraseña debe tener al menos 8 caracteres', 'error')
        return
      }
      if (newDbUser.value.permissions.length === 0) {
        store.showNotification('Selecciona al menos un permiso', 'error')
        return
      }
      dbUserCreateLoading.value = true
      try {
        await api.createDbUser(selectedDatabase.value.id, {
          username_suffix: newDbUser.value.suffix,
          password: newDbUser.value.password,
          permissions: newDbUser.value.permissions,
        })
        store.showNotification('Usuario añadido correctamente', 'success')
        newDbUser.value = { suffix: '', password: '', permissions: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'] }
        await loadDbUsers(selectedDatabase.value.id)
      } catch (error) {
        store.showNotification(`Error creando usuario: ${error.message}`, 'error')
      } finally {
        dbUserCreateLoading.value = false
      }
    }

    const confirmDeleteDbUser = async (dbUser) => {
      if (confirm(`¿Eliminar el usuario "${dbUser.username}" de MariaDB? Esta acción no se puede deshacer.`)) {
        try {
          await api.deleteDbUser(selectedDatabase.value.id, dbUser.id)
          store.showNotification('Usuario eliminado correctamente', 'success')
          await loadDbUsers(selectedDatabase.value.id)
        } catch (error) {
          store.showNotification(`Error eliminando usuario: ${error.message}`, 'error')
        }
      }
    }

    // Parsea permisos que pueden venir como JSON array o como string CSV
    const parsePerms = (raw) => {
      if (!raw) return []
      if (Array.isArray(raw)) return raw
      const s = raw.trim()
      if (s.startsWith('[')) {
        try { return JSON.parse(s) } catch { /* fallback */ }
      }
      return s.split(',').map(p => p.trim()).filter(Boolean)
    }

    // ── Edición inline de usuario adicional ────────────────────────────────
    const editingDbUser     = ref(null)   // usuario que se está editando
    const editDbUserLoading = ref(false)
    const editDbUserForm    = ref({ permissions: [], new_password: '', showPassword: false })

    const startEditDbUser = (u) => {
      editingDbUser.value  = u
      editDbUserForm.value = {
        permissions:  parsePerms(u.permissions),
        new_password: '',
        showPassword: false,
      }
    }

    const cancelEditDbUser = () => { editingDbUser.value = null }

    const saveEditDbUser = async () => {
      editDbUserLoading.value = true
      try {
        const payload = { permissions: editDbUserForm.value.permissions }
        if (editDbUserForm.value.new_password) {
          if (editDbUserForm.value.new_password.length < 8) {
            store.showNotification('La contraseña debe tener al menos 8 caracteres', 'error')
            return
          }
          payload.new_password = editDbUserForm.value.new_password
        }
        await databaseService.updateDbUser(selectedDatabase.value.id, editingDbUser.value.id, payload)
        store.showNotification('Usuario actualizado correctamente', 'success')
        editingDbUser.value = null
        await loadDbUsers(selectedDatabase.value.id)
      } catch (error) {
        store.showNotification(`Error actualizando usuario: ${error.message}`, 'error')
      } finally {
        editDbUserLoading.value = false
      }
    }

    onMounted(() => {
      loadDatabases()
      loadUsers()
      loadDomains()
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
      pmaLoading,
      // Usuarios adicionales de BD
      showUsersModal,
      dbUsers,
      dbUsersLoading,
      dbUserCreateLoading,
      showDbUserPassword,
      newDbUser,
      availablePermissions,
      dbUserPreviewName,
      openUsersModal,
      handleCreateDbUser,
      confirmDeleteDbUser,
      parsePerms,
      // Edición inline
      editingDbUser,
      editDbUserLoading,
      editDbUserForm,
      startEditDbUser,
      cancelEditDbUser,
      saveEditDbUser,
    }
  }
}
</script>

<style scoped>
.db-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); margin-bottom: var(--sp-5); flex-wrap: wrap; }
.db-head h2 { margin: 0 0 2px; }
</style>
