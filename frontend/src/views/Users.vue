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
        <div v-if="loading" class="loading">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="users.length === 0" class="alert alert-info">
          No hay usuarios creados aún
        </div>
        <table v-else class="table table-hover">
          <thead>
            <tr>
              <th>Usuario</th>
              <th>Email</th>
              <th>Nombre</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <i class="bi bi-person-circle"></i> {{ user.username }}
              </td>
              <td>{{ user.email }}</td>
              <td>{{ user.first_name }} {{ user.last_name }}</td>
              <td>
                <span v-if="user.is_active" class="badge bg-success">Activo</span>
                <span v-else class="badge bg-danger">Inactivo</span>
              </td>
              <td>
                <button class="btn btn-sm btn-warning me-2" @click="openEditForm(user)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-danger" @click="deleteUserConfirm(user.id)">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
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
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'

export default {
  name: 'Users',
  components: {
    Modal,
    UserForm
  },
  setup() {
    const store = useMainStore()
    const users = ref([])
    const loading = ref(false)
    const showUserForm = ref(false)
    const editingUser = ref(null)

    const loadUsers = async () => {
      loading.value = true
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar usuarios', 'danger')
      } finally {
        loading.value = false
      }
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

    const deleteUserConfirm = (userId) => {
      if (confirm('¿Estás seguro de que deseas eliminar este usuario?')) {
        deleteUser(userId)
      }
    }

    const deleteUser = async (userId) => {
      try {
        await api.deleteUser(userId)
        store.showNotification('Usuario eliminado', 'success')
        loadUsers()
      } catch (error) {
        store.showNotification('Error al eliminar usuario', 'danger')
      }
    }

    onMounted(loadUsers)

    return {
      users,
      loading,
      showUserForm,
      editingUser,
      openCreateForm,
      openEditForm,
      closeUserForm,
      handleUserSubmit,
      deleteUserConfirm
    }
  }
}
</script>
