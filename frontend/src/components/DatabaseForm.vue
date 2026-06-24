<template>
  <form @submit.prevent="handleSubmit">

    <!-- Selector de usuario propietario: obligatorio para admin/reseller -->
    <div v-if="isAdminOrReseller && !isEditing" class="mb-3">
      <label class="form-label">Usuario (cliente propietario)</label>
      <select v-model.number="form.user_id" class="form-select" required>
        <option :value="null">Selecciona un cliente</option>
        <option v-for="user in clientUsers" :key="user.id" :value="user.id">
          {{ user.username }} ({{ user.email }})
        </option>
      </select>
      <div v-if="clientUsers.length === 0" class="form-text text-warning">
        No hay cuentas de cliente. Las bases de datos pertenecen a un cliente, no
        al administrador; crea primero un usuario en la sección Usuarios.
      </div>
      <small v-else class="text-muted">
        La BD y su usuario MariaDB se crearán bajo este cliente, no bajo tu cuenta.
      </small>
    </div>

    <!-- Sufijo de BD -->
    <div class="mb-3">
      <label class="form-label">Nombre de BD (sufijo)</label>
      <input
        v-model="form.db_name_suffix"
        type="text"
        class="form-control"
        placeholder="wordpress"
        pattern="^[a-z0-9_]{1,32}$"
        required
      />
      <small class="text-muted">
        Ej: wordpress. Nombre real: <code>{{ predictedDbName }}</code>
        (máx 64 caracteres)
      </small>
    </div>

    <!-- Sufijo de usuario -->
    <div class="mb-3">
      <label class="form-label">Usuario MariaDB (sufijo)</label>
      <input
        v-model="form.db_user_suffix"
        type="text"
        class="form-control"
        placeholder="wpuser"
        pattern="^[a-z0-9_]{1,32}$"
        required
      />
      <small class="text-muted">
        Ej: wpuser. Usuario real: <code>{{ predictedDbUser }}</code>
        (máx 32 caracteres)
      </small>
    </div>

    <!-- Contraseña -->
    <div class="mb-3">
      <label class="form-label">Contraseña BD</label>
      <PasswordField v-model="form.db_password" placeholder="Contraseña de la base de datos" @valid="pwdValid = $event" />
    </div>

    <!-- Charset y Collation -->
    <div class="row">
      <div class="col-md-6 mb-3">
        <label class="form-label">Charset</label>
        <select v-model="form.db_charset" class="form-select" required>
          <option value="">Selecciona charset</option>
          <option v-for="charset in charsets" :key="charset" :value="charset">
            {{ charset }}
          </option>
        </select>
      </div>
      <div class="col-md-6 mb-3">
        <label class="form-label">Collation</label>
        <select v-model="form.db_collation" class="form-select" required>
          <option value="">Selecciona collation</option>
          <option v-for="collation in availableCollations" :key="collation" :value="collation">
            {{ collation }}
          </option>
        </select>
      </div>
    </div>

    <!-- Dominio (opcional) -->
    <div class="mb-3">
      <label class="form-label">Dominio asociado (opcional)</label>
      <select v-model.number="form.domain_id" class="form-select">
        <option :value="null">-- Sin dominio --</option>
        <option v-for="domain in userDomains" :key="domain.id" :value="domain.id">
          {{ domain.domain_name }}
        </option>
      </select>
      <small class="text-muted">Vincula esta BD a un dominio para mejor organización</small>
    </div>

    <!-- Quota -->
    <div class="mb-3">
      <label class="form-label">Límite de almacenamiento</label>
      <SizeInput v-model="form.quota_mb" />
      <small class="text-muted">0 = sin límite, máx 100 GB</small>
    </div>

    <!-- Botones -->
    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        {{ isEditing ? 'Actualizar' : 'Crear' }} BD
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
import databaseService from '../services/databaseService'
import PasswordField from './PasswordField.vue'
import SizeInput from './SizeInput.vue'

