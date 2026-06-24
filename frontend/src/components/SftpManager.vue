<template>
  <div class="sftp">
    <div v-if="loading" class="sftp__loading">
      <span class="sftp__spinner"></span>
    </div>
    <div v-else-if="error" class="sftp__alert sftp__alert--warn">
      {{ error }}
    </div>
    <div v-else>
      <!-- Toggle SFTP enabled -->
      <div class="sftp__toggle-row">
        <div>
          <button type="button" class="sftp__switch" :class="{ on: status.enabled }"
                  :disabled="busy" @click="status.enabled = !status.enabled; toggleEnabled()">
            <span class="sftp__switch-knob"></span>
          </button>
          <strong class="sftp__switch-label">{{ status.enabled ? 'SFTP activo' : 'SFTP desactivado' }}</strong>
          <div class="sftp__muted">
            <span v-if="status.enabled">
              chroot a <code>{{ status.chroot_to }}</code> — sólo SFTP, sin shell.
            </span>
            <span v-else>El usuario no puede conectar por SFTP.</span>
          </div>
        </div>
      </div>

      <template v-if="status.enabled">
        <!-- Password -->
        <div class="sftp__box sftp__box--inset">
          <div class="sftp__box-head">
            <span class="sftp__box-title"><i class="bi bi-key"></i> Contraseña SFTP (cuenta Linux)</span>
            <span v-if="status.password_set_at" class="sftp__muted">cambiada {{ formatDate(status.password_set_at) }}</span>
            <span v-else class="sftp__danger"><i class="bi bi-exclamation-triangle"></i> nunca asignada</span>
          </div>
          <form @submit.prevent="changePassword" class="sftp__pwd-form">
            <PasswordField v-model="newPassword" placeholder="Nueva contraseña SFTP" />
            <button type="submit" class="sftp__btn sftp__btn--primary" :disabled="busy">
              <span v-if="busy" class="sftp__spinner sftp__spinner--sm"></span>Guardar contraseña
            </button>
          </form>
        </div>

        <!-- SSH Keys -->
        <div class="sftp__box">
          <div class="sftp__box-head">
            <span class="sftp__box-title">
              <i class="bi bi-shield-lock"></i> Claves SSH públicas
              <span class="sftp__chip">{{ status.ssh_keys.length }}</span>
            </span>
            <span class="sftp__muted">authorized_keys</span>
          </div>

          <div v-if="!status.ssh_keys.length" class="sftp__muted sftp__mb">
            Sin claves añadidas. Sube tu clave pública (más seguro que contraseña).
          </div>
          <ul v-else class="sftp__keys">
            <li v-for="k in status.ssh_keys" :key="k.fingerprint" class="sftp__key">
              <div>
                <span class="sftp__chip sftp__chip--blue">{{ k.type }}</span>
                <span v-if="k.comment" class="sftp__muted">{{ k.comment }}</span>
                <div class="sftp__fp">{{ k.fingerprint }}</div>
              </div>
              <button class="sftp__btn sftp__btn--icon-danger" @click="removeKey(k.fingerprint)" :disabled="busy">
                <i class="bi bi-trash"></i>
              </button>
            </li>
          </ul>

          <form @submit.prevent="addKey">
            <textarea class="sftp__input sftp__input--mono" rows="2" v-model="newKey"
                      placeholder="ssh-ed25519 AAAAC3NzaC1lZ... usuario@maquina"></textarea>
            <div class="sftp__form-foot">
              <span class="sftp__muted">Formato OpenSSH: tipo base64 comentario</span>
              <button type="submit" class="sftp__btn sftp__btn--success" :disabled="busy || !newKey.trim()">
                <i class="bi bi-plus-lg"></i> Añadir clave
              </button>
            </div>
          </form>
        </div>

        <div class="sftp__alert sftp__alert--info">
          <strong>Cómo conectar:</strong>
          <code>sftp {{ status.username }}@TU_SERVIDOR</code>
          — el cliente verá <code>web/</code>, <code>files/</code>, y <code>.ssh/</code>.
        </div>
      </template>

      <!-- ═══ Cuentas SFTP adicionales ═══ -->
      <div class="sftp__box">
        <div class="sftp__box-head">
          <span class="sftp__box-title">
            <i class="bi bi-people"></i> Cuentas SFTP adicionales
            <span class="sftp__chip">{{ accounts.length }}</span>
          </span>
          <button class="sftp__btn sftp__btn--success" @click="showCreate = !showCreate" :disabled="busy">
            <i class="bi bi-plus-lg"></i> Nueva cuenta
          </button>
        </div>
        <p class="sftp__muted sftp__mb">
          Cada cuenta queda <strong>enjaulada exclusivamente</strong> a la carpeta que elijas
          dentro del espacio del cliente (no ve nada más).
        </p>

        <!-- Form crear -->
        <div v-if="showCreate" class="sftp__box sftp__box--inset sftp__mb">
          <div class="sftp__grid">
            <div class="sftp__field">
              <label>Nombre (etiqueta)</label>
              <input class="sftp__input" v-model="newAcc.label" placeholder="dev1" pattern="[a-z][a-z0-9_]+">
              <span class="sftp__muted">usuario: {{ status.username }}_{{ newAcc.label || 'xxx' }}</span>
            </div>
            <div class="sftp__field">
              <label>Carpeta destino</label>
              <select class="sftp__input" v-model="newAcc.target_subpath">
                <option value="" disabled>— elige carpeta —</option>
                <option v-for="f in folders" :key="f" :value="f">{{ f }}</option>
              </select>
            </div>
            <div class="sftp__field">
              <label>Contraseña</label>
              <input type="password" class="sftp__input" v-model="newAcc.password" placeholder="(opcional)" minlength="8">
            </div>
          </div>
          <div class="sftp__form-foot sftp__form-foot--end">
            <button class="sftp__btn sftp__btn--ghost" @click="showCreate=false" :disabled="busy">Cancelar</button>
            <button class="sftp__btn sftp__btn--primary" @click="createAccount"
                    :disabled="busy || !newAcc.label || !newAcc.target_subpath">
              <span v-if="busy" class="sftp__spinner sftp__spinner--sm"></span>Crear cuenta
            </button>
          </div>
        </div>

        <!-- Lista -->
        <div v-if="!accounts.length" class="sftp__muted">Sin cuentas adicionales.</div>
        <div v-else class="sftp__table-wrap">
          <table class="sftp__table">
            <thead>
              <tr><th>Usuario</th><th>Carpeta (jaula)</th><th>Claves</th><th class="sftp__ta-end">Acciones</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in accounts" :key="a.id">
                <td class="sftp__mono">{{ a.username }}</td>
                <td><code>{{ a.target_relative }}</code></td>
                <td><span class="sftp__chip">{{ a.ssh_keys.length }}</span></td>
                <td class="sftp__ta-end">
                  <button class="sftp__btn sftp__btn--icon" @click="openAccPassword(a)" title="Cambiar contraseña">
                    <i class="bi bi-key"></i>
                  </button>
                  <button class="sftp__btn sftp__btn--icon-danger" @click="deleteAccount(a)" title="Eliminar">
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import PasswordField from './PasswordField.vue'

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

