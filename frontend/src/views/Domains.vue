<template>
  <div class="domains-view">
    <!-- Cabecera -->
    <header class="page-head">
      <div>
        <h1 class="page-title">Dominios</h1>
        <p class="page-sub">
          {{ domains.length }} {{ domains.length === 1 ? 'dominio' : 'dominios' }}
          <template v-if="domains.length"> · {{ sslCount }} con SSL</template>
        </p>
      </div>
      <div class="page-head__actions">
        <select v-if="isAdminOrReseller" v-model="selectedUser" class="svq-select" @change="loadDomains">
          <option value="">Todos los usuarios</option>
          <option v-for="user in users" :key="user.id" :value="user.id">{{ user.username }}</option>
        </select>
        <div class="view-toggle">
          <button :class="{ active: viewMode === 'cards' }" @click="viewMode = 'cards'" title="Tarjetas"><i class="bi bi-grid"></i></button>
          <button :class="{ active: viewMode === 'table' }" @click="viewMode = 'table'" title="Tabla"><i class="bi bi-list-ul"></i></button>
        </div>
        <BaseButton variant="primary" icon="plus-lg" @click="openCreateForm">Crear dominio</BaseButton>
      </div>
    </header>

    <!-- Carga -->
    <div v-if="loading" class="cards-grid">
      <div v-for="n in 6" :key="n" class="svq-skeleton" style="height:200px;border-radius:var(--r-lg)"></div>
    </div>

    <!-- Vacío -->
    <BaseCard v-else-if="domains.length === 0">
      <EmptyState icon="globe2" title="Aún no hay dominios"
        description="Crea tu primer dominio para empezar a alojar sitios web.">
        <BaseButton variant="primary" icon="plus-lg" @click="openCreateForm">Crear dominio</BaseButton>
      </EmptyState>
    </BaseCard>

    <!-- ===== Vista de tarjetas ===== -->
    <div v-else-if="viewMode === 'cards'" class="cards-grid">
      <article v-for="domain in domains" :key="domain.id" class="dcard" :class="`dcard--${domainTone(domain)}`">
        <div class="dcard__head">
          <div class="dcard__title">
            <i class="bi bi-globe2"></i>
            <a :href="'http://' + domain.domain_name" target="_blank" class="dcard__name" @click.stop>{{ domain.domain_name }}</a>
          </div>
          <StatusBadge
            :status="domain.is_suspended ? 'warning' : (domain.is_active ? 'active' : 'error')"
            :label="domain.is_suspended ? 'Suspendido' : (domain.is_active ? 'Activo' : 'Inactivo')" />
        </div>

        <p v-if="isAdminOrReseller" class="dcard__owner"><i class="bi bi-person"></i> {{ getUserName(domain.user_id) }}</p>

        <div class="dcard__stats">
          <div class="dstat">
            <span class="dstat__k">SSL</span>
            <StatusBadge :status="domain.ssl_enabled ? 'valid' : 'none'"
              :label="domain.ssl_enabled ? 'Activo' : 'Sin SSL'"
              :icon="domain.ssl_enabled ? 'lock-fill' : 'unlock'" :dot="false" />
          </div>
          <div class="dstat">
            <span class="dstat__k">PHP</span>
            <span class="dstat__v mono">{{ domain.php_version || '—' }}</span>
          </div>
          <div class="dstat">
            <span class="dstat__k">Cache</span>
            <StatusBadge :status="domain.fastcgi_cache_enabled ? 'active' : 'none'"
              :label="domain.fastcgi_cache_enabled ? 'On' : 'Off'"
              :icon="domain.fastcgi_cache_enabled ? 'lightning-fill' : 'lightning'" :dot="false" />
          </div>
          <div class="dstat">
            <span class="dstat__k">Tamaño</span>
            <span v-if="diskInfo[domain.id]" class="dstat__v mono">{{ formatMB(diskInfo[domain.id].public_html_mb) }}</span>
            <button v-else class="dstat__load" @click="loadDiskInfo(domain)"><i class="bi bi-hdd"></i></button>
          </div>
        </div>

        <div class="dcard__actions">
          <BaseButton variant="subtle" size="sm" icon="box-arrow-in-right" tag="router-link" v-bind="{ to: `/domains/${domain.id}` }">Abrir</BaseButton>
          <BaseButton variant="ghost" size="sm" icon="lock" @click="openSSLManager(domain)">SSL</BaseButton>
          <div class="dcard__more">
            <button class="more-btn" @click="toggleMenu(domain.id)" title="Más acciones"><i class="bi bi-three-dots"></i></button>
            <div class="more-menu" v-if="openMenuId === domain.id" v-click-away="() => openMenuId = null">
              <button @click="run(openPhpManager, domain)"><i class="bi bi-filetype-php"></i> Configuración PHP</button>
              <button @click="run(openCacheManager, domain)"><i class="bi bi-lightning"></i> FastCGI cache</button>
              <button @click="run(openLogsViewer, domain)"><i class="bi bi-binoculars"></i> Ver registros</button>
              <button @click="run(openIPv6Manager, domain)"><i class="bi bi-diagram-3"></i> IPv6</button>
              <button @click="run(changePHPPrompt, domain)"><i class="bi bi-arrow-repeat"></i> Cambiar PHP</button>
              <button @click="run(openEditForm, domain)"><i class="bi bi-pencil"></i> Editar</button>
              <button @click="run(downloadSite, domain)" :disabled="downloadingId === domain.id"><i class="bi bi-download"></i> Descargar sitio</button>
              <button v-if="!domain.is_suspended" @click="run(suspendDomain, domain)"><i class="bi bi-pause-circle"></i> Suspender</button>
              <button v-else @click="run(unsuspendDomain, domain)"><i class="bi bi-play-circle"></i> Reactivar</button>
              <div class="more-sep"></div>
              <button class="is-danger" @click="run(() => deleteDomainConfirm(domain.id))"><i class="bi bi-trash"></i> Eliminar</button>
            </div>
          </div>
        </div>
      </article>
    </div>

    <!-- ===== Vista de tabla (compacta) ===== -->
    <BaseCard v-else flush>
      <div class="table-wrap">
        <table class="svq-table">
          <thead>
            <tr>
              <th>Dominio</th>
              <th v-if="isAdminOrReseller">Usuario</th>
              <th>PHP</th>
              <th>SSL</th>
              <th>Cache</th>
              <th>Tamaño</th>
              <th>Estado</th>
              <th class="ta-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="domain in domains" :key="domain.id">
              <td>
                <router-link :to="`/domains/${domain.id}`" class="t-domain"><i class="bi bi-globe2"></i>{{ domain.domain_name }}</router-link>
              </td>
              <td v-if="isAdminOrReseller" class="t-muted">{{ getUserName(domain.user_id) }}</td>
              <td class="mono">{{ domain.php_version || '—' }}</td>
              <td><StatusBadge :status="domain.ssl_enabled ? 'valid' : 'none'" :label="domain.ssl_enabled ? 'SSL' : 'No'" :dot="false" /></td>
              <td><StatusBadge :status="domain.fastcgi_cache_enabled ? 'active' : 'none'" :label="domain.fastcgi_cache_enabled ? 'On' : 'Off'" :dot="false" /></td>
              <td class="mono t-muted">{{ diskInfo[domain.id] ? formatMB(diskInfo[domain.id].public_html_mb) : '—' }}</td>
              <td>
                <StatusBadge :status="domain.is_suspended ? 'warning' : (domain.is_active ? 'active' : 'error')"
                  :label="domain.is_suspended ? 'Suspendido' : (domain.is_active ? 'Activo' : 'Inactivo')" />
              </td>
              <td class="ta-end">
                <div class="t-actions">
                  <router-link class="icon-act" :to="`/domains/${domain.id}`" title="Ver detalle"><i class="bi bi-box-arrow-in-right"></i></router-link>
                  <button class="icon-act" @click="openSSLManager(domain)" title="SSL"><i class="bi bi-lock"></i></button>
                  <button class="icon-act" @click="openFileManager(domain)" title="Archivos"><i class="bi bi-folder2-open"></i></button>
                  <button class="icon-act" @click="openEditForm(domain)" title="Editar"><i class="bi bi-pencil"></i></button>
                  <button class="icon-act is-danger" @click="deleteDomainConfirm(domain.id)" title="Eliminar"><i class="bi bi-trash"></i></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

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
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import DomainForm from '../components/DomainForm.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import EmptyState from '../components/ui/EmptyState.vue'