export default {
  name: 'DatabaseForm',
  components: { PasswordField, SizeInput },
  props: {
    database: { type: Object, default: null },
    domains: { type: Array, default: () => [] },
    users: { type: Array, default: () => [] },
    ownerUsername: { type: String, default: '' }
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const pwdValid = ref(false)
    const charsetList = ref([])
    const collationMap = ref({})
    const isEditing = ref(!!props.database)

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role) || store.currentUser?.is_admin
    )

    // Solo clientes pueden ser propietarios (las BDs no son del admin)
    const clientUsers = computed(() =>
      props.users.filter(u => u.role !== 'admin' && !u.is_admin)
    )

    const form = ref({
      db_name_suffix: props.database?.db_name_suffix || '',
      db_user_suffix: props.database?.db_user_suffix || '',
      db_password: '',
      db_charset: props.database?.db_charset || 'utf8mb4',
      db_collation: props.database?.db_collation || 'utf8mb4_unicode_ci',
      // Para admin/reseller arranca vacío (debe elegir cliente); para usuario
      // normal es él mismo.
      user_id: props.database?.user_id ||
               (['admin', 'reseller'].includes(store.currentUser?.role) || store.currentUser?.is_admin
                 ? null : store.currentUser?.id),
      domain_id: props.database?.domain_id || null,
      quota_mb: props.database?.quota_mb || 1024
    })

    const charsets = computed(() => charsetList.value)

    const availableCollations = computed(() => {
      return collationMap.value[form.value.db_charset] || []
    })

    const currentUser = computed(() => store.currentUser)

    const userDomains = computed(() => {
      return props.domains.filter(d =>
        store.currentUser?.is_admin || d.user_id === store.currentUser?.id
      )
    })

    // Username del propietario: el cliente seleccionado (admin/reseller) o el
    // propio usuario. Determina el prefijo real de la BD y del usuario MariaDB.
    const ownerUsername = computed(() => {
      if (form.value.user_id) {
        const u = props.users.find(x => x.id === form.value.user_id)
        if (u) return u.username
      }
      return props.ownerUsername || currentUser.value?.username || 'user'
    })

    const predictedDbName = computed(() => {
      if (!form.value.db_name_suffix) return '(nombre real)'
      const prefix = ownerUsername.value.slice(0, 16)
      return `${prefix}_${form.value.db_name_suffix}`.slice(0, 64)
    })

    const predictedDbUser = computed(() => {
      if (!form.value.db_user_suffix) return '(usuario real)'
      const prefix = ownerUsername.value.slice(0, 10)
      return `${prefix}_${form.value.db_user_suffix}`.slice(0, 32)
    })

    const loadCharsets = async () => {
      try {
        const data = await databaseService.getCharsets()
        charsetList.value = data.map(c => c.charset)
        data.forEach(c => {
          collationMap.value[c.charset] = c.collations.map(col => col.name)
        })
      } catch (error) {
        store.showNotification('Error cargando charsets: ' + error.message, 'error')
      }
    }

    const handleSubmit = async () => {
      if (!form.value.db_password && !isEditing.value) {
        store.showNotification('Ingresa una contraseña', 'error')
        return
      }

      // Admin/reseller deben asignar la BD a un cliente (no al admin)
      if (!isEditing.value && isAdminOrReseller.value && !form.value.user_id) {
        store.showNotification('Selecciona el usuario propietario de la base de datos', 'error')
        return
      }

      loading.value = true
      try {
        if (isEditing.value) {
          await databaseService.update(props.database.id, {
            domain_id: form.value.domain_id,
            quota_mb: form.value.quota_mb,
            is_active: true
          })
          store.showNotification('BD actualizada correctamente', 'success')
        } else {
          await databaseService.create(form.value)
          store.showNotification(
            `⚠️ BD creada. Guarda la contraseña: ${form.value.db_password}`,
            'success'
          )
        }
        emit('submit')
      } catch (error) {
        store.showNotification(`Error: ${error.message}`, 'error')
      } finally {
        loading.value = false
      }
    }

    onMounted(() => {
      loadCharsets()
    })

    return {
      form,
      loading,
      pwdValid,
      charsets,
      availableCollations,
      isEditing,
      isAdminOrReseller,
      clientUsers,
      predictedDbName,
      predictedDbUser,
      userDomains,
      handleSubmit
    }
  }
}
</script>
