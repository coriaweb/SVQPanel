<template>
  <div class="lic-page">
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Licencia</h1>
        <p class="page-head__subtitle">Estado de la licencia de tu panel SVQPanel</p>
      </div>
    </div>

    <div v-if="loading" class="lic-loading">
      <span class="spinner-border spinner-border-sm"></span> Comprobando licencia…
    </div>

    <template v-else>
      <!-- Estado actual -->
      <div class="lic-card" :class="status.valid ? 'lic-card--ok' : 'lic-card--bad'">
        <div class="lic-status">
          <i class="bi" :class="status.valid ? 'bi-patch-check-fill' : 'bi-exclamation-triangle-fill'"></i>
          <div>
            <div class="lic-status__title">
              {{ status.valid ? 'Licencia activa' : 'Sin licencia válida' }}
            </div>
            <div class="lic-status__sub">{{ reasonText }}</div>
          </div>
        </div>
        <div v-if="status.valid" class="lic-meta">
          <div><span>Plan</span><strong>{{ status.plan || '—' }}</strong></div>
          <div><span>Caduca</span><strong>{{ formatDate(status.expires) }}</strong></div>
        </div>
      </div>

      <!-- Activar / cambiar licencia -->
      <div class="lic-card">
        <h3 class="lic-card__title">{{ status.valid ? 'Cambiar licencia' : 'Activar licencia' }}</h3>
        <p class="lic-hint">
          Introduce la clave que obtuviste en tu área de cliente de
          <a href="https://www.svqhost.com" target="_blank" rel="noopener">SVQHost</a>.
          La licencia se vincula al primer servidor que la active.
        </p>
        <div class="lic-form">
          <input v-model="keyInput" type="text" class="lic-input"
                 placeholder="SVQ-XXXX-XXXX-XXXX" :disabled="activating" />
          <button class="lic-btn lic-btn--primary" @click="activate" :disabled="activating || !keyInput.trim()">
            <span v-if="activating" class="spinner-border spinner-border-sm"></span>
            <i v-else class="bi bi-check-lg"></i> Activar
          </button>
        </div>
        <div v-if="activateMsg" class="lic-msg" :class="activateOk ? 'lic-msg--ok' : 'lic-msg--bad'">
          {{ activateMsg }}
        </div>
      </div>

      <!-- Identificador del servidor -->
      <div class="lic-card lic-card--muted">
        <h3 class="lic-card__title">Identificador de este servidor</h3>
        <p class="lic-hint">Huella usada para vincular la licencia (no contiene datos personales).</p>
        <code class="lic-fingerprint">{{ status.fingerprint || '—' }}</code>
      </div>
    </template>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'

export default {
  name: 'License',
  setup() {
    const store = useMainStore()
    const loading = ref(true)
    const status = ref({ valid: false, reason: null, plan: null, expires: null, fingerprint: null })
    const keyInput = ref('')
    const activating = ref(false)
    const activateMsg = ref('')
    const activateOk = ref(false)

    const reasonMap = {
      ok: 'Tu licencia es válida y está activa.',
      no_key: 'Aún no has introducido ninguna clave de licencia.',
      offline: 'No se pudo contactar con el servidor de licencias.',
      expired: 'La licencia ha caducado. Renuévala en tu área de cliente.',
      suspended: 'La licencia está suspendida. Contacta con SVQHost.',
      not_found: 'La clave de licencia no existe.',
      fingerprint_mismatch: 'Esta licencia ya está activada en otro servidor.',
      bad_signature: 'La respuesta del servidor de licencias no es válida.',
      stale: 'La licencia necesita revalidarse.',
    }
    const reasonText = computed(() => reasonMap[status.value.reason] || 'Estado de licencia desconocido.')

    const load = async (refresh = false) => {
      loading.value = true
      try {
        status.value = await api.getLicenseStatus(refresh)
      } catch (e) {
        store.showNotification('Error consultando la licencia: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const activate = async () => {
      activating.value = true
      activateMsg.value = ''
      try {
        status.value = await api.activateLicense(keyInput.value.trim())
        activateOk.value = true
        activateMsg.value = '¡Licencia activada correctamente!'
        keyInput.value = ''
        store.showNotification('Licencia activada', 'success')
      } catch (e) {
        activateOk.value = false
        activateMsg.value = e.message || 'No se pudo activar la licencia.'
      } finally {
        activating.value = false
      }
    }

    const formatDate = (iso) => {
      if (!iso) return '—'
      try { return new Date(iso).toLocaleDateString() } catch { return iso }
    }

    onMounted(() => load(true))

    return { loading, status, keyInput, activating, activateMsg, activateOk,
             reasonText, activate, formatDate }
  },
}
</script>

<style scoped>
.lic-page { max-width: 720px; }
.lic-loading { display:flex; align-items:center; gap:.5rem; color:var(--text-muted); padding:2rem; }
.lic-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-lg,14px);
  padding:1.2rem 1.4rem; margin-bottom:1rem; }
.lic-card--ok  { border-color: rgba(34,197,94,.4); background: linear-gradient(90deg, rgba(34,197,94,.08), transparent); }
.lic-card--bad { border-color: rgba(232,89,12,.4); background: linear-gradient(90deg, rgba(232,89,12,.08), transparent); }
.lic-card--muted { opacity:.9; }
.lic-card__title { font-size:1rem; font-weight:600; margin:0 0 .4rem; }
.lic-status { display:flex; align-items:center; gap:.9rem; }
.lic-status .bi { font-size:1.8rem; }
.lic-card--ok .bi  { color:#22c55e; }
.lic-card--bad .bi { color:var(--svq-orange,#e8590c); }
.lic-status__title { font-weight:700; font-size:1.05rem; }
.lic-status__sub { color:var(--text-muted); font-size:.88rem; }
.lic-meta { display:flex; gap:2rem; margin-top:1rem; padding-top:1rem; border-top:1px solid var(--border); }
.lic-meta div { display:flex; flex-direction:column; }
.lic-meta span { font-size:.78rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px; }
.lic-meta strong { font-size:1rem; }
.lic-hint { color:var(--text-muted); font-size:.88rem; margin:.2rem 0 .8rem; }
.lic-form { display:flex; gap:.6rem; }
.lic-input { flex:1; padding:.55rem .8rem; border:1px solid var(--border); border-radius:var(--r-md,8px);
  background:var(--surface-inset,#f8fafc); color:var(--text); font-family:var(--font-mono,monospace); }
.lic-btn { display:inline-flex; align-items:center; gap:.4rem; padding:.55rem 1rem; border:none;
  border-radius:var(--r-md,8px); cursor:pointer; font-weight:600; }
.lic-btn--primary { background:var(--svq-orange,#e8590c); color:#fff; }
.lic-btn--primary:disabled { opacity:.5; cursor:not-allowed; }
.lic-msg { margin-top:.7rem; font-size:.88rem; padding:.5rem .7rem; border-radius:var(--r-md,8px); }
.lic-msg--ok  { background:rgba(34,197,94,.12); color:#16a34a; }
.lic-msg--bad { background:rgba(232,89,12,.12); color:var(--svq-orange,#e8590c); }
.lic-fingerprint { display:block; word-break:break-all; font-size:.8rem; color:var(--text-muted);
  background:var(--surface-inset,#f8fafc); padding:.5rem .7rem; border-radius:var(--r-md,8px); }
</style>
