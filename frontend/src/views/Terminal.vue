<template>
  <div class="sv-view">
    <div class="page-head">
      <div>
        <h1 class="page-title">Terminal web</h1>
        <p class="page-sub">Consola en el navegador. La sesión se abre con un token de un solo uso que caduca en segundos.</p>
      </div>
      <div v-if="isAdmin && status" style="display:flex;gap:8px;align-items:center">
        <span class="sv-badge" :class="status.active ? 'sv-badge--on' : 'sv-badge--off'">
          <i class="bi" :class="status.active ? 'bi-check-circle' : 'bi-x-circle'"></i>
          ttyd {{ status.active ? 'activo' : (status.installed ? 'parado' : 'no instalado') }}
        </span>
        <button v-if="!status.active" class="btn btn-sm btn-primary" :disabled="installing" @click="install">
          <span v-if="installing" class="spinner-border spinner-border-sm me-1"></span>
          <i v-else class="bi bi-download"></i> Instalar / activar
        </button>
      </div>
    </div>

    <!-- No disponible -->
    <BaseCard v-if="status && !status.active && !sessionOpen">
      <div style="text-align:center;padding:2rem 1rem">
        <i class="bi bi-terminal" style="font-size:2.5rem;color:var(--text-muted)"></i>
        <h5 style="margin-top:1rem">El terminal web no está activo</h5>
        <p style="color:var(--text-muted);max-width:480px;margin:.5rem auto">
          <template v-if="isAdmin">Pulsa "Instalar / activar" para descargar ttyd y arrancar el servicio.</template>
          <template v-else>Pide a un administrador que active el terminal web del servidor.</template>
        </p>
      </div>
    </BaseCard>

    <!-- Lanzador -->
    <BaseCard v-else-if="!sessionOpen">
      <div style="padding:1rem">
        <h5 style="margin-bottom:1rem"><i class="bi bi-terminal"></i> Abrir sesión</h5>

        <div v-if="isAdmin" class="sv-field" style="max-width:420px;margin-bottom:1rem">
          <label style="font-weight:600;font-size:.85rem">Sesión como</label>
          <select v-model="target" class="form-select form-select-sm">
            <option value="root">root (administración del servidor)</option>
            <option v-for="u in users" :key="u.id" :value="u.username">
              {{ u.username }} (jailed, su entorno)
            </option>
          </select>
        </div>
        <p v-else style="color:var(--text-muted);font-size:.9rem;margin-bottom:1rem">
          Se abrirá una sesión limitada a tu propia cuenta.
        </p>

        <button class="btn btn-primary" :disabled="opening" @click="openSession">
          <span v-if="opening" class="spinner-border spinner-border-sm me-1"></span>
          <i v-else class="bi bi-play-fill"></i> Abrir terminal
        </button>
        <p v-if="error" class="text-danger" style="margin-top:.75rem;font-size:.85rem">{{ error }}</p>
      </div>
    </BaseCard>

    <!-- Terminal abierto -->
    <BaseCard v-else style="padding:0;overflow:hidden">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:.5rem .9rem;border-bottom:1px solid var(--border)">
        <span style="font-weight:600;font-size:.85rem">
          <i class="bi bi-terminal"></i> Sesión: <code>{{ sessionTarget }}</code>
        </span>
        <button class="btn btn-sm btn-outline-secondary" @click="closeSession">
          <i class="bi bi-x-lg"></i> Cerrar
        </button>
      </div>
      <iframe v-if="iframeUrl" :src="iframeUrl" class="sv-terminal-frame"></iframe>
    </BaseCard>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { useMainStore } from '../stores/useMainStore.js'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'

export default {
  name: 'Terminal',
  components: { BaseCard },
  setup() {
    const store = useMainStore()
    const isAdmin = computed(() => store.currentUser && (store.currentUser.is_admin || store.currentUser.role === 'admin'))

    const status = ref(null)
    const users = ref([])
    const target = ref('root')
    const installing = ref(false)
    const opening = ref(false)
    const error = ref('')

    const sessionOpen = ref(false)
    const sessionTarget = ref('')
    const iframeUrl = ref('')

    const loadStatus = async () => {
      if (!isAdmin.value) { status.value = { active: true, installed: true }; return }
      try { status.value = await api.getTerminalStatus() }
      catch (e) { status.value = { active: false, installed: false } }
    }

    const loadUsers = async () => {
      if (!isAdmin.value) return
      try { users.value = await api.getUsers() } catch (e) { users.value = [] }
    }

    const install = async () => {
      installing.value = true
      error.value = ''
      try {
        status.value = await api.installTerminal()
        store.showNotification('Terminal web activado', 'success')
      } catch (e) {
        error.value = e.message || String(e)
        store.showNotification('Error: ' + error.value, 'danger')
      } finally {
        installing.value = false
      }
    }

    const openSession = async () => {
      opening.value = true
      error.value = ''
      try {
        const res = await api.openTerminalSession(isAdmin.value ? target.value : null)
        sessionTarget.value = res.target
        // ttyd con -a permite pasar el token como argumento al launcher vía ?arg=
        iframeUrl.value = `${res.url}?arg=${encodeURIComponent(res.token)}`
        sessionOpen.value = true
      } catch (e) {
        error.value = e.message || String(e)
      } finally {
        opening.value = false
      }
    }

    const closeSession = () => {
      sessionOpen.value = false
      iframeUrl.value = ''
      sessionTarget.value = ''
    }

    onMounted(async () => {
      await loadStatus()
      await loadUsers()
    })

    return {
      isAdmin, status, users, target, installing, opening, error,
      sessionOpen, sessionTarget, iframeUrl,
      install, openSession, closeSession,
    }
  },
}
</script>

<style scoped>
.sv-terminal-frame {
  width: 100%;
  height: 70vh;
  border: 0;
  display: block;
  background: #000;
}
</style>
