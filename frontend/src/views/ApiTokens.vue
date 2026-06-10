<template>
  <div>
    <div class="page-head">
      <div>
        <h2><i class="bi bi-key"></i> API Tokens</h2>
        <p class="text-muted mb-0">
          Acceso programático a la API del panel · {{ tokens.length }}
          {{ tokens.length === 1 ? 'token' : 'tokens' }}
        </p>
      </div>
      <button class="btn btn-primary" @click="openCreate">
        <i class="bi bi-plus-circle"></i> Crear token
      </button>
    </div>

    <!-- Pista de documentación -->
    <div class="alert alert-info">
      <i class="bi bi-info-circle-fill me-2"></i>
      Usa el token en la cabecera <code>Authorization: Bearer &lt;token&gt;</code>.
      La referencia de la API está en <a href="/docs" target="_blank">/docs</a> (Swagger).
      El token hereda <strong>tus permisos</strong>: solo puede hacer lo que tú puedes hacer en el panel.
    </div>

    <!-- Filtro por usuario (solo admin) -->
    <div v-if="isAdmin" class="mb-3">
      <select v-model="selectedUser" class="form-select" @change="load">
        <option value="">Todos los tokens</option>
        <option value="mine">Mis tokens</option>
      </select>
    </div>

    <!-- Tabla de tokens -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="tokens.length === 0" class="alert alert-info m-3 mb-0">
          <i class="bi bi-info-circle me-2"></i>
          No tienes ningún token creado todavía.
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Nombre</th>
                <th v-if="isAdmin">Usuario</th>
                <th>Token</th>
                <th>IPs permitidas</th>
                <th>Caducidad</th>
                <th>Último uso</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tokens" :key="t.id">
                <td>{{ t.name }}</td>
                <td v-if="isAdmin" class="small">{{ t.username || '—' }}</td>
                <td><code>{{ t.prefix }}…</code></td>
                <td class="small">
                  <span v-if="t.allowed_ips && t.allowed_ips.length">
                    {{ t.allowed_ips.join(', ') }}
                  </span>
                  <span v-else class="text-muted">cualquiera</span>
                </td>
                <td class="small">{{ t.expires_at ? fmtDate(t.expires_at) : 'No caduca' }}</td>
                <td class="small">{{ t.last_used_at ? fmtDate(t.last_used_at) : 'Nunca' }}</td>
                <td>
                  <span v-if="t.is_revoked" class="badge bg-danger">Revocado</span>
                  <span v-else-if="t.is_expired" class="badge bg-warning text-dark">Caducado</span>
                  <span v-else class="badge bg-success">Activo</span>
                </td>
                <td>
                  <button
                    class="btn btn-sm btn-outline-danger"
                    :disabled="t.is_revoked"
                    @click="confirmRevoke(t)"
                    title="Revocar"
                  >
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal: crear token -->
    <div v-if="showCreate" class="modal-backdrop-custom" @click.self="showCreate = false">
      <div class="modal-card">
        <h4 class="mb-3"><i class="bi bi-key"></i> Nuevo API token</h4>

        <div class="mb-3">
          <label class="form-label">Nombre</label>
          <input v-model="form.name" class="form-control" placeholder="ej. Script de backups" maxlength="64" />
        </div>

        <div class="mb-3">
          <label class="form-label">Caducidad (opcional)</label>
          <input v-model="form.expires_at" type="date" class="form-control" />
          <small class="text-muted">Déjalo vacío para que no caduque.</small>
        </div>

        <div class="mb-3">
          <label class="form-label">IPs permitidas (opcional)</label>
          <textarea
            v-model="form.allowed_ips"
            class="form-control"
            rows="2"
            placeholder="Una IPv4 por línea o separadas por comas. Vacío = cualquier IP."
          ></textarea>
          <small class="text-muted">Si indicas IPs, el token <strong>solo</strong> funcionará desde ellas.</small>
        </div>

        <div class="alert alert-warning small">
          <i class="bi bi-shield-exclamation me-1"></i>
          Un API token salta el doble factor (2FA) y puede operar la API en tu nombre.
          El secreto se mostrará <strong>una sola vez</strong>: guárdalo en un sitio seguro.
        </div>

        <div class="d-flex justify-content-end gap-2">
          <button class="btn btn-secondary" @click="showCreate = false">Cancelar</button>
          <button class="btn btn-primary" :disabled="creating || !form.name.trim()" @click="submitCreate">
            <span v-if="creating" class="spinner-border spinner-border-sm me-1"></span>
            Crear token
          </button>
        </div>
      </div>
    </div>

    <!-- Modal: secreto recién creado (una sola vez) -->
    <div v-if="createdSecret" class="modal-backdrop-custom">
      <div class="modal-card">
        <h4 class="mb-3"><i class="bi bi-check-circle text-success"></i> Token creado</h4>
        <p class="small text-muted mb-2">
          Cópialo ahora. Por seguridad <strong>no se volverá a mostrar</strong>.
        </p>
        <div class="input-group mb-3">
          <input :value="createdSecret" class="form-control font-monospace" readonly @focus="$event.target.select()" />
          <button class="btn btn-outline-primary" @click="copySecret">
            <i class="bi" :class="copied ? 'bi-check2' : 'bi-clipboard'"></i>
            {{ copied ? 'Copiado' : 'Copiar' }}
          </button>
        </div>
        <div class="d-flex justify-content-end">
          <button class="btn btn-primary" @click="closeSecret">Hecho, lo he guardado</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import tokenService from '../services/tokenService'