<style scoped>
.sftp { display: flex; flex-direction: column; gap: 1rem; }

/* Estados */
.sftp__loading { text-align: center; padding: 1.5rem; }
.sftp__spinner {
  display: inline-block; width: 1.1rem; height: 1.1rem;
  border: 2px solid var(--border); border-top-color: var(--ac);
  border-radius: 50%; animation: sftp-spin .6s linear infinite; vertical-align: -2px;
}
.sftp__spinner--sm { width: .85rem; height: .85rem; margin-right: .4rem; }
@keyframes sftp-spin { to { transform: rotate(360deg); } }

.sftp__muted { font-size: .8rem; color: var(--text-muted); }
.sftp__danger { font-size: .8rem; color: var(--danger); }
.sftp__mb { margin-bottom: .6rem; }
.sftp code {
  font-family: var(--font-mono, monospace);
  background: var(--surface-inset); padding: .05rem .35rem; border-radius: 4px; font-size: .85em;
}

/* Toggle / switch */
.sftp__toggle-row { display: flex; justify-content: space-between; align-items: flex-start; }
.sftp__switch {
  position: relative; width: 42px; height: 24px; border-radius: 999px;
  border: none; background: var(--surface-inset); cursor: pointer; vertical-align: middle;
  transition: background .15s; padding: 0;
}
.sftp__switch.on { background: var(--ac); }
.sftp__switch:disabled { opacity: .6; cursor: not-allowed; }
.sftp__switch-knob {
  position: absolute; top: 3px; left: 3px; width: 18px; height: 18px;
  background: #fff; border-radius: 50%; transition: transform .15s;
}
.sftp__switch.on .sftp__switch-knob { transform: translateX(18px); }
.sftp__switch-label { margin-left: .6rem; font-size: .9rem; }

