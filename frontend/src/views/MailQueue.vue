<template>
  <div class="sv-view">
    <div class="mq-head">
      <div>
        <h2 class="mq-title"><i class="bi bi-envelope-paper"></i> Cola de correo</h2>
        <p class="mq-subtitle">Mensajes de Postfix en cola de entrega · {{ count }} en cola</p>
      </div>
      <div class="mq-actions">
        <button class="mq-btn" :disabled="loading" @click="load">
          <i class="bi bi-arrow-clockwise"></i> Actualizar
        </button>
        <button class="mq-btn mq-btn--primary" :disabled="loading || !count" @click="flush">
          <i class="bi bi-send"></i> Reintentar todo
        </button>
        <button class="mq-btn mq-btn--danger" :disabled="loading || !count" @click="purge">
          <i class="bi bi-trash"></i> Vaciar cola
        </button>
      </div>
    </div>

    <div v-if="loading" class="mq-loading"><span class="mq-spinner"></span></div>

    <div v-else-if="!available" class="mq-empty">
      <i class="bi bi-envelope-slash"></i>
      <p>Postfix no está instalado en este servidor.</p>
    </div>

    <div v-else-if="!count" class="mq-empty">
      <i class="bi bi-check2-circle"></i>
      <p>La cola de correo está vacía.</p>
    </div>

    <div v-else class="mq-table-wrap">
      <table class="mq-table">
        <thead>
          <tr>
            <th>ID</th><th>Cola</th><th>Remitente</th><th>Destinatario(s)</th>
            <th>Tamaño</th><th>Motivo</th><th class="mq-ta-end">Acciones</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in messages" :key="m.id">
            <td class="mq-mono">{{ m.id }}</td>
            <td><span class="mq-chip" :class="queueClass(m.queue)">{{ m.queue || '—' }}</span></td>
            <td class="mq-ell" :title="m.sender">{{ m.sender || '—' }}</td>
            <td class="mq-ell" :title="(m.recipients||[]).join(', ')">{{ (m.recipients||[]).join(', ') || '—' }}</td>
            <td>{{ fmtSize(m.size) }}</td>
            <td class="mq-ell mq-muted" :title="m.reason">{{ m.reason || '—' }}</td>
            <td class="mq-ta-end mq-nowrap">
              <button class="mq-btn mq-btn--icon" title="Ver" @click="view(m.id)"><i class="bi bi-eye"></i></button>
              <button class="mq-btn mq-btn--icon" title="Reintentar" @click="requeue(m.id)"><i class="bi bi-arrow-repeat"></i></button>
              <button class="mq-btn mq-btn--icon-danger" title="Borrar" @click="del(m.id)"><i class="bi bi-trash"></i></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Modal ver contenido -->
    <div v-if="viewing" class="mq-modal" @click.self="viewing = null">
      <div class="mq-modal-box">
        <div class="mq-modal-head">
          <strong>Mensaje {{ viewing.id }}</strong>
          <button class="mq-btn mq-btn--icon" @click="viewing = null"><i class="bi bi-x-lg"></i></button>
        </div>
        <pre class="mq-pre">{{ viewing.content }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const store = useMainStore()
const loading = ref(true)
const available = ref(true)
const messages = ref([])
const viewing = ref(null)

const count = computed(() => messages.value.length)

function fmtSize(b) {
  if (!b) return '—'
  if (b < 1024) return b + ' B'
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1048576).toFixed(1) + ' MB'
}
function queueClass(q) {
  if (q === 'deferred') return 'mq-chip--warn'
  if (q === 'hold') return 'mq-chip--danger'
  if (q === 'active') return 'mq-chip--blue'
  return ''
}

async function load() {
  loading.value = true
  try {
    const r = await api.get('/api/mail-queue')
    available.value = r.available !== false
    messages.value = r.messages || []
  } catch (e) {
    store.showNotification('Error al cargar la cola: ' + (e.message || e), 'danger')
  } finally {
    loading.value = false
  }
}

