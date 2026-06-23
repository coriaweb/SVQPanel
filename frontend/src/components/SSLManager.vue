<template>
  <div>
    <!-- Dominio canónico (www / sin www / ninguno) — aplica con o sin SSL -->
    <div class="ssl-options canonical-box">
      <div class="canonical-head">
        <span class="ssl-opt-title">Dominio canónico</span>
        <span class="ssl-opt-desc">Redirige (301) a la variante elegida. Por defecto: forzar www.</span>
      </div>
      <div class="canonical-choices">
        <button v-for="opt in canonicalOptions" :key="opt.value"
          class="canonical-btn" :class="{ on: canonical === opt.value }"
          :disabled="savingCanonical"
          @click="setCanonical(opt.value)">
          <i v-if="canonical === opt.value" class="bi bi-check-lg"></i>
          {{ opt.label }}
        </button>
      </div>
    </div>

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
        <div class="ssl-opt-row" :class="{ active: forceHttps }">
          <div class="ssl-opt-info">
            <span class="ssl-opt-title">Forzar HTTPS</span>
            <span class="ssl-opt-desc">Redirige HTTP → HTTPS automáticamente (301)</span>
          </div>
          <button class="ssl-pill-btn" :class="forceHttps ? 'on' : 'off'" @click="forceHttps = !forceHttps; saveToggle()" :disabled="toggling">
            <span class="pill-dot"></span>
            <span>{{ forceHttps ? 'Activo' : 'Inactivo' }}</span>
          </button>
        </div>
        <div class="ssl-opt-row" :class="{ active: hsts, disabled: !forceHttps }">
          <div class="ssl-opt-info">
            <span class="ssl-opt-title">HSTS <span v-if="!forceHttps" class="ssl-req">(requiere Forzar HTTPS)</span></span>
            <span class="ssl-opt-desc">Obliga HTTPS en el navegador hasta 1 año. Irreversible a corto plazo.</span>
          </div>
          <button class="ssl-pill-btn" :class="hsts ? 'on' : 'off'" @click="if(forceHttps){ hsts = !hsts; saveToggle() }" :disabled="toggling || !forceHttps">
            <span class="pill-dot"></span>
            <span>{{ hsts ? 'Activo' : 'Inactivo' }}</span>
          </button>
        </div>
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

        <div class="ssl-field">
          <label>Email para Let's Encrypt <span class="ssl-required">*</span></label>
          <input v-model="email" type="email" class="form-control form-control-sm"
            placeholder="admin@tudominio.com" autocomplete="email" />
          <span class="ssl-hint">Let's Encrypt lo necesita para notificarte de renovaciones. Debe ser un email real.</span>
        </div>

        <div class="alert alert-info py-2 small">
          <i class="bi bi-info-circle me-1"></i>
          El dominio debe apuntar a este servidor y ser accesible por el puerto 80. Tarda ~30 segundos.
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-success btn-sm" @click="createSSL" :disabled="loading || !email">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-shield-check me-1"></i>Emitir certificado
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
    const email = ref('')

    // Dominio canónico (www / non-www / none)
    const canonical = ref(props.domain.canonical_domain || 'www')
    const savingCanonical = ref(false)
    const canonicalOptions = [
      { value: 'www',     label: 'Forzar www' },
      { value: 'non-www', label: 'Forzar sin www' },
      { value: 'none',    label: 'Sin redirección' },
    ]

    const setCanonical = async (value) => {
      if (value === canonical.value || savingCanonical.value) return
      const prev = canonical.value
      canonical.value = value
      savingCanonical.value = true
      try {
        await api.put(`/api/domains/${props.domain.id}/canonical`, { canonical_domain: value })
        emit('reload')
        store.showNotification('Dominio canónico actualizado', 'success')
      } catch (e) {
        canonical.value = prev
        store.showNotification('Error al cambiar el dominio canónico: ' + (e.message || ''), 'danger')
      } finally {
        savingCanonical.value = false
      }
    }

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
        await api.put(`/api/domains/${props.domain.id}/ssl/toggle`, {
          enabled: true,
          force_https: forceHttps.value,
          hsts_enabled: hsts.value,
        })
        await loadSSL()
        emit('reload')
        store.showNotification('Opciones SSL guardadas', 'success')
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
        await api.toggleDomainSSL(props.domain.id, {
          enabled: true,
          force_https: forceHttps.value,
          hsts_enabled: hsts.value,
          email: email.value,
        })
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
        await api.post(`/api/domains/${props.domain.id}/ssl/renew`, {})
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
      forceHttps, hsts, email,
      canonical, savingCanonical, canonicalOptions, setCanonical,
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

.canonical-box {
  margin-bottom: 1rem; padding: .75rem .85rem;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.canonical-head { display: flex; flex-direction: column; gap: .15rem; margin-bottom: .6rem; }
.canonical-choices { display: flex; gap: .4rem; flex-wrap: wrap; }
.canonical-btn {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .35rem .8rem; border-radius: 999px;
  font-size: .78rem; font-weight: 500;
  border: 1.5px solid var(--border); background: var(--surface-3);
  color: var(--text-muted); cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
}
.canonical-btn.on {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: var(--accent); color: var(--accent);
}
.canonical-btn:disabled { opacity: .5; cursor: not-allowed; }

.ssl-opt-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding: .65rem .85rem;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid transparent;
  transition: background .15s, border-color .15s;
}
.ssl-opt-row.active {
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-2));
  border-color: color-mix(in srgb, var(--accent) 20%, transparent);
}
.ssl-opt-row.disabled { opacity: .5; }
.ssl-opt-info { display: flex; flex-direction: column; gap: .15rem; }
.ssl-opt-title { font-size: .875rem; font-weight: 500; }
.ssl-opt-desc { font-size: .77rem; color: var(--text-muted); }
.ssl-req { font-size: .75rem; font-weight: 400; color: var(--text-muted); }

.ssl-pill-btn {
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .3rem .75rem; border-radius: 999px;
  font-size: .78rem; font-weight: 500;
  border: 1.5px solid; cursor: pointer; white-space: nowrap;
  transition: background .15s, color .15s, border-color .15s;
  flex-shrink: 0;
}
.ssl-pill-btn.on {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: var(--accent); color: var(--accent);
}
.ssl-pill-btn.off {
  background: var(--surface-3); border-color: var(--border); color: var(--text-muted);
}
.ssl-pill-btn:disabled { opacity: .5; cursor: not-allowed; }
.pill-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: currentColor;
}

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

.ssl-field { display: flex; flex-direction: column; gap: .3rem; }
.ssl-field label { font-size: .82rem; font-weight: 600; color: var(--text-secondary); }
.ssl-required { color: var(--danger); }
.ssl-hint { font-size: .75rem; color: var(--text-muted); }
</style>
