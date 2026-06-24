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

    <!-- Contraseña al crear -->
    <div v-if="!isEditing" class="mb-3">
      <label for="password" class="form-label">Contraseña</label>
      <PasswordField v-model="form.password" placeholder="Contraseña del usuario" />
    </div>

    <!-- Cambiar contraseña al editar -->
    <div v-if="isEditing" class="mb-3">
      <div
        class="d-flex align-items-center gap-2 mb-2 cursor-pointer"
        style="cursor:pointer"
        @click="showPasswordChange = !showPasswordChange"
      >
        <i :class="showPasswordChange ? 'bi bi-chevron-down' : 'bi bi-chevron-right'" class="text-muted"></i>
        <span class="fw-semibold small text-muted text-uppercase">Cambiar contraseña</span>
        <span v-if="showPasswordChange" class="badge bg-warning text-dark small">opcional</span>
      </div>

      <div v-if="showPasswordChange" class="border rounded p-3 bg-light">
        <div class="mb-2">
          <label class="form-label small mb-1">Nueva contraseña</label>
          <PasswordField v-model="form.new_password" placeholder="Nueva contraseña" />
        </div>
        <div class="mb-1">
          <label class="form-label small mb-1">Confirmar contraseña</label>
          <input
            v-model="form.new_password_confirm"
            type="password"
            class="form-control form-control-sm"
            :class="passwordError ? 'is-invalid' : ''"
            placeholder="Repite la contraseña"
          />
          <div v-if="passwordError" class="invalid-feedback d-block">{{ passwordError }}</div>
        </div>
      </div>
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
        <label for="plan_id" class="form-label">Plan</label>
        <select id="plan_id" v-model="form.plan_id" class="form-select" :disabled="!plans.length">
          <option :value="null">— Sin plan (límites manuales) —</option>
          <option v-for="p in plans" :key="p.id" :value="p.id">
            {{ p.name }}
            <template v-if="p.owner_id === null"> (global)</template>
            <template v-else> ({{ p.owner_username }})</template>
          </option>
        </select>
        <small class="text-muted">
          Al asignar plan se copian sus límites; si lo dejas vacío usa los valores manuales.
        </small>
      </div>
    </div>

    <div class="row" v-if="!form.plan_id">
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
      <div class="col-md-6 mb-3">
        <label for="disk_quota_mb" class="form-label">Cuota de disco (MB)</label>
        <input
          id="disk_quota_mb"
          v-model.number="form.disk_quota_mb"
          type="number"
          class="form-control"
          min="0"
          placeholder="1024"
        />
        <small class="text-muted">0 = sin límite · se aplica con cuotas del SO</small>
      </div>
    </div>
    <div class="row" v-else>
      <div class="col-12 mb-3">
        <div class="alert alert-info py-2 mb-0 small">
          <i class="bi bi-info-circle me-1"></i>
          Los límites se copiarán del plan seleccionado al guardar.
        </div>
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
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import PasswordField from './PasswordField.vue'

export default {
  name: 'UserForm',
  components: { PasswordField },
  props: {
    user:     { type: Object, default: null },
    parentId: { type: Number, default: null }
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const isEditing = ref(!!props.user)
    const showPasswordChange = ref(false)

    const form = ref({
      username:            props.user?.username    || '',
      email:               props.user?.email       || '',
      first_name:          props.user?.first_name  || '',
      last_name:           props.user?.last_name   || '',
      password:            '',
      new_password:        '',
      new_password_confirm:'',
      role:                props.user?.role        || 'user',
      domains_limit:       props.user?.domains_limit ?? 10,
      disk_quota_mb:       props.user?.disk_quota_mb ?? 1024,
      plan_id:             props.user?.plan_id     ?? null,
      is_active:           props.user?.is_active   ?? true,
    })

    const plans = ref([])
    onMounted(async () => {
      try { plans.value = await api.getPlans() }
      catch (e) { /* ignorar: usuario sin permisos para planes */ }
    })

    const roleDescription = computed(() => ({
      admin:    'Acceso total al panel',
      reseller: 'Puede gestionar sus propios usuarios',
      user:     'Solo gestiona sus propios dominios',
    }[form.value.role] ?? ''))

    const passwordError = computed(() => {
      if (!form.value.new_password && !form.value.new_password_confirm) return null
      if (form.value.new_password.length < 8) return 'Mínimo 8 caracteres'
      if (form.value.new_password !== form.value.new_password_confirm) return 'Las contraseñas no coinciden'
      return null
    })

    const handleSubmit = async () => {
      // Validar contraseña si se está cambiando
      if (isEditing.value && form.value.new_password && passwordError.value) {
        store.showNotification(passwordError.value, 'danger')
        return
      }

      loading.value = true
      try {
        let userId
        if (isEditing.value) {
          const payload = {
            email:         form.value.email,
            first_name:    form.value.first_name,
            last_name:     form.value.last_name,
            role:          form.value.role,
            domains_limit: form.value.domains_limit,
            is_active:     form.value.is_active,
          }
          // Solo enviar cuota si el usuario no tiene plan (con plan la fija el plan)
          if (!form.value.plan_id) {
            payload.disk_quota_mb = form.value.disk_quota_mb
          }
          // Solo incluir new_password si se rellenó y es válida
          if (form.value.new_password && !passwordError.value) {
            payload.new_password = form.value.new_password
          }
          await api.updateUser(props.user.id, payload)
          userId = props.user.id
          // Aplicar plan si cambió
          const prevPlanId = props.user.plan_id ?? null
          if (form.value.plan_id !== prevPlanId) {
            if (form.value.plan_id) await api.assignPlanToUser(userId, form.value.plan_id)
            else                    await api.unassignPlanFromUser(userId)
          }
          store.showNotification('Usuario actualizado correctamente', 'success')
        } else {
          const created = await api.createUser({
            username:      form.value.username,
            email:         form.value.email,
            first_name:    form.value.first_name,
            last_name:     form.value.last_name,
            password:      form.value.password,
            role:          form.value.role,
            domains_limit: form.value.domains_limit,
            is_active:     form.value.is_active,
            ...(props.parentId ? { parent_id: props.parentId } : {})
          })
          userId = created?.id
          if (userId && form.value.plan_id) {
            await api.assignPlanToUser(userId, form.value.plan_id)
          }
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
      form, loading, isEditing,
      showPasswordChange, passwordError,
      roleDescription, handleSubmit,
      plans,
    }
  }
}
</script>
