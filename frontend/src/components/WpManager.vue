<template>
  <BaseCard title="WordPress instalado" icon="wordpress">
    <template #actions>
      <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="loadingInfo" @click="loadInfo">Refrescar</BaseButton>
    </template>

    <div v-if="errorInfo && !info" class="wpm-error"><i class="bi bi-exclamation-triangle"></i> {{ errorInfo }}</div>

    <template v-else>
      <!-- Resumen (solo cuando ya se analizó WP; no bloquea el resto) -->
      <div v-if="info" class="wpm-summary">
        <div class="wpm-stat"><span class="wpm-stat__k">Versión WP</span><span class="wpm-stat__v mono">{{ info.version || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Idioma</span><span class="wpm-stat__v">{{ info.locale || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Plugins</span><span class="wpm-stat__v">{{ info.plugins_active }}/{{ info.plugins_total }} activos</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Temas</span><span class="wpm-stat__v">{{ info.themes_total }}</span></div>
      </div>
      <div v-else-if="loadingInfo" class="wpm-summary wpm-summary--loading">
        <div class="wpm-stat"><span class="wpm-stat__k">Analizando la instalación…</span><span class="wpm-stat__v"><span class="spinner"></span></span></div>
      </div>

      <!-- Avisos de actualización (independiente; solo se muestra si hay info) -->
      <div v-if="info && loadingUpdates && !info.updates.checked" class="wpm-uptodate">
        <span class="spinner"></span> Comprobando actualizaciones…
      </div>
      <div v-else-if="info && totalUpdates > 0" class="wpm-updbanner">
        <i class="bi bi-arrow-up-circle"></i>
        <span>Hay <strong>{{ totalUpdates }}</strong> actualización(es) pendiente(s):
          <template v-if="info.updates.core">core, </template>
          <template v-if="info.updates.plugins">{{ info.updates.plugins }} plugin(s), </template>
          <template v-if="info.updates.themes">{{ info.updates.themes }} tema(s)</template>
        </span>
      </div>
      <div v-else-if="info && info.updates.checked" class="wpm-uptodate"><i class="bi bi-check-circle"></i> Todo está actualizado.</div>

      <!-- Los tabs SIEMPRE visibles: no esperan al análisis de WP (que es lento).
           Cada pane carga lo suyo; Seguridad va a la BD y es instantáneo. -->
      <BaseTabs v-model="tab" :tabs="tabs" />

      <!-- ── Tab General (necesita info de WP) ── -->
      <div v-if="tab === 'general'" class="wpm-pane">
        <div v-if="!info" class="wpm-loading"><span class="spinner"></span> Analizando la instalación de WordPress…</div>
        <template v-else>
          <div class="wpm-actions">
            <BaseButton v-if="info.updates.core" variant="primary" size="sm" icon="arrow-up-circle" :loading="busy==='core'" @click="run('update-core', {}, 'core')">Actualizar WordPress</BaseButton>
            <a class="wpm-link" :href="adminUrl" target="_blank"><i class="bi bi-box-arrow-up-right"></i> Abrir wp-admin</a>
          </div>
          <div class="wpm-quick">
            <button class="wpm-qbtn" :disabled="!!busy" @click="run('flush-permalinks', {}, 'perma')"><i class="bi bi-link-45deg"></i> Regenerar permalinks</button>
            <button class="wpm-qbtn" :disabled="!!busy" @click="run('flush-cache', {}, 'cache')"><i class="bi bi-trash"></i> Vaciar caché</button>
            <button class="wpm-qbtn" :disabled="!!busy" @click="toggleMaintenance"><i class="bi bi-cone-striped"></i> {{ info.maintenance ? 'Quitar mantenimiento' : 'Modo mantenimiento' }}</button>
            <button class="wpm-qbtn wpm-qbtn--warn" :disabled="!!busy" @click="confirmSalts"><i class="bi bi-shield-lock"></i> Regenerar claves (cierra sesiones)</button>
          </div>
        </template>
      </div>

      <!-- ── Tab Plugins / Temas ── -->
      <div v-else-if="tab === 'plugins' || tab === 'themes'" class="wpm-pane">
        <div class="wpm-itembar">
          <BaseButton variant="ghost" size="sm" icon="arrow-up-circle" :loading="busy==='updall'"
            @click="run('update-items', { kind: itemKind }, 'updall')">Actualizar todos</BaseButton>
          <span class="dd-muted">{{ items.length }} {{ itemKind === 'plugin' ? 'plugins' : 'temas' }}</span>
        </div>
        <div v-if="loadingItems" class="wpm-loading"><span class="spinner"></span> Cargando…</div>
        <table v-else class="wpm-table">
          <thead><tr><th>Nombre</th><th>Versión</th><th>Estado</th><th></th></tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.name">
              <td><span class="wpm-name">{{ it.title || it.name }}</span><br><span class="mono dd-muted">{{ it.name }}</span></td>
              <td class="mono">{{ it.version }}<br v-if="it.update==='available'"><span v-if="it.update==='available'" class="wpm-newver">→ {{ it.update_version }}</span></td>
              <td>
                <span class="wpm-badge" :class="it.status==='active' ? 'is-on' : 'is-off'">{{ statusLabel(it.status) }}</span>
              </td>
              <td class="wpm-rowactions">
                <button v-if="it.update==='available'" class="wpm-mini" :disabled="!!busy" @click="run('update-items', { kind: itemKind, name: it.name }, 'i:'+it.name)" title="Actualizar"><i class="bi bi-arrow-up-circle"></i></button>
                <button v-if="it.status==='active'" class="wpm-mini" :disabled="!!busy" @click="run('toggle-item', { kind: itemKind, name: it.name, activate: false }, 't:'+it.name)" title="Desactivar"><i class="bi bi-pause-circle"></i></button>
                <button v-else class="wpm-mini" :disabled="!!busy" @click="run('toggle-item', { kind: itemKind, name: it.name, activate: true }, 't:'+it.name)" title="Activar"><i class="bi bi-play-circle"></i></button>
                <button class="wpm-mini wpm-mini--danger" :disabled="!!busy || it.status==='active'" @click="deleteItem(it)" :title="it.status==='active' ? (itemKind==='theme' ? 'Activa otro tema antes de borrar' : 'Desactiva el plugin antes de borrar') : 'Eliminar'"><i class="bi bi-trash"></i></button>
              </td>
            </tr>
            <tr v-if="!items.length"><td colspan="4" class="dd-muted" style="text-align:center;padding:1rem">No hay {{ itemKind === 'plugin' ? 'plugins' : 'temas' }}.</td></tr>
          </tbody>
        </table>
      </div>

      <!-- ── Tab Acceso / Admin ── -->
      <div v-else-if="tab === 'access'" class="wpm-pane">
        <div class="wpm-actions">
          <BaseButton variant="ghost" size="sm" icon="people" :loading="loadingUsers" @click="loadAdmins">Cargar administradores</BaseButton>
        </div>
        <table v-if="admins.length" class="wpm-table">
          <thead><tr><th>Usuario</th><th>Email</th><th></th></tr></thead>
          <tbody>
            <tr v-for="u in admins" :key="u.ID">
              <td><span class="wpm-name">{{ u.user_login }}</span><br><span class="dd-muted">{{ u.display_name }}</span></td>
              <td class="mono">{{ u.user_email }}</td>
              <td class="wpm-rowactions">
                <button class="wpm-mini" :disabled="!!busy" @click="resetPw(u.user_login)" title="Resetear contraseña"><i class="bi bi-key"></i></button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="wpm-urlbox">
          <label class="app-field">
            <span>URL del sitio (siteurl / home)</span>
            <div class="wpm-urlrow">
              <input class="svq-input mono" v-model="newUrl" :placeholder="info.siteurl" />
              <BaseButton variant="primary" size="sm" :loading="busy==='url'" @click="changeUrl">Cambiar</BaseButton>
            </div>
          </label>
          <small class="dd-muted">Cuidado: cambiar la URL puede dejar el sitio inaccesible si no coincide con el dominio/DNS.</small>
        </div>

        <div v-if="resetResult" class="app-result">
          <p class="app-result__title"><i class="bi bi-check-circle-fill"></i> Contraseña actualizada</p>
          <div class="app-result__row"><span>Usuario</span><span class="mono">{{ resetResult.user_login }}</span></div>
          <div class="app-result__row"><span>Nueva contraseña</span><span class="mono">{{ resetResult.new_password }}</span></div>
        </div>
      </div>

      <!-- ── Tab Seguridad (anti fuerza bruta WordPress) ── -->
      <div v-else-if="tab === 'security'" class="wpm-pane">
        <!-- Aviso de ataque en curso (solo si está bajo ataque y sin proteger) -->
        <div v-if="attack && attack.under_attack" class="wpm-attack">
          <div class="wpm-attack__icon"><i class="bi bi-exclamation-octagon-fill"></i></div>
          <div class="wpm-attack__body">
            <strong>Tu WordPress está recibiendo un ataque de fuerza bruta.</strong>
            <p>
              En la última hora se han registrado
              <span v-if="attack.xmlrpc_hits >= attack.threshold"><b>{{ attack.xmlrpc_hits.toLocaleString() }}</b> intentos contra <code>xmlrpc.php</code></span>
              <span v-if="attack.xmlrpc_hits >= attack.threshold && attack.wplogin_hits >= attack.threshold"> y </span>
              <span v-if="attack.wplogin_hits >= attack.threshold"><b>{{ attack.wplogin_hits.toLocaleString() }}</b> contra <code>wp-login.php</code></span>.
              Activa la protección para cortarlo sin afectar a tu acceso.
            </p>
            <BaseButton variant="primary" size="sm" icon="shield-fill-check" :loading="busy==='wpprotect-all'" @click="enableAllProtection">
              Activar protección recomendada
            </BaseButton>
          </div>
        </div>

        <div class="wpm-sec">
          <!-- XML-RPC -->
          <div class="wpm-sec__row">
            <div class="wpm-sec__info">
              <span class="wpm-sec__title"><i class="bi bi-shield-lock"></i> Bloquear XML-RPC</span>
              <small class="dd-muted">
                <code>xmlrpc.php</code> casi no se usa hoy (lo sustituye la API REST). Bloquearlo
                corta los ataques de amplificación/fuerza bruta. Desactívalo solo si usas la app
                móvil de WordPress o Jetpack con publicación remota.
              </small>
            </div>
            <button type="button" class="wpm-toggle" :class="{ 'is-on': prot.xmlrpc_blocked }"
                    :disabled="!!busy" role="switch" :aria-checked="prot.xmlrpc_blocked"
                    @click="toggleXmlrpc(!prot.xmlrpc_blocked)">
              <span class="wpm-toggle__knob"></span>
            </button>
          </div>

          <!-- Rate-limit wp-login -->
          <div class="wpm-sec__row">
            <div class="wpm-sec__info">
              <span class="wpm-sec__title"><i class="bi bi-speedometer"></i> Limitar intentos de login</span>
              <small class="dd-muted">
                Limita las peticiones por minuto a <code>wp-login.php</code> desde una misma IP.
                Una persona necesita 1-2 intentos; un bot mete miles. Recomendado: <b>3/min</b>.
                0 = sin límite.
              </small>
            </div>
            <div class="wpm-sec__rl">
              <input type="number" min="0" max="600" class="svq-input" style="width:5rem" v-model.number="rlInput" :disabled="!!busy" />
              <span class="dd-muted">/min</span>
              <BaseButton variant="ghost" size="sm" :loading="busy==='wprl'" @click="saveRateLimit">Guardar</BaseButton>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Tab Consola WP-CLI ── -->
      <div v-else-if="tab === 'cli'" class="wpm-pane">
        <p class="dd-muted" style="margin:0 0 .75rem">
          Ejecuta comandos <a href="https://developer.wordpress.org/cli/commands/" target="_blank"
          rel="noopener">wp-cli</a> sobre este WordPress, como el usuario del dominio.
          No hace falta escribir el <code>wp</code> inicial.
        </p>

        <div class="wpm-cli-bar">
          <select class="svq-input" style="max-width:16rem" v-model="cliQuickSel" @change="applyQuick">
            <option value="">Comandos rápidos…</option>
            <option v-for="q in cliQuick" :key="q.cmd" :value="q.cmd">{{ q.label }}</option>
          </select>
        </div>

        <div class="wpm-cli-inputrow">
          <span class="wpm-cli-prompt mono">wp</span>
          <input class="svq-input mono" v-model="cliInput" :disabled="cliRunning"
                 placeholder="plugin list --status=active"
                 @keyup.enter="runCli" @keyup.up="cliHistPrev" @keyup.down="cliHistNext" />
          <BaseButton variant="primary" size="sm" icon="play-fill" :loading="cliRunning" @click="runCli">
            Ejecutar
          </BaseButton>
        </div>

        <div v-if="cliLog.length" class="wpm-cli-out mono" ref="cliOutEl">
          <div v-for="(e, i) in cliLog" :key="i" class="wpm-cli-entry">
            <div class="wpm-cli-cmd">$ {{ e.command }}
              <span class="wpm-cli-rc" :class="e.rc === 0 ? 'is-ok' : 'is-err'">rc={{ e.rc }}</span>
            </div>
            <pre v-if="e.stdout" class="wpm-cli-stdout">{{ e.stdout }}</pre>
            <pre v-if="e.stderr" class="wpm-cli-stderr">{{ e.stderr }}</pre>
            <div v-if="e.truncated" class="wpm-cli-stderr">… salida truncada (demasiado larga)</div>
          </div>
        </div>
        <p v-else class="dd-muted" style="margin:.5rem 0 0;font-size:.85em">
          <i class="bi bi-info-circle"></i>
          Ejemplos: <code>plugin list</code> · <code>db optimize</code> ·
          <code>search-replace https://viejo.com https://nuevo.com --dry-run</code> ·
          <code>cron event run --all</code>. Los comandos interactivos
          (<code>shell</code>, <code>db cli</code>) y los flags
          <code>--path/--ssh/--http/--require/--exec</code> están bloqueados.
          Cada comando queda registrado en la auditoría.
        </p>
      </div>
    </template>
  </BaseCard>
</template>

<script>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseTabs from './ui/BaseTabs.vue'

export default {
  name: 'WpManager',
  components: { BaseCard, BaseButton, BaseTabs },
  props: {
    domainId:   { type: [Number, String], default: null },
    domainName: { type: String, default: '' },
  },
  setup(props) {
    const store = useMainStore()
    const route = useRoute()
    // El id se normaliza a entero válido. Fuente primaria: el prop; respaldo:
    // el parámetro de la ruta (/domains/:id). Así, aunque el prop llegue como
    // NaN/undefined en un render temprano, el componente sigue funcionando.
    const did = computed(() => {
      let n = parseInt(props.domainId, 10)
      if (!Number.isInteger(n)) n = parseInt(route.params.id, 10)
      return Number.isInteger(n) ? n : null
    })
    const info = ref(null)
    const loadingInfo = ref(true)   // arranca en "analizando" hasta la 1ª carga
    const errorInfo = ref('')
    const tab = ref('general')
    const tabs = [
      { key: 'general', label: 'General', icon: 'speedometer2' },
      { key: 'plugins', label: 'Plugins', icon: 'plug' },
      { key: 'themes',  label: 'Temas',   icon: 'palette' },
      { key: 'access',  label: 'Acceso',  icon: 'key' },
      { key: 'security', label: 'Seguridad', icon: 'shield-check' },
      { key: 'cli',     label: 'Consola', icon: 'terminal' },
    ]
    const busy = ref('')          // id de la acción en curso (desactiva botones)
    const items = ref([])
    const loadingItems = ref(false)
    const admins = ref([])
    const loadingUsers = ref(false)
    const resetResult = ref(null)
    const newUrl = ref('')

    const itemKind = computed(() => (tab.value === 'themes' ? 'theme' : 'plugin'))
    const totalUpdates = computed(() => {
      if (!info.value?.updates) return 0
      const u = info.value.updates
      return (u.core || 0) + (u.plugins || 0) + (u.themes || 0)
    })
    const adminUrl = computed(() => (info.value?.siteurl || '').replace(/\/$/, '') + '/wp-admin')

    const loadingUpdates = ref(false)

    // Carga rápida: una sola llamada wp eval (sin consultar la red por updates).
    const loadInfo = async () => {
      if (did.value == null) { loadingInfo.value = false; return }
      loadingInfo.value = true; errorInfo.value = ''
      try {
        const r = await api.getWpInfo(did.value)
        info.value = r.data
        newUrl.value = r.data.siteurl || ''
        loadUpdates()  // en segundo plano, no bloquea la vista
      } catch (e) { errorInfo.value = e.message || 'No pude leer la instalación' }
      finally { loadingInfo.value = false }
    }

    // Actualizaciones aparte (consulta a wordpress.org, lento): no bloquea.
    const loadUpdates = async () => {
      if (did.value == null) return
      loadingUpdates.value = true
      try {
        const r = await api.getWpUpdates(did.value)
        if (info.value) info.value = { ...info.value, updates: r.data }
      } catch (e) { /* silencioso: el resumen sigue mostrándose sin updates */ }
      finally { loadingUpdates.value = false }
    }

    const loadItems = async () => {
      if (did.value == null) return
      loadingItems.value = true
      try { const r = await api.getWpItems(did.value, itemKind.value); items.value = r.data || [] }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { loadingItems.value = false }
    }

    const loadAdmins = async () => {
      if (did.value == null) return
      loadingUsers.value = true
      try { const r = await api.wpAction(did.value, 'admin-users'); admins.value = r.data.users || [] }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { loadingUsers.value = false }
    }

    // Ejecuta una acción genérica. Refresca SOLO lo que cambió, sin volver a
    // leer toda la info (cada lectura completa son varios procesos wp-cli).
    const run = async (action, payload, busyId) => {
      if (did.value == null) return
      busy.value = busyId || action
      try {
        const r = await api.wpAction(did.value, action, payload)
        store.showNotification(r.data?.output || r.data?.note || 'Hecho', 'success')
        // Actualización local mínima según la acción:
        if (action === 'maintenance' && info.value) {
          info.value = { ...info.value, maintenance: !!payload.enable }
        } else if (action === 'update-core') {
          await loadInfo()                 // cambia versión/updates: recargar
        } else if (action === 'update-items' || action === 'toggle-item') {
          await loadItems()                // refresca la tabla; updates aparte
          loadUpdates()
        } else if (action === 'delete-item') {
          await loadItems()                // desaparece de la tabla
          loadInfo()                       // actualiza conteos del resumen
        }
        return r.data
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally { busy.value = '' }
    }

    const toggleMaintenance = () => run('maintenance', { enable: !info.value.maintenance }, 'maint')

    const deleteItem = (it) => {
      const tipo = itemKind.value === 'theme' ? 'tema' : 'plugin'
      if (!confirm(`¿Eliminar el ${tipo} "${it.title || it.name}"? Se borrarán sus archivos de forma permanente.`)) return
      run('delete-item', { kind: itemKind.value, name: it.name }, 'd:' + it.name)
    }

    const confirmSalts = () => {
      if (confirm('Regenerar las claves de seguridad cerrará TODAS las sesiones abiertas (tendrás que volver a iniciar sesión). ¿Continuar?'))
        run('regenerate-salts', {}, 'salts')
    }

    const resetPw = async (login) => {
      if (!confirm(`¿Resetear la contraseña de "${login}"? Se generará una nueva.`)) return
      resetResult.value = null
      const data = await run('reset-password', { user_login: login }, 'pw')
      if (data?.new_password) resetResult.value = data
    }

    const changeUrl = () => {
      if (!newUrl.value) return
      if (!confirm(`¿Cambiar la URL del sitio a ${newUrl.value}?`)) return
      run('set-url', { url: newUrl.value }, 'url')
    }

    const statusLabel = (s) => ({ active: 'Activo', inactive: 'Inactivo', 'must-use': 'Must-use', 'dropin': 'Drop-in', parent: 'Padre' }[s] || s)

    // ── Seguridad (anti fuerza bruta WordPress) ──────────────────────────────
    const prot = ref({ xmlrpc_blocked: false, wp_login_ratelimit: 0 })
    const attack = ref(null)
    const rlInput = ref(0)
    const loadingSec = ref(false)

    const loadSecurity = async () => {
      if (did.value == null) return
      loadingSec.value = true
      try {
        // api.get() devuelve el JSON directamente (no envuelto en {data}).
        const r = await api.getDomainWpProtection(did.value)
        prot.value = { xmlrpc_blocked: r.xmlrpc_blocked, wp_login_ratelimit: r.wp_login_ratelimit }
        rlInput.value = r.wp_login_ratelimit || 0
        attack.value = r.attack || null
      } catch (e) { /* silencioso: el pane simplemente no muestra estado */ }
      finally { loadingSec.value = false }
    }

    const applyProtection = async (body, busyId) => {
      busy.value = busyId
      try {
        const r = await api.setDomainWpProtection(did.value, body)
        prot.value = { xmlrpc_blocked: r.xmlrpc_blocked, wp_login_ratelimit: r.wp_login_ratelimit }
        rlInput.value = r.wp_login_ratelimit || 0
        // tras aplicar, el aviso de ataque deja de tener sentido para lo mitigado
        await loadSecurity()
        store.showNotification('Protección actualizada', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || 'no se pudo aplicar'), 'danger')
      } finally { busy.value = '' }
    }

    const toggleXmlrpc = (checked) => applyProtection({ xmlrpc_blocked: checked }, 'wpx')
    const saveRateLimit = () => applyProtection({ wp_login_ratelimit: Math.max(0, Math.min(600, rlInput.value || 0)) }, 'wprl')
    // Botón del aviso: bloquea xmlrpc y pone 3/min en wp-login de una vez.
    const enableAllProtection = () => applyProtection({ xmlrpc_blocked: true, wp_login_ratelimit: 3 }, 'wpprotect-all')

    // ── Consola WP-CLI ──
    const cliInput = ref('')
    const cliRunning = ref(false)
    const cliLog = ref([])        // entradas {command, rc, stdout, stderr, truncated}
    const cliQuickSel = ref('')
    const cliOutEl = ref(null)
    const cliHist = ref([])       // historial de comandos (flechas ↑/↓)
    let cliHistIdx = -1

    const cliQuick = [
      { label: 'Listar plugins activos',        cmd: 'plugin list --status=active' },
      { label: 'Optimizar base de datos',       cmd: 'db optimize' },
      { label: 'Reparar base de datos',         cmd: 'db repair' },
      { label: 'Vaciar transients',             cmd: 'transient delete --all' },
      { label: 'Ejecutar crons pendientes',     cmd: 'cron event run --due-now' },
      { label: 'Comprobar integridad del core', cmd: 'core verify-checksums' },
      { label: 'Buscar y reemplazar (prueba)',  cmd: "search-replace 'https://viejo.com' 'https://nuevo.com' --dry-run" },
      { label: 'Redis Object Cache (requiere su plugin)', cmd: 'redis status' },
    ]

    const applyQuick = () => {
      if (cliQuickSel.value) { cliInput.value = cliQuickSel.value; cliQuickSel.value = '' }
    }

    const cliHistPrev = () => {
      if (!cliHist.value.length) return
      cliHistIdx = cliHistIdx < 0 ? cliHist.value.length - 1 : Math.max(0, cliHistIdx - 1)
      cliInput.value = cliHist.value[cliHistIdx]
    }
    const cliHistNext = () => {
      if (cliHistIdx < 0) return
      cliHistIdx += 1
      if (cliHistIdx >= cliHist.value.length) { cliHistIdx = -1; cliInput.value = ''; return }
      cliInput.value = cliHist.value[cliHistIdx]
    }

    const runCli = async () => {
      const command = cliInput.value.trim()
      if (!command || cliRunning.value) return
      cliRunning.value = true
      try {
        const r = await api.wpCli(did.value, command)
        cliLog.value.push(r.data)
        cliHist.value.push(command)
        cliHistIdx = -1
        cliInput.value = ''
        await nextTick()
        if (cliOutEl.value) cliOutEl.value.scrollTop = cliOutEl.value.scrollHeight
      } catch (e) {
        store.showNotification('Error: ' + (e.message || 'no se pudo ejecutar'), 'danger')
      } finally { cliRunning.value = false }
    }

    // Cargar listado al entrar en las pestañas de plugins/temas
    watch(tab, (t) => {
      if ((t === 'plugins' || t === 'themes')) loadItems()
      if (t === 'access' && !admins.value.length) loadAdmins()
      if (t === 'security') loadSecurity()
    })

    // Cargar info cuando el componente esté montado y el id sea válido. Si el id
    // se resuelve más tarde (route.params aún no listo), el watch lo reintenta.
    onMounted(loadInfo)
    watch(did, (v, prev) => { if (v != null && prev == null) loadInfo() })

    return {
      info, loadingInfo, errorInfo, tab, tabs, busy, items, loadingItems,
      admins, loadingUsers, loadingUpdates, resetResult, newUrl, itemKind, totalUpdates, adminUrl,
      loadInfo, loadItems, loadAdmins, run, toggleMaintenance, deleteItem, confirmSalts,
      resetPw, changeUrl, statusLabel,
      prot, attack, rlInput, loadSecurity, toggleXmlrpc, saveRateLimit, enableAllProtection,
      cliInput, cliRunning, cliLog, cliQuick, cliQuickSel, cliOutEl,
      runCli, applyQuick, cliHistPrev, cliHistNext,
    }
  },
}
</script>

<style scoped>
.wpm-loading, .wpm-error { display:flex; align-items:center; gap:.5rem; padding:.75rem 0; color: var(--text-muted); }
.wpm-error { color: var(--danger); }
.wpm-summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap:.5rem; margin-bottom:.75rem; }
.wpm-summary--loading { opacity:.7; }
.wpm-stat { background: var(--surface-inset); border:1px solid var(--border); border-radius: var(--radius-md); padding:.5rem .75rem; }
.wpm-stat__k { display:block; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color: var(--text-muted); }
.wpm-stat__v { font-weight:600; }
.wpm-updbanner, .wpm-uptodate { display:flex; align-items:center; gap:.5rem; padding:.55rem .75rem; border-radius: var(--radius-md); margin-bottom:.75rem; font-size:.9rem; }
.wpm-updbanner { background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--warning); }
.wpm-uptodate { background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success); }
.wpm-pane { padding-top:.75rem; }
.wpm-actions { display:flex; align-items:center; gap:.75rem; margin-bottom:.75rem; flex-wrap:wrap; }
.wpm-link { display:inline-flex; align-items:center; gap:.3rem; font-size:.85rem; color: var(--accent); text-decoration:none; }
.wpm-link:hover { text-decoration: underline; }
.wpm-quick { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:.5rem; }
.wpm-qbtn { display:flex; align-items:center; gap:.5rem; padding:.6rem .8rem; border:1px solid var(--border); background: var(--surface); border-radius: var(--radius-md); cursor:pointer; color: var(--text); font-size:.88rem; text-align:left; transition: background .15s; }
.wpm-qbtn:hover:not(:disabled) { background: var(--surface-inset); }
.wpm-qbtn:disabled { opacity:.5; cursor:not-allowed; }
.wpm-qbtn--warn { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 40%, var(--border)); }
.wpm-itembar { display:flex; align-items:center; justify-content:space-between; gap:.75rem; margin-bottom:.5rem; }
.wpm-table { width:100%; border-collapse: collapse; font-size:.86rem; }
.wpm-table th { text-align:left; font-size:.72rem; text-transform:uppercase; color: var(--text-muted); padding:.4rem .5rem; border-bottom:1px solid var(--border); }
.wpm-table td { padding:.5rem; border-bottom:1px solid var(--border); vertical-align:top; }
.wpm-name { font-weight:600; }
.wpm-newver { color: var(--warning); font-size:.78rem; }

