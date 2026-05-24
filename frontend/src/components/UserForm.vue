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
      <small class="text-muted">Solo letras, números y guiones</small>
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

    <div class="mb-3">
      <label for="first_name" class="form-label">Nombre</label>
      <input
        id="first_name"
        v-model="form.first_name"
        type="text"
        class="form-control"
        placeholder="Juan"
      />
    </div>

    <div class="mb-3">
      <label for="last_name" class="form-label">Apellido</label>
      <input
        id="last_name"
        v-model="form.last_name"
        type="text"
        class="form-control"
        placeholder="Pérez"
      />
    </div>

    <div v-if="!isEditing" class="mb-3">
      <label for="password" class="form-label">Contraseña</label>
      <input
        id="password"
        v-model="form.password"
        type="password"
        class="form-control"
        placeholder="••••••••"
        required
      />
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
import { ref } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'UserForm',
  props: {
    user: {
      type: Object,
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
      is_active: props.user?.is_active ?? true
    })

    const handleSubmit = async () => {
      loading.value = true
      try {
        if (isEditing.value) {
          await api.updateUser(props.user.id, {
            email: form.value.email,
            first_name: form.value.first_name,
            last_name: form.value.last_name,
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
            is_active: form.value.is_active
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
      handleSubmit
    }
  }
}
</script>
