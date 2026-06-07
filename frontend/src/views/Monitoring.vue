<template>
  <div class="sv-view">
    <!-- Cabecera -->
    <div class="mon-head">
      <div>
        <h2 class="mon-title"><i class="bi bi-graph-up"></i> Monitorización</h2>
        <p class="mon-subtitle">Histórico de recursos y alertas del servidor</p>
      </div>
      <div class="mon-range">
        <button v-for="r in ['24h','7d','30d']" :key="r"
                class="mon-range__btn" :class="{ 'mon-range__btn--active': range === r }"
                @click="setRange(r)">{{ r }}</button>
      </div>
    </div>

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

    onMounted(async () => {
      await Promise.all([loadHistory(), loadConfig(), loadEvents()])
      // Refresco automático cada 60s
      refreshTimer = setInterval(() => { loadHistory(); loadEvents() }, 60000)
    })
    onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })

    return {
      range, points, loading, cfg, events, savingCfg, testing,
      seriesCpu, seriesRam, seriesDisk, seriesLoad, seriesRx, seriesTx,
      openAlerts, setRange, saveCfg, sendTest, relTime,
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
</style>
