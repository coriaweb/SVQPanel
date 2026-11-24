<template>
  <BaseCard title="Laravel" icon="box-seam">
    <template #actions>
      <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="loading" @click="loadInfo">Refrescar</BaseButton>
    </template>

    <div v-if="errorMsg && !info" class="lv-error"><i class="bi bi-exclamation-triangle"></i> {{ errorMsg }}</div>
    <div v-else-if="!info" class="lv-loading"><span class="spinner"></span> Analizando el proyecto…</div>

    <template v-else>
      <div class="lv-summary">
        <div class="lv-stat"><span class="lv-stat__k">Laravel</span><span class="lv-stat__v mono">{{ info.version || '—' }}</span></div>
        <div class="lv-stat"><span class="lv-stat__k">Entorno</span><span class="lv-stat__v mono">{{ info.env.APP_ENV || '—' }}</span></div>
        <div class="lv-stat"><span class="lv-stat__k">Debug</span>
          <span class="lv-stat__v" :class="{ 'lv-bad': isDebug }">{{ isDebug ? 'Activado' : 'Desactivado' }}</span></div>
        <div class="lv-stat"><span class="lv-stat__k">Estado</span>
          <span class="lv-stat__v" :class="{ 'lv-warnc': info.down }">{{ info.down ? 'Mantenimiento' : 'En línea' }}</span></div>
        <div class="lv-stat"><span class="lv-stat__k">Caché de config</span><span class="lv-stat__v">{{ info.config_cached ? 'Sí' : 'No' }}</span></div>
      </div>
      <div class="lv-path dd-muted">
        <i class="bi bi-terminal"></i> Proyecto en <code class="mono">{{ info.root }}</code> · {{ info.php }}
        <template v-if="info.php_required"> · composer.json pide PHP <code>{{ info.php_required }}</code></template>
      </div>

      <BaseTabs v-model="tab" :tabs="tabs" />

      <!-- ── Estado ── -->
      <div v-if="tab === 'status'" class="lv-pane">
        <div class="lv-section-title">Diagnóstico</div>
        <div v-if="!info.checks.length" class="lv-ok"><i class="bi bi-check-circle-fill"></i> Todo correcto: no se ha encontrado ningún problema.</div>
        <div v-for="c in info.checks" :key="c.id" class="lv-check" :class="'lv-check--' + c.level">
          <i class="bi" :class="levelIcon(c.level)"></i>
          <div class="lv-check__body">
            <div class="lv-check__title">{{ c.title }}</div>
            <div class="lv-check__detail">{{ c.detail }}</div>
          </div>
          <BaseButton v-if="c.fix" :variant="c.level === 'critical' ? 'primary' : 'subtle'" size="sm"
                      :loading="busy === 'fix:' + c.id" :disabled="!!busy" @click="fix(c)">{{ c.fix_label || 'Arreglar' }}</BaseButton>
        </div>

        <div class="lv-section-title">Acciones</div>
        <div class="lv-quick">
          <button class="lv-qbtn" :disabled="!!busy" @click="action('optimize')" title="Cachea config, rutas, vistas y eventos (más rápido en producción)">
            <i class="bi bi-lightning-charge"></i> Optimizar</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="action('optimize-clear')" title="Borra todas las cachés de Laravel (tras cambiar código o .env)">
            <i class="bi bi-eraser"></i> Limpiar cachés</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="action('cache-clear')" title="Vacía la caché de la aplicación (Cache::)">
            <i class="bi bi-trash"></i> Vaciar caché de datos</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="action('migrate-status')"><i class="bi bi-list-check"></i> Estado de migraciones</button>
          <button class="lv-qbtn lv-qbtn--warn" :disabled="!!busy" @click="confirmMigrate"><i class="bi bi-database-up"></i> Ejecutar migraciones</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="action('storage-link')"><i class="bi bi-link-45deg"></i> storage:link</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="toggleDown">
            <i class="bi bi-cone-striped"></i> {{ info.down ? 'Quitar mantenimiento' : 'Modo mantenimiento' }}</button>
          <button class="lv-qbtn" :disabled="!!busy" @click="action('queue-restart')" title="Pide a los workers de la cola que se reinicien para cargar el código nuevo">
            <i class="bi bi-arrow-repeat"></i> Reiniciar colas</button>
        </div>
        <div v-if="bypassUrl" class="lv-bypass">
          <i class="bi bi-key"></i>
          <div>Web en mantenimiento. Para seguir viéndola tú, abre este enlace (deja una cookie en tu navegador):<br>
            <a :href="bypassUrl" target="_blank" rel="noopener" class="mono">{{ bypassUrl }}</a></div>
        </div>

        <div class="lv-section-title">Tareas programadas</div>
        <div class="lv-cron">
          <div class="lv-cron__row">
            <div>
              <div class="lv-cron__title">Planificador (<code>schedule:run</code> cada minuto)</div>
              <div class="dd-muted lv-cron__desc">
                Ejecuta las tareas que definas con <code>Schedule</code>.
                <template v-if="info.uses_scheduler">Tu proyecto define tareas.</template>
                <template v-else>Tu proyecto no parece definir ninguna.</template>
                <template v-if="info.crons.scheduler.manual_ids.length"> Ya tienes un cron puesto a mano con schedule:run (pestaña Cron).</template>
              </div>
            </div>
            <BaseButton :variant="info.crons.scheduler.enabled ? 'danger' : 'subtle'" size="sm" :loading="busy === 'cron:scheduler'"
                        :disabled="!!busy" @click="toggleCron('scheduler')">{{ info.crons.scheduler.enabled ? 'Desactivar' : 'Activar' }}</BaseButton>
          </div>
          <div class="lv-cron__row">
            <div>
              <div class="lv-cron__title">Cola (<code>queue:work --stop-when-empty</code> cada minuto)</div>
              <div class="dd-muted lv-cron__desc">
                Procesa los trabajos en cola (correos, notificaciones…) si usas
                <code>QUEUE_CONNECTION={{ info.env.QUEUE_CONNECTION || 'database' }}</code>. Pueden tardar hasta un minuto en salir.
                <template v-if="info.crons.queue.manual_ids.length"> Ya tienes un cron puesto a mano con queue:work.</template>
              </div>
            </div>
            <BaseButton :variant="info.crons.queue.enabled ? 'danger' : 'subtle'" size="sm" :loading="busy === 'cron:queue'"
                        :disabled="!!busy" @click="toggleCron('queue')">{{ info.crons.queue.enabled ? 'Desactivar' : 'Activar' }}</BaseButton>
          </div>
        </div>
      </div>

      <!-- ── Consola artisan ── -->
      <div v-else-if="tab === 'console'" class="lv-pane">
        <p class="dd-muted lv-intro">
          Ejecuta comandos <code>php artisan</code> en tu proyecto, como tu usuario y con el PHP del dominio.
          No admite comandos que se quedan abiertos (tinker, serve, queue:work…): para esos usa la terminal.
        </p>
        <div class="lv-cli-bar">
          <select class="svq-input" style="max-width:18rem" v-model="quickSel" @change="applyQuick">
            <option value="">Comandos frecuentes…</option>
            <option v-for="q in quickCmds" :key="q" :value="q">{{ q }}</option>
          </select>
        </div>
        <div class="lv-cli-inputrow">
          <span class="lv-cli-prompt mono">php artisan</span>
          <input class="svq-input mono" v-model="cliInput" :disabled="cliRunning" placeholder="route:list"
                 @keyup.enter="runCli" @keyup.up="histPrev" @keyup.down="histNext" />
          <BaseButton variant="primary" size="sm" icon="play-fill" :loading="cliRunning" @click="runCli">Ejecutar</BaseButton>
        </div>
        <div v-if="cliLog.length" class="lv-cli-out mono">
          <div v-for="(e, i) in cliLog" :key="i" class="lv-cli-entry">
            <div class="lv-cli-cmd">$ {{ e.command }} <span :class="e.rc === 0 ? 'lv-okc' : 'lv-bad'">[{{ e.rc }}]</span></div>
            <pre>{{ e.stdout }}</pre>
            <pre v-if="e.stderr" class="lv-bad">{{ e.stderr }}</pre>
          </div>
        </div>
        <div v-if="history.length" class="lv-hist">
          <div class="lv-section-title">Historial</div>
          <div v-for="(h, i) in history" :key="i" class="lv-hist__row" @click="cliInput = (h.command || '').replace(/^php artisan /, '')">
            <span class="mono">{{ h.command }}</span>
            <span :class="h.rc === 0 ? 'lv-okc' : 'lv-bad'">{{ h.rc }}</span>
          </div>
        </div>
      </div>

      <!-- ── .env ── -->
      <div v-else-if="tab === 'env'" class="lv-pane">
        <p class="dd-muted lv-intro">
          Configuración de tu aplicación (base de datos, correo, claves…). Se valida antes de guardar:
          una línea mal escrita dejaría la web en error 500. Se guarda una copia en <code>.env.svqpanel.bak</code>
          <template v-if="info.config_cached"> y se vuelve a cachear la configuración para que el cambio se aplique</template>.
        </p>
        <div v-if="envLoading" class="lv-loading"><span class="spinner"></span> Cargando…</div>
        <template v-else>
          <div v-if="!envRevealed" class="lv-env-hidden">
            <i class="bi bi-eye-slash"></i>
            <div>El .env contiene contraseñas y claves. Se oculta para que no queden a la vista en pantalla.</div>
            <BaseButton variant="subtle" size="sm" icon="eye" @click="envRevealed = true">Mostrar y editar</BaseButton>
          </div>
          <template v-else>
            <textarea class="svq-input mono lv-env" v-model="envText" spellcheck="false" rows="22"></textarea>
            <div class="lv-actions">
              <BaseButton variant="primary" size="sm" icon="save" :loading="busy === 'env'" :disabled="!!busy || envText === envOrig" @click="saveEnv">Guardar .env</BaseButton>
              <BaseButton variant="ghost" size="sm" :disabled="!!busy || envText === envOrig" @click="envText = envOrig">Descartar cambios</BaseButton>
              <BaseButton variant="ghost" size="sm" icon="eye-slash" @click="envRevealed = false">Ocultar</BaseButton>
            </div>
          </template>
        </template>
      </div>

      <!-- ── Logs ── -->
      <div v-else-if="tab === 'logs'" class="lv-pane">
        <div v-if="logLoading && !logData" class="lv-loading"><span class="spinner"></span> Cargando…</div>
        <p v-else-if="!logFiles.length" class="dd-muted">No hay logs en <code>storage/logs</code>.</p>
        <template v-else>
          <div class="lv-logbar">
            <select class="svq-input" style="max-width:20rem" v-model="logFile" @change="loadLogs">
              <option v-for="f in logFiles" :key="f.name" :value="f.name">{{ f.name }} ({{ fmtSize(f.size) }})</option>
            </select>
            <select class="svq-input" style="max-width:9rem" v-model.number="logLines" @change="loadLogs">
              <option :value="100">100 líneas</option><option :value="300">300 líneas</option>
              <option :value="1000">1000 líneas</option><option :value="3000">3000 líneas</option>
            </select>
            <label class="lv-onlyerr"><input type="checkbox" v-model="onlyErrors" /> Solo errores</label>
            <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="logLoading" @click="loadLogs">Recargar</BaseButton>
            <BaseButton variant="ghost" size="sm" icon="trash" :disabled="!!busy" @click="clearLog">Vaciar</BaseButton>
          </div>
          <div v-if="logData" class="dd-muted lv-logmeta">{{ logData.errors }} error(es) en las últimas {{ logData.lines }} líneas</div>
          <pre class="lv-log mono"><template v-for="(l, i) in logView" :key="i"><span :class="lineClass(l)">{{ l }}
