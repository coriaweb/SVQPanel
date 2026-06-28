<template>
  <div class="sv-view">
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Monitor de correo</h1>
        <p class="page-head__sub">
          Envíos y recepciones de todos los dominios · estados y motivos · {{ data.date || '—' }}
        </p>
      </div>
      <div class="mm-head-actions">
        <div class="mm-daybtns">
          <button :class="{ on: isToday }" @click="setDay('today')">Hoy</button>
          <button :class="{ on: isYesterday }" @click="setDay('yesterday')">Ayer</button>
          <input type="date" class="svq-input mm-date" v-model="date" :max="todayStr" @change="reload" />
        </div>
        <button class="svq-btn svq-btn--ghost" :disabled="loading" @click="reload">
          <span v-if="loading" class="mm-spin"></span>
          <i v-else class="bi bi-arrow-repeat"></i> Actualizar
        </button>
      </div>
    </div>

    <!-- Resumen -->
    <div class="mm-summary">
      <div class="mm-stat mm-stat--sent"><span class="mm-stat__n">{{ data.counts?.sent || 0 }}</span><span class="mm-stat__k"><i class="bi bi-send"></i> Enviados</span></div>
      <div class="mm-stat mm-stat--recv"><span class="mm-stat__n">{{ data.counts?.received || 0 }}</span><span class="mm-stat__k"><i class="bi bi-inbox"></i> Recibidos</span></div>
      <div class="mm-stat mm-stat--rej"><span class="mm-stat__n">{{ data.counts?.rejected || 0 }}</span><span class="mm-stat__k"><i class="bi bi-shield-x"></i> Rechazados</span></div>
      <div class="mm-stat mm-stat--grey"><span class="mm-stat__n">{{ data.counts?.greylisted || 0 }}</span><span class="mm-stat__k"><i class="bi bi-hourglass"></i> En espera</span></div>
      <div class="mm-stat mm-stat--bounce"><span class="mm-stat__n">{{ data.counts?.bounced || 0 }}</span><span class="mm-stat__k"><i class="bi bi-arrow-return-left"></i> Rebotados</span></div>
      <div class="mm-stat mm-stat--defer"><span class="mm-stat__n">{{ data.counts?.deferred || 0 }}</span><span class="mm-stat__k"><i class="bi bi-hourglass-split"></i> Diferidos</span></div>
    </div>

    <!-- Filtros -->
    <div class="mm-filters">
      <div class="mm-search">
        <i class="bi bi-search"></i>
        <input v-model="search" type="search" class="svq-input" placeholder="Buscar remitente, destinatario o motivo…" @keyup.enter="reload" />
      </div>
      <select v-model="typeFilter" class="svq-input mm-typefilter">
        <option value="">Todos los tipos</option>
        <option value="sent">Enviados</option>
        <option value="received">Recibidos</option>
        <option value="rejected">Rechazados</option>
        <option value="greylisted">En espera (greylist)</option>
        <option value="bounced">Rebotados</option>
        <option value="deferred">Diferidos</option>
      </select>
      <span class="mm-count" v-if="data.available">{{ filteredEvents.length }} de {{ data.total_events || 0 }} eventos</span>
    </div>

    <!-- Tabla -->
    <div class="mm-card">
      <div v-if="loading" class="mm-empty"><span class="mm-spin"></span> Cargando…</div>
      <div v-else-if="!data.available" class="mm-empty">
        <i class="bi bi-inbox"></i> {{ data.message || 'Sin datos para esta fecha.' }}
      </div>
      <div v-else-if="!filteredEvents.length" class="mm-empty">
        <i class="bi bi-search"></i> No hay eventos que coincidan.
      </div>
      <div v-else class="mm-table-wrap">
      <table class="mm-table">
        <thead>
          <tr>
            <th style="width:130px">Hora</th>
            <th style="width:100px">Tipo</th>
            <th>De</th>
            <th>Para</th>
            <th style="width:180px">Antispam</th>
            <th>Detalle</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(e, i) in filteredEvents" :key="i">
            <td class="mm-mono">{{ e.ts }}</td>
            <td><span class="mm-type" :class="'mm-type--' + e.type">{{ typeLabel(e.type) }}</span></td>
            <td class="mm-mono mm-addr" :title="e.from">{{ e.from || '—' }}</td>
            <td class="mm-mono mm-addr" :title="e.to">{{ e.to || '—' }}</td>
            <td>
              <template v-if="e.spam_action">
                <span class="mm-spam" :class="spamClass(e)" :title="symbolsTitle(e)">
                  {{ e.spam_action }}
                  <span v-if="e.spam_score != null" class="mm-score">{{ e.spam_score }}/{{ e.spam_threshold }}</span>
                </span>
                <div v-if="e.spam_symbols && e.spam_symbols.length" class="mm-syms">
                  <span v-for="s in e.spam_symbols" :key="s.name" :title="s.name + ' (+' + s.weight + ')'">{{ s.label || s.name }}</span>
                </div>
              </template>
              <span v-else class="mm-status" :class="'mm-status--' + e.status">{{ statusLabel(e.status) }}</span>
            </td>
            <td class="mm-detail" :title="e.reason || e.relay">{{ e.reason || e.relay || '' }}</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'MailMonitor',
  setup() {
    const store = useMainStore()
    const loading = ref(false)
    const data    = ref({ counts: {}, events: [], available: false })
    const search  = ref('')
    const typeFilter = ref('')

    const todayStr = new Date().toISOString().slice(0, 10)
    const yesterdayStr = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
    const date = ref(todayStr)

    const isToday = computed(() => date.value === todayStr)
    const isYesterday = computed(() => date.value === yesterdayStr)

    const filteredEvents = computed(() => {
      let ev = data.value.events || []
      if (typeFilter.value) ev = ev.filter(e => e.type === typeFilter.value)
      return ev
    })

    const typeLabel = (t) => ({
      sent: 'Enviado', received: 'Recibido', rejected: 'Rechazado',
      greylisted: 'En espera', bounced: 'Rebotado', deferred: 'Diferido',
    })[t] || t
    const statusLabel = (s) => ({
      sent: 'Entregado', received: 'Recibido', rejected: 'Rechazado',
      greylisted: 'En espera', bounced: 'Rebotado', deferred: 'Diferido',
    })[s] || s

    const spamClass = (e) => {
      const a = (e.spam_action || '').toLowerCase()
      if (a.includes('spam') || a.includes('rechaz')) return 'mm-spam--bad'
      if (a.includes('sospech')) return 'mm-spam--warn'
      if (a.includes('greylist') || a.includes('reintentar')) return 'mm-spam--grey'
      return 'mm-spam--ok'
    }
    const symbolsTitle = (e) =>
      (e.spam_symbols || []).map(s => `${s.label || s.name} (+${s.weight})`).join('\n') || ''

    const reload = async () => {
      loading.value = true
      try {
        data.value = await api.mailMonitor({ date: date.value, search: search.value })
      } catch (e) {
        store.showNotification('Error al cargar el monitor: ' + (e.message || e), 'danger')
        data.value = { counts: {}, events: [], available: false, message: 'Error al cargar.' }
      } finally { loading.value = false }
    }

    const setDay = (which) => {
      date.value = which === 'today' ? todayStr : yesterdayStr
      reload()
    }

    onMounted(reload)

    return {
      loading, data, search, typeFilter, date, todayStr,
      isToday, isYesterday, filteredEvents,
      typeLabel, statusLabel, reload, setDay,
      spamClass, symbolsTitle,
    }
  },
}
</script>

