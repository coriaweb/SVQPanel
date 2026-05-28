<template>
  <div>
    <div v-if="loading" class="text-center py-3">
      <div class="spinner-border spinner-border-sm"></div>
    </div>
    <div v-else-if="error" class="alert alert-warning small mb-0">
      {{ error }}
    </div>
    <div v-else>
      <!-- Toggle SFTP enabled -->
      <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
          <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" id="sftpSwitch"
                   v-model="status.enabled" @change="toggleEnabled" :disabled="busy">
            <label class="form-check-label" for="sftpSwitch">
              <strong>{{ status.enabled ? 'SFTP activo' : 'SFTP desactivado' }}</strong>
            </label>
          </div>
          <div class="small text-muted">
            <span v-if="status.enabled">
              chroot a <code class="small">{{ status.chroot_to }}</code> — sólo SFTP, sin shell.
            </span>
            <span v-else>
              El usuario no puede conectar por SFTP.
            </span>
          </div>
        </div>
      </div>

      <template v-if="status.enabled">
        <!-- Password -->
        <div class="border rounded p-3 mb-3 bg-light">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <strong class="small">
              <i class="bi bi-key me-1"></i>Contraseña SFTP (cuenta Linux)
            </strong>
            <small v-if="status.password_set_at" class="text-muted">
              cambiada {{ formatDate(status.password_set_at) }}
            </small>
            <small v-else class="text-danger">
              <i class="bi bi-exclamation-triangle me-1"></i>nunca asignada
            </small>
          </div>
          <form @submit.prevent="changePassword" class="row g-2 align-items-end">
            <div class="col">
              <input type="password" class="form-control form-control-sm"
                     v-model="newPassword" placeholder="Nueva contraseña (min. 8)"
                     minlength="8" required>
            </div>
            <div class="col-auto">
              <button type="submit" class="btn btn-sm btn-primary" :disabled="busy">
                <span v-if="busy" class="spinner-border spinner-border-sm me-1"></span>
                Guardar
              </button>
            </div>
          </form>
        </div>

        <!-- SSH Keys -->
        <div class="border rounded p-3 mb-3">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <strong class="small">
              <i class="bi bi-shield-lock me-1"></i>Claves SSH públicas
              <span class="badge bg-secondary ms-1">{{ status.ssh_keys.length }}</span>
            </strong>
            <small class="text-muted">authorized_keys</small>
          </div>

          <div v-if="!status.ssh_keys.length" class="small text-muted mb-2">
            Sin claves añadidas. Sube tu clave pública (más seguro que contraseña).
          </div>
          <ul v-else class="list-unstyled mb-2">
            <li v-for="k in status.ssh_keys" :key="k.fingerprint"
                class="d-flex justify-content-between align-items-center border-bottom py-1 small">
              <div>
                <span class="badge bg-info text-dark me-2">{{ k.type }}</span>
                <span v-if="k.comment" class="text-muted">{{ k.comment }}</span>
                <div class="font-monospace text-muted" style="font-size: 11px;">{{ k.fingerprint }}</div>
              </div>
              <button class="btn btn-sm btn-outline-danger" @click="removeKey(k.fingerprint)" :disabled="busy">
                <i class="bi bi-trash"></i>
              </button>
            </li>
          </ul>

          <form @submit.prevent="addKey">
            <textarea class="form-control form-control-sm font-monospace" rows="2"
                      v-model="newKey" placeholder="ssh-ed25519 AAAAC3NzaC1lZ... usuario@maquina"
                      style="font-size: 11px;"></textarea>
            <div class="d-flex justify-content-between align-items-center mt-2">
              <small class="text-muted">Formato OpenSSH: tipo base64 comentario</small>
              <button type="submit" class="btn btn-sm btn-success" :disabled="busy || !newKey.trim()">
                <i class="bi bi-plus-lg me-1"></i>Añadir clave
              </button>
            </div>
          </form>
        </div>

        <div class="alert alert-info small mb-3">
          <strong>Cómo conectar:</strong>
          <code class="ms-1">sftp {{ status.username }}@TU_SERVIDOR</code>
          — el cliente verá <code>web/</code>, <code>files/</code>, y <code>.ssh/</code>.
        </div>
      </template>

      <!-- ═══ Cuentas SFTP adicionales (subcuentas con jaula estricta) ═══ -->
      <div class="border rounded p-3">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <strong class="small">
            <i class="bi bi-people me-1"></i>Cuentas SFTP adicionales
            <span class="badge bg-secondary ms-1">{{ accounts.length }}</span>
          </strong>
          <button class="btn btn-sm btn-success" @click="showCreate = !showCreate" :disabled="busy">
            <i class="bi bi-plus-lg me-1"></i>Nueva cuenta
          </button>
        </div>
        <p class="small text-muted mb-2">
          Cada cuenta queda <strong>enjaulada exclusivamente</strong> a la carpeta que elijas
          dentro del espacio del cliente (no ve nada más).
        </p>

        <!-- Form crear -->
        <div v-if="showCreate" class="bg-light rounded p-3 mb-3">
          <div class="row g-2">
            <div class="col-md-4">
              <label class="form-label small mb-1">Nombre (etiqueta)</label>
              <input class="form-control form-control-sm" v-model="newAcc.label"
                     placeholder="dev1" pattern="[a-z][a-z0-9_]+">
              <small class="text-muted">usuario: {{ status.username }}_{{ newAcc.label || 'xxx' }}</small>
            </div>
            <div class="col-md-5">
              <label class="form-label small mb-1">Carpeta destino</label>
              <select class="form-select form-select-sm" v-model="newAcc.target_subpath">
                <option value="" disabled>— elige carpeta —</option>
                <option v-for="f in folders" :key="f" :value="f">{{ f }}</option>
              </select>
            </div>
            <div class="col-md-3">
              <label class="form-label small mb-1">Contraseña</label>
              <input type="password" class="form-control form-control-sm" v-model="newAcc.password"
                     placeholder="(opcional)" minlength="8">
            </div>
          </div>
          <div class="text-end mt-2">
            <button class="btn btn-sm btn-outline-secondary me-2" @click="showCreate=false" :disabled="busy">Cancelar</button>
            <button class="btn btn-sm btn-primary" @click="createAccount"
                    :disabled="busy || !newAcc.label || !newAcc.target_subpath">
              <span v-if="busy" class="spinner-border spinner-border-sm me-1"></span>Crear cuenta
            </button>
          </div>
        </div>

        <!-- Lista -->
        <div v-if="!accounts.length" class="small text-muted">Sin cuentas adicionales.</div>
        <table v-else class="table table-sm align-middle mb-0">
          <thead class="table-light">
            <tr><th>Usuario</th><th>Carpeta (jaula)</th><th>Claves</th><th class="text-end">Acciones</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in accounts" :key="a.id">
              <td class="font-monospace small">{{ a.username }}</td>
              <td><code class="small">{{ a.target_relative }}</code></td>
              <td><span class="badge bg-secondary">{{ a.ssh_keys.length }}</span></td>
              <td class="text-end">
                <button class="btn btn-sm btn-outline-secondary me-1" @click="openAccPassword(a)" title="Cambiar contraseña">
                  <i class="bi bi-key"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="deleteAccount(a)" title="Eliminar">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'

