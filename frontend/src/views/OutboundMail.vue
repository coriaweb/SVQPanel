<template>
  <div class="sv-view">
    <div class="om-head">
      <div>
        <h2 class="om-title"><i class="bi bi-send-check"></i> Envío saliente (web)</h2>
        <p class="om-subtitle">
          Correo NO autenticado (formularios PHP, WordPress…) por usuario del sistema ·
          últimos 60 min
        </p>
      </div>
      <button class="om-btn" :disabled="loading" @click="load">
        <i class="bi bi-arrow-clockwise"></i> Actualizar
      </button>
    </div>

    <div class="om-note">
      <i class="bi bi-info-circle"></i>
      Cada sitio web envía como <code>usuario_sistema@{{ hostname || 'servidor' }}</code>.
      Si un sitio se compromete y supera su límite/hora, sus correos se rechazan
      automáticamente (anti-spam). Aquí ves el consumo de la última hora.
    </div>

    <div v-if="loading" class="om-loading"><span class="om-spinner"></span></div>

    <div v-else-if="!rows.length" class="om-empty">
      <i class="bi bi-inbox"></i>
      <p>No hay usuarios con límite de envío configurado todavía.</p>
    </div>

    <div v-else class="om-table-wrap">
      <table class="om-table">
        <thead>
          <tr><th></th><th>Usuario (sistema)</th><th>Enviados (1h)</th><th>Límite/h</th><th>Uso</th><th>Estado</th></tr>
        </thead>
        <tbody>
          <template v-for="r in rows" :key="r.user">
            <tr :class="rowClass(r.state)">
              <td class="om-toggle">
                <button v-if="r.recipients && r.recipients.length" class="om-exp"
                        @click="toggle(r.user)" :title="expanded === r.user ? 'Ocultar' : 'Ver destinatarios'">
                  <i class="bi" :class="expanded === r.user ? 'bi-chevron-down' : 'bi-chevron-right'"></i>
                </button>
              </td>
              <td class="om-mono">{{ r.user }}</td>
              <td>{{ r.sent_last_hour }}</td>
              <td>{{ r.limit || '—' }}</td>
              <td>
                <div class="om-bar">
                  <div class="om-bar-fill" :class="barClass(r.state)" :style="{ width: Math.min(r.pct,100)+'%' }"></div>
                </div>
                <span class="om-pct">{{ r.pct }}%</span>
              </td>
              <td>
                <span class="om-badge" :class="badgeClass(r.state)">
                  <i class="bi" :class="badgeIcon(r.state)"></i> {{ stateLabel(r.state) }}
                </span>
              </td>
            </tr>
            <tr v-if="expanded === r.user && r.recipients.length" class="om-rcpt-row">
              <td></td>
              <td colspan="5">
                <div class="om-rcpt-title">Destinatarios (última hora):</div>
                <ul class="om-rcpt-list">
                  <li v-for="d in r.recipients" :key="d.to">
                    <code>{{ d.to }}</code>
                    <span v-if="d.count > 1" class="om-rcpt-count">×{{ d.count }}</span>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const store = useMainStore()
const loading = ref(true)
const rows = ref([])
const hostname = ref('')
const expanded = ref(null)

function toggle(user) { expanded.value = expanded.value === user ? null : user }

function rowClass(s) { return s === 'blocked' ? 'om-row-blocked' : (s === 'warn' ? 'om-row-warn' : '') }
function barClass(s) { return s === 'blocked' ? 'om-fill-danger' : (s === 'warn' ? 'om-fill-warn' : 'om-fill-ok') }
function badgeClass(s) { return s === 'blocked' ? 'om-badge-danger' : (s === 'warn' ? 'om-badge-warn' : 'om-badge-ok') }
function badgeIcon(s) { return s === 'blocked' ? 'bi-x-octagon' : (s === 'warn' ? 'bi-exclamation-triangle' : 'bi-check-circle') }
function stateLabel(s) { return s === 'blocked' ? 'Bloqueado' : (s === 'warn' ? 'Cerca del límite' : 'OK') }

