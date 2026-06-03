<template>
  <div>
    <!-- Cert activo -->
    <div v-if="ssl && ssl.ssl_enabled" class="ssl-active">
      <div class="ssl-badge">
        <i class="bi bi-shield-check-fill"></i>
        <div>
          <strong>Certificado Activo</strong>
          <span class="ssl-expiry">Válido hasta {{ formatDate(ssl.ssl_expires || ssl.cert_info?.not_after) }}</span>
        </div>
      </div>

      <div class="ssl-meta">
        <div class="ssl-meta-row"><span>Emisor</span><span>{{ ssl.cert_info?.issuer || "Let's Encrypt" }}</span></div>
        <div class="ssl-meta-row"><span>Dominio</span><span class="mono">{{ domain.domain_name }}</span></div>
        <div v-if="ssl.cert_info?.sans?.length" class="ssl-meta-row"><span>SANs</span><span class="mono">{{ ssl.cert_info.sans.join(', ') }}</span></div>
        <div class="ssl-meta-row"><span>Auto-renovación</span><span>Habilitada (certbot.timer)</span></div>
      </div>

      <!-- Opciones SSL -->
      <div class="ssl-options">
        <label class="ssl-toggle-row">
          <div>
            <span class="ssl-opt-title">Forzar HTTPS</span>
            <span class="ssl-opt-desc">Redirige todo el tráfico HTTP → HTTPS (301)</span>
          </div>
          <input type="checkbox" class="svq-check" v-model="forceHttps" @change="saveToggle" :disabled="toggling" />
        </label>
        <label class="ssl-toggle-row">
          <div>
            <span class="ssl-opt-title">HSTS</span>
            <span class="ssl-opt-desc">Strict-Transport-Security: max-age=1 año. Solo activar si el dominio siempre usará HTTPS.</span>
          </div>
          <input type="checkbox" class="svq-check" v-model="hsts" @change="saveToggle" :disabled="toggling || !forceHttps" />
        </label>
      </div>

      <!-- Acciones -->
      <div class="ssl-actions">
        <button class="btn btn-sm btn-outline-primary" @click="renewSSL" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
          <i v-else class="bi bi-arrow-repeat me-1"></i>Renovar
        </button>
        <button class="btn btn-sm btn-outline-danger" @click="showRevokeConfirm = true" :disabled="loading">
          <i class="bi bi-x-circle me-1"></i>Revocar
        </button>
      </div>

      <div v-if="showRevokeConfirm" class="revoke-confirm">
        <p><i class="bi bi-exclamation-triangle-fill"></i> ¿Revocar el certificado SSL? El dominio quedará en HTTP.</p>
        <div class="d-flex gap-2">
          <button class="btn btn-danger btn-sm" @click="revokeSSL" :disabled="loading">Confirmar</button>
          <button class="btn btn-secondary btn-sm" @click="showRevokeConfirm = false">Cancelar</button>
        </div>
      </div>
    </div>

    <!-- Sin cert -->
    <div v-else>
      <div v-if="!showForm" class="ssl-empty">
        <i class="bi bi-shield-x ssl-empty-icon"></i>
        <p>Este dominio no tiene certificado SSL.</p>
        <p class="ssl-empty-hint">Se emitirá un certificado Let's Encrypt gratuito. El dominio debe apuntar a este servidor.</p>
        <button class="btn btn-success btn-sm" @click="showForm = true">
          <i class="bi bi-plus-circle me-1"></i>Emitir certificado SSL
        </button>
      </div>

      <div v-else class="ssl-form">
        <p>Se emitirá un certificado <strong>Let's Encrypt</strong> para:</p>
        <div class="mono mb-3">{{ domain.domain_name }}</div>
        <div class="alert alert-info py-2 small">
          <i class="bi bi-info-circle me-1"></i>
          El dominio debe ser accesible desde Internet en el puerto 80. El proceso tarda ~30 segundos.
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-success btn-sm" @click="createSSL" :disabled="loading">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-shield-check me-1"></i>Emitir
          </button>
          <button class="btn btn-secondary btn-sm" @click="showForm = false" :disabled="loading">Cancelar</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'SSLManager',
  props: {
    domain: { type: Object, required: true }
  },
  emits: ['reload'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading  = ref(false)
    const toggling = ref(false)
    const showForm = ref(false)
    const showRevokeConfirm = ref(false)
    const ssl = ref(null)
    const forceHttps = ref(false)
    const hsts = ref(false)

    const loadSSL = async () => {
      try {
        const data = await api.getSSL(props.domain.id)
        ssl.value = (data?.ssl_enabled || data?.cert_info) ? data : null
        forceHttps.value = data?.force_https || false
        hsts.value = data?.hsts_enabled || false
      } catch {
        ssl.value = null
      }
    }

    const saveToggle = async () => {
      toggling.value = true
      try {
        await api.post(`/api/domains/${props.domain.id}/ssl/toggle`, {
          enabled: true,
          force_https: forceHttps.value,
          hsts_enabled: hsts.value,
        })
        await loadSSL()
        emit('reload')
      } catch (e) {
        store.showNotification('Error al guardar opciones SSL: ' + e.message, 'danger')
        await loadSSL()
      } finally {
        toggling.value = false
      }
    }

    const createSSL = async () => {
      loading.value = true
      try {
        await api.createSSL(props.domain.id, { domain_name: props.domain.domain_name, auto_renewal: true })
        store.showNotification('Certificado SSL emitido correctamente', 'success')
        showForm.value = false
        await loadSSL()
        emit('reload')
      } catch (e) {
        store.showNotification('Error al crear certificado: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const renewSSL = async () => {
      loading.value = true
      try {
        await api.createSSL(props.domain.id, { domain_name: props.domain.domain_name, auto_renewal: true })
        store.showNotification('Certificado renovado correctamente', 'success')
        await loadSSL()
      } catch (e) {
        store.showNotification('Error al renovar: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const revokeSSL = async () => {
      loading.value = true
      try {
        await api.deleteSSL(props.domain.id)
        store.showNotification('Certificado revocado', 'warning')
        ssl.value = null
        showRevokeConfirm.value = false
        emit('reload')
      } catch (e) {
        store.showNotification('Error al revocar: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const formatDate = (date) => {
      if (!date) return 'N/A'
      return new Date(date).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    }

    onMounted(loadSSL)

    return {
      ssl, loading, toggling, showForm, showRevokeConfirm,
      forceHttps, hsts,
      createSSL, renewSSL, revokeSSL, saveToggle, formatDate,
    }
  }
}
</script>

<style scoped>
.ssl-active { display: flex; flex-direction: column; gap: 1rem; }

.ssl-badge {
  display: flex; align-items: center; gap: .75rem;
  padding: .75rem 1rem;
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
  border-radius: var(--radius-md);
  color: var(--success);
}
.ssl-badge i { font-size: 1.5rem; }
.ssl-badge strong { display: block; font-size: .95rem; }
.ssl-expiry { font-size: .8rem; opacity: .8; }

.ssl-meta { display: flex; flex-direction: column; gap: .25rem; }
.ssl-meta-row { display: flex; gap: 1rem; font-size: .85rem; }
.ssl-meta-row span:first-child { min-width: 120px; color: var(--text-muted); }

.ssl-options { display: flex; flex-direction: column; gap: .5rem; }
.ssl-toggle-row {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 1rem; cursor: pointer;
  padding: .6rem .75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
.ssl-toggle-row:hover { background: var(--surface-3); }
.ssl-opt-title { display: block; font-size: .875rem; font-weight: 500; }
.ssl-opt-desc { display: block; font-size: .78rem; color: var(--text-muted); margin-top: .1rem; }

.ssl-actions { display: flex; gap: .5rem; }

.revoke-confirm {
  padding: .75rem;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
  font-size: .875rem;
}
.revoke-confirm p { margin-bottom: .5rem; }
.revoke-confirm i { color: var(--danger); }

.ssl-empty {
  display: flex; flex-direction: column; align-items: center;
  gap: .5rem; text-align: center; padding: 1.5rem 1rem;
}
.ssl-empty-icon { font-size: 2.5rem; color: var(--text-muted); }
.ssl-empty-hint { font-size: .82rem; color: var(--text-muted); max-width: 340px; }

.ssl-form { display: flex; flex-direction: column; gap: .75rem; }
</style>
