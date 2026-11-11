<template>
  <div class="ccb">
    <!-- 1. ¿Qué quieres programar? -->
    <div class="ccb-types">
      <button v-for="t in TYPES" :key="t.key" type="button" class="ccb-type"
              :class="{ 'is-on': type === t.key }" :disabled="t.key === 'app' && !anyApps"
              :title="t.key === 'app' && !anyApps ? 'No se ha detectado ninguna aplicación compatible en tus dominios' : ''"
              @click="setType(t.key)">
        <i class="bi" :class="t.icon"></i>
        <span class="ccb-type__label">{{ t.label }}</span>
        <span class="ccb-type__hint">{{ t.hint }}</span>
      </button>
    </div>

    <!-- 2. Dominio (script / app) -->
    <div v-if="type === 'script' || type === 'app'" class="ccb-field">
      <label>Dominio</label>
      <div v-if="loadingDomains" class="ccb-muted"><span class="ccb-spin"></span> Cargando dominios…</div>
      <p v-else-if="!domainOptions.length" class="ccb-muted">
        {{ type === 'app' ? 'Ningún dominio tiene una aplicación compatible.' : 'No hay dominios con web.' }}
      </p>
      <select v-else v-model.number="domainId" class="svq-input" @change="onDomain">
        <option :value="null" disabled>Elige un dominio…</option>
        <option v-for="d in domainOptions" :key="d.id" :value="d.id">
          {{ d.domain_name }}{{ showOwner ? ' · ' + d.owner : '' }} (PHP {{ d.php_version || 'sistema' }})
        </option>
      </select>
    </div>

    <!-- 3a. Script: explorador -->
    <div v-if="type === 'script' && domain" class="ccb-field">
      <label>Script a ejecutar</label>
      <div class="ccb-browser">
        <div class="ccb-crumbs">
          <button type="button" class="ccb-crumb" @click="browseTo('')">
            <i class="bi bi-house"></i> {{ domain.domain_name }}
          </button>
          <span v-for="(c, i) in crumbs" :key="c.path" class="ccb-crumbwrap">
            <span class="ccb-muted">/</span>
            <button type="button" class="ccb-crumb" :disabled="i === crumbs.length - 1"
                    @click="browseTo(c.path)">{{ c.name }}</button>
          </span>
        </div>
        <div class="ccb-list">
          <div v-if="browsing" class="ccb-muted ccb-pad"><span class="ccb-spin"></span> Cargando…</div>
          <div v-else-if="browseError" class="ccb-err ccb-pad">{{ browseError }}</div>
          <template v-else>
            <button v-if="listing.parent !== null && listing.parent !== undefined" type="button"
                    class="ccb-item" @click="browseTo(listing.parent)">
              <i class="bi bi-arrow-90deg-up"></i> ..
            </button>
            <button v-for="e in listing.entries" :key="e.path" type="button" class="ccb-item"
                    :class="{ 'is-on': e.path === scriptPath }"
                    @click="e.type === 'dir' ? browseTo(e.path) : pickScript(e.path)">
              <i class="bi" :class="e.type === 'dir' ? 'bi-folder-fill ccb-dir' : (e.name.endsWith('.sh') ? 'bi-terminal' : 'bi-filetype-php')"></i>
              {{ e.name }}
              <i v-if="e.path === scriptPath" class="bi bi-check-lg ccb-check"></i>
            </button>
            <p v-if="!listing.entries.length" class="ccb-muted ccb-pad">Esta carpeta no tiene subcarpetas ni scripts .php / .sh.</p>
          </template>
        </div>
      </div>
      <small class="ccb-muted">
        Consejo: los scripts de tareas van mejor en <code>private/</code>, fuera de la web pública.
      </small>
      <div v-if="scriptPath" class="ccb-field ccb-mt">
        <label>Argumentos (opcional)</label>
        <input v-model="scriptArgs" class="svq-input mono" placeholder="--modo=completo"
               @change="buildScript" />
      </div>
    </div>

    <!-- 3b. App detectada -->
    <div v-if="type === 'app' && domain" class="ccb-field">
      <label>Aplicación</label>
      <div class="ccb-apps">
        <button v-for="a in domain.apps" :key="a.key" type="button" class="ccb-app"
                :class="{ 'is-on': appKey === a.key }" @click="pickApp(a)">
          <strong>{{ a.label }}</strong>
          <span class="ccb-muted">{{ a.desc }}</span>
        </button>
      </div>
    </div>

    <!-- 3c. URL -->
    <div v-if="type === 'url'" class="ccb-field">
      <label>URL a visitar</label>
      <input v-model="url" class="svq-input mono" placeholder="https://midominio.com/cron.php?clave=…"
             @change="buildUrl" @keyup.enter="buildUrl" />
      <small class="ccb-muted">El servidor abrirá esta dirección (como si la visitaras) a la hora programada. Límite: 5 minutos por visita.</small>
    </div>

    <!-- 3d. Personalizado -->
    <div v-if="type === 'custom'" class="ccb-field">
      <label>Comando <span class="ccb-req">*</span></label>
      <input :value="modelValue" class="svq-input mono"
             placeholder="/usr/bin/php8.4 /home/usuario/web/dominio.com/private/tarea.php"
             @input="$emit('update:modelValue', $event.target.value)" />
      <small class="ccb-muted">
        Ruta absoluta al script o ejecutable. No se permiten <code>;</code>, <code>&amp;&amp;</code>, <code>|</code> ni
        <code>&gt;</code>: si necesitas encadenar órdenes, ponlas en un script y programa el script.
      </small>
    </div>

    <div v-if="buildError" class="ccb-err">{{ buildError }}</div>

    <!-- Comando generado -->
    <div v-if="type !== 'custom' && modelValue" class="ccb-result">
      <div class="ccb-result__head">
        <span class="ccb-muted"><i class="bi bi-terminal"></i> Comando que se ejecutará</span>
        <button type="button" class="ccb-link" @click="setType('custom', true)">Editar a mano</button>
      </div>
      <code class="ccb-cmd">{{ modelValue }}</code>
      <span v-if="runAs" class="ccb-muted">Se ejecutará como el usuario <strong>{{ runAs }}</strong>.</span>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '../../services/api.js'

