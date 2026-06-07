<template>
  <div class="sv-view">
    <!-- Cabecera -->
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Logs del servidor</h1>
        <p class="page-head__sub">Consulta los registros más importantes del sistema con búsqueda.</p>
      </div>
    </div>

    <BaseCard title="Visor de logs" icon="card-text">
      <template #actions>
        <label class="lg-auto">
          <input type="checkbox" v-model="autoRefresh"> Auto
        </label>
        <BaseButton variant="ghost" size="sm" :loading="loading" @click="load">
          <i class="bi bi-arrow-repeat"></i> Actualizar
        </BaseButton>
      </template>

      <!-- Controles -->
      <div class="lg-controls">
        <select class="svq-input lg-select" v-model="selected" @change="onSelect">
          <optgroup v-for="(logs, group) in grouped" :key="group" :label="group">
            <option v-for="l in logs" :key="l.key" :value="l.key">{{ l.label }}</option>
          </optgroup>
        </select>

        <div class="lg-search">
          <i class="bi bi-search"></i>
          <input class="svq-input" v-model="search" placeholder="Buscar en el log…"
                 @keyup.enter="load" />
          <button v-if="search" class="lg-clear" @click="search=''; load()" title="Limpiar"><i class="bi bi-x"></i></button>
        </div>

        <select class="svq-input lg-lines" v-model.number="lines" @change="load" title="Líneas a mostrar">
          <option :value="100">100 líneas</option>
          <option :value="300">300 líneas</option>
          <option :value="1000">1000 líneas</option>
          <option :value="2000">2000 líneas</option>
        </select>
      </div>

      <!-- Salida -->
      <div class="lg-output-wrap">
        <div v-if="loading" class="lg-center"><div class="spinner-border spinner-border-sm"></div></div>
        <div v-else-if="error" class="lg-error"><i class="bi bi-exclamation-triangle"></i> {{ error }}</div>
        <EmptyState v-else-if="!rows.length" icon="card-text"
                    title="Sin líneas"
                    :description="search ? 'Ningún resultado para tu búsqueda.' : 'Este log está vacío.'" />
        <pre v-else ref="outputEl" class="lg-output"><code v-for="(r, i) in rows" :key="i"
          class="lg-line" :class="lineClass(r)" v-html="highlight(r)"></code></pre>
      </div>

      <div class="lg-foot">
        <span class="lg-muted">{{ rows.length }} líneas{{ search ? ' (filtradas)' : '' }}</span>
        <BaseButton variant="ghost" size="sm" @click="copyAll" :disabled="!rows.length">
          <i class="bi bi-clipboard"></i> Copiar
        </BaseButton>
      </div>
    </BaseCard>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import EmptyState from '../components/ui/EmptyState.vue'