/* Cajas */
.sftp__box {
  border: 1px solid var(--border); border-radius: var(--r-md);
  padding: 1rem; background: var(--surface);
}
.sftp__box--inset { background: var(--surface-2); }
.sftp__box-head {
  display: flex; justify-content: space-between; align-items: center;
  gap: 1rem; margin-bottom: .75rem; flex-wrap: wrap;
}
.sftp__box-title { font-size: .85rem; font-weight: 600; display: inline-flex; align-items: center; gap: .4rem; }

/* Chips / badges */
.sftp__chip {
  display: inline-block; min-width: 1.4em; text-align: center;
  padding: .1rem .45rem; border-radius: 999px; font-size: .72rem; font-weight: 600;
  background: var(--surface-inset); color: var(--text-secondary);
}
.sftp__chip--blue { background: color-mix(in srgb, var(--info) 15%, transparent); color: var(--info); }

/* Inputs / forms */
.sftp__input {
  width: 100%; padding: .4rem .6rem; font-size: .85rem;
  border: 1px solid var(--border); border-radius: var(--r-sm);
  background: var(--surface); color: var(--text);
}
.sftp__input:focus { outline: none; border-color: var(--ac); }
.sftp__input--mono { font-family: var(--font-mono, monospace); font-size: 11px; }
.sftp__inline-form { display: flex; gap: .5rem; align-items: center; }
.sftp__inline-form .sftp__input { flex: 1; }
.sftp__pwd-form { display: flex; flex-direction: column; gap: .6rem; align-items: flex-start; }
.sftp__pwd-form > :first-child { width: 100%; }
.sftp__form-foot { display: flex; justify-content: space-between; align-items: center; gap: .5rem; margin-top: .6rem; }
.sftp__form-foot--end { justify-content: flex-end; }
.sftp__grid { display: grid; grid-template-columns: 1.2fr 1.4fr 1fr; gap: .75rem; }
@media (max-width: 640px) { .sftp__grid { grid-template-columns: 1fr; } }
.sftp__field { display: flex; flex-direction: column; gap: .25rem; }
.sftp__field label { font-size: .78rem; font-weight: 600; color: var(--text-secondary); }

/* Botones */
.sftp__btn {
  display: inline-flex; align-items: center; gap: .35rem; justify-content: center;
  padding: .4rem .8rem; font-size: .82rem; font-weight: 500;
  border-radius: var(--r-sm); border: 1px solid var(--border);
  background: var(--surface-2); color: var(--text); cursor: pointer; white-space: nowrap;
  transition: background .15s, border-color .15s, color .15s;
}
.sftp__btn:disabled { opacity: .55; cursor: not-allowed; }
.sftp__btn--primary { background: var(--ac); border-color: var(--ac); color: #fff; }
.sftp__btn--success { background: var(--success); border-color: var(--success); color: #fff; }
.sftp__btn--ghost { background: transparent; }
.sftp__btn--icon, .sftp__btn--icon-danger { padding: .35rem .5rem; }
.sftp__btn--icon-danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }
.sftp__btn--icon-danger:hover:not(:disabled) { background: color-mix(in srgb, var(--danger) 10%, transparent); }

/* Claves */
.sftp__keys { list-style: none; padding: 0; margin: 0 0 .6rem; }
.sftp__key {
  display: flex; justify-content: space-between; align-items: center;
  gap: 1rem; padding: .4rem 0; border-bottom: 1px solid var(--border); font-size: .82rem;
}
.sftp__fp { font-family: var(--font-mono, monospace); color: var(--text-muted); font-size: 11px; margin-top: .15rem; }

/* Alertas */
.sftp__alert { padding: .65rem .85rem; border-radius: var(--r-sm); font-size: .82rem; }
.sftp__alert--info { background: color-mix(in srgb, var(--info) 8%, transparent); border: 1px solid color-mix(in srgb, var(--info) 25%, transparent); }
.sftp__alert--warn { background: color-mix(in srgb, var(--warning) 10%, transparent); border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent); }

/* Tabla */
.sftp__table-wrap { overflow-x: auto; }
.sftp__table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.sftp__table th, .sftp__table td { padding: .5rem .6rem; text-align: left; border-bottom: 1px solid var(--border); }
.sftp__table th { font-size: .75rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .02em; }
.sftp__mono { font-family: var(--font-mono, monospace); font-size: .82rem; }
.sftp__ta-end { text-align: right; }
</style>