// Directiva ligera para cerrar menús al hacer clic fuera
const clickAway = {
  mounted(el, binding) {
    el._away = (e) => { if (!el.contains(e.target)) binding.value(e) }
    setTimeout(() => document.addEventListener('click', el._away), 0)
  },
  unmounted(el) { document.removeEventListener('click', el._away) },
}

export default {
  name: 'Domains',
  components: { Modal, DomainForm, SSLManager, IPv6Manager, BaseCard, BaseButton, StatusBadge, EmptyState },
  directives: { clickAway },
  setup() {
    const store = useMainStore()
    const router = useRouter()

    const domains      = ref([])
    const users        = ref([])
    const phpVersions  = ref([])
    const selectedUser = ref('')
    const loading      = ref(false)
    const viewMode     = ref(localStorage.getItem('domainsView') || 'cards')
    const openMenuId   = ref(null)

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

    const downloadingId = ref(null)
    const downloadSite = async (domain) => {
      downloadingId.value = domain.id
      try {
        store.showNotification(`Preparando descarga de ${domain.domain_name}…`, 'info')
        const { blob, filename } = await api.downloadDomainSite(domain.id)
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      } catch (e) {
        store.showNotification(`Error al descargar: ${e.message}`, 'danger')
      } finally {
        downloadingId.value = null
      }
    }

    const suspendDomain = async (domain) => {
      if (!confirm(`¿Suspender el dominio ${domain.domain_name}? Quedará inaccesible hasta que lo reactives.`)) return
      try {
        await api.suspendDomain(domain.id)
        store.showNotification(`Dominio ${domain.domain_name} suspendido`, 'warning')
        await loadDomains()
      } catch (e) {
        store.showNotification(`Error al suspender: ${e.message}`, 'danger')
      }
    }

    const unsuspendDomain = async (domain) => {
      try {
        await api.unsuspendDomain(domain.id)
        store.showNotification(`Dominio ${domain.domain_name} reactivado`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification(`Error al reactivar: ${e.message}`, 'danger')
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

    // ─── Vista tarjetas: helpers UI ────────────────────────────────────────────
    watch(viewMode, (v) => localStorage.setItem('domainsView', v))

    const sslCount = computed(() => domains.value.filter(d => d.ssl_enabled).length)

    // Tono del borde superior de la tarjeta: peor estado manda
    const domainTone = (d) => {
      if (d.is_suspended || !d.is_active) return 'warning'
      if (!d.ssl_enabled) return 'neutral'
      return 'ok'
    }

    const toggleMenu = (id) => { openMenuId.value = openMenuId.value === id ? null : id }

    // Ejecuta una acción y cierra el menú contextual
    const run = (fn, ...args) => { openMenuId.value = null; fn(...args) }

    // Cambio de PHP desde el menú (sin <select> en la tarjeta)
    const changePHPPrompt = async (domain) => {
      const current = domain.php_version || phpVersions.value[0]
      const opts = phpVersions.value.join(', ')
      const version = window.prompt(`Versión de PHP para ${domain.domain_name}\nDisponibles: ${opts}`, current)
      if (!version || version === current) return
      if (!phpVersions.value.includes(version)) {
        store.showNotification(`Versión no válida. Disponibles: ${opts}`, 'danger')
        return
      }
      try {
        await api.changePHPVersion(domain.id, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'danger')
      }
    }

    onMounted(async () => {
      await Promise.all([loadPHPVersions(), loadUsers(), loadDomains()])
    })

    return {
      domains, users, phpVersions, selectedUser, loading,
      viewMode, openMenuId, sslCount, domainTone, toggleMenu, run, changePHPPrompt,
      isAdminOrReseller,
      showDomainForm, showSSLManager, showIPv6Manager,
      editingDomain, selectedDomain,
      openCreateForm, openEditForm, closeDomainForm, handleDomainSubmit,
      openSSLManager, closeSSLManager,
      openIPv6Manager, closeIPv6Manager,
      openFileManager,
      deleteDomainConfirm, changePHP, suspendDomain, unsuspendDomain,
      downloadingId, downloadSite,
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

<style scoped>
.domains-view { max-width: var(--content-max); margin: 0 auto; display: flex; flex-direction: column; gap: var(--sp-5); }

.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); flex-wrap: wrap; }
.page-title { margin: 0; font-size: var(--fs-2xl); font-weight: var(--fw-bold); letter-spacing: -.02em; color: var(--text); }
.page-sub { margin: var(--sp-1) 0 0; color: var(--text-secondary); }
.page-head__actions { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }

.svq-select {
  height: 38px; padding: 0 var(--sp-3);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-md);
  font-size: var(--fs-base); cursor: pointer;
}
.svq-select:focus { outline: none; border-color: var(--color-primary); box-shadow: var(--shadow-focus); }

.view-toggle { display: inline-flex; background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--r-md); padding: 2px; }
.view-toggle button { border: none; background: transparent; color: var(--text-muted); width: 34px; height: 32px; border-radius: var(--r-sm); cursor: pointer; font-size: 15px; transition: all var(--t-fast); }
.view-toggle button.active { background: var(--surface); color: var(--color-primary); box-shadow: var(--shadow-xs); }

.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-4); }