<style scoped>
.page-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap; margin-bottom:1.2rem; }
.page-head__title { font-size:1.6rem; font-weight:700; }
.page-head__sub { color:var(--text-muted); font-size:.9rem; margin-top:.2rem; }
.mm-head-actions { display:flex; gap:.6rem; align-items:center; flex-wrap:wrap; }
.mm-daybtns { display:flex; gap:0; border:1px solid var(--border); border-radius:var(--r-md,8px); overflow:hidden; }
.mm-daybtns button { border:0; background:var(--surface); color:var(--text-secondary); padding:.4rem .9rem; cursor:pointer; font-size:.85rem; border-right:1px solid var(--border); }
.mm-daybtns button.on { background:var(--color-primary); color:#fff; }
.mm-date { border:0!important; border-radius:0!important; min-width:140px; }
.svq-btn { display:inline-flex; align-items:center; gap:.4rem; border:1px solid var(--border); background:var(--surface); color:var(--text); padding:.4rem .8rem; border-radius:var(--r-md,8px); cursor:pointer; font-size:.85rem; }
.svq-btn:hover { border-color:var(--border-strong); }

.mm-summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.8rem; margin-bottom:1.2rem; }
.mm-stat { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-lg,12px); padding:1rem 1.1rem; display:flex; flex-direction:column; gap:.2rem; }
.mm-stat__n { font-size:1.7rem; font-weight:700; line-height:1; }
.mm-stat__k { font-size:.82rem; color:var(--text-muted); }
.mm-stat--sent   { border-top:3px solid #3b82f6; }
.mm-stat--recv   { border-top:3px solid #10b981; }
.mm-stat--rej    { border-top:3px solid #ef4444; }
.mm-stat--grey   { border-top:3px solid #64748b; }
.mm-stat--bounce { border-top:3px solid #f59e0b; }
.mm-stat--defer  { border-top:3px solid #a78bfa; }

.mm-filters { display:flex; gap:.7rem; align-items:center; margin-bottom:.8rem; flex-wrap:wrap; }
.mm-search { position:relative; display:flex; align-items:center; flex:1; min-width:240px; }
.mm-search i { position:absolute; left:.6rem; color:var(--text-muted); font-size:.85rem; pointer-events:none; }
.mm-search .svq-input { padding-left:1.9rem; width:100%; }
.mm-typefilter { min-width:160px; }
.mm-count { color:var(--text-muted); font-size:.82rem; white-space:nowrap; }

.mm-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-lg,12px); overflow:hidden; }
.mm-empty { padding:3rem 1rem; text-align:center; color:var(--text-muted); }
/* Scroll horizontal en móvil: la tabla es ancha (6 columnas), así se pueden
   ver las de la derecha (Antispam/Detalle) deslizando. */
.mm-table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.mm-table { width:100%; border-collapse:collapse; font-size:.86rem; min-width:760px; }
.mm-table th { text-align:left; padding:.6rem .9rem; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color:var(--text-muted); border-bottom:1px solid var(--border); background:var(--surface-inset); }
.mm-table td { padding:.5rem .9rem; border-bottom:1px solid var(--border); vertical-align:middle; }
.mm-table tbody tr:hover { background:var(--surface-inset); }
.mm-mono { font-family:var(--font-mono,monospace); font-size:.82rem; }
.mm-addr { max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mm-detail { color:var(--text-muted); font-size:.8rem; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

.mm-type, .mm-status { display:inline-block; font-size:.72rem; font-weight:600; padding:.1rem .5rem; border-radius:999px; }
.mm-type--sent     { color:#3b82f6; background:color-mix(in srgb,#3b82f6 14%,transparent); }
.mm-type--received { color:#10b981; background:color-mix(in srgb,#10b981 14%,transparent); }
.mm-type--rejected { color:#ef4444; background:color-mix(in srgb,#ef4444 14%,transparent); }
.mm-type--greylisted { color:#64748b; background:color-mix(in srgb,#64748b 16%,transparent); }
.mm-type--bounced  { color:#f59e0b; background:color-mix(in srgb,#f59e0b 14%,transparent); }
.mm-type--deferred { color:#a78bfa; background:color-mix(in srgb,#a78bfa 14%,transparent); }
.mm-status--sent, .mm-status--received { color:#10b981; background:color-mix(in srgb,#10b981 12%,transparent); }
.mm-status--rejected, .mm-status--bounced { color:#ef4444; background:color-mix(in srgb,#ef4444 12%,transparent); }
.mm-status--greylisted { color:#64748b; background:color-mix(in srgb,#64748b 14%,transparent); }
.mm-status--deferred { color:#f59e0b; background:color-mix(in srgb,#f59e0b 12%,transparent); }
.mm-spam { display:inline-flex; align-items:center; gap:.3rem; font-size:.74rem; font-weight:600; padding:.12rem .5rem; border-radius:999px; }
.mm-spam .mm-score { font-weight:500; opacity:.8; font-variant-numeric:tabular-nums; }
.mm-spam--ok   { color:#10b981; background:color-mix(in srgb,#10b981 12%,transparent); }
.mm-spam--warn { color:#f59e0b; background:color-mix(in srgb,#f59e0b 14%,transparent); }
.mm-spam--bad  { color:#ef4444; background:color-mix(in srgb,#ef4444 14%,transparent); }
.mm-spam--grey { color:#6b7280; background:color-mix(in srgb,#6b7280 14%,transparent); }
.mm-syms { display:flex; flex-direction:column; gap:.15rem; margin-top:.3rem; }
.mm-syms span { font-size:.7rem; color:var(--text-muted); line-height:1.25; }
.mm-syms span::before { content:"· "; opacity:.6; }
.mm-spin { display:inline-block; width:14px; height:14px; border:2px solid currentColor; border-right-color:transparent; border-radius:50%; animation:mm-spin .7s linear infinite; vertical-align:-2px; }
@keyframes mm-spin { to { transform:rotate(360deg); } }
</style>