export default {
  name: 'Logs',
  components: { BaseCard, BaseButton, EmptyState },
  setup() {
    const store = useMainStore()
    const catalog = ref([])
    const selected = ref('')
    const search = ref('')
    const lines = ref(300)
    const rows = ref([])
    const loading = ref(false)
    const error = ref('')
    const autoRefresh = ref(false)
    const outputEl = ref(null)
    let timer = null

    const grouped = computed(() => {
      const g = {}
      for (const l of catalog.value) {
        (g[l.group] = g[l.group] || []).push(l)
      }
      return g
    })

    const loadCatalog = async () => {
      try {
        const data = await api.getLogsCatalog()
        catalog.value = data.logs || []
        if (catalog.value.length && !selected.value) {
          // Por defecto, el primero (suele ser nginx error) o syslog
          const pref = catalog.value.find(l => l.key === 'syslog') || catalog.value[0]
          selected.value = pref.key
          await load()
        }
      } catch (e) {
        error.value = 'No se pudo cargar el catálogo de logs: ' + e.message
      }
    }

    const load = async () => {
      if (!selected.value) return
      loading.value = true
      error.value = ''
      try {
        const data = await api.readSystemLog(selected.value, {
          lines: lines.value, search: search.value,
        })
        rows.value = data.lines || []
        await nextTick()
        // Auto-scroll al final (lo más reciente)
        if (outputEl.value) outputEl.value.scrollTop = outputEl.value.scrollHeight
      } catch (e) {
        error.value = e.message || 'Error al leer el log'
        rows.value = []
      } finally {
        loading.value = false
      }
    }

    const onSelect = () => { search.value = ''; load() }

    // Resaltado del término de búsqueda + escape de HTML
    const esc = (s) => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
    const highlight = (line) => {
      let h = esc(line)
      if (search.value) {
        const re = new RegExp('(' + search.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi')
        h = h.replace(re, '<mark>$1</mark>')
      }
      return h
    }
    // Colorea por nivel detectado en la línea
    const lineClass = (line) => {
      const l = line.toLowerCase()
      if (/\b(error|fatal|crit|denied|failed|fail)\b/.test(l)) return 'lg-line--err'
      if (/\b(warn|warning)\b/.test(l)) return 'lg-line--warn'
      if (/\b(notice|info)\b/.test(l)) return 'lg-line--info'
      return ''
    }

    const copyAll = async () => {
      try {
        await navigator.clipboard.writeText(rows.value.join('\n'))
        store.showNotification('Log copiado al portapapeles', 'success')
      } catch { store.showNotification('No se pudo copiar', 'danger') }
    }

    // Auto-refresco cada 10s si está activado
    const tick = () => { if (autoRefresh.value && !loading.value) load() }

    onMounted(() => {
      loadCatalog()
      timer = setInterval(tick, 10000)
    })
    onUnmounted(() => { if (timer) clearInterval(timer) })

    return {
      catalog, grouped, selected, search, lines, rows, loading, error,
      autoRefresh, outputEl, load, onSelect, highlight, lineClass, copyAll,
    }
  },
}
</script>

<style scoped>
.page-head { margin-bottom: var(--sp-5); }
.page-head__title { font-size: 1.5rem; font-weight: var(--fw-bold, 700); margin: 0; }
.page-head__sub { color: var(--text-muted); margin: .25rem 0 0; font-size: var(--fs-sm); }

.lg-auto { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-sm); color: var(--text-secondary); cursor: pointer; }

.lg-controls { display: flex; gap: var(--sp-3); flex-wrap: wrap; margin-bottom: var(--sp-4); }
.lg-select { min-width: 240px; flex-shrink: 0; }
.lg-lines { width: auto; flex-shrink: 0; }
.lg-search { position: relative; flex: 1; min-width: 200px; display: flex; align-items: center; }
.lg-search > .bi { position: absolute; left: 10px; color: var(--text-muted); pointer-events: none; }
.lg-search .svq-input { width: 100%; padding-left: 32px; padding-right: 30px; box-sizing: border-box; }
.lg-clear { position: absolute; right: 6px; background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 2px; }
.lg-clear:hover { color: var(--text); }

.lg-output-wrap { border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; background: var(--svq-navy, #0f172a); }
.lg-center { display: flex; justify-content: center; padding: var(--sp-6); }
.lg-error { padding: var(--sp-4); color: var(--danger); display: flex; align-items: center; gap: .5rem; }
.lg-output { margin: 0; padding: var(--sp-3) var(--sp-4); max-height: 62vh; overflow: auto; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.55; color: #cdd6e4; }
.lg-line { display: block; white-space: pre-wrap; word-break: break-word; }
.lg-line--err  { color: #fca5a5; }
.lg-line--warn { color: #fcd34d; }
.lg-line--info { color: #93c5fd; }
.lg-output :deep(mark) { background: var(--svq-orange, #f08a2a); color: #1a1a1a; border-radius: 2px; padding: 0 1px; }

.lg-foot { display: flex; align-items: center; justify-content: space-between; margin-top: var(--sp-3); }
.lg-muted { color: var(--text-muted); font-size: var(--fs-sm); }
</style>