import { useMainStore } from '../stores/useMainStore'

export default {
  name: 'ApiTokens',
  setup() {
    const store = useMainStore()
    const tokens = ref([])
    const loading = ref(true)
    const selectedUser = ref('')

    const showCreate = ref(false)
    const creating = ref(false)
    const form = ref({ name: '', expires_at: '', allowed_ips: '' })

    const createdSecret = ref('')
    const copied = ref(false)

    const isAdmin = computed(() => store.currentUser?.role === 'admin')

    const fmtDate = (d) => {
      try { return new Date(d).toLocaleString() } catch { return d }
    }

    const load = async () => {
      loading.value = true
      try {
        // admin con "Mis tokens" → filtra por su id; resto → sus propios tokens
        const uid = isAdmin.value && selectedUser.value === 'mine' ? store.currentUser?.id : null
        tokens.value = await tokenService.list(uid)
      } catch (e) {
        store.showNotification(`Error cargando tokens: ${e.message}`, 'error')
      } finally {
        loading.value = false
      }
    }

    const openCreate = () => {
      form.value = { name: '', expires_at: '', allowed_ips: '' }
      showCreate.value = true
    }

    const submitCreate = async () => {
      creating.value = true
      try {
        const ips = form.value.allowed_ips
          .split(/[\n,]+/).map(s => s.trim()).filter(Boolean)
        const payload = { name: form.value.name.trim() }
        if (form.value.expires_at) payload.expires_at = new Date(form.value.expires_at).toISOString()
        if (ips.length) payload.allowed_ips = ips

        const res = await tokenService.create(payload)
        showCreate.value = false
        createdSecret.value = res.secret
        copied.value = false
        await load()
      } catch (e) {
        store.showNotification(`Error creando token: ${e.message}`, 'error')
      } finally {
        creating.value = false
      }
    }

    const copySecret = async () => {
      try {
        await navigator.clipboard.writeText(createdSecret.value)
        copied.value = true
      } catch {
        store.showNotification('No se pudo copiar; selecciona y copia manualmente.', 'warning')
      }
    }

    const closeSecret = () => {
      createdSecret.value = ''
      copied.value = false
    }

    const confirmRevoke = async (t) => {
      if (!confirm(`¿Revocar el token "${t.name}"? Dejará de funcionar al instante y no se puede deshacer.`)) return
      try {
        await tokenService.revoke(t.id)
        store.showNotification('Token revocado', 'success')
        await load()
      } catch (e) {
        store.showNotification(`Error revocando token: ${e.message}`, 'error')
      }
    }

    onMounted(load)

    return {
      tokens, loading, selectedUser, isAdmin,
      showCreate, creating, form, openCreate, submitCreate,
      createdSecret, copied, copySecret, closeSecret,
      confirmRevoke, load, fmtDate,
    }
  },
}
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}
.modal-backdrop-custom {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  padding: 1rem;
}
.modal-card {
  background: var(--color-surface, #fff);
  border-radius: var(--radius-lg, 12px);
  padding: 1.5rem;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.font-monospace { font-family: var(--font-mono, monospace); }
</style>