const props = defineProps({
  userId: { type: Number, required: true },
})

const loading     = ref(true)
const busy        = ref(false)
const error       = ref(null)
const status      = ref({ enabled: false, ssh_keys: [] })
const newPassword = ref('')
const newKey      = ref('')

// Subcuentas
const accounts   = ref([])
const folders    = ref([])
const showCreate = ref(false)
const newAcc     = ref({ label: '', target_subpath: '', password: '' })

function formatDate(s) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    status.value = await api.getSftpStatus(props.userId)
    await loadAccounts()
  } catch (e) {
    error.value = 'No se pudo cargar el estado SFTP: ' + e.message
  } finally {
    loading.value = false
  }
}

async function loadAccounts() {
  try {
    accounts.value = await api.getSftpAccounts(props.userId)
    const f = await api.getSftpFolders(props.userId)
    folders.value = f.folders || []
  } catch (e) { /* sin permisos o sin carpetas */ }
}

async function createAccount() {
  busy.value = true
  try {
    const payload = { label: newAcc.value.label, target_subpath: newAcc.value.target_subpath }
    if (newAcc.value.password) payload.password = newAcc.value.password
    await api.createSftpAccount(props.userId, payload)
    newAcc.value = { label: '', target_subpath: '', password: '' }
    showCreate.value = false
    await loadAccounts()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

async function deleteAccount(a) {
  if (!confirm(`¿Eliminar la cuenta ${a.username}? Se desmonta la jaula y se borra el usuario.`)) return
  busy.value = true
  try {
    await api.deleteSftpAccount(props.userId, a.id)
    await loadAccounts()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

async function openAccPassword(a) {
  const pwd = prompt(`Nueva contraseña para ${a.username} (mín. 8 caracteres):`)
  if (!pwd) return
  if (pwd.length < 8) { alert('Mínimo 8 caracteres'); return }
  busy.value = true
  try {
    await api.setSftpAccountPassword(props.userId, a.id, pwd)
    alert('Contraseña actualizada')
    await loadAccounts()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

async function toggleEnabled() {
  busy.value = true
  try {
    await api.setSftpEnabled(props.userId, status.value.enabled)
    await load()
  } catch (e) {
    alert('Error: ' + e.message)
    await load()
  } finally {
    busy.value = false
  }
}

async function changePassword() {
  if (newPassword.value.length < 8) return
  busy.value = true
  try {
    await api.setSftpPassword(props.userId, newPassword.value)
    newPassword.value = ''
    await load()
    alert('Contraseña actualizada')
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

async function addKey() {
  busy.value = true
  try {
    await api.addSftpKey(props.userId, newKey.value.trim())
    newKey.value = ''
    await load()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

async function removeKey(fp) {
  if (!confirm(`¿Eliminar la clave ${fp}?`)) return
  busy.value = true
  try {
    await api.removeSftpKey(props.userId, fp)
    await load()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>