/* Inputs/selects del componente: .svq-input vive en el scoped de DomainDetail
   y NO alcanza a los hijos; sin esta regla salían con el estilo nativo. */
.wpm-pane .svq-input {
  height: 36px; padding: 0 .65rem;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong, var(--border));
  border-radius: var(--radius-md); font-size: .86rem;
}
.wpm-pane select.svq-input { cursor: pointer; }
.wpm-pane .svq-input:focus {
  outline: none; border-color: var(--color-primary, var(--accent));
  box-shadow: var(--shadow-focus, 0 0 0 3px color-mix(in srgb, var(--accent) 20%, transparent));
}

/* ── Consola WP-CLI ── */
.wpm-cli-bar { margin-bottom:.5rem; }
.wpm-cli-inputrow .svq-input { flex:1; }
.wpm-cli-inputrow { display:flex; align-items:center; gap:.5rem; }
.wpm-cli-prompt { color: var(--text-muted); font-weight:700; }
.wpm-cli-out {
  margin-top:.75rem; max-height: 420px; overflow:auto;
  background: var(--surface-inset); border:1px solid var(--border);
  border-radius: var(--radius-md); padding:.6rem .75rem; font-size:.8rem;
}
.wpm-cli-entry { margin-bottom:.75rem; }
.wpm-cli-entry:last-child { margin-bottom:0; }
.wpm-cli-cmd { font-weight:700; margin-bottom:.2rem; }
.wpm-cli-rc { font-weight:600; font-size:.72rem; margin-left:.5rem; padding:.05rem .4rem; border-radius:999px; }
.wpm-cli-rc.is-ok  { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.wpm-cli-rc.is-err { background: color-mix(in srgb, var(--danger) 15%, transparent);  color: var(--danger); }
.wpm-cli-stdout, .wpm-cli-stderr { margin:0; white-space:pre-wrap; word-break:break-word; font-size:.8rem; }
.wpm-cli-stderr { color: var(--danger); }
.wpm-badge { font-size:.72rem; padding:.15rem .5rem; border-radius:999px; }
.wpm-badge.is-on { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.wpm-badge.is-off { background: var(--surface-inset); color: var(--text-muted); }
.wpm-rowactions { white-space:nowrap; text-align:right; }
.wpm-mini { background:none; border:1px solid var(--border); border-radius: var(--radius-sm); width:30px; height:30px; cursor:pointer; color: var(--text); margin-left:.25rem; }
.wpm-mini:hover:not(:disabled) { background: var(--surface-inset); }
.wpm-mini:disabled { opacity:.5; cursor:not-allowed; }
.wpm-mini--danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }
.wpm-mini--danger:hover:not(:disabled) { background: color-mix(in srgb, var(--danger) 12%, transparent); }
.wpm-urlbox { margin-top:1rem; padding-top:1rem; border-top:1px solid var(--border); }
.wpm-urlrow { display:flex; gap:.5rem; align-items:center; }
.wpm-urlrow .svq-input { flex:1; }
.mono { font-family: var(--font-mono, monospace); }

/* ── Pane Seguridad ── */
.wpm-attack { display:flex; gap:.75rem; padding:.85rem 1rem; margin-bottom:1rem;
  border:1px solid color-mix(in srgb, var(--danger) 45%, var(--border));
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-radius: var(--radius-md); }
.wpm-attack__icon { color: var(--danger); font-size:1.4rem; line-height:1; padding-top:.1rem; }
.wpm-attack__body { flex:1; }
.wpm-attack__body strong { color: var(--danger); }
.wpm-attack__body p { margin:.35rem 0 .6rem; font-size:.88rem; color: var(--text); }
.wpm-attack__body code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.82rem; }
.wpm-sec { display:flex; flex-direction:column; gap:.25rem; }
.wpm-sec__row { display:flex; align-items:center; justify-content:space-between; gap:1rem;
  padding:.85rem 0; border-bottom:1px solid var(--border); }