const TYPES = [
  { key: 'script', icon: 'bi-filetype-php', label: 'Un script de mi web', hint: 'PHP o .sh de tu dominio' },
  { key: 'url',    icon: 'bi-globe',        label: 'Visitar una URL',     hint: 'Abrir una dirección web' },
  { key: 'app',    icon: 'bi-boxes',        label: 'Tarea de una app',    hint: 'Laravel, WordPress, Nextcloud…' },
  { key: 'custom', icon: 'bi-code-slash',   label: 'Comando propio',      hint: 'Para usuarios avanzados' },
]

export default {
  name: 'CronCommandBuilder',
  props: {
    modelValue: { type: String, default: '' },   // comando
    initialType: { type: String, default: 'script' },
    showOwner: { type: Boolean, default: false }, // admin/reseller: mostrar dueño de cada dominio
  },
  // owner: user_id con el que debe crearse el cron (dueño del dominio) o null
  // suggest: frecuencia recomendada por la app ('*/5 * * * *')
  emits: ['update:modelValue', 'owner', 'domain', 'suggest'],
  setup(props, { emit }) {
    const type = ref(props.initialType)
    const domains = ref([])
    const loadingDomains = ref(false)
    const domainId = ref(null)
    const buildError = ref('')
    const runAs = ref('')

    const anyApps = computed(() => domains.value.some((d) => d.apps && d.apps.length))
    const domainOptions = computed(() =>
      type.value === 'app' ? domains.value.filter((d) => d.apps && d.apps.length) : domains.value)
    const domain = computed(() => domains.value.find((d) => d.id === domainId.value) || null)

    const loadDomains = async () => {
      loadingDomains.value = true
      try { domains.value = (await api.cronAssistantDomains()) || [] }
      catch { domains.value = [] }
      finally { loadingDomains.value = false }
    }
    onMounted(loadDomains)

    const resetCommand = () => {
      emit('update:modelValue', '')
      buildError.value = ''
      runAs.value = ''
    }

    const setType = (t, keepCommand = false) => {
      if (type.value === t) return
      type.value = t
      // «Editar a mano» (keepCommand) conserva comando Y dueño: el cron debe
      // seguir ejecutándose como el usuario del dominio del que salió.
      if (!keepCommand) resetCommand()
      scriptPath.value = ''
      appKey.value = ''
      if ((t === 'custom' && !keepCommand) || t === 'url') { emit('owner', null); emit('domain', null) }
      else if (t !== 'custom' && domain.value) onDomain()
      if (t === 'app' && domain.value && !domain.value.apps.length) domainId.value = null
    }

    const setOwnerFromDomain = () => {
      const d = domain.value
      emit('owner', d ? d.user_id : null)
      emit('domain', d ? d.id : null)
      runAs.value = d ? d.owner : ''
    }

    // ── Script ───────────────────────────────────────────────────────────
    const listing = ref({ path: '', parent: null, entries: [] })
    const browsing = ref(false)
    const browseError = ref('')
    const scriptPath = ref('')
    const scriptArgs = ref('')
    const crumbs = computed(() => {
      const parts = (listing.value.path || '').split('/').filter(Boolean)
      return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
    })

    const browseTo = async (path) => {
      if (!domain.value) return
      browsing.value = true
      browseError.value = ''
      try { listing.value = await api.cronAssistantBrowse(domain.value.id, path) }
      catch (e) { browseError.value = e.message || 'No se pudo abrir la carpeta' }
      finally { browsing.value = false }
    }

    const buildScript = async () => {
      if (!domain.value || !scriptPath.value) return
      buildError.value = ''
      try {
        const r = await api.cronAssistantBuild({
          template: 'script', domain_id: domain.value.id,
          path: scriptPath.value, args: scriptArgs.value,
        })
        emit('update:modelValue', r.command)
        setOwnerFromDomain()
      } catch (e) {
        emit('update:modelValue', '')
        buildError.value = e.message
      }
    }
    const pickScript = (path) => { scriptPath.value = path; buildScript() }

    // ── App ──────────────────────────────────────────────────────────────
    const appKey = ref('')
    const pickApp = (a) => {
      appKey.value = a.key
      buildError.value = ''
      emit('update:modelValue', a.command)
      if (a.suggest) emit('suggest', a.suggest)
      setOwnerFromDomain()
    }

    const onDomain = () => {
      resetCommand()
      scriptPath.value = ''
      appKey.value = ''
      if (type.value === 'script') {
        // Abrir directamente private/ si existe: es donde suelen ir los scripts
        listing.value = { path: '', parent: null, entries: [] }
        browseTo('').then(() => {
          if (listing.value.entries.some((e) => e.type === 'dir' && e.name === 'private')) browseTo('private')
        })
      } else if (type.value === 'app' && domain.value && domain.value.apps.length === 1) {
        pickApp(domain.value.apps[0])
      }
      setOwnerFromDomain()
    }

    // ── URL ──────────────────────────────────────────────────────────────
    const url = ref('')
    const buildUrl = async () => {
      buildError.value = ''
      if (!url.value.trim()) { emit('update:modelValue', ''); return }
      try {
        const r = await api.cronAssistantBuild({ template: 'url', url: url.value.trim() })
        emit('update:modelValue', r.command)
      } catch (e) {
        emit('update:modelValue', '')
        buildError.value = e.message
      }
    }

    return {
      TYPES, type, setType, domains, loadingDomains, domainOptions, domainId, domain, anyApps,
      onDomain, buildError, runAs,
      listing, browsing, browseError, crumbs, browseTo, scriptPath, scriptArgs, pickScript, buildScript,
      appKey, pickApp, url, buildUrl,
    }
  },
}
</script>

