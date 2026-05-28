<template>
  <form @submit.prevent="handleSubmit">

    <div class="mb-3">
      <label class="form-label">Nombre de Dominio</label>
      <input
        v-model="form.domain_name"
        type="text"
        class="form-control"
        placeholder="ejemplo.com"
        required
        :disabled="isEditing"
      />
      <small class="text-muted">Ej: ejemplo.com o sub.ejemplo.com</small>
    </div>

    <!-- Selector de usuario: solo para admin/reseller -->
    <div v-if="isAdminOrReseller && !isEditing" class="mb-3">
      <label class="form-label">Usuario</label>
      <select v-model="form.user_id" class="form-select" required>
        <option value="">Selecciona un usuario</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }} ({{ user.email }})
        </option>
      </select>
    </div>

    <div class="mb-3">
      <label class="form-label">Versión PHP</label>
      <select v-model="form.php_version" class="form-select" required>
        <option value="">Selecciona versión</option>
        <option v-for="version in availablePhpVersions" :key="version" :value="version">
          PHP {{ version }}
        </option>
      </select>
      <div class="form-text">Solo se muestran versiones instaladas y activas en el servidor.</div>
    </div>

    <div class="mb-3 form-check">
      <input id="is_active" v-model="form.is_active" type="checkbox" class="form-check-input" />
      <label for="is_active" class="form-check-label">Dominio activo</label>
    </div>

    <!-- Rendimiento (solo al editar: requiere un dominio ya existente) -->
    <template v-if="isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Rendimiento</p>

      <div class="mb-2 form-check">
        <input id="fcgi_cache" v-model="form.fastcgi_cache_enabled" type="checkbox" class="form-check-input" />
        <label for="fcgi_cache" class="form-check-label">
          <i class="bi bi-lightning-charge me-1"></i> Habilitar caché FastCGI (NGINX)
        </label>
      </div>
      <div v-if="form.fastcgi_cache_enabled" class="mb-3 ps-4">
        <label class="form-label small mb-1">Duración de la caché (minutos)</label>
        <input
          v-model.number="form.fastcgi_cache_ttl_minutes"
          type="number" min="1" max="1440"
          class="form-control form-control-sm"
          style="max-width:160px"
        />
        <div class="form-text">Tiempo que NGINX cachea las respuestas PHP. Ej: 2, 30, 60.</div>
      </div>
    </template>

    <!-- Opciones extras (solo en creación) -->
    <template v-if="!isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Servicios adicionales</p>

      <div class="mb-2 form-check">
        <input id="dns_enabled" v-model="form.dns_enabled" type="checkbox" class="form-check-input" />
        <label for="dns_enabled" class="form-check-label">
          <i class="bi bi-diagram-3 me-1"></i> Soporte DNS
          <small class="text-muted">(Crear zona en servidor DNS)</small>
        </label>
      </div>

      <div class="mb-3 form-check">
        <input id="mail_enabled" v-model="form.mail_enabled" type="checkbox" class="form-check-input" />
        <label for="mail_enabled" class="form-check-label">
          <i class="bi bi-envelope me-1"></i> Soporte Correo
          <small class="text-muted">(Crear dominio de correo)</small>
        </label>
      </div>
    </template>

    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        {{ isEditing ? 'Actualizar' : 'Crear' }} Dominio
      </button>
      <button type="button" class="btn btn-secondary" @click="$emit('cancel')" :disabled="loading">
        Cancelar
      </button>
    </div>
  </form>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'DomainForm',
  props: {
    domain:      { type: Object, default: null },
    // Versiones PHP ya cargadas por el padre (para no hacer doble petición)
    phpVersions: { type: Array, default: () => [] },
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading   = ref(false)
    const isEditing = ref(!!props.domain)
    const users     = ref([])
    const localPhpVersions = ref([])

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    // Versiones disponibles: usa las del padre si las pasa, si no carga propias
    const availablePhpVersions = computed(() =>
      props.phpVersions.length ? props.phpVersions : localPhpVersions.value
    )

    const form = ref({
      domain_name: props.domain?.domain_name || '',
      user_id:     props.domain?.user_id     || (isAdminOrReseller.value ? '' : store.currentUser?.id),
      php_version: props.domain?.php_version || '',
      is_active:   props.domain?.is_active   ?? true,
      fastcgi_cache_enabled:     props.domain?.fastcgi_cache_enabled     ?? false,
      fastcgi_cache_ttl_minutes: props.domain?.fastcgi_cache_ttl_minutes ?? 60,
      dns_enabled:  false,
      mail_enabled: false,
    })

    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch { /* silencioso */ }
    }

    const loadPHPVersions = async () => {
      if (props.phpVersions.length) return   // el padre ya las pasó
      try {
        const data = await api.getPHPVersions()
        localPhpVersions.value = data?.versions?.length ? data.versions : ['8.2']
      } catch {
        localPhpVersions.value = ['8.2']
      }
      // Ajustar versión seleccionada si la actual no está en la lista
      if (!form.value.php_version || !availablePhpVersions.value.includes(form.value.php_version)) {
        form.value.php_version = availablePhpVersions.value[0] || '8.2'
      }
    }

    const handleSubmit = async () => {
      loading.value = true
      try {
        if (isEditing.value) {
          await api.updateDomain(props.domain.id, {
            php_version: form.value.php_version,
            is_active:   form.value.is_active,
          })
          // Caché FastCGI: solo si cambió respecto al estado original (reescribe el vhost)
          const prevEnabled = props.domain.fastcgi_cache_enabled ?? false
          const prevTtl     = props.domain.fastcgi_cache_ttl_minutes ?? 60
          const cacheChanged =
            form.value.fastcgi_cache_enabled !== prevEnabled ||
            (form.value.fastcgi_cache_enabled && form.value.fastcgi_cache_ttl_minutes !== prevTtl)
          if (cacheChanged) {
            await api.setDomainCache(
              props.domain.id,
              form.value.fastcgi_cache_enabled,
              form.value.fastcgi_cache_ttl_minutes,
            )
          }
          store.showNotification('Dominio actualizado correctamente', 'success')
        } else {
          const userId = isAdminOrReseller.value
            ? form.value.user_id
            : store.currentUser?.id
          await api.createDomain({
            domain_name: form.value.domain_name,
            user_id:     userId,
            php_version: form.value.php_version,
            is_active:   form.value.is_active,
            dns_enabled:  form.value.dns_enabled,
            mail_enabled: form.value.mail_enabled,
          })
          store.showNotification('Dominio creado correctamente', 'success')
        }
        emit('submit')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    onMounted(async () => {
      await Promise.all([loadUsers(), loadPHPVersions()])
      // Si la versión guardada no está en la lista, seleccionar la primera disponible
      if (form.value.php_version && !availablePhpVersions.value.includes(form.value.php_version)) {
        form.value.php_version = availablePhpVersions.value[0] || '8.2'
      } else if (!form.value.php_version && availablePhpVersions.value.length) {
        form.value.php_version = availablePhpVersions.value[0]
      }
    })

    return {
      form, loading, isEditing, users,
      isAdminOrReseller, availablePhpVersions,
      handleSubmit,
    }
  }
}
</script>