/* ===== Tarjeta de dominio ===== */
.dcard {
  background: var(--surface);
  border: 1px solid var(--border);
  border-top: 3px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--sp-5);
  display: flex; flex-direction: column; gap: var(--sp-4);
  transition: box-shadow var(--t-base) var(--ease), transform var(--t-base) var(--ease);
}
.dcard:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.dcard--ok { border-top-color: var(--success); }
.dcard--warning { border-top-color: var(--warning); }
.dcard--neutral { border-top-color: var(--border-strong); }

.dcard__head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-2); }
.dcard__title { display: flex; align-items: center; gap: var(--sp-2); min-width: 0; }
.dcard__title .bi { color: var(--color-primary); font-size: 17px; flex-shrink: 0; }
.dcard__name { font-weight: var(--fw-semibold); color: var(--text); text-decoration: none; font-size: var(--fs-md); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dcard__name:hover { color: var(--color-primary); text-decoration: underline; }
.dcard__owner { margin: -8px 0 0; font-size: var(--fs-sm); color: var(--text-muted); display: flex; align-items: center; gap: 5px; }

.dcard__stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3) var(--sp-4); }
.dstat { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); }
.dstat__k { font-size: var(--fs-sm); color: var(--text-muted); }
.dstat__v { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); }
.dstat__load { border: none; background: var(--surface-inset); color: var(--text-muted); border-radius: var(--r-sm); width: 26px; height: 22px; cursor: pointer; }
.mono { font-family: var(--font-mono); }