.wpm-sec__row:last-child { border-bottom:none; }
.wpm-sec__info { flex:1; }
.wpm-sec__title { display:flex; align-items:center; gap:.45rem; font-weight:600; margin-bottom:.2rem; }
.wpm-sec__info small { display:block; line-height:1.4; }
.wpm-sec__info code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.8rem; }
.wpm-sec__rl { display:flex; align-items:center; gap:.5rem; white-space:nowrap; }
/* toggle basado en clase (no depende de :checked, robusto frente a CSS global) */
.wpm-toggle { position:relative; flex-shrink:0; width:44px; height:24px; padding:0;
  border:1px solid var(--border); border-radius:999px; background: var(--surface-inset);
  cursor:pointer; transition: background .2s, border-color .2s; }
.wpm-toggle__knob { position:absolute; top:2px; left:2px; width:18px; height:18px;
  background:#fff; border-radius:50%; transition: transform .2s; box-shadow:0 1px 2px rgba(0,0,0,.25); }
.wpm-toggle.is-on { background: var(--accent, #6366f1); border-color: var(--accent, #6366f1); }
.wpm-toggle.is-on .wpm-toggle__knob { transform: translateX(20px); }
.wpm-toggle:disabled { opacity:.55; cursor:not-allowed; }
</style>
