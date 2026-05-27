<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-people"></i> Usuarios</h2>
      <button class="btn btn-primary" @click="openCreateForm">
        <i class="bi bi-person-plus"></i> Crear Usuario
      </button>
    </div>

    <!-- Users Table -->
    <div class="card">
      <div class="card-body">
        <div v-if="loading" class="text-center py-4">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="users.length === 0" class="alert alert-info">
          No hay usuarios creados aún
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle">
            <thead class="table-light">
              <tr>
                <th>Usuario</th>
                <th>Plan</th>
                <th>Rol</th>
                <th>Dominios</th>
                <th style="min-width: 160px;">Disco</th>
                <th style="min-width: 160px;">Tráfico (mes)</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td>
                  <i class="bi bi-person-circle text-secondary me-1"></i>
                  <strong>{{ user.username }}</strong>
                  <div class="small text-muted">{{ user.email }}</div>
                  <div v-if="user.first_name || user.last_name" class="small text-muted">
                    {{ [user.first_name, user.last_name].filter(Boolean).join(' ') }}
                  </div>
                </td>
                <td>
                  <span v-if="user.plan_name" class="badge bg-info">{{ user.plan_name }}</span>
                  <span v-else class="text-muted small">—</span>
                </td>
                <td>
                  <span :class="roleBadgeClass(user.role)" class="badge">
                    {{ roleLabel(user.role) }}
                  </span>
                </td>
                <td>
                  <span class="text-muted">
                    <i class="bi bi-globe2 me-1"></i>
                    {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}
                  </span>
                </td>
                <td>
                  <UsageBar :used="user.disk_used_mb || 0" :quota="user.disk_quota_mb || 0" />
                </td>
                <td>
                  <UsageBar :used="user.traffic_used_mb_month || 0" :quota="user.traffic_quota_mb_month || 0" />
                </td>
                <td>
                  <span v-if="user.is_active" class="badge bg-success">Activo</span>
                  <span v-else class="badge bg-danger">Inactivo</span>
                </td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button
                      class="btn btn-outline-primary"
                      @click="goToAccount(user.id)"
                      title="Gestionar cuenta"
                    >
                      <i class="bi bi-box-arrow-in-right"></i> Gestionar
                    </button>
                    <button class="btn btn-outline-warning" @click="openEditForm(user)" title="Editar">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger" @click="deleteUserConfirm(user)" title="Eliminar">
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

    <!-- User Form Modal -->
    <Modal :isOpen="showUserForm" :title="editingUser ? 'Editar Usuario' : 'Crear Usuario'" @close="closeUserForm">
      <UserForm
        :user="editingUser"
        @submit="handleUserSubmit"
        @cancel="closeUserForm"
      />
    </Modal>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'
import UsageBar from '../components/UsageBar.vue'

export default {
  name: 'Users',
  components: {
    Modal,
    UserForm,
    UsageBar
  },
  setup() {
    const store = useMainStore()
    const router = useRouter()
    const users = ref([])
    const loading = ref(false)
    const showUserForm = ref(false)
    const editingUser = ref(null)

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

    const loadUsers = async () => {
      loading.value = true
      try {
        const data = await api.getUsers(0, 100)
        users.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar usuarios', 'danger')
      } finally {
        loading.value = false
      }
    }

    const goToAccount = (userId) => {
      router.push(`/users/${userId}/account`)
    }

    const openCreateForm = () => {
      editingUser.value = null
      showUserForm.value = true
    }

    const openEditForm = (user) => {
      editingUser.value = user
      showUserForm.value = true
    }

    const closeUserForm = () => {
      showUserForm.value = false
      editingUser.value = null
    }

    const handleUserSubmit = async () => {
      await loadUsers()
      closeUserForm()
    }

    const deleteUserConfirm = (user) => {
      if (confirm(`¿Eliminar usuario "${user.username}"?\n\nEsto eliminará también su cuenta del sistema y todos sus archivos.`)) {
        deleteUser(user.id)
      }
    }

    const deleteUser = async (userId) => {
      try {
        await api.deleteUser(userId)
        store.showNotification('Usuario eliminado', 'success')
        loadUsers()
      } catch (error) {
        store.showNotification('Error al eliminar usuario: ' + error.message, 'danger')
      }
    }

    onMounted(loadUsers)

    return {
      users,
      loading,
      showUserForm,
      editingUser,
      roleLabel,
      roleBadgeClass,
      goToAccount,
      openCreateForm,
      openEditForm,
      closeUserForm,
      handleUserSubmit,
      deleteUserConfirm
    }
  }
}
</script>
