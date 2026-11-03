<template>
  <Modal :isOpen="isOpen" :title="`Importar en ${database?.db_name || ''}`" size="lg" @close="close">
    <div v-if="loading" class="text-center py-4"><div class="spinner-border"></div></div>
    <div v-else>
      <!-- Estado del import -->
      <div v-if="job.exists" class="imp-job mb-4">
        <template v-if="job.running">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <strong><span class="spinner-border spinner-border-sm me-2"></span>Importando {{ job.file }}</strong>
            <button class="btn btn-sm btn-outline-danger" @click="cancelImport" :disabled="busy">
              <i class="bi bi-stop-circle me-1"></i>Cancelar
            </button>
          </div>
          <div class="imp-bar"><div class="imp-bar__fill" :style="{ width: pct(job.progress) }"></div></div>
          <div class="small text-muted mt-1">
            {{ pct(job.progress) }} · lleva {{ duration(now - job.started) }}<span v-if="eta"> · quedan unos {{ eta }}</span>
          </div>
          <div class="small text-muted mt-2">
            Sigue en el servidor aunque cierres esta ventana o el navegador.
          </div>
        </template>
        <div v-else-if="job.state === 'done'" class="alert alert-success mb-0">
          <i class="bi bi-check-circle me-1"></i>
          <strong>{{ job.file }}</strong> importado en {{ duration(job.finished - job.started) }}.
          <span v-if="job.deleted">El fichero se ha borrado.</span>
          <pre v-if="job.warnings" class="imp-pre mt-2">{{ job.warnings }}</pre>
        </div>
        <div v-else-if="job.state === 'error'" class="alert alert-danger mb-0">
          <i class="bi bi-x-circle me-1"></i>
          La importación de <strong>{{ job.file }}</strong> ha fallado:
          <pre class="imp-pre mt-2">{{ job.error }}</pre>
        </div>
      </div>

      <div v-if="!hasPassword" class="alert alert-warning">
        <i class="bi bi-key me-1"></i>
        El panel no tiene guardada la contraseña de esta BD. Cámbiala con
        «Cambiar contraseña» para poder importar.
      </div>

      <!-- Subir desde el ordenador -->
      <h6 class="fw-semibold mb-2"><i class="bi bi-cloud-upload me-1"></i>Subir desde tu ordenador</h6>
      <p class="small text-muted mb-2">
        .sql, .sql.gz o .zip, sin límite de tamaño. Se envía por trozos: si se corta,
        vuelve a elegir el mismo fichero y sigue donde se quedó.
      </p>
      <div v-if="upload" class="mb-3">
        <div class="d-flex justify-content-between small mb-1">
          <span><code>{{ upload.name }}</code> · {{ bytes(upload.offset) }} de {{ bytes(upload.size) }}</span>
          <span>{{ upload.speed ? bytes(upload.speed) + '/s' : '' }}<span v-if="upload.retry"> · reintentando…</span></span>
        </div>
        <div class="imp-bar"><div class="imp-bar__fill" :style="{ width: pct(upload.offset / upload.size) }"></div></div>
        <div class="d-flex justify-content-between align-items-center mt-1">
          <span class="small text-muted">No cierres esta pestaña mientras sube.</span>
          <button class="btn btn-sm btn-outline-secondary" @click="upload.stop = true">Pausar</button>
        </div>
      </div>
      <input v-else type="file" class="form-control mb-3" accept=".sql,.gz,.zip"
             @change="onPick" :disabled="busy" />

      <!-- Ficheros en ~/imports -->
      <h6 class="fw-semibold mb-2"><i class="bi bi-folder2-open me-1"></i>Ficheros en la carpeta imports</h6>
      <p class="small text-muted mb-2">
        Para ficheros muy grandes es más rápido subirlos por SFTP a
        <code>{{ path }}</code>.
        <button class="btn btn-link btn-sm p-0 align-baseline" @click="refresh">Actualizar lista</button>
      </p>
      <div v-if="files.length === 0 && partial.length === 0" class="text-muted small mb-3">La carpeta está vacía.</div>
      <ul v-else class="list-group mb-3">
        <li v-for="f in files" :key="f.name" class="list-group-item d-flex align-items-center gap-2">
          <input class="form-check-input mt-0" type="radio" :value="f.name" v-model="selected" :id="`imp-${f.name}`" />
          <label class="flex-fill imp-name" :for="`imp-${f.name}`"><code>{{ f.name }}</code></label>
          <span class="small text-muted">{{ bytes(f.size) }} · {{ date(f.mtime) }}</span>
          <button class="btn btn-sm btn-outline-danger" title="Borrar" @click="remove(f.name)" :disabled="busy">
            <i class="bi bi-trash"></i>
          </button>
        </li>
        <li v-for="p in partial" :key="'p-' + p.name" class="list-group-item d-flex align-items-center gap-2">
          <i class="bi bi-hourglass-split text-warning"></i>
          <span class="flex-fill imp-name"><code>{{ p.name }}</code>
            <span class="small text-muted"> subida a medias ({{ bytes(p.received) }} de {{ bytes(p.size) }}): vuelve a elegirlo para seguir</span>
          </span>
          <button class="btn btn-sm btn-outline-danger" title="Descartar" @click="remove(p.name, p.size)" :disabled="busy || !!upload">
            <i class="bi bi-trash"></i>
          </button>
        </li>
      </ul>

      <!-- Opciones + lanzar -->
      <div class="form-check mb-1">
        <input class="form-check-input" type="checkbox" id="imp-force" v-model="force" />
        <label class="form-check-label small" for="imp-force">Continuar aunque alguna sentencia falle</label>
      </div>
      <div class="form-check mb-3">
        <input class="form-check-input" type="checkbox" id="imp-del" v-model="deleteAfter" />
        <label class="form-check-label small" for="imp-del">Borrar el fichero cuando termine bien</label>
      </div>
      <div class="alert alert-info small">
        <i class="bi bi-info-circle me-1"></i>
        Se importa sobre <strong>{{ database?.db_name }}</strong>: si el volcado trae
        <code>DROP TABLE</code> (lo normal), las tablas con el mismo nombre se sustituyen.
      </div>
      <button class="btn btn-primary" @click="startImport"
              :disabled="!selected || busy || job.running || !hasPassword || !!upload">
        <i class="bi bi-database-up me-1"></i>Importar {{ selected || '' }}
      </button>
    </div>
  </Modal>
