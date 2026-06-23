<template>
  <div class="sv-view">
    <div class="pr-head">
      <div>
        <h2 class="pr-title"><i class="bi bi-cpu"></i> Procesos</h2>
        <p class="pr-subtitle">Procesos del sistema · ordenados por {{ sortBy === 'cpu' ? 'CPU' : 'memoria' }}</p>
      </div>
      <div class="pr-actions">
        <div class="pr-toggle">
          <button :class="{ on: sortBy === 'cpu' }" @click="setSort('cpu')">CPU</button>
          <button :class="{ on: sortBy === 'mem' }" @click="setSort('mem')">Memoria</button>
        </div>
        <input class="pr-filter" v-model="filter" placeholder="Filtrar (usuario, comando…)">
        <button class="pr-btn" :disabled="loading" @click="load"><i class="bi bi-arrow-clockwise"></i> Actualizar</button>
      </div>
    </div>

    <div v-if="loading && !rows.length" class="pr-loading"><span class="pr-spinner"></span></div>

    <div v-else class="pr-table-wrap">
      <table class="pr-table">
        <thead>
          <tr><th>PID</th><th>Usuario</th><th>CPU%</th><th>MEM%</th><th>RSS</th><th>Comando</th><th class="pr-ta-end">Acción</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in filtered" :key="p.pid">
            <td class="pr-mono">{{ p.pid }}</td>
            <td>{{ p.user }}</td>
            <td><span :class="cpuClass(p.cpu)">{{ p.cpu.toFixed(1) }}</span></td>
            <td>{{ p.mem.toFixed(1) }}</td>
            <td>{{ p.rss_mb }} MB</td>
            <td class="pr-cmd" :title="p.command">{{ p.command }}</td>
            <td class="pr-ta-end pr-nowrap">
              <span v-if="p.protected" class="pr-prot" title="Proceso crítico protegido"><i class="bi bi-shield-lock"></i></span>
              <template v-else>
                <button class="pr-btn pr-btn--icon" title="Terminar (SIGTERM)" @click="kill(p, false)"><i class="bi bi-x-circle"></i></button>
                <button class="pr-btn pr-btn--icon-danger" title="Forzar (SIGKILL)" @click="kill(p, true)"><i class="bi bi-exclamation-octagon"></i></button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const store = useMainStore()
const loading = ref(true)
const rows = ref([])
const sortBy = ref('cpu')
const filter = ref('')

const filtered = computed(() => {
  const f = filter.value.trim().toLowerCase()
  if (!f) return rows.value
  return rows.value.filter(p =>
    String(p.pid).includes(f) ||
    (p.user || '').toLowerCase().includes(f) ||
    (p.command || '').toLowerCase().includes(f)
  )
})

function cpuClass(c) { return c >= 50 ? 'pr-hot' : (c >= 15 ? 'pr-warm' : '') }

function setSort(s) { if (sortBy.value !== s) { sortBy.value = s; load() } }

async function load() {
  loading.value = true
  try {
    const r = await api.get(`/api/processes?sort_by=${sortBy.value}&limit=200`)
    rows.value = r.processes || []
  } catch (e) {
    store.showNotification('Error al cargar procesos: ' + (e.message || e), 'danger')
  } finally {
    loading.value = false
  }
}

async function kill(p, force) {
  const verb = force ? 'forzar el cierre de (SIGKILL)' : 'terminar (SIGTERM)'
  if (!confirm(`¿Seguro que quieres ${verb} el proceso ${p.pid} (${p.name})?`)) return
  try {
    await api.delete(`/api/processes/${p.pid}${force ? '?force=1' : ''}`)
    store.showNotification(`Proceso ${p.pid} terminado`, 'success')
    setTimeout(load, 400)
  } catch (e) {
    store.showNotification('Error: ' + (e.message || e), 'danger')
  }
}

onMounted(load)
</script>

<style scoped>
.pr-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
.pr-title { font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: .5rem; }
.pr-subtitle { color: var(--text-muted); font-size: .9rem; margin-top: .25rem; }
.pr-actions { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }

.pr-toggle { display: inline-flex; border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden; }
.pr-toggle button { padding: .4rem .8rem; font-size: .82rem; border: none; background: var(--surface-2); color: var(--text-secondary); cursor: pointer; }
.pr-toggle button.on { background: var(--ac); color: #fff; }

.pr-filter { padding: .4rem .6rem; font-size: .85rem; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface); color: var(--text); min-width: 200px; }
.pr-filter:focus { outline: none; border-color: var(--ac); }

.pr-loading { text-align: center; padding: 2rem; }
.pr-spinner { display: inline-block; width: 1.4rem; height: 1.4rem; border: 2px solid var(--border); border-top-color: var(--ac); border-radius: 50%; animation: pr-spin .6s linear infinite; }
@keyframes pr-spin { to { transform: rotate(360deg); } }

.pr-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--r-md); }
.pr-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.pr-table th, .pr-table td { padding: .5rem .7rem; text-align: left; border-bottom: 1px solid var(--border); }
.pr-table th { font-size: .73rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .02em; background: var(--surface-2); position: sticky; top: 0; }
.pr-table tr:last-child td { border-bottom: none; }
.pr-mono { font-family: var(--font-mono, monospace); }
.pr-cmd { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono, monospace); font-size: .78rem; color: var(--text-secondary); }
.pr-nowrap { white-space: nowrap; }
.pr-ta-end { text-align: right; }
.pr-hot { color: var(--danger); font-weight: 700; }
.pr-warm { color: var(--warning); font-weight: 600; }
.pr-prot { color: var(--text-muted); }

.pr-btn { display: inline-flex; align-items: center; gap: .35rem; padding: .4rem .8rem; font-size: .82rem; border-radius: var(--r-sm); border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; }
.pr-btn:disabled { opacity: .55; cursor: not-allowed; }
.pr-btn--icon, .pr-btn--icon-danger { padding: .35rem .5rem; }
.pr-btn--icon-danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }
</style>