</span></template></pre>
        </template>
      </div>

      <div v-if="lastOutput" class="lv-output">
        <div class="lv-output__head">
          <span><i class="bi bi-terminal"></i> Salida del último comando</span>
          <button class="lv-output__clear" @click="lastOutput = ''" title="Ocultar"><i class="bi bi-x-lg"></i></button>
        </div>
        <pre class="lv-output__body mono">{{ lastOutput }}</pre>
      </div>
    </template>
  </BaseCard>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseTabs from './ui/BaseTabs.vue'

export default {
  name: 'LaravelManager',
  components: { BaseCard, BaseButton, BaseTabs },
  props: {
    domainId:   { type: [Number, String], default: null },
    domainName: { type: String, default: '' },
  },
  emits: ['changed'],
  setup(props, { emit }) {
    const store = useMainStore()
    const route = useRoute()
    // DomainDetail no expone domainId a su template (llega undefined → NaN):
    // igual que WpManager/ComposerManager, se cae al id de la ruta.
    const did = computed(() => {
      const n = parseInt(props.domainId, 10)
      return Number.isInteger(n) ? n : parseInt(route.params.id, 10)
    })

    const tab = ref('status')
    const tabs = [
      { key: 'status',  label: 'Estado',  icon: 'clipboard-check' },
      { key: 'console', label: 'Consola artisan', icon: 'terminal' },
      { key: 'env',     label: '.env',    icon: 'file-earmark-lock' },
      { key: 'logs',    label: 'Logs',    icon: 'journal-text' },
    ]

    const info = ref(null)
    const loading = ref(false)
    const errorMsg = ref('')
    const busy = ref('')
    const lastOutput = ref('')
    const bypassUrl = ref('')

    const isDebug = computed(() => ['true', '1', '(true)'].includes(String(info.value?.env?.APP_DEBUG || '').toLowerCase()))

    const loadInfo = async () => {
      loading.value = true; errorMsg.value = ''
      try { const r = await api.getLaravelInfo(did.value); info.value = r.data }
      catch (e) { errorMsg.value = e.message || 'No se pudo analizar el proyecto' }
      finally { loading.value = false }
    }

    const levelIcon = (l) => ({ critical: 'bi-x-octagon-fill', warning: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill' }[l] || 'bi-info-circle')

    const done = async (r, okMsg) => {
      lastOutput.value = r.data?.output || okMsg
      store.showNotification(okMsg, 'success')
      await loadInfo()
    }
    const failed = (e) => {
      lastOutput.value = e.message || 'Error'
      store.showNotification('Error: ' + (e.message || 'falló el comando').split('\n')[0], 'danger')
    }

    const fix = async (c) => {
      if (c.id === 'template' && !confirm('Se aplicará la plantilla Laravel: la web servirá la carpeta /public del proyecto. ¿Continuar?')) return
      busy.value = 'fix:' + c.id
      try {
        const r = await api.laravelFix(did.value, c.id)
        await done(r, 'Arreglado: ' + c.title)
        if (c.id === 'template') emit('changed')
      } catch (e) { failed(e) } finally { busy.value = '' }
    }

    const action = async (a) => {
      busy.value = 'act:' + a
      try {
        const r = await api.laravelAction(did.value, a)
        if (a === 'down') bypassUrl.value = r.data?.bypass_url || ''
        if (a === 'up') bypassUrl.value = ''
        await done(r, 'artisan: hecho')
      } catch (e) { failed(e) } finally { busy.value = '' }
    }
    const confirmMigrate = () => {
      if (!confirm('Se ejecutarán las migraciones pendientes sobre la base de datos de PRODUCCIÓN (migrate --force). Haz una copia antes si no estás seguro. ¿Continuar?')) return
      action('migrate')
    }
    const toggleDown = () => {
      if (info.value.down) return action('up')
      if (!confirm('Los visitantes verán «Servicio no disponible» (503) hasta que lo quites. ¿Activar el modo mantenimiento?')) return
      action('down')
    }

    const toggleCron = async (kind) => {
      const enable = !info.value.crons[kind].enabled
      busy.value = 'cron:' + kind
      try {
        const r = await api.laravelCron(did.value, kind, enable)
        await done(r, r.data?.output || 'Hecho')
      } catch (e) { failed(e) } finally { busy.value = '' }
    }

    // ── Consola ──
    const quickCmds = ['about', 'route:list', 'migrate:status', 'config:show app', 'schedule:list',
                       'queue:failed', 'queue:retry all', 'view:clear', 'route:clear', 'config:clear',
                       'event:list', 'db:show', 'model:show User']
    const quickSel = ref('')
    const applyQuick = () => { if (quickSel.value) cliInput.value = quickSel.value; quickSel.value = '' }
    const cliInput = ref('')
    const cliRunning = ref(false)
    const cliLog = ref([])
    const history = ref([])
    let histIdx = -1
    const loadHistory = async () => {
      try { const r = await api.laravelArtisanHistory(did.value); history.value = r.data || [] } catch (e) { /* opcional */ }
    }
    const runCli = async () => {
      const cmd = cliInput.value.trim()
      if (!cmd || cliRunning.value) return
      cliRunning.value = true
      try {
        const r = await api.laravelArtisan(did.value, cmd)
        cliLog.value.unshift(r.data)
        cliLog.value = cliLog.value.slice(0, 20)
        cliInput.value = ''; histIdx = -1
        loadHistory()
      } catch (e) {
        cliLog.value.unshift({ command: 'php artisan ' + cmd, rc: '!', stdout: '', stderr: e.message || 'Error' })
      } finally { cliRunning.value = false }
    }
    const histPrev = () => {
      if (!history.value.length) return
      histIdx = Math.min(histIdx + 1, history.value.length - 1)
      cliInput.value = (history.value[histIdx].command || '').replace(/^php artisan /, '')
    }
    const histNext = () => {
      if (histIdx <= 0) { histIdx = -1; cliInput.value = ''; return }
      histIdx -= 1
      cliInput.value = (history.value[histIdx].command || '').replace(/^php artisan /, '')
    }

    // ── .env ──
    const envText = ref('')
    const envOrig = ref('')
    const envLoading = ref(false)
    const envRevealed = ref(false)
    const loadEnv = async () => {
      envLoading.value = true
      try { const r = await api.getLaravelEnv(did.value); envText.value = envOrig.value = r.data?.content || '' }
      catch (e) { failed(e) } finally { envLoading.value = false }
    }
    const saveEnv = async () => {
      busy.value = 'env'
      try {
        const r = await api.saveLaravelEnv(did.value, envText.value)
        envOrig.value = envText.value
        await done(r, '.env guardado')
      } catch (e) { failed(e) } finally { busy.value = '' }
    }

    // ── Logs ──
    const logFiles = ref([])
    const logFile = ref('')
    const logLines = ref(300)
    const logData = ref(null)
    const logLoading = ref(false)
    const onlyErrors = ref(false)
    const loadLogs = async () => {
      logLoading.value = true
      try {
        const r = await api.getLaravelLogs(did.value, logFile.value, logLines.value)
        logFiles.value = r.data?.files || []
        logData.value = r.data?.log || null
        if (logData.value) logFile.value = logData.value.name
      } catch (e) { failed(e) } finally { logLoading.value = false }
    }
    const errRe = /^\[\d{4}-\d\d-\d\d[^\]]*\]\s+\w+\.(ERROR|CRITICAL|ALERT|EMERGENCY):/
    const logView = computed(() => {
      const lines = (logData.value?.content || '').split('\n')
      if (!onlyErrors.value) return lines
      return lines.filter(l => errRe.test(l))
    })
    const lineClass = (l) => errRe.test(l) ? 'lv-bad' : (/^\[\d{4}-\d\d-\d\d[^\]]*\]\s+\w+\.WARNING:/.test(l) ? 'lv-warnc' : '')
    const clearLog = async () => {
      if (!confirm(`¿Vaciar ${logFile.value}? Se pierde su contenido.`)) return
      busy.value = 'logclear'
      try { await api.clearLaravelLog(did.value, logFile.value); store.showNotification('Log vaciado', 'success'); await loadLogs() }
      catch (e) { failed(e) } finally { busy.value = '' }
    }
    const fmtSize = (b) => b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : b >= 1024 ? Math.round(b / 1024) + ' KB' : b + ' B'

    watch(tab, (t) => {
      if (t === 'console' && !history.value.length) loadHistory()
      if (t === 'env' && !envOrig.value && !envLoading.value) loadEnv()
      if (t === 'logs') loadLogs()
    })
    onMounted(loadInfo)

    return {
      tab, tabs, info, loading, errorMsg, busy, lastOutput, bypassUrl, isDebug,
      loadInfo, levelIcon, fix, action, confirmMigrate, toggleDown, toggleCron,
      quickCmds, quickSel, applyQuick, cliInput, cliRunning, cliLog, history, runCli, histPrev, histNext,
      envText, envOrig, envLoading, envRevealed, saveEnv,
      logFiles, logFile, logLines, logData, logLoading, onlyErrors, loadLogs, logView, lineClass, clearLog, fmtSize,
    }
  },
}
</script>

