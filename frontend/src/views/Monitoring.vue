<template>
  <div class="sv-view">
    <!-- Cabecera -->
    <div class="mon-head">
      <div>
        <h2 class="mon-title"><i class="bi bi-graph-up"></i> Monitorización</h2>
        <p class="mon-subtitle">Histórico de recursos y alertas del servidor</p>
      </div>
      <div v-if="tab==='recursos'" class="mon-range">
        <button v-for="r in ['24h','7d','30d']" :key="r"
                class="mon-range__btn" :class="{ 'mon-range__btn--active': range === r }"
                @click="setRange(r)">{{ r }}</button>
      </div>
      <button v-else class="mon-btn mon-btn--ghost mon-btn--sm" @click="loadMail" :disabled="mailLoading">
        <span v-if="mailLoading" class="spinner-border spinner-border-sm"></span>
        <i v-else class="bi bi-arrow-repeat"></i> Actualizar
      </button>
    </div>

    <!-- Pestañas -->
    <div class="mon-tabs">
      <button class="mon-tab" :class="{'mon-tab--active': tab==='recursos'}" @click="tab='recursos'">
        <i class="bi bi-cpu"></i> Recursos
      </button>
      <button class="mon-tab" :class="{'mon-tab--active': tab==='correo'}" @click="selectMailTab">
        <i class="bi bi-envelope"></i> Correo
      </button>
    </div>

    <!-- ════════════ PESTAÑA RECURSOS ════════════ -->
    <template v-if="tab==='recursos'">

    <!-- Alertas abiertas -->
    <div v-if="openAlerts.length" class="mon-alerts">
      <div v-for="a in openAlerts" :key="a.id" class="mon-alert" :class="`mon-alert--${a.level}`">
        <i :class="a.level === 'critical' ? 'bi bi-exclamation-octagon-fill' : 'bi bi-exclamation-triangle-fill'"></i>
        <span>{{ a.message }}</span>
        <span class="mon-alert__time">{{ relTime(a.created_at) }}</span>
      </div>
    </div>

    <!-- Gráficas -->
    <div v-if="loading" class="mon-loading"><div class="spinner-border spinner-border-sm"></div></div>
    <div v-else-if="!points.length" class="mon-empty">
      <i class="bi bi-graph-up"></i>
      <p>Aún no hay datos de monitorización.</p>
      <small>El servidor toma una muestra cada 5 minutos; vuelve en un rato.</small>
    </div>
    <div v-else class="mon-grid">
      <MetricChart title="CPU" unit="%" color="var(--ac)"
                   :series="seriesCpu" :max="100" :format="v => v.toFixed(0) + '%'" />
      <MetricChart title="RAM" unit="%" color="#8b5cf6"
                   :series="seriesRam" :max="100" :format="v => v.toFixed(0) + '%'" />
      <MetricChart title="Disco" unit="%" color="#06b6d4"
                   :series="seriesDisk" :max="100" :format="v => v.toFixed(0) + '%'" />
      <MetricChart title="Carga" unit="load 5m" color="#f59e0b"
                   :series="seriesLoad" :format="v => v.toFixed(2)" />
      <MetricChart title="Red ↓" unit="Mbps" color="#10b981"
                   :series="seriesRx" :format="v => v.toFixed(1)" />
      <MetricChart title="Red ↑" unit="Mbps" color="#ef4444"
                   :series="seriesTx" :format="v => v.toFixed(1)" />
    </div>

    <!-- Configuración de alertas -->
    <div class="mon-card">
      <div class="mon-card-head">
        <span class="mon-card-title"><i class="bi bi-bell"></i> Alertas por email</span>
        <button class="mon-btn mon-btn--ghost mon-btn--sm" @click="sendTest" :disabled="testing">
          <span v-if="testing" class="spinner-border spinner-border-sm"></span>
          <i v-else class="bi bi-send"></i> Probar email
        </button>
      </div>
      <div class="mon-card-body" v-if="cfg">
        <div class="mon-field">
          <label>Email de destino <span class="mon-hint">(vacío = email del admin)</span></label>
          <input v-model="cfg.notify_email" type="email" class="form-control form-control-sm"
                 placeholder="alertas@tudominio.com">
        </div>

        <div class="mon-alert-rules">
          <!-- Disco -->
          <div class="mon-rule">
            <label class="mon-switch">
              <input type="checkbox" v-model="cfg.disk_enabled">
              <span><i class="bi bi-hdd"></i> Disco lleno</span>
            </label>
            <div class="mon-rule__cfg" v-if="cfg.disk_enabled">
              Aviso al <input v-model.number="cfg.disk_warn_pct" type="number" min="1" max="99" class="mon-num">%
              · crítico al <input v-model.number="cfg.disk_crit_pct" type="number" min="1" max="100" class="mon-num">%
            </div>
          </div>

          <!-- Servicios -->
          <div class="mon-rule">
            <label class="mon-switch">
              <input type="checkbox" v-model="cfg.service_enabled">
              <span><i class="bi bi-hdd-rack"></i> Servicio caído</span>
            </label>
            <div class="mon-rule__cfg" v-if="cfg.service_enabled">
              <input v-model="cfg.service_watch" class="form-control form-control-sm font-monospace"
                     placeholder="nginx,postgresql,php-fpm,postfix,dovecot" style="max-width:420px">
            </div>
          </div>

          <!-- Carga / RAM -->
          <div class="mon-rule">
            <label class="mon-switch">
              <input type="checkbox" v-model="cfg.load_enabled">
              <span><i class="bi bi-speedometer2"></i> Carga / RAM alta</span>
            </label>
            <div class="mon-rule__cfg" v-if="cfg.load_enabled">
              Carga si load_5 > nCPU ×
              <input v-model.number="cfg.load_factor" type="number" step="0.1" min="0.5" max="5" class="mon-num">
              · RAM al <input v-model.number="cfg.ram_warn_pct" type="number" min="1" max="100" class="mon-num">%
            </div>
          </div>

          <!-- SSL -->
          <div class="mon-rule">
            <label class="mon-switch">
              <input type="checkbox" v-model="cfg.ssl_enabled">
              <span><i class="bi bi-shield-lock"></i> SSL por expirar</span>
            </label>
            <div class="mon-rule__cfg" v-if="cfg.ssl_enabled">
              Avisar <input v-model.number="cfg.ssl_days_before" type="number" min="1" max="90" class="mon-num">
              días antes de expirar
            </div>
          </div>
        </div>

        <button class="mon-btn mon-btn--primary mon-btn--sm" @click="saveCfg" :disabled="savingCfg">
          <span v-if="savingCfg" class="spinner-border spinner-border-sm"></span>
          <i v-else class="bi bi-save"></i> Guardar alertas
        </button>
      </div>
    </div>

    <!-- Historial de alertas -->
    <div class="mon-card" v-if="events.length">
      <div class="mon-card-head">
        <span class="mon-card-title"><i class="bi bi-clock-history"></i> Historial de alertas</span>
      </div>
      <div class="mon-table-wrap">
        <table class="mon-table">
          <thead><tr><th>Estado</th><th>Tipo</th><th>Mensaje</th><th>Cuándo</th></tr></thead>
          <tbody>
            <tr v-for="e in events" :key="e.id">
              <td>
                <span class="mon-badge" :class="e.open ? (e.level==='critical'?'mon-badge--danger':'mon-badge--warn') : 'mon-badge--ok'">
                  {{ e.open ? (e.level === 'critical' ? 'Crítico' : 'Activo') : 'Resuelto' }}
                </span>
              </td>
              <td style="font-family:var(--font-mono);font-size:.8rem">{{ e.kind }}</td>
              <td style="font-size:.85rem">{{ e.message }}</td>
              <td style="font-size:.8rem;color:var(--text-muted);white-space:nowrap">{{ relTime(e.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    </template>

    <!-- ════════════ PESTAÑA CORREO ════════════ -->
    <template v-if="tab==='correo'">
      <div v-if="mailLoading && !mail" class="mon-loading"><div class="spinner-border spinner-border-sm"></div></div>
      <div v-else-if="mail">
        <!-- Estado de servicios -->
        <div class="mail-services">
          <div class="mail-svc" :class="mail.services.postfix ? 'mail-svc--on' : 'mail-svc--off'">
            <i class="bi" :class="mail.services.postfix ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"></i>
            Postfix <small>SMTP</small>
          </div>
          <div class="mail-svc" :class="mail.services.dovecot ? 'mail-svc--on' : 'mail-svc--off'">
            <i class="bi" :class="mail.services.dovecot ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"></i>
            Dovecot <small>IMAP/POP3</small>
          </div>
          <div class="mail-svc" :class="mail.services.rspamd ? 'mail-svc--on' : 'mail-svc--off'">
            <i class="bi" :class="mail.services.rspamd ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"></i>
            Rspamd <small>antispam</small>
          </div>
        </div>

        <!-- Contadores del día -->
        <div class="mail-counters">
          <div class="mail-counter"><div class="mail-counter__val">{{ mail.summary.received }}</div><div class="mail-counter__lbl">Recibidos hoy</div></div>
          <div class="mail-counter"><div class="mail-counter__val mc-ok">{{ mail.summary.delivered }}</div><div class="mail-counter__lbl">Entregados</div></div>
          <div class="mail-counter"><div class="mail-counter__val mc-warn">{{ mail.summary.deferred }}</div><div class="mail-counter__lbl">Diferidos</div></div>
          <div class="mail-counter"><div class="mail-counter__val mc-err">{{ mail.summary.bounced }}</div><div class="mail-counter__lbl">Rebotados</div></div>
          <div class="mail-counter"><div class="mail-counter__val mc-err">{{ mail.summary.rejected }}</div><div class="mail-counter__lbl">Rechazados</div></div>
          <div class="mail-counter"><div class="mail-counter__val" :class="mail.queue.count > 0 ? 'mc-warn' : ''">{{ mail.queue.count }}</div><div class="mail-counter__lbl">En cola</div></div>
        </div>

        <div class="mon-grid2">
          <!-- Cola de correo -->
          <div class="mon-card">
            <div class="mon-card-head">
              <span class="mon-card-title"><i class="bi bi-hourglass-split"></i> Cola de correo</span>
              <span class="mon-badge" :class="mail.queue.count > 0 ? 'mon-badge--warn' : 'mon-badge--ok'">
                {{ mail.queue.count }} · {{ mail.queue.size_kb }} KB
              </span>
            </div>
            <div class="mon-card-body">
              <div v-if="!mail.queue.count" class="mail-empty"><i class="bi bi-check-circle"></i> Cola vacía. Todo el correo se está entregando.</div>
              <div v-else class="mon-table-wrap">
                <table class="mon-table">
                  <thead><tr><th>ID</th><th>De</th><th>Para</th><th>Edad</th><th>Motivo</th></tr></thead>
                  <tbody>
                    <tr v-for="m in mail.queue.messages" :key="m.id">
                      <td style="font-family:var(--font-mono);font-size:.78rem">{{ m.id }}</td>
                      <td style="font-size:.8rem">{{ m.sender }}</td>
                      <td style="font-size:.8rem">{{ m.recipients.join(', ') }}</td>
                      <td style="font-size:.8rem;white-space:nowrap">{{ fmtAge(m.age_s) }}</td>
                      <td style="font-size:.76rem;color:var(--text-muted)">{{ m.reason || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- Antispam -->
          <div class="mon-card">
            <div class="mon-card-head">
              <span class="mon-card-title"><i class="bi bi-shield-fill-check"></i> Antispam (Rspamd)</span>
            </div>
            <div class="mon-card-body">
              <div v-if="!mail.rspamd.available" class="mail-empty">Rspamd no responde.</div>
              <div v-else class="mail-rspamd">
                <div class="mail-stat"><span>Escaneados</span><strong>{{ mail.rspamd.scanned }}</strong></div>
                <div class="mail-stat"><span>Limpios (ham)</span><strong class="mc-ok">{{ mail.rspamd.ham }}</strong></div>
                <div class="mail-stat"><span>Spam</span><strong class="mc-err">{{ mail.rspamd.spam }}</strong></div>
                <div class="mail-stat"><span>Rechazados</span><strong class="mc-err">{{ mail.rspamd.reject }}</strong></div>
                <div class="mail-stat"><span>Greylisted</span><strong class="mc-warn">{{ mail.rspamd.greylist }}</strong></div>
                <div class="mail-stat"><span>Aprendidos</span><strong>{{ mail.rspamd.learned }}</strong></div>
              </div>
            </div>
          </div>
        </div>

        <div class="mon-grid2">
          <!-- Top remitentes -->
          <div class="mon-card">
            <div class="mon-card-head"><span class="mon-card-title"><i class="bi bi-person-up"></i> Top remitentes (hoy)</span></div>
            <div class="mon-card-body">
              <div v-if="!mail.summary.top_senders.length" class="mail-empty">Sin datos hoy.</div>
              <div v-for="s in mail.summary.top_senders" :key="s.addr" class="mail-toprow">
                <span class="mail-topaddr">{{ s.addr }}</span><span class="mail-topcount">{{ s.count }}</span>
              </div>
            </div>
          </div>

          <!-- Top motivos de rechazo -->
          <div class="mon-card">
            <div class="mon-card-head"><span class="mon-card-title"><i class="bi bi-shield-x"></i> Motivos de rechazo (hoy)</span></div>
            <div class="mon-card-body">
              <div v-if="!mail.summary.top_reject_reasons.length" class="mail-empty">Sin rechazos hoy.</div>
              <div v-for="r in mail.summary.top_reject_reasons" :key="r.reason" class="mail-toprow">
                <span class="mail-topaddr" :title="r.reason">{{ r.reason }}</span><span class="mail-topcount mc-err">{{ r.count }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Errores recientes (rebotes) -->
        <div class="mon-card" v-if="mail.summary.recent_errors.length">
          <div class="mon-card-head"><span class="mon-card-title"><i class="bi bi-exclamation-triangle"></i> Rebotes recientes</span></div>
          <div class="mon-card-body">
            <div v-for="(e, i) in mail.summary.recent_errors" :key="i" class="mail-error">
              <span class="mail-error__to">{{ e.to }}</span>
              <span class="mail-error__msg">{{ e.msg }}</span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import MetricChart from '../components/ui/MetricChart.vue'

export default {
  name: 'Monitoring',
  components: { MetricChart },
  setup() {
    const store = useMainStore()
    const range = ref('24h')
    const points = ref([])
    const loading = ref(true)
    const cfg = ref(null)
    const events = ref([])
    const savingCfg = ref(false)
    const testing = ref(false)
    let refreshTimer = null

    const mkSeries = (key) => computed(() => points.value.map(p => ({ ts: p.ts, value: p[key] })))
    const seriesCpu  = mkSeries('cpu')
    const seriesRam  = mkSeries('ram')
    const seriesDisk = mkSeries('disk')
    const seriesLoad = mkSeries('load')
    const seriesRx   = mkSeries('rx_mbps')
    const seriesTx   = mkSeries('tx_mbps')

    const openAlerts = computed(() => events.value.filter(e => e.open))

    const loadHistory = async () => {
      loading.value = true
      try {
        const data = await api.get(`/api/monitoring/history?range=${range.value}`)
        points.value = data.points || []
      } catch (e) {
        store.showNotification('Error al cargar histórico', 'danger')
      } finally {
        loading.value = false
      }
    }

    const loadConfig = async () => {
      try { cfg.value = await api.get('/api/monitoring/alerts/config') } catch {}
    }
    const loadEvents = async () => {
      try { events.value = await api.get('/api/monitoring/alerts/events?limit=50') } catch {}
    }

    const setRange = (r) => { range.value = r; loadHistory() }

    const saveCfg = async () => {
      savingCfg.value = true
      try {
        cfg.value = await api.put('/api/monitoring/alerts/config', cfg.value)
        store.showNotification('Alertas guardadas', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingCfg.value = false
      }
    }

    const sendTest = async () => {
      testing.value = true
      try {
        await api.post('/api/monitoring/alerts/test', {})
        store.showNotification('Email de prueba enviado', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        testing.value = false
      }
    }

    const relTime = (iso) => {
      if (!iso) return '—'
      const diff = (Date.now() - new Date(iso).getTime()) / 1000
      if (diff < 60) return 'hace un momento'
      if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`
      if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`
      return `hace ${Math.floor(diff / 86400)} d`
    }

    // ── Pestaña Correo ──
    const tab = ref('recursos')
    const mail = ref(null)
    const mailLoading = ref(false)
    const fmtAge = (s) => {
      if (s < 60) return s + 's'
      if (s < 3600) return Math.floor(s / 60) + 'm'
      if (s < 86400) return Math.floor(s / 3600) + 'h'
      return Math.floor(s / 86400) + 'd'
    }
    const loadMail = async () => {
      mailLoading.value = true
      try {
        mail.value = await api.get('/api/monitoring/services/mail')
      } catch (e) {
        store.showNotification('Error al cargar estadísticas de correo: ' + e.message, 'danger')
      } finally { mailLoading.value = false }
    }
    const selectMailTab = () => {
      tab.value = 'correo'
      if (!mail.value) loadMail()
    }

    onMounted(async () => {
      await Promise.all([loadHistory(), loadConfig(), loadEvents()])
      // Refresco automático cada 60s
      refreshTimer = setInterval(() => {
        if (tab.value === 'recursos') { loadHistory(); loadEvents() }
        else { loadMail() }
      }, 60000)
    })
    onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })

    return {
      range, points, loading, cfg, events, savingCfg, testing,
      seriesCpu, seriesRam, seriesDisk, seriesLoad, seriesRx, seriesTx,
      openAlerts, setRange, saveCfg, sendTest, relTime,
      tab, mail, mailLoading, loadMail, selectMailTab, fmtAge,
    }
  },
}
</script>

<style scoped>
.sv-view { display:flex; flex-direction:column; gap:20px; }

.mon-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap; }
.mon-title { font-size:1.5rem; font-weight:700; margin:0 0 .25rem; display:flex; align-items:center; gap:.5rem; }
.mon-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }

/* Selector de rango */
.mon-range { display:flex; gap:2px; background:var(--surface-2); border-radius:var(--r-sm,6px); padding:3px; }
.mon-range__btn { padding:.35rem .85rem; border:none; background:none; border-radius:var(--r-sm,6px); font-size:.82rem; font-weight:500; cursor:pointer; color:var(--text-muted); }
.mon-range__btn--active { background:var(--surface); color:var(--text); box-shadow:0 1px 2px rgba(0,0,0,.08); }

/* Alertas abiertas */
.mon-alerts { display:flex; flex-direction:column; gap:8px; }
.mon-alert { display:flex; align-items:center; gap:.6rem; padding:.6rem 1rem; border-radius:var(--r-md,10px); font-size:.875rem; }
.mon-alert--warning { background:color-mix(in srgb,var(--warning,#f59e0b) 12%,transparent); color:var(--warning,#d97706); border:1px solid color-mix(in srgb,var(--warning,#f59e0b) 25%,transparent); }
.mon-alert--critical { background:color-mix(in srgb,var(--danger) 12%,transparent); color:var(--danger); border:1px solid color-mix(in srgb,var(--danger) 25%,transparent); }
.mon-alert__time { margin-left:auto; font-size:.75rem; opacity:.8; }

/* Grid de gráficas */
.mon-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }

/* Cards */
.mon-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); overflow:hidden; }
.mon-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); }
.mon-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
.mon-card-body { padding:1.25rem; display:flex; flex-direction:column; gap:1rem; }

/* Campos */
.mon-field { display:flex; flex-direction:column; gap:.35rem; max-width:420px; }
.mon-field label { font-size:.82rem; font-weight:600; color:var(--text-secondary); }
.mon-hint { font-weight:400; color:var(--text-muted); }
.mon-num { width:54px; padding:.15rem .3rem; border:1px solid var(--border); border-radius:4px; background:var(--surface); color:var(--text); font-size:.82rem; text-align:center; }

/* Reglas de alerta */
.mon-alert-rules { display:flex; flex-direction:column; gap:.85rem; }
.mon-rule { display:flex; flex-direction:column; gap:.4rem; padding-bottom:.85rem; border-bottom:1px solid var(--border); }
.mon-rule:last-child { border-bottom:none; padding-bottom:0; }
.mon-switch { display:flex; align-items:center; gap:.5rem; font-weight:600; font-size:.9rem; cursor:pointer; }
.mon-switch input { width:16px; height:16px; cursor:pointer; }
.mon-rule__cfg { font-size:.82rem; color:var(--text-muted); padding-left:1.6rem; display:flex; align-items:center; gap:.3rem; flex-wrap:wrap; }

/* Botones */
.mon-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--r-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.mon-btn--primary { background:var(--ac); color:#fff; border-color:var(--ac); align-self:flex-start; }
.mon-btn--primary:hover { opacity:.9; }
.mon-btn--ghost { background:var(--surface); color:var(--text-secondary); border-color:var(--border); }
.mon-btn--ghost:hover { background:var(--surface-2); color:var(--text); }
.mon-btn--sm { padding:.3rem .7rem; font-size:.82rem; }
.mon-btn:disabled { opacity:.5; cursor:not-allowed; }

/* Tabla */
.mon-table-wrap { overflow-x:auto; }
.mon-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.mon-table th { padding:.6rem 1rem; text-align:left; font-size:.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); }
.mon-table td { padding:.6rem 1rem; border-bottom:1px solid var(--border); }
.mon-table tr:last-child td { border-bottom:none; }

/* Badges */
.mon-badge { display:inline-flex; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }
.mon-badge--ok { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); }
.mon-badge--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 15%,transparent); color:var(--warning,#d97706); }
.mon-badge--danger { background:color-mix(in srgb,var(--danger) 15%,transparent); color:var(--danger); }

/* Estados */
.mon-loading { display:flex; justify-content:center; padding:3rem; }
.mon-empty { display:flex; flex-direction:column; align-items:center; gap:.5rem; padding:3rem; color:var(--text-muted); text-align:center; }
.mon-empty i { font-size:2.5rem; }

/* Pestañas */
.mon-tabs { display:flex; gap:2px; padding:.35rem; background:var(--surface-2); border-radius:var(--r-md,10px); width:fit-content; }
.mon-tab { display:inline-flex; align-items:center; gap:6px; padding:.45rem .9rem; border-radius:var(--r-sm,6px); font-size:.85rem; font-weight:500; cursor:pointer; border:none; background:none; color:var(--text-muted); transition:all .15s; }
.mon-tab:hover { background:var(--surface); color:var(--text); }
.mon-tab--active { background:var(--surface); color:var(--text); box-shadow:0 1px 3px rgba(0,0,0,.08); }
.mon-tab--active i { color:var(--svq-orange); }

/* Correo: servicios */
.mail-services { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
@media (max-width:640px){ .mail-services { grid-template-columns:1fr; } }
.mail-svc { display:flex; align-items:center; gap:.6rem; padding:.85rem 1.1rem; border:1px solid var(--border); border-radius:var(--r-md,10px); background:var(--surface); font-weight:600; }
.mail-svc small { color:var(--text-muted); font-weight:400; }
.mail-svc i { font-size:1.2rem; }
.mail-svc--on i { color:var(--success); }
.mail-svc--off { border-color:color-mix(in srgb,var(--danger) 40%,transparent); }
.mail-svc--off i { color:var(--danger); }

/* Correo: contadores */
.mail-counters { display:grid; grid-template-columns:repeat(6,1fr); gap:12px; }
@media (max-width:820px){ .mail-counters { grid-template-columns:repeat(3,1fr); } }
@media (max-width:480px){ .mail-counters { grid-template-columns:repeat(2,1fr); } }
.mail-counter { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); padding:.85rem; text-align:center; }
.mail-counter__val { font-size:1.6rem; font-weight:700; line-height:1; color:var(--text); }
.mail-counter__lbl { font-size:.72rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:.03em; margin-top:.35rem; }
.mc-ok { color:var(--success); } .mc-warn { color:var(--warning,#d97706); } .mc-err { color:var(--danger); }

.mon-grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:820px){ .mon-grid2 { grid-template-columns:1fr; } }

.mail-empty { display:flex; align-items:center; gap:.5rem; color:var(--text-muted); font-size:.875rem; padding:1rem 0; }
.mail-rspamd { display:grid; grid-template-columns:1fr 1fr; gap:.5rem .75rem; }
.mail-stat { display:flex; justify-content:space-between; align-items:center; padding:.4rem .6rem; background:var(--surface-2); border-radius:var(--r-sm,6px); font-size:.85rem; }
.mail-stat strong { font-family:var(--font-mono); }

.mail-toprow { display:flex; justify-content:space-between; align-items:center; gap:.75rem; padding:.4rem 0; border-bottom:1px solid var(--border); font-size:.82rem; }
.mail-toprow:last-child { border-bottom:none; }
.mail-topaddr { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text-secondary); }
.mail-topcount { font-family:var(--font-mono); font-weight:700; flex-shrink:0; }

.mail-error { display:flex; gap:.75rem; padding:.5rem 0; border-bottom:1px solid var(--border); font-size:.82rem; }
.mail-error:last-child { border-bottom:none; }
.mail-error__to { font-weight:600; flex-shrink:0; color:var(--text); }
.mail-error__msg { color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; }
</style>
