<template>
  <form @submit.prevent="handleSubmit">
    <div class="mb-3">
      <label for="domain_name" class="form-label">Nombre de Dominio</label>
      <input
        id="domain_name"
        v-model="form.domain_name"
        type="text"
        class="form-control"
        placeholder="ejemplo.com"
        required
        :disabled="isEditing"
      />
      <small class="text-muted">Ej: ejemplo.com o sub.ejemplo.com</small>
    </div>

    <div class="mb-3">
      <label for="user_id" class="form-label">Usuario</label>
      <select
        id="user_id"
        v-model="form.user_id"
        class="form-select"
        required
        :disabled="isEditing"
      >
        <option value="">Selecciona un usuario</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }} ({{ user.email }})
        </option>
      </select>
    </div>

    <div class="mb-3">
      <label for="php_version" class="form-label">Versión PHP</label>
      <select
        id="php_version"
        v-model="form.php_version"
        class="form-select"
        required
      >
        <option value="">Selecciona versión</option>
        <option v-for="version in phpVersions" :key="version" :value="version">
          PHP {{ version }}
        </option>
      </select>
    </div>

    <div class="mb-3 form-check">
      <input
        id="is_active"
        v-model="form.is_active"
        type="checkbox"
        class="form-check-input"
      />
      <label for="is_active" class="form-check-label">
        Dominio activo
      </label>
    </div>

    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        {{ isEditing ? 'Actualizar' : 'Crear' }} Dominio
      </button>
      <button type="button" class="btn btn-secondary" @click="$emit('cancel')" :disabled="loading">
        Cancelar
      </button>
    </div>
  </form>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'DomainForm',
  props: {
    domain: {
      type: Object,
      default: null
    }
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const isEditing = ref(!!props.domain)
    const users = ref([])
    const phpVersions = ref(['7.4', '8.0', '8.1', '8.2', '8.3'])

    const form = ref({
      domain_name: props.domain?.domain_name || '',
      user_id: props.domain?.user_id || '',
      php_version: props.domain?.php_version || '8.2',
      is_active: props.domain?.is_active ?? true
    })

    const loadUsers = async () => {
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar usuarios', 'danger')
      }
    }

    const handleSubmit = async () => {
      loading.value = true
      try {
        if (isEditing.value) {
          await api.updateDomain(props.domain.id, {
            php_version: form.value.php_version,
            is_active: form.value.is_active
          })
          store.showNotification('Dominio actualizado correctamente', 'success')
        } else {
          await api.createDomain({
            domain_name: form.value.domain_name,
            user_id: form.value.user_id,
            php_version: form.value.php_version,
            is_active: form.value.is_active
          })
          store.showNotification('Dominio creado correctamente', 'success')
        }
        emit('submit')
      } catch (error) {
        store.showNotification('Error al procesar dominio: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    onMounted(loadUsers)

    return {
      form,
      loading,
      isEditing,
      users,
      phpVersions,
      handleSubmit
    }
  }
}
</script>