async function load() {
  loading.value = true
  try {
    const r = await api.get('/api/outbound-mail')
    rows.value = r.rows || []
    hostname.value = r.hostname || ''
  } catch (e) {
    store.showNotification('Error al cargar el envío saliente: ' + (e.message || e), 'danger')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.om-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
.om-title { font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: .5rem; }
.om-subtitle { color: var(--text-muted); font-size: .9rem; margin-top: .25rem; }

.om-note { background: color-mix(in srgb, var(--info) 8%, transparent); border: 1px solid color-mix(in srgb, var(--info) 25%, transparent); border-radius: var(--r-md); padding: .7rem .9rem; font-size: .82rem; margin-bottom: 1.25rem; }
.om-note code, .om-table code { background: var(--surface-inset); padding: .05rem .35rem; border-radius: 4px; font-family: var(--font-mono, monospace); font-size: .85em; }

.om-loading { text-align: center; padding: 2rem; }
.om-spinner { display: inline-block; width: 1.4rem; height: 1.4rem; border: 2px solid var(--border); border-top-color: var(--ac); border-radius: 50%; animation: om-spin .6s linear infinite; }
@keyframes om-spin { to { transform: rotate(360deg); } }

.om-empty { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.om-empty i { font-size: 2.5rem; display: block; margin-bottom: .5rem; }

.om-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--r-md); }
.om-table { width: 100%; border-collapse: collapse; font-size: .87rem; }
.om-table th, .om-table td { padding: .6rem .75rem; text-align: left; border-bottom: 1px solid var(--border); vertical-align: middle; }
.om-table th { font-size: .73rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .02em; background: var(--surface-2); }
.om-table tr:last-child td { border-bottom: none; }
.om-mono { font-family: var(--font-mono, monospace); font-weight: 600; }
.om-row-blocked { background: color-mix(in srgb, var(--danger) 7%, transparent); }
.om-row-warn { background: color-mix(in srgb, var(--warning) 7%, transparent); }

.om-bar { display: inline-block; width: 90px; height: 7px; background: var(--surface-inset); border-radius: 999px; overflow: hidden; vertical-align: middle; margin-right: .5rem; }
.om-bar-fill { height: 100%; border-radius: 999px; transition: width .2s; }
.om-fill-ok { background: var(--success); }
.om-fill-warn { background: var(--warning); }
.om-fill-danger { background: var(--danger); }
.om-pct { font-size: .8rem; color: var(--text-muted); }

.om-badge { display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
.om-badge-ok { background: color-mix(in srgb, var(--success) 14%, transparent); color: var(--success); }
.om-badge-warn { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.om-badge-danger { background: color-mix(in srgb, var(--danger) 15%, transparent); color: var(--danger); }

.om-btn { display: inline-flex; align-items: center; gap: .35rem; padding: .4rem .8rem; font-size: .82rem; border-radius: var(--r-sm); border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; }
.om-btn:disabled { opacity: .55; cursor: not-allowed; }

.om-toggle { width: 32px; text-align: center; }
.om-exp { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 2px 4px; font-size: .9rem; }
.om-exp:hover { color: var(--ac); }
.om-rcpt-row td { background: var(--surface-2); }
.om-rcpt-title { font-size: .76rem; font-weight: 600; color: var(--text-muted); margin-bottom: .35rem; }
.om-rcpt-list { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: .4rem; }
.om-rcpt-list li { font-size: .8rem; }
.om-rcpt-list code { background: var(--surface-inset); padding: .1rem .4rem; border-radius: 4px; font-family: var(--font-mono, monospace); }
.om-rcpt-count { color: var(--danger); font-weight: 600; margin-left: .2rem; font-size: .78rem; }
</style>
