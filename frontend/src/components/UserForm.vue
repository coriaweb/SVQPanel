<template>
  <form @submit.prevent="handleSubmit">
    <div class="mb-3">
      <label for="username" class="form-label">Usuario</label>
      <input
        id="username"
        v-model="form.username"
        type="text"
        class="form-control"
        placeholder="nombre_usuario"
        required
        :disabled="isEditing"
      />
      <small class="text-muted">Solo letras, números y guiones bajos</small>
    </div>

    <div class="mb-3">
      <label for="email" class="form-label">Email</label>
      <input
        id="email"
        v-model="form.email"
        type="email"
        class="form-control"
        placeholder="usuario@ejemplo.com"
        required
      />
    </div>

    <div class="row">
      <div class="col-md-6 mb-3">
        <label for="first_name" class="form-label">Nombre</label>
        <input
          id="first_name"
          v-model="form.first_name"
          type="text"
          class="form-control"
          placeholder="Juan"
        />
      </div>
      <div class="col-md-6 mb-3">
        <label for="last_name" class="form-label">Apellido</label>
        <input
          id="last_name"
          v-model="form.last_name"
          type="text"
          class="form-control"
          placeholder="Pérez"
        />
      </div>
    </div>

    <div v-if="!isEditing" class="mb-3">
      <label for="password" class="form-label">Contraseña</label>
      <input
        id="password"
        v-model="form.password"
        type="password"
        class="form-control"
        placeholder="Mínimo 8 caracteres"
        required
        minlength="8"
      />
    </div>

    <div class="row">
      <div class="col-md-6 mb-3">
        <label for="role" class="form-label">Rol</label>
        <select id="role" v-model="form.role" class="form-select">
          <option value="user">👤 Usuario</option>
          <option value="reseller">🏪 Revendedor</option>
          <option value="admin">🔑 Administrador</option>
        </select>
        <small class="text-muted">{{ roleDescription }}</small>
      </div>
      <div class="col-md-6 mb-3">
        <label for="domains_limit" class="form-label">Límite de dominios</label>
        <input
          id="domains_limit"
          v-model.number="form.domains_limit"
          type="number"
          class="form-control"
          min="0"
          placeholder="10"
        />
        <small class="text-muted">0 = sin límite</small>
      </div>
    </div>

    <div class="mb-3 form-check">
      <input
        id="is_active"
        v-model="form.is_active"
        type="checkbox"
        class="form-check-input"
      />
      <label for="is_active" class="form-check-label">
        Usuario activo
      </label>
    </div>

    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        {{ isEditing ? 'Actualizar' : 'Crear' }} Usuario
      </button>
      <button type="button" class="btn btn-secondary" @click="$emit('cancel')" :disabled="loading">
        Cancelar
      </button>
    </div>
  </form>
</template>

<script>
import { ref, computed } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'UserForm',
  props: {
    user: {
      type: Object,
      default: null
    },
    parentId: {
      type: Number,
      default: null
    }
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const isEditing = ref(!!props.user)

    const form = ref({
      username: props.user?.username || '',
      email: props.user?.email || '',
      first_name: props.user?.first_name || '',
      last_name: props.user?.last_name || '',
      password: '',
      role: props.user?.role || 'user',
      domains_limit: props.user?.domains_limit ?? 10,
      is_active: props.user?.is_active ?? true
    })

    const roleDescription = computed(() => {
      switch (form.value.role) {
        case 'admin': return 'Acceso total al panel'
        case 'reseller': return 'Puede gestionar sus propios usuarios'
        case 'user': return 'Solo gestiona sus propios dominios'
        default: return ''
      }
    })

    const handleSubmit = async () => {
      loading.value = true
      try {
        if (isEditing.value) {
          await api.updateUser(props.user.id, {
            email: form.value.email,
            first_name: form.value.first_name,
            last_name: form.value.last_name,
            role: form.value.role,
            domains_limit: form.value.domains_limit,
            is_active: form.value.is_active
          })
          store.showNotification('Usuario actualizado correctamente', 'success')
        } else {
          await api.createUser({
            username: form.value.username,
            email: form.value.email,
            first_name: form.value.first_name,
            last_name: form.value.last_name,
            password: form.value.password,
            role: form.value.role,
            domains_limit: form.value.domains_limit,
            is_active: form.value.is_active,
            ...(props.parentId ? { parent_id: props.parentId } : {})
          })
          store.showNotification('Usuario creado correctamente', 'success')
        }
        emit('submit')
      } catch (error) {
        store.showNotification('Error al procesar usuario: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    return {
      form,
      loading,
      isEditing,
      roleDescription,
      handleSubmit
    }
  }
}
</script>
