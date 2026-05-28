<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-globe"></i> Dominios</h2>
      <button class="btn btn-primary" @click="openCreateForm">
        <i class="bi bi-plus-circle"></i> Crear Dominio
      </button>
    </div>

    <!-- Filtro por usuario (solo admin/reseller) -->
    <div v-if="isAdminOrReseller" class="mb-3">
      <select v-model="selectedUser" class="form-select" @change="loadDomains">
        <option value="">Todos los usuarios</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }}
        </option>
      </select>
    </div>

    <!-- Tabla de dominios -->
    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="domains.length === 0" class="alert alert-info m-3 mb-0">
          No hay dominios creados aún
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Dominio</th>
                <th v-if="isAdminOrReseller">Usuario</th>
                <th>PHP</th>
                <th>SSL</th>
                <th>IPv6</th>
                <th>Cache</th>
                <th>Tamaño</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="domain in domains" :key="domain.id">
                <td>
                  <i class="bi bi-globe text-primary me-1"></i>
                  <a :href="'http://' + domain.domain_name" target="_blank" class="text-decoration-none fw-semibold">
                    {{ domain.domain_name }}
                  </a>
                </td>
                <td v-if="isAdminOrReseller">{{ getUserName(domain.user_id) }}</td>
                <td>
                  <select
                    class="form-select form-select-sm"
                    style="min-width:100px"
                    @change="changePHP(domain, $event)"
                  >
                    <option
                      v-for="v in phpVersions"
                      :key="v"
                      :value="v"
                      :selected="v === domain.php_version"
                    >PHP {{ v }}</option>
                  </select>
                </td>
                <td>
                  <span v-if="domain.ssl_enabled" class="badge bg-success">
                    <i class="bi bi-lock-fill me-1"></i>SSL
                  </span>
                  <span v-else class="badge bg-light text-secondary border">
                    <i class="bi bi-unlock me-1"></i>No
                  </span>
                </td>
                <td>
                  <span
                    v-if="domain.ipv6"
                    class="badge bg-primary font-monospace"
                    style="font-size:.7rem; cursor:pointer"
                    :title="domain.ipv6"
                    @click="openIPv6Manager(domain)"
                  >
                    <i class="bi bi-diagram-3 me-1"></i>{{ domain.ipv6.slice(-8) }}…
                  </span>
                  <button
                    v-else
                    class="btn btn-outline-secondary btn-sm py-0"
                    style="font-size:.75rem"
                    @click="openIPv6Manager(domain)"
                    title="Asignar IPv6"
                  >
                    <i class="bi bi-plus-circle me-1"></i>IPv6
                  </button>
                </td>
                <td>
                  <button
                    class="btn btn-sm py-0 px-1"
                    :class="domain.fastcgi_cache_enabled ? 'btn-success' : 'btn-outline-secondary'"
                    :title="domain.fastcgi_cache_enabled
                            ? `FastCGI cache activo (${domain.fastcgi_cache_ttl_minutes}m)`
                            : 'FastCGI cache desactivado — clic para configurar'"
                    @click="openCacheManager(domain)"
                  >
                    <i :class="domain.fastcgi_cache_enabled ? 'bi bi-lightning-fill' : 'bi bi-lightning'"></i>
                  </button>
                </td>
                <td>
                  <span v-if="diskInfo[domain.id]" class="small font-monospace" :title="`public_html: ${formatMB(diskInfo[domain.id].public_html_mb)} — logs: ${formatMB(diskInfo[domain.id].logs_mb)}`">
                    {{ formatMB(diskInfo[domain.id].public_html_mb) }}
                  </span>
                  <button v-else class="btn btn-link btn-sm py-0 px-1" @click="loadDiskInfo(domain)">
                    <i class="bi bi-hdd"></i>
                  </button>
                </td>
                <td>
                  <span v-if="domain.is_active" class="badge bg-success">Activo</span>
                  <span v-else class="badge bg-danger">Inactivo</span>
                </td>
                <td>
                  <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-dark" @click="openPhpManager(domain)" title="Configuración PHP (php.ini)">
                      <i class="bi bi-filetype-php"></i>
                    </button>
                    <button class="btn btn-outline-info" @click="openLogsViewer(domain)" title="Ver registros (access/error)">
                      <i class="bi bi-binoculars"></i>
                    </button>
                    <button class="btn btn-outline-success" @click="openSSLManager(domain)" title="SSL">
                      <i class="bi bi-lock"></i>
                    </button>
                    <button class="btn btn-outline-primary" @click="openIPv6Manager(domain)" title="IPv6">
                      <i class="bi bi-diagram-3"></i>
                    </button>
                    <button class="btn btn-outline-secondary" @click="openFileManager(domain)" title="Archivos">
                      <i class="bi bi-folder2-open"></i>
                    </button>
                    <button class="btn btn-outline-warning" @click="openEditForm(domain)" title="Editar">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger" @click="deleteDomainConfirm(domain.id)" title="Eliminar">
                      <i class="bi bi-trash"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal: crear/editar dominio -->
    <Modal :isOpen="showDomainForm" :title="editingDomain ? 'Editar Dominio' : 'Crear Dominio'" @close="closeDomainForm">
      <DomainForm
        :domain="editingDomain"
        :phpVersions="phpVersions"
        @submit="handleDomainSubmit"
        @cancel="closeDomainForm"
      />
    </Modal>

    <!-- Modal: SSL -->
    <Modal v-if="selectedDomain" :isOpen="showSSLManager" :title="'SSL — ' + selectedDomain.domain_name" @close="closeSSLManager">
      <SSLManager :domain="selectedDomain" @reload="reloadDomains" />
    </Modal>

    <!-- Modal: IPv6 -->
    <Modal v-if="selectedDomain" :isOpen="showIPv6Manager" :title="'IPv6 — ' + selectedDomain.domain_name" @close="closeIPv6Manager">
      <IPv6Manager :domain="selectedDomain" @reload="reloadDomains" />
    </Modal>

    <!-- Modal: FastCGI cache por dominio -->
    <Modal v-if="cacheDomain" :isOpen="showCacheManager"
           :title="'FastCGI Cache — ' + cacheDomain.domain_name" @close="closeCacheManager">
      <div class="mb-3">
        <p class="small text-muted mb-2">
          Cachea las respuestas de PHP-FPM directamente en nginx. Acelera mucho sitios estáticos/WordPress
          de lectura. <strong>Bypass automático</strong> para POST, query strings, admin de WordPress y
          usuarios logueados (cookies WP/WooCommerce).
        </p>
        <div class="form-check form-switch mb-3">
          <input class="form-check-input" type="checkbox" id="cacheSwitch"
                 v-model="cacheForm.enabled" :disabled="cacheSaving">
          <label class="form-check-label" for="cacheSwitch">
            <strong>{{ cacheForm.enabled ? 'Cache activa' : 'Cache desactivada' }}</strong>
          </label>
        </div>
        <div v-if="cacheForm.enabled" class="mb-3">
          <label class="form-label small">TTL (minutos)</label>
          <input type="number" class="form-control form-control-sm" style="max-width: 200px;"
                 v-model.number="cacheForm.ttl_minutes" min="1" max="1440">
          <small class="text-muted">Tiempo de vida de cada página cacheada. Default: 60 minutos.</small>
        </div>
      </div>

      <div class="d-flex gap-2 justify-content-between">
        <button v-if="cacheDomain.fastcgi_cache_enabled"
                class="btn btn-sm btn-outline-warning" @click="purgeCache" :disabled="cacheSaving">
          <i class="bi bi-trash3 me-1"></i> Purgar cache ahora
        </button>
        <div class="d-flex gap-2 ms-auto">
          <button class="btn btn-sm btn-outline-secondary" @click="closeCacheManager" :disabled="cacheSaving">
            Cancelar
          </button>
          <button class="btn btn-sm btn-primary" @click="saveCache" :disabled="cacheSaving">
            <span v-if="cacheSaving" class="spinner-border spinner-border-sm me-1"></span>
            Guardar y aplicar
          </button>
        </div>
      </div>
    </Modal>

    <!-- Modal: configuración PHP por dominio -->
    <Modal v-if="phpDomain" :isOpen="showPhpManager"
           :title="'PHP — ' + phpDomain.domain_name" @close="closePhpManager">
      <div v-if="phpLoading" class="text-center py-4">
        <div class="spinner-border spinner-border-sm"></div>
      </div>
      <div v-else>
        <p class="small text-muted mb-3">
          Ajustes php.ini propios de este dominio (PHP {{ phpDomain.php_version }}).
          Vacío = usa el valor global del servidor. <strong>No puedes superar el límite del servidor.</strong>
        </p>

        <table class="table table-sm align-middle">
          <thead class="table-light">
            <tr>
              <th>Directiva</th>
              <th style="width: 140px;">Valor</th>
              <th style="width: 120px;">Servidor</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(spec, key) in phpDirectives" :key="key">
              <td>
                <div>{{ spec.label }}</div>
                <code class="small text-muted">{{ key }}</code>
              </td>
              <td>
                <select v-if="spec.type === 'bool'" class="form-select form-select-sm" v-model="phpForm[key]">
                  <option value="">(servidor)</option>
                  <option value="On">On</option>
                  <option value="Off">Off</option>
                </select>
                <input v-else class="form-control form-control-sm" v-model="phpForm[key]"
                       :placeholder="phpDefaults[key] || '(servidor)'">
              </td>
              <td class="small text-muted font-monospace">{{ phpDefaults[key] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>

        <div class="d-flex justify-content-between mt-3">
          <small class="text-muted align-self-center">
            <i class="bi bi-info-circle me-1"></i>
            <span v-if="phpHasPool" class="text-success">Pool dedicado activo</span>
            <span v-else>Usando php.ini global</span>
          </small>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" @click="closePhpManager" :disabled="phpSaving">Cancelar</button>
            <button class="btn btn-sm btn-primary" @click="savePhpConfig" :disabled="phpSaving">
              <span v-if="phpSaving" class="spinner-border spinner-border-sm me-1"></span>
              Guardar y aplicar
            </button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- Modal: visor de logs por dominio -->
    <Modal v-if="logsDomain" :isOpen="showLogsViewer" :title="'Registros — ' + logsDomain.domain_name" @close="closeLogsViewer">
      <div class="mb-2 d-flex justify-content-between align-items-center">
        <ul class="nav nav-pills nav-sm">
          <li class="nav-item">
            <a class="nav-link" :class="{active: logTab==='access'}" href="#" @click.prevent="switchLog('access')">
              <i class="bi bi-file-text me-1"></i> access.log
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" :class="{active: logTab==='error'}" href="#" @click.prevent="switchLog('error')">
              <i class="bi bi-bug me-1"></i> error.log
            </a>
          </li>
        </ul>
        <div class="d-flex gap-2 align-items-center">
          <select v-model.number="logLines" @change="loadLogs" class="form-select form-select-sm" style="width: 110px;">
            <option :value="50">50 líneas</option>
            <option :value="200">200</option>
            <option :value="500">500</option>
            <option :value="2000">2000</option>
          </select>
          <button class="btn btn-sm btn-outline-secondary" @click="loadLogs" title="Refrescar">
            <i class="bi bi-arrow-clockwise"></i>
          </button>
        </div>
      </div>

      <div v-if="logsLoading" class="text-center py-4">
        <div class="spinner-border spinner-border-sm"></div>
      </div>
      <div v-else-if="!logsData.exists" class="alert alert-info">
        {{ logsData.message || 'Sin datos.' }}
        <div class="small text-muted mt-1 font-monospace">{{ logsData.path }}</div>
      </div>
      <div v-else>
        <div class="small text-muted mb-2 font-monospace">{{ logsData.path }} — {{ logsData.count }} líneas</div>
        <pre class="bg-dark text-light p-2 rounded" style="max-height: 60vh; overflow:auto; font-size: 11px; white-space: pre-wrap; word-break: break-all;">{{ logsData.lines.join('\n') }}</pre>
      </div>
    </Modal>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import DomainForm from '../components/DomainForm.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'

export default {
  name: 'Domains',
  components: { Modal, DomainForm, SSLManager, IPv6Manager },
  setup() {
    const store = useMainStore()
    const router = useRouter()

    const domains      = ref([])
    const users        = ref([])
    const phpVersions  = ref([])
    const selectedUser = ref('')
    const loading      = ref(false)

    const showDomainForm  = ref(false)
    const showSSLManager  = ref(false)
    const showIPv6Manager = ref(false)
    const editingDomain   = ref(null)
    const selectedDomain  = ref(null)

    // Logs por dominio
    const showLogsViewer = ref(false)
    const logsDomain     = ref(null)
    const logTab         = ref('access')
    const logLines       = ref(200)
    const logsData       = ref({ exists: false, lines: [], path: '' })
    const logsLoading    = ref(false)

    // Disco por dominio (cache: {domainId: {public_html_mb, ...}})
    const diskInfo = ref({})

    // FastCGI cache
    const showCacheManager = ref(false)
    const cacheDomain      = ref(null)
    const cacheForm        = ref({ enabled: false, ttl_minutes: 60 })
    const cacheSaving      = ref(false)

    // PHP config (php.ini por dominio)
    const showPhpManager = ref(false)
    const phpDomain      = ref(null)
    const phpLoading     = ref(false)
    const phpSaving      = ref(false)
    const phpDirectives  = ref({})
    const phpDefaults    = ref({})
    const phpForm        = ref({})
    const phpHasPool     = ref(false)

    // Rol del usuario actual
    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    // ─── Carga de datos ───────────────────────────────────────────────────────

    const loadDomains = async () => {
      loading.value = true
      try {
        const data = await api.getDomains(selectedUser.value || null)
        domains.value = Array.isArray(data) ? data : []
        // Cargar disk info para todos los dominios en paralelo (no bloqueante)
        diskInfo.value = {}
        for (const d of domains.value) loadDiskInfo(d)
      } catch (e) {
        store.showNotification('Error al cargar dominios', 'danger')
      } finally {
        loading.value = false
      }
    }

    const loadDiskInfo = async (domain) => {
      try {
        const info = await api.getDomainDisk(domain.id)
        diskInfo.value = { ...diskInfo.value, [domain.id]: info }
      } catch (e) {
        // silencioso: el botón quedará disponible para reintentar
      }
    }

    const formatMB = (mb) => {
      if (!mb) return '0 MB'
      if (mb >= 1024) return (mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1) + ' GB'
      return mb + ' MB'
    }

    // ─── FastCGI cache ───────────────────────────────────────────────────────
    const openCacheManager = (d) => {
      cacheDomain.value = d
      cacheForm.value = {
        enabled: d.fastcgi_cache_enabled || false,
        ttl_minutes: d.fastcgi_cache_ttl_minutes || 60,
      }
      showCacheManager.value = true
    }
    const closeCacheManager = () => {
      showCacheManager.value = false
      cacheDomain.value = null
    }
    const saveCache = async () => {
      cacheSaving.value = true
      try {
        await api.setDomainCache(cacheDomain.value.id, cacheForm.value.enabled, cacheForm.value.ttl_minutes)
        store.showNotification(cacheForm.value.enabled ? 'Cache activada' : 'Cache desactivada', 'success')
        closeCacheManager()
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        cacheSaving.value = false
      }
    }
    const purgeCache = async () => {
      if (!confirm(`¿Purgar la cache de ${cacheDomain.value.domain_name}?`)) return
      cacheSaving.value = true
      try {
        const r = await api.purgeDomainCache(cacheDomain.value.id)
        store.showNotification(`Cache purgada — ${r.freed_mb} MB liberados`, 'success')
      } catch (e) {
        store.showNotification('Error purgando: ' + e.message, 'danger')
      } finally {
        cacheSaving.value = false
      }
    }

    // ─── PHP config ──────────────────────────────────────────────────────────
    const openPhpManager = async (domain) => {
      phpDomain.value = domain
      showPhpManager.value = true
      phpLoading.value = true
      try {
        const cfg = await api.getDomainPhpConfig(domain.id)
        phpDirectives.value = cfg.directives || {}
        phpDefaults.value   = cfg.server_defaults || {}
        phpHasPool.value    = cfg.has_pool
        // Inicializar el form: override actual o vacío
        const form = {}
        for (const key of Object.keys(phpDirectives.value)) {
          form[key] = (cfg.overrides && cfg.overrides[key] != null) ? cfg.overrides[key] : ''
        }
        phpForm.value = form
      } catch (e) {
        store.showNotification('Error cargando config PHP: ' + e.message, 'danger')
      } finally {
        phpLoading.value = false
      }
    }
    const closePhpManager = () => {
      showPhpManager.value = false
      phpDomain.value = null
    }
    const savePhpConfig = async () => {
      phpSaving.value = true
      try {
        // Enviar solo los no vacíos
        const overrides = {}
        for (const [k, v] of Object.entries(phpForm.value)) {
          if (String(v).trim() !== '') overrides[k] = String(v).trim()
        }
        await api.setDomainPhpConfig(phpDomain.value.id, overrides)
        store.showNotification('Configuración PHP aplicada', 'success')
        closePhpManager()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        phpSaving.value = false
      }
    }

    // ─── Logs ────────────────────────────────────────────────────────────────
    const openLogsViewer = (domain) => {
      logsDomain.value = domain
      logTab.value = 'access'
      showLogsViewer.value = true
      loadLogs()
    }
    const closeLogsViewer = () => {
      showLogsViewer.value = false
      logsDomain.value = null
      logsData.value = { exists: false, lines: [], path: '' }
    }
    const switchLog = (t) => {
      logTab.value = t
      loadLogs()
    }
    const loadLogs = async () => {
      if (!logsDomain.value) return
      logsLoading.value = true
      try {
        logsData.value = await api.getDomainLogs(logsDomain.value.id, logTab.value, logLines.value)
      } catch (e) {
        store.showNotification('Error cargando logs: ' + e.message, 'danger')
        logsData.value = { exists: false, lines: [], path: '', message: e.message }
      } finally {
        logsLoading.value = false
      }
    }

    const reloadDomains = async () => {
      await loadDomains()
      // Si hay un modal de IPv6 abierto, actualiza el domain seleccionado
      if (selectedDomain.value) {
        const fresh = domains.value.find(d => d.id === selectedDomain.value.id)
        if (fresh) selectedDomain.value = { ...fresh }
      }
    }

    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return   // usuarios normales no necesitan la lista
      try {
        const data = await api.getUsers()
        users.value = Array.isArray(data) ? data : []
      } catch {
        // silencioso — el filtro simplemente no aparece si falla
      }
    }

    const loadPHPVersions = async () => {
      try {
        const data = await api.getPHPVersions()
        phpVersions.value = data?.versions?.length ? data.versions : ['8.2']
      } catch {
        phpVersions.value = ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5']
      }
    }

    const getUserName = (userId) => {
      const user = users.value.find(u => u.id === userId)
      return user ? user.username : `#${userId}`
    }

    // ─── Acciones ─────────────────────────────────────────────────────────────

    const openCreateForm = () => { editingDomain.value = null; showDomainForm.value = true }
    const openEditForm   = (d) => { editingDomain.value = d;    showDomainForm.value = true }
    const closeDomainForm= () => { showDomainForm.value = false; editingDomain.value = null }

    const handleDomainSubmit = async () => { await loadDomains(); closeDomainForm() }

    const openSSLManager  = (d) => { selectedDomain.value = d; showSSLManager.value = true }
    const closeSSLManager = () => { showSSLManager.value = false; selectedDomain.value = null }

    const openIPv6Manager  = (d) => { selectedDomain.value = { ...d }; showIPv6Manager.value = true }
    const closeIPv6Manager = () => { showIPv6Manager.value = false; selectedDomain.value = null }
    const openFileManager = (d) => { router.push({ path: '/files', query: { domain: d.id } }) }

    const deleteDomainConfirm = (domainId) => {
      if (confirm('¿Eliminar este dominio? Se borrarán todos sus archivos.')) {
        api.deleteDomain(domainId)
          .then(() => { store.showNotification('Dominio eliminado', 'success'); loadDomains() })
          .catch(e => store.showNotification('Error al eliminar: ' + e.message, 'danger'))
      }
    }

    const changePHP = async (domain, event) => {
      const version = event.target.value
      try {
        await api.changePHPVersion(domain.id, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'danger')
        await loadDomains()   // revertir el select visualmente
      }
    }

    onMounted(async () => {
      await Promise.all([loadPHPVersions(), loadUsers(), loadDomains()])
    })

    return {
      domains, users, phpVersions, selectedUser, loading,
      isAdminOrReseller,
      showDomainForm, showSSLManager, showIPv6Manager,
      editingDomain, selectedDomain,
      openCreateForm, openEditForm, closeDomainForm, handleDomainSubmit,
      openSSLManager, closeSSLManager,
      openIPv6Manager, closeIPv6Manager,
      openFileManager,
      deleteDomainConfirm, changePHP,
      loadDomains, reloadDomains, getUserName,
      // Logs + disk
      showLogsViewer, logsDomain, logTab, logLines, logsData, logsLoading,
      diskInfo, loadDiskInfo, formatMB,
      openLogsViewer, closeLogsViewer, switchLog, loadLogs,
      // FastCGI cache
      showCacheManager, cacheDomain, cacheForm, cacheSaving,
      openCacheManager, closeCacheManager, saveCache, purgeCache,
      // PHP config
      showPhpManager, phpDomain, phpLoading, phpSaving,
      phpDirectives, phpDefaults, phpForm, phpHasPool,
      openPhpManager, closePhpManager, savePhpConfig,
    }
  }
}
</script>