async function flush() {
  try {
    const r = await api.post('/api/mail-queue/flush', {})
    store.showNotification(r.message || 'Cola reencolada', 'success')
    await load()
  } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
}

async function purge() {
  if (!confirm('¿Vaciar TODA la cola de correo? Se borrarán todos los mensajes en cola.')) return
  try {
    const r = await api.delete('/api/mail-queue/ALL')
    store.showNotification(r.message || 'Cola vaciada', 'success')
    await load()
  } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
}

async function requeue(id) {
  try {
    await api.post(`/api/mail-queue/${id}/requeue`, {})
    store.showNotification('Mensaje re-encolado', 'success')
    await load()
  } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
}

async function del(id) {
  if (!confirm(`¿Borrar el mensaje ${id} de la cola?`)) return
  try {
    await api.delete(`/api/mail-queue/${id}`)
    store.showNotification('Mensaje borrado', 'success')
    await load()
  } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
}

async function view(id) {
  try {
    const r = await api.get(`/api/mail-queue/${id}`)
    viewing.value = { id, content: r.content }
  } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
}

onMounted(load)
</script>

<style scoped>
.mq-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
.mq-title { font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: .5rem; }
.mq-subtitle { color: var(--text-muted); font-size: .9rem; margin-top: .25rem; }
.mq-actions { display: flex; gap: .5rem; flex-wrap: wrap; }

.mq-loading { text-align: center; padding: 2rem; }
.mq-spinner { display: inline-block; width: 1.4rem; height: 1.4rem; border: 2px solid var(--border); border-top-color: var(--ac); border-radius: 50%; animation: mq-spin .6s linear infinite; }
@keyframes mq-spin { to { transform: rotate(360deg); } }

.mq-empty { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.mq-empty i { font-size: 2.5rem; display: block; margin-bottom: .5rem; }

.mq-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--r-md); }
.mq-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.mq-table th, .mq-table td { padding: .55rem .7rem; text-align: left; border-bottom: 1px solid var(--border); }
.mq-table th { font-size: .73rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .02em; background: var(--surface-2); }
.mq-table tr:last-child td { border-bottom: none; }
.mq-mono { font-family: var(--font-mono, monospace); font-size: .8rem; }
.mq-muted { color: var(--text-muted); }
.mq-ell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mq-nowrap { white-space: nowrap; }
.mq-ta-end { text-align: right; }

.mq-chip { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .72rem; font-weight: 600; background: var(--surface-inset); color: var(--text-secondary); }
.mq-chip--warn { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.mq-chip--danger { background: color-mix(in srgb, var(--danger) 15%, transparent); color: var(--danger); }
.mq-chip--blue { background: color-mix(in srgb, var(--info) 15%, transparent); color: var(--info); }

.mq-btn { display: inline-flex; align-items: center; gap: .35rem; padding: .4rem .8rem; font-size: .82rem; font-weight: 500; border-radius: var(--r-sm); border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; }
.mq-btn:disabled { opacity: .55; cursor: not-allowed; }
.mq-btn--primary { background: var(--ac); border-color: var(--ac); color: #fff; }
.mq-btn--danger { background: var(--danger); border-color: var(--danger); color: #fff; }
.mq-btn--icon, .mq-btn--icon-danger { padding: .35rem .5rem; }
.mq-btn--icon-danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }

.mq-modal { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 1rem; }
.mq-modal-box { background: var(--surface); border-radius: var(--r-md); max-width: 800px; width: 100%; max-height: 80vh; display: flex; flex-direction: column; }
.mq-modal-head { display: flex; justify-content: space-between; align-items: center; padding: .85rem 1rem; border-bottom: 1px solid var(--border); }
.mq-pre { margin: 0; padding: 1rem; overflow: auto; font-family: var(--font-mono, monospace); font-size: .78rem; white-space: pre-wrap; word-break: break-word; }
</style>
