<template>
  <div>
    <!-- Dominio canónico (www / sin www / ninguno) — aplica con o sin SSL.
         No tiene sentido en subdominios (nadie usa www.sub.dominio.com): oculto. -->
    <div v-if="!domain.is_subdomain" class="ssl-options canonical-box">
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
            <span v-if="loading" class="ssl-spin"></span>
            <i v-else class="bi bi-shield-check me-1"></i>
            {{ loading ? 'Emitiendo…' : 'Emitir certificado' }}
          </button>
          <button class="btn btn-secondary btn-sm" @click="showForm = false" :disabled="loading">Cancelar</button>
        </div>
        <!-- Progreso real de la emisión: fases del job + salida de certbot en vivo -->
        <div v-if="loading && !issueJob" class="ssl-progress">
          <span class="ssl-spin ssl-spin--lg"></span>
          <div>
            <strong>Iniciando la emisión…</strong>
          </div>
        </div>
        <div v-if="issueJob" class="ssl-progress ssl-progress--steps">
          <div class="ssl-steps">
            <div v-for="(s, i) in issueJob.steps" :key="i" class="ssl-step" :class="'is-' + stepState(i)">
              <i v-if="stepState(i) === 'done'" class="bi bi-check-circle-fill"></i>
              <i v-else-if="stepState(i) === 'failed'" class="bi bi-x-circle-fill"></i>
              <span v-else-if="stepState(i) === 'running'" class="ssl-spin"></span>
              <i v-else class="bi bi-circle"></i>
              <span>{{ s }}</span>
            </div>
          </div>
          <div v-if="issueJob.status === 'running' && issueJob.detail" class="ssl-step-live mono" :title="issueJob.detail">
            {{ issueJob.detail }}
          </div>
          <div v-if="issueJob.status === 'failed'" class="ssl-step-error">
            <strong><i class="bi bi-x-circle-fill me-1"></i>La emisión falló</strong>
            <pre class="ssl-error-text">{{ issueJob.error }}</pre>
          </div>
          <div v-if="issueJob.status === 'running'" class="ssl-hint">
            Suele tardar ~30 segundos. Puedes salir de esta página: la emisión continúa en el servidor.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import { formatDate as fmtDate } from '../utils/datetime'

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

    // ── Emisión con progreso real: el POST lanza un job en el servidor y aquí
    //    se hace polling cada 2s (fases + última línea de certbot). Si el
    //    usuario sale y vuelve, onMounted reanuda el polling del job en curso.
    const issueJob = ref(null)
    let pollAlive = false
    const sleep = (ms) => new Promise(r => setTimeout(r, ms))

    const stepState = (i) => {
      const j = issueJob.value
      if (!j) return 'pending'
      if (j.status === 'success' || i < j.current) return 'done'
      if (i === j.current) return j.status === 'failed' ? 'failed' : 'running'
      return 'pending'
    }

    const pollIssue = async () => {
      pollAlive = true
      while (pollAlive) {
        await sleep(2000)
        if (!pollAlive) return
        try {
          const r = await api.getDomainSslIssue(props.domain.id)
          if (r.job) issueJob.value = r.job
        } catch { /* fallo transitorio de red: seguir intentando */ }
        const st = issueJob.value?.status
        if (st === 'success') {
          loading.value = false
          showForm.value = false
          issueJob.value = null
          store.showNotification('Certificado SSL emitido correctamente', 'success')
          await loadSSL()
          emit('reload')
          return
        }
        if (st === 'failed') {
          loading.value = false   // el detalle del error queda visible en el checklist
          return
        }
      }
    }

    const createSSL = async () => {
      loading.value = true
      issueJob.value = null
      try {
        const r = await api.startDomainSslIssue(props.domain.id, {
          enabled: true,
          force_https: true,
          hsts_enabled: hsts.value,
          email: email.value,
        })
        issueJob.value = r.job
        await pollIssue()
      } catch (e) {
        loading.value = false
        store.showNotification('Error al iniciar la emisión: ' + e.message, 'danger')
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

    const formatDate = (date) => date ? fmtDate(date) : 'N/A'

    onMounted(async () => {
      await loadSSL()
      // Si hay una emisión en curso (p. ej. el usuario recargó la página a
      // mitad), retomar el checklist y el polling donde estaba.
      try {
        const r = await api.getDomainSslIssue(props.domain.id)
        if (r.job?.status === 'running') {
          showForm.value = true
          loading.value = true
          issueJob.value = r.job
          pollIssue()
        }
      } catch { /* sin job previo */ }
    })
    onUnmounted(() => { pollAlive = false })

    return {
      ssl, loading, toggling, showForm, showRevokeConfirm,
      forceHttps, hsts, email, issueJob, stepState,
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

/* Spinner propio (no depende del bootstrap-compat) para que SIEMPRE se vea. */
.ssl-spin {
  display: inline-block; width: .9rem; height: .9rem; vertical-align: -2px;
  margin-right: .4rem; border: 2px solid currentColor; border-right-color: transparent;
  border-radius: 50%; animation: ssl-spin-kf .7s linear infinite;
}
.ssl-spin--lg { width: 1.4rem; height: 1.4rem; border-width: 3px; color: var(--ac); margin: 0; }
@keyframes ssl-spin-kf { to { transform: rotate(360deg); } }

.ssl-progress {
  display: flex; align-items: center; gap: .75rem; margin-top: .9rem;
  padding: .75rem 1rem; border-radius: var(--r-md, 10px);
  background: color-mix(in srgb, var(--ac) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ac) 25%, transparent);
}

/* Checklist de fases reales del job de emisión */
.ssl-progress--steps { flex-direction: column; align-items: stretch; gap: .55rem; }
.ssl-steps { display: flex; flex-direction: column; gap: .45rem; }
.ssl-step {
  display: flex; align-items: center; gap: .55rem;
  font-size: .85rem; color: var(--text-muted);
}
.ssl-step i { font-size: .95rem; }
.ssl-step.is-done    { color: var(--success); }
.ssl-step.is-running { color: var(--text-primary, inherit); font-weight: 500; }
.ssl-step.is-failed  { color: var(--danger); }
.ssl-step .ssl-spin  { margin: 0; width: .95rem; height: .95rem; color: var(--ac); flex-shrink: 0; }
.ssl-step-live {
  font-size: .72rem; color: var(--text-muted);
  background: var(--surface-2); border-radius: 6px; padding: .35rem .55rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ssl-step-error { font-size: .82rem; color: var(--danger); }
.ssl-error-text {
  white-space: pre-wrap; word-break: break-word; margin: .35rem 0 0;
  font-size: .72rem; color: var(--danger); max-height: 180px; overflow: auto;
}
</style>