.dcard__actions { display: flex; align-items: center; gap: var(--sp-2); padding-top: var(--sp-3); border-top: 1px solid var(--border); }
.dcard__more { margin-left: auto; position: relative; }
.more-btn { width: 34px; height: 32px; border: 1px solid var(--border); background: var(--surface); border-radius: var(--r-md); color: var(--text-secondary); cursor: pointer; transition: all var(--t-fast); }
.more-btn:hover { background: var(--surface-inset); color: var(--text); }
.more-menu {
  position: absolute; right: 0; bottom: calc(100% + 6px);
  min-width: 210px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-md); box-shadow: var(--shadow-lg);
  padding: var(--sp-2); z-index: 50;
}
.more-menu button {
  display: flex; align-items: center; gap: var(--sp-2); width: 100%;
  padding: 8px var(--sp-3); border: none; background: transparent;
  color: var(--text-secondary); font-size: var(--fs-sm); border-radius: var(--r-sm);
  cursor: pointer; text-align: left; transition: background var(--t-fast), color var(--t-fast);
}
.more-menu button .bi { width: 16px; }
.more-menu button:hover { background: var(--surface-inset); color: var(--text); }
.more-menu button.is-danger { color: var(--danger); }
.more-menu button.is-danger:hover { background: var(--danger-bg); }
.more-menu button:disabled { opacity: .5; cursor: not-allowed; }
.more-sep { height: 1px; background: var(--border); margin: var(--sp-2) 0; }

/* ===== Tabla compacta ===== */
.table-wrap { overflow-x: auto; }
.svq-table { width: 100%; border-collapse: collapse; font-size: var(--fs-base); }
.svq-table thead th {
  text-align: left; padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-xs); font-weight: var(--fw-semibold); text-transform: uppercase; letter-spacing: .05em;
  color: var(--text-muted); border-bottom: 1px solid var(--border); white-space: nowrap;
}
.svq-table tbody td { padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); color: var(--text); }
.svq-table tbody tr:last-child td { border-bottom: none; }
.svq-table tbody tr:hover { background: var(--surface-inset); }
.ta-end { text-align: right; }
.t-domain { display: inline-flex; align-items: center; gap: 6px; color: var(--text); font-weight: var(--fw-medium); text-decoration: none; }
.t-domain .bi { color: var(--color-primary); }
.t-domain:hover { color: var(--color-primary); }
.t-muted { color: var(--text-muted); }
.t-actions { display: inline-flex; gap: 4px; justify-content: flex-end; }
.icon-act { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border: 1px solid var(--border); background: var(--surface); border-radius: var(--r-sm); color: var(--text-secondary); cursor: pointer; transition: all var(--t-fast); text-decoration: none; }
.icon-act:hover { background: var(--surface-inset); color: var(--text); }
.icon-act.is-danger:hover { background: var(--danger-bg); color: var(--danger); border-color: var(--danger-border); }

@media (max-width: 600px) {
  .cards-grid { grid-template-columns: 1fr; }
  .page-head__actions { width: 100%; }
}
</style>