<style scoped>
.lv-loading, .lv-error { display:flex; align-items:center; gap:.5rem; padding:.75rem 0; color: var(--text-muted); }
.lv-error { color: var(--danger); }
.lv-summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap:.5rem; margin-bottom:.6rem; }
.lv-stat { background: var(--surface-inset); border:1px solid var(--border); border-radius: var(--radius-md); padding:.5rem .75rem; }
.lv-stat__k { display:block; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color: var(--text-muted); }
.lv-stat__v { font-weight:600; }
.lv-path { font-size:.82rem; margin-bottom:.75rem; word-break:break-all; }
code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.8rem; }
.lv-pane { padding-top:1rem; }
.lv-intro { font-size:.86rem; line-height:1.5; margin:0 0 .75rem; }
.lv-section-title { font-weight:600; font-size:.9rem; margin:1.1rem 0 .5rem; }
.lv-pane > .lv-section-title:first-child { margin-top:0; }
.lv-ok { display:flex; gap:.5rem; align-items:center; color: var(--success, #16a34a); font-size:.88rem; }
.lv-check { display:flex; gap:.65rem; align-items:flex-start; padding:.6rem .75rem; margin-bottom:.45rem; border-radius: var(--radius-md); border:1px solid var(--border); }
.lv-check > i { margin-top:.15rem; }
.lv-check__body { flex:1; min-width:0; }
.lv-check__title { font-weight:600; font-size:.88rem; }
.lv-check__detail { font-size:.82rem; color: var(--text-muted); line-height:1.45; margin-top:.1rem; }
.lv-check--critical { border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); background: color-mix(in srgb, var(--danger) 7%, transparent); }
.lv-check--critical > i { color: var(--danger); }
.lv-check--warning { border-color: color-mix(in srgb, var(--warning, #d97706) 40%, var(--border)); background: color-mix(in srgb, var(--warning, #d97706) 8%, transparent); }
.lv-check--warning > i { color: var(--warning, #d97706); }
.lv-check--info > i { color: var(--color-primary); }
.lv-quick { display:flex; flex-wrap:wrap; gap:.45rem; }
.lv-qbtn { display:inline-flex; align-items:center; gap:.4rem; background: var(--surface); border:1px solid var(--border); border-radius: var(--radius-md); padding:.4rem .7rem; font-size:.84rem; color: var(--text); cursor:pointer; }
.lv-qbtn:hover:not(:disabled) { background: var(--surface-inset); }
.lv-qbtn:disabled { opacity:.6; cursor:not-allowed; }
.lv-qbtn--warn { border-color: color-mix(in srgb, var(--warning, #d97706) 45%, var(--border)); }
.lv-bypass { display:flex; gap:.5rem; margin-top:.6rem; font-size:.84rem; padding:.6rem .75rem; border-radius: var(--radius-md); background: var(--surface-inset); word-break:break-all; }
.lv-cron { display:flex; flex-direction:column; gap:.5rem; }
.lv-cron__row { display:flex; gap:1rem; align-items:center; justify-content:space-between; padding:.6rem .75rem; border:1px solid var(--border); border-radius: var(--radius-md); }
.lv-cron__title { font-weight:600; font-size:.88rem; }
.lv-cron__desc { font-size:.8rem; line-height:1.45; margin-top:.15rem; }
.lv-cli-bar { margin-bottom:.5rem; }
.lv-cli-inputrow { display:flex; gap:.5rem; align-items:center; }
.lv-cli-inputrow .svq-input { flex:1; }
.lv-cli-prompt { color: var(--text-muted); font-size:.85rem; white-space:nowrap; }
.lv-cli-out { margin-top:.75rem; border:1px solid var(--border); border-radius: var(--radius-md); max-height:460px; overflow:auto; background: var(--surface-inset); padding:.5rem .75rem; font-size:.8rem; }
.lv-cli-entry + .lv-cli-entry { border-top:1px dashed var(--border); margin-top:.5rem; padding-top:.5rem; }
.lv-cli-cmd { font-weight:600; }
.lv-cli-out pre { margin:.25rem 0 0; white-space:pre-wrap; word-break:break-word; }
.lv-hist__row { display:flex; justify-content:space-between; gap:1rem; padding:.3rem .5rem; font-size:.8rem; cursor:pointer; border-radius: var(--radius-sm); }
.lv-hist__row:hover { background: var(--surface-inset); }
.lv-env { width:100%; font-size:.8rem; line-height:1.45; resize:vertical; }
.lv-env-hidden { display:flex; gap:.75rem; align-items:center; padding:.9rem; border:1px dashed var(--border); border-radius: var(--radius-md); font-size:.86rem; }
.lv-env-hidden > div { flex:1; }
.lv-actions { display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.6rem; }
.lv-logbar { display:flex; gap:.5rem; flex-wrap:wrap; align-items:center; margin-bottom:.5rem; }
.lv-onlyerr { display:inline-flex; gap:.3rem; align-items:center; font-size:.84rem; }
.lv-logmeta { font-size:.8rem; margin-bottom:.4rem; }
.lv-log { margin:0; max-height:520px; overflow:auto; font-size:.76rem; line-height:1.4; background: var(--surface-inset); border:1px solid var(--border); border-radius: var(--radius-md); padding:.6rem .75rem; white-space:pre-wrap; word-break:break-word; }
.lv-bad { color: var(--danger); }
.lv-warnc { color: var(--warning, #d97706); }
.lv-okc { color: var(--success, #16a34a); }
.lv-output { margin-top:1rem; border:1px solid var(--border); border-radius: var(--radius-md); overflow:hidden; }
.lv-output__head { display:flex; align-items:center; justify-content:space-between; padding:.45rem .75rem; background: var(--surface-inset); font-size:.82rem; }
.lv-output__clear { background:none; border:none; color: var(--text-muted); cursor:pointer; }
.lv-output__body { margin:0; padding:.75rem; max-height:320px; overflow:auto; font-size:.8rem; white-space:pre-wrap; word-break:break-word; background: var(--surface); }
.mono { font-family: var(--font-mono, monospace); }
</style>