<style scoped>
.ccb { display: flex; flex-direction: column; gap: var(--sp-3); }
.ccb-types { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--sp-2); }
@media (max-width: 640px) { .ccb-types { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.ccb-type {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left;
  padding: var(--sp-3); border: 1px solid var(--border); border-radius: var(--r-md, 10px);
  background: var(--surface); cursor: pointer; transition: all .12s; color: var(--text);
}
.ccb-type .bi { font-size: 1.15rem; color: var(--text-secondary); margin-bottom: 2px; }
.ccb-type:hover:not(:disabled) { border-color: var(--svq-orange); }
.ccb-type.is-on { border-color: var(--svq-orange); box-shadow: 0 0 0 1px var(--svq-orange) inset;
  background: color-mix(in srgb, var(--svq-orange) 7%, var(--surface)); }
.ccb-type.is-on .bi { color: var(--svq-orange); }
.ccb-type:disabled { opacity: .45; cursor: not-allowed; }
.ccb-type__label { font-size: var(--fs-sm); font-weight: var(--fw-semibold); }
.ccb-type__hint { font-size: var(--fs-xs); color: var(--text-muted); }
.ccb-field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.ccb-field > label { font-size: var(--fs-sm); font-weight: var(--fw-semibold); }
.ccb-field .svq-input { width: 100%; box-sizing: border-box; min-width: 0; }
.ccb-mt { margin-top: var(--sp-2); }
.ccb-req { color: var(--danger); }
.ccb-muted { color: var(--text-muted); font-size: var(--fs-xs); }
.ccb-err { color: var(--danger); font-size: var(--fs-sm); }
.ccb-pad { padding: var(--sp-3); margin: 0; }
.ccb-browser { border: 1px solid var(--border); border-radius: var(--r-md, 10px); overflow: hidden; }
.ccb-crumbs { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; padding: 6px 10px;
  background: var(--surface-inset); border-bottom: 1px solid var(--border); font-size: var(--fs-xs); }
.ccb-crumbwrap { display: inline-flex; align-items: center; gap: 4px; }
.ccb-crumb { background: none; border: none; padding: 2px 4px; border-radius: var(--r-sm);
  color: var(--svq-orange); cursor: pointer; font-size: var(--fs-xs); }
.ccb-crumb:disabled { color: var(--text); cursor: default; font-weight: var(--fw-semibold); }
.ccb-crumb:hover:not(:disabled) { background: var(--surface); }
.ccb-list { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; }
.ccb-item { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border: none;
  border-bottom: 1px solid var(--border); background: var(--surface); text-align: left;
  font-size: var(--fs-sm); color: var(--text); cursor: pointer; font-family: var(--font-mono); }
.ccb-item:last-child { border-bottom: none; }
.ccb-item:hover { background: var(--surface-inset); }
.ccb-item.is-on { background: color-mix(in srgb, var(--svq-orange) 10%, var(--surface)); font-weight: var(--fw-semibold); }
.ccb-dir { color: #e0a526; }
.ccb-check { margin-left: auto; color: var(--svq-orange); }
.ccb-apps { display: flex; flex-direction: column; gap: 6px; }
.ccb-app { display: flex; flex-direction: column; gap: 2px; text-align: left; padding: var(--sp-3);
  border: 1px solid var(--border); border-radius: var(--r-md, 10px); background: var(--surface);
  cursor: pointer; color: var(--text); font-size: var(--fs-sm); }
.ccb-app:hover { border-color: var(--svq-orange); }
.ccb-app.is-on { border-color: var(--svq-orange); box-shadow: 0 0 0 1px var(--svq-orange) inset; }
.ccb-result { display: flex; flex-direction: column; gap: 6px; padding: var(--sp-3);
  background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--r-md, 10px); }
.ccb-result__head { display: flex; justify-content: space-between; align-items: center; }
.ccb-link { background: none; border: none; color: var(--svq-orange); cursor: pointer; font-size: var(--fs-xs); padding: 0; }
.ccb-link:hover { text-decoration: underline; }
.ccb-cmd { font-family: var(--font-mono); font-size: var(--fs-xs); word-break: break-all; color: var(--text); }
.ccb-spin { display: inline-block; width: 12px; height: 12px; border: 2px solid currentColor;
  border-right-color: transparent; border-radius: 50%; animation: ccb-kf .7s linear infinite; vertical-align: -2px; }
@keyframes ccb-kf { to { transform: rotate(360deg); } }
</style>
