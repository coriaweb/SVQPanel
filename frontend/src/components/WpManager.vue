<template>
  <BaseCard title="WordPress instalado" icon="wordpress">
    <template #actions>
      <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="loadingInfo" @click="loadInfo">Refrescar</BaseButton>
    </template>

    <div v-if="loadingInfo && !info" class="wpm-loading"><span class="spinner"></span> Analizando la instalación…</div>
    <div v-else-if="errorInfo" class="wpm-error"><i class="bi bi-exclamation-triangle"></i> {{ errorInfo }}</div>

    <template v-else-if="info">
      <!-- Resumen -->
      <div class="wpm-summary">
        <div class="wpm-stat"><span class="wpm-stat__k">Versión WP</span><span class="wpm-stat__v mono">{{ info.version || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Idioma</span><span class="wpm-stat__v">{{ info.locale || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Plugins</span><span class="wpm-stat__v">{{ info.plugins_active }}/{{ info.plugins_total }} activos</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Temas</span><span class="wpm-stat__v">{{ info.themes_total }}</span></div>
      </div>

      <!-- Avisos de actualización -->
      <div v-if="totalUpdates > 0" class="wpm-updbanner">
        <i class="bi bi-arrow-up-circle"></i>
        <span>Hay <strong>{{ totalUpdates }}</strong> actualización(es) pendiente(s):
          <template v-if="info.updates.core">core, </template>
          <template v-if="info.updates.plugins">{{ info.updates.plugins }} plugin(s), </template>
          <template v-if="info.updates.themes">{{ info.updates.themes }} tema(s)</template>
        </span>
      </div>
      <div v-else class="wpm-uptodate"><i class="bi bi-check-circle"></i> Todo está actualizado.</div>

      <BaseTabs v-model="tab" :tabs="tabs" />

      <!-- ── Tab General ── -->
      <div v-if="tab === 'general'" class="wpm-pane">
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
    </template>
  </BaseCard>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseTabs from './ui/BaseTabs.vue'

export default {
  name: 'WpManager',
  components: { BaseCard, BaseButton, BaseTabs },
  props: {
    domainId:   { type: [Number, String], required: true },
    domainName: { type: String, default: '' },
  },
  setup(props) {
    const store = useMainStore()
    // domainId puede llegar como string desde route.params; lo normalizamos a
    // entero válido. Si no lo es (montaje temprano), no lanzamos peticiones.
    const did = computed(() => {
      const n = parseInt(props.domainId, 10)
      return Number.isInteger(n) ? n : null
    })
    const info = ref(null)
    const loadingInfo = ref(false)
    const errorInfo = ref('')
    const tab = ref('general')
    const tabs = [
      { key: 'general', label: 'General', icon: 'speedometer2' },
      { key: 'plugins', label: 'Plugins', icon: 'plug' },
      { key: 'themes',  label: 'Temas',   icon: 'palette' },
      { key: 'access',  label: 'Acceso',  icon: 'key' },
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

    const loadInfo = async () => {
      if (did.value == null) return
      loadingInfo.value = true; errorInfo.value = ''
      try {
        const r = await api.getWpInfo(did.value)
        info.value = r.data
        newUrl.value = r.data.siteurl || ''
      } catch (e) { errorInfo.value = e.message || 'No pude leer la instalación' }
      finally { loadingInfo.value = false }
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

    // Ejecuta una acción genérica; refresca info/listado al terminar.
    const run = async (action, payload, busyId) => {
      if (did.value == null) return
      busy.value = busyId || action
      try {
        const r = await api.wpAction(did.value, action, payload)
        store.showNotification(r.data?.output || r.data?.note || 'Hecho', 'success')
        await loadInfo()
        if (action === 'update-items' || action === 'toggle-item') await loadItems()
        return r.data
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally { busy.value = '' }
    }

    const toggleMaintenance = () => run('maintenance', { enable: !info.value.maintenance }, 'maint')

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

    // Cargar listado al entrar en las pestañas de plugins/temas
    watch(tab, (t) => {
      if ((t === 'plugins' || t === 'themes')) loadItems()
      if (t === 'access' && !admins.value.length) loadAdmins()
    })

    // Cargar info cuando el componente esté montado y el id sea válido. Si el id
    // se resuelve más tarde (route.params aún no listo), el watch lo reintenta.
    onMounted(loadInfo)
    watch(did, (v, prev) => { if (v != null && prev == null) loadInfo() })

    return {
      info, loadingInfo, errorInfo, tab, tabs, busy, items, loadingItems,
      admins, loadingUsers, resetResult, newUrl, itemKind, totalUpdates, adminUrl,
      loadInfo, loadItems, loadAdmins, run, toggleMaintenance, confirmSalts,
      resetPw, changeUrl, statusLabel,
    }
  },
}
</script>

<style scoped>
.wpm-loading, .wpm-error { display:flex; align-items:center; gap:.5rem; padding:.75rem 0; color: var(--text-muted); }
.wpm-error { color: var(--danger); }
.wpm-summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap:.5rem; margin-bottom:.75rem; }
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
.wpm-badge { font-size:.72rem; padding:.15rem .5rem; border-radius:999px; }
.wpm-badge.is-on { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.wpm-badge.is-off { background: var(--surface-inset); color: var(--text-muted); }
.wpm-rowactions { white-space:nowrap; text-align:right; }
.wpm-mini { background:none; border:1px solid var(--border); border-radius: var(--radius-sm); width:30px; height:30px; cursor:pointer; color: var(--text); margin-left:.25rem; }
.wpm-mini:hover:not(:disabled) { background: var(--surface-inset); }
.wpm-mini:disabled { opacity:.5; cursor:not-allowed; }
.wpm-urlbox { margin-top:1rem; padding-top:1rem; border-top:1px solid var(--border); }
.wpm-urlrow { display:flex; gap:.5rem; align-items:center; }
.wpm-urlrow .svq-input { flex:1; }
.mono { font-family: var(--font-mono, monospace); }
</style>