</template>

<script>
import { ref, computed, watch, onUnmounted } from 'vue'
import Modal from './Modal.vue'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'

const CHUNK = 8 * 1024 * 1024

export default {
  name: 'DbImportModal',
  components: { Modal },
  props: {
    isOpen: { type: Boolean, required: true },
    database: { type: Object, default: null },
  },
  emits: ['close', 'imported'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const busy = ref(false)
    const files = ref([])
    const partial = ref([])
    const path = ref('')
    const job = ref({ exists: false })
    const hasPassword = ref(true)
    const selected = ref('')
    const force = ref(false)
    const deleteAfter = ref(false)
    const upload = ref(null)
    const now = ref(Date.now() / 1000)
    let timer = null
    let progSamples = []

    const base = () => `/api/databases/${props.database.id}/import`

    const refresh = async () => {
      const d = await api.get(base())
      files.value = d.files || []
      partial.value = d.partial || []
      path.value = d.path || ''
      hasPassword.value = d.has_password !== false
      const wasRunning = job.value.running
      job.value = d.job || { exists: false }
      if (wasRunning && !job.value.running && job.value.state === 'done') emit('imported')
      if (selected.value && !files.value.some(f => f.name === selected.value)) selected.value = ''
      if (!selected.value && files.value.length === 1) selected.value = files.value[0].name
    }

    const tick = async () => {
      now.value = Date.now() / 1000
      if (!job.value.running) return
      try {
        await refresh()
        progSamples.push([now.value, job.value.progress || 0])
        progSamples = progSamples.slice(-30)
      } catch { /* siguiente vuelta */ }
    }

    watch(() => props.isOpen, async (open) => {
      clearInterval(timer)
      if (!open) return
      loading.value = true
      progSamples = []
      try { await refresh() } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'error')
      } finally { loading.value = false }
      timer = setInterval(tick, 3000)
    })
    onUnmounted(() => clearInterval(timer))

    const eta = computed(() => {
      if (progSamples.length < 3) return ''
      const [t0, p0] = progSamples[0]
      const [t1, p1] = progSamples[progSamples.length - 1]
      if (p1 <= p0) return ''
      return duration((1 - p1) * (t1 - t0) / (p1 - p0))
    })

    // ── Subida por trozos ──
    const putChunk = async (name, size, offset, blob) => {
      const headers = { ...api.getHeaders(), 'Content-Type': 'application/octet-stream' }
      const q = `name=${encodeURIComponent(name)}&size=${size}&offset=${offset}`
      const r = await fetch(`${base()}/upload?${q}`, { method: 'PUT', headers, body: blob })
      let data = null
      try { data = await r.json() } catch { /* sin cuerpo */ }
      if (!r.ok) {
        const err = new Error(data?.detail || data?.message || `Error ${r.status}`)
        err.fatal = r.status >= 400 && r.status < 500 && ![408, 429].includes(r.status)
        throw err
      }
      return data
    }

    const onPick = async (ev) => {
      const file = ev.target.files?.[0]
      ev.target.value = ''
      if (!file) return
      const name = file.name.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^[._-]+/, '')
      const size = file.size
      try {
        const q = `name=${encodeURIComponent(name)}&size=${size}`
        const { offset } = await api.get(`${base()}/upload?${q}`)
        upload.value = { name, size, offset, speed: 0, retry: false, stop: false }
      } catch (e) {
        store.showNotification(e.message, 'error')
        return
      }
      const up = upload.value
      let t0 = Date.now(), sent0 = up.offset
      try {
        while (up.offset < size && !up.stop) {
          const blob = file.slice(up.offset, Math.min(up.offset + CHUNK, size))
          for (let attempt = 0; ; attempt++) {
            try {
              const r = await putChunk(name, size, up.offset, blob)
              up.offset = r.offset
              up.retry = false
              break
            } catch (e) {
              if (e.fatal || attempt >= 8) throw e
              up.retry = true
              await new Promise(res => setTimeout(res, Math.min(30000, 1000 * 2 ** attempt)))
            }
          }
          const dt = (Date.now() - t0) / 1000
          if (dt > 2) { up.speed = (up.offset - sent0) / dt; t0 = Date.now(); sent0 = up.offset }
        }
        if (up.offset >= size) {
          store.showNotification(`${name} subido`, 'success')
          selected.value = name
        }
      } catch (e) {
        store.showNotification(`Subida detenida: ${e.message}. Vuelve a elegir el fichero para seguir.`, 'error')
      } finally {
        upload.value = null
        await refresh().catch(() => {})
      }
    }

    const remove = async (name, size = null) => {
      if (!confirm(`¿Borrar ${name}${size !== null ? ' (subida a medias)' : ''}?`)) return
      busy.value = true
      try {
        const q = size !== null ? `?size=${size}` : ''
        await api.delete(`${base()}/files/${encodeURIComponent(name)}${q}`)
        await refresh()
      } catch (e) { store.showNotification(e.message, 'error') } finally { busy.value = false }
    }

    const startImport = async () => {
      if (!confirm(`¿Importar ${selected.value} en ${props.database.db_name}?`)) return
      busy.value = true
      try {
        job.value = await api.post(base(), {
          filename: selected.value, force: force.value, delete_after: deleteAfter.value,
        })
        progSamples = []
      } catch (e) { store.showNotification(e.message, 'error') } finally { busy.value = false }
    }

    const cancelImport = async () => {
      if (!confirm('¿Cancelar la importación? La BD quedará a medias.')) return
      busy.value = true
      try { job.value = await api.post(`${base()}/cancel`, {}) }
      catch (e) { store.showNotification(e.message, 'error') } finally { busy.value = false }
    }

    const close = () => {
      if (upload.value && !confirm('Hay una subida en curso. Si cierras se pausa (podrás seguirla luego). ¿Cerrar?')) return
      if (upload.value) upload.value.stop = true
      emit('close')
    }

    const bytes = (n) => {
      if (!n) return '0 B'
      const u = ['B', 'KB', 'MB', 'GB', 'TB']
      const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
      return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
    }
    const pct = (p) => `${Math.floor((p || 0) * 1000) / 10}%`
    function duration (s) {
      s = Math.max(0, Math.round(s || 0))
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
      return h ? `${h} h ${m} min` : m ? `${m} min` : `${s} s`
    }
    const date = (t) => new Date(t * 1000).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' })

    return {
      loading, busy, files, partial, path, job, hasPassword, selected, force, deleteAfter,
      upload, now, eta, refresh, onPick, remove, startImport, cancelImport, close,
      bytes, pct, duration, date,
    }
  },
}
</script>

<style scoped>
.imp-job { padding: var(--sp-4); border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--surface-2); }
.imp-bar { height: 8px; border-radius: 999px; background: var(--surface-inset); overflow: hidden; }
.imp-bar__fill { height: 100%; background: var(--color-primary); transition: width .4s var(--ease); }
.imp-pre { white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; font-size: var(--fs-xs); margin: 0; }
.imp-name { min-width: 0; overflow-wrap: anywhere; }
</style>
