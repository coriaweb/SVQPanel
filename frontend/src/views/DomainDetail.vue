<template>
  <div class="domain-detail">
    <!-- Cabecera -->
    <header class="dd-head">
      <div class="dd-head__left">
        <router-link to="/domains" class="dd-back" title="Volver a dominios"><i class="bi bi-arrow-left"></i></router-link>
        <div>
          <h1 class="dd-title">
            <i class="bi bi-globe2"></i>
            {{ domain?.domain_name || '—' }}
          </h1>
          <p class="dd-sub" v-if="domain">
            <StatusBadge
              :status="domain.is_suspended ? 'warning' : (domain.is_active ? 'active' : 'error')"
              :label="domain.is_suspended ? 'Suspendido' : (domain.is_active ? 'Activo' : 'Inactivo')" />
            <span class="dd-sub__sep">·</span>
            <span class="mono">PHP {{ domain.php_version || '—' }}</span>
          </p>
        </div>
      </div>
      <div class="dd-head__actions" v-if="domain">
        <BaseButton variant="secondary" size="sm" icon="box-arrow-up-right" tag="a"
          v-bind="{ href: 'http://' + domain.domain_name, target: '_blank' }">Visitar</BaseButton>
        <BaseButton variant="secondary" size="sm" icon="folder2-open" @click="goFiles">Archivos</BaseButton>
      </div>
    </header>

    <div v-if="loading" class="svq-skeleton" style="height:300px;border-radius:var(--r-lg)"></div>

    <template v-else-if="domain">
      <BaseTabs v-model="tab" :tabs="tabList" />

      <!-- ===== Overview ===== -->
      <div v-show="tab === 'overview'" class="dd-grid">
        <BaseCard title="Información" icon="info-circle">
          <div class="kv">
            <div class="kv__row"><span class="kv__k">Document root</span><span class="kv__v mono">{{ domain.public_html || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">IPv4</span><span class="kv__v mono">{{ domain.ipv4 || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">IPv6</span><span class="kv__v mono">{{ domain.ipv6 || 'sin asignar' }}</span></div>
            <div class="kv__row"><span class="kv__k">Creado</span><span class="kv__v">{{ formatDate(domain.created_at) }}</span></div>
          </div>
        </BaseCard>

        <BaseCard title="SSL" icon="shield-lock">
          <template #actions><StatusBadge :status="domain.ssl_enabled ? 'valid' : 'none'" :label="domain.ssl_enabled ? 'Activo' : 'Sin SSL'" /></template>
          <p class="dd-muted">{{ domain.ssl_enabled ? 'Certificado activo para este dominio.' : 'Este dominio no tiene certificado SSL.' }}</p>
          <BaseButton variant="subtle" size="sm" icon="shield-check" @click="tab = 'ssl'">Gestionar SSL</BaseButton>
        </BaseCard>

        <BaseCard title="PHP" icon="filetype-php">
          <template #actions><span class="mono dd-php">{{ domain.php_version || '—' }}</span></template>
          <p class="dd-muted">Versión y ajustes php.ini de este dominio.</p>
          <BaseButton variant="subtle" size="sm" icon="sliders" @click="tab = 'php'">Configurar PHP</BaseButton>
        </BaseCard>

        <BaseCard title="FastCGI cache" icon="lightning-charge">
          <template #actions>
            <StatusBadge :status="domain.fastcgi_cache_enabled ? 'active' : 'none'" :label="domain.fastcgi_cache_enabled ? 'Activa' : 'Off'" />
          </template>
          <p class="dd-muted">
            {{ domain.fastcgi_cache_enabled ? `Cache activa (TTL ${domain.fastcgi_cache_ttl_minutes || 60} min).` : 'Cache desactivada.' }}
          </p>
          <div class="dd-actions-row">
            <BaseButton variant="subtle" size="sm" :icon="domain.fastcgi_cache_enabled ? 'lightning-fill' : 'lightning'" @click="toggleCache" :loading="cacheSaving">
              {{ domain.fastcgi_cache_enabled ? 'Desactivar' : 'Activar' }}
            </BaseButton>
            <BaseButton v-if="domain.fastcgi_cache_enabled" variant="ghost" size="sm" icon="trash3" @click="purgeCache" :loading="cacheSaving">Purgar</BaseButton>
          </div>
        </BaseCard>

        <BaseCard title="Recursos" icon="hdd" class="dd-span2">
          <template #actions>
            <BaseButton variant="ghost" size="sm" icon="arrow-repeat" @click="loadDisk" :loading="diskLoading">Recalcular</BaseButton>
          </template>
          <div v-if="disk" class="disk-grid">
            <div class="disk-item"><span class="disk-k">public_html</span><span class="disk-v mono">{{ formatMB(disk.public_html_mb) }}</span></div>
            <div class="disk-item"><span class="disk-k">Logs</span><span class="disk-v mono">{{ formatMB(disk.logs_mb) }}</span></div>
            <div class="disk-item"><span class="disk-k">Total</span><span class="disk-v mono">{{ formatMB((disk.public_html_mb || 0) + (disk.logs_mb || 0)) }}</span></div>
          </div>
          <p v-else class="dd-muted">Pulsa «Recalcular» para medir el uso de disco.</p>
        </BaseCard>

        <BaseCard title="Instalar aplicación" icon="box-seam" class="dd-span2">
          <p class="dd-muted">Instala una aplicación lista para usar en este dominio (crea su base de datos y la configura).</p>
          <div class="app-install">
            <div class="app-install__row">
              <label class="app-field">
                <span>Aplicación</span>
                <select class="svq-select" v-model="appForm.app">
                  <option value="wordpress">WordPress</option>
                  <option value="laravel">Laravel</option>
                  <option value="nextcloud">Nextcloud</option>
                  <option value="prestashop">PrestaShop</option>
                </select>
              </label>
              <label class="app-field" v-if="appNeedsAdmin">
                <span>Usuario admin</span>
                <input class="svq-input" v-model="appForm.admin_user" placeholder="admin" />
              </label>
            </div>
            <div class="app-install__row" v-if="appNeedsAdmin">
              <label class="app-field">
                <span>Contraseña admin</span>
                <input class="svq-input" v-model="appForm.admin_password" type="text" placeholder="mín. 8 caracteres" />
              </label>
              <label class="app-field" v-if="appNeedsEmail">
                <span>Email admin</span>
                <input class="svq-input" v-model="appForm.admin_email" type="email" :placeholder="`admin@${domain.domain_name}`" />
              </label>
            </div>
            <p v-if="appForm.app === 'laravel'" class="dd-muted"><i class="bi bi-info-circle"></i> Laravel se instala sin usuario admin (lo defines en tu app). Servirá desde <code>/public</code> automáticamente.</p>
            <p v-else-if="appForm.app === 'nextcloud'" class="dd-muted"><i class="bi bi-info-circle"></i> Nextcloud se instala desatendido con esta cuenta admin. La primera carga puede tardar unos segundos.</p>
            <p v-else-if="appForm.app === 'prestashop'" class="dd-muted"><i class="bi bi-info-circle"></i> PrestaShop se instala desatendido. Entrarás al back office con tu <strong>email</strong> y contraseña; la URL de admin se mostrará al terminar.</p>
            <div class="app-install__foot">
              <small class="dd-muted"><i class="bi bi-exclamation-triangle"></i> El dominio debe estar vacío (sin web previa).</small>
              <BaseButton variant="primary" size="sm" icon="download" :loading="installing" @click="doInstallApp">Instalar</BaseButton>
            </div>
            <div v-if="installResult" class="app-result">
              <p class="app-result__title"><i class="bi bi-check-circle-fill"></i> {{ installResult.message }}</p>
              <div class="app-result__row"><span>URL</span><a :href="installResult.data.url" target="_blank" class="mono">{{ installResult.data.url }}</a></div>
              <div class="app-result__row" v-if="installResult.data.admin_url"><span>Admin</span><a :href="installResult.data.admin_url" target="_blank" class="mono">{{ installResult.data.admin_url }}</a></div>
              <div class="app-result__row" v-if="installResult.data.admin_user"><span>Usuario</span><span class="mono">{{ installResult.data.admin_user }}</span></div>
              <div class="app-result__row" v-if="installResult.data.warning"><span>Aviso</span><span style="color:var(--warning)">{{ installResult.data.warning }}</span></div>
            </div>
          </div>
        </BaseCard>

        <BaseCard title="Acciones rápidas" icon="lightning-charge">
          <div class="quick-col">
            <BaseButton variant="ghost" size="sm" icon="diagram-3" block @click="tab = 'ipv6'">Gestionar IPv6</BaseButton>
            <BaseButton variant="ghost" size="sm" icon="download" block :loading="downloading" @click="downloadSite">Descargar sitio</BaseButton>
            <BaseButton v-if="!domain.is_suspended" variant="ghost" size="sm" icon="pause-circle" block @click="suspend">Suspender</BaseButton>
            <BaseButton v-else variant="ghost" size="sm" icon="play-circle" block @click="unsuspend">Reactivar</BaseButton>
            <BaseButton variant="danger" size="sm" icon="trash" block @click="remove">Eliminar dominio</BaseButton>
          </div>
        </BaseCard>
      </div>

      <!-- ===== SSL ===== -->
      <BaseCard v-show="tab === 'ssl'" title="Certificado SSL" icon="shield-lock">
        <SSLManager :domain="domain" @reload="reloadDomain" />
      </BaseCard>

      <!-- ===== PHP ===== -->
      <BaseCard v-show="tab === 'php'" title="Configuración PHP" icon="filetype-php">
        <template #actions>
          <select class="svq-select svq-select--sm" :value="domain.php_version" @change="changePHP($event.target.value)">
            <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </template>
        <div v-if="phpLoading" class="svq-skeleton" style="height:200px"></div>
        <div v-else>
          <p class="dd-muted">Ajustes php.ini propios (vacío = valor global del servidor). No puedes superar el límite del servidor.</p>
          <div class="php-table">
            <div class="php-row php-row--head">
              <span>Directiva</span><span>Valor</span><span>Servidor</span>
            </div>
            <div class="php-row" v-for="(spec, key) in phpDirectives" :key="key">
              <div>
                <div class="php-label">{{ spec.label }}</div>
                <code class="php-code">{{ key }}</code>
              </div>
              <div>
                <select v-if="spec.type === 'bool'" class="svq-input" v-model="phpForm[key]">
                  <option value="">(servidor)</option><option value="On">On</option><option value="Off">Off</option>
                </select>
                <input v-else class="svq-input" v-model="phpForm[key]" :placeholder="phpDefaults[key] || '(servidor)'">
              </div>
              <div class="php-server mono">{{ phpDefaults[key] ?? '—' }}</div>
            </div>
          </div>
          <div class="dd-form-foot">
            <small class="dd-muted">
              <i class="bi bi-info-circle"></i>
              <span v-if="phpHasPool" style="color:var(--success)"> Pool dedicado activo</span>
              <span v-else> Usando php.ini global</span>
            </small>
            <BaseButton variant="primary" size="sm" :loading="phpSaving" @click="savePhp">Guardar y aplicar</BaseButton>
          </div>
        </div>
      </BaseCard>

      <!-- ===== IPv6 ===== -->
      <BaseCard v-show="tab === 'ipv6'" title="IPv6" icon="diagram-3">
        <IPv6Manager :domain="domain" @reload="reloadDomain" />
      </BaseCard>

      <!-- ===== Logs ===== -->
      <BaseCard v-show="tab === 'logs'" title="Registros" icon="journal-text" flush>
        <template #actions>
          <div class="logs-controls">
            <div class="seg">
              <button :class="{active: logTab==='access'}" @click="switchLog('access')">access</button>
              <button :class="{active: logTab==='error'}" @click="switchLog('error')">error</button>
            </div>
            <select class="svq-select svq-select--sm" v-model.number="logLines" @change="loadLogs">
              <option :value="50">50</option><option :value="200">200</option><option :value="500">500</option><option :value="2000">2000</option>
            </select>
            <button class="icon-act" @click="loadLogs" title="Refrescar"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
        </template>
        <div class="logs-body">
          <div v-if="logsLoading" class="svq-skeleton" style="height:200px;margin:var(--sp-4)"></div>
          <div v-else-if="!logsData.exists" class="dd-muted" style="padding:var(--sp-5)">
            {{ logsData.message || 'Sin datos.' }}
            <div class="mono dd-muted" style="margin-top:6px">{{ logsData.path }}</div>
          </div>
          <template v-else>
            <div class="logs-meta mono">{{ logsData.path }} — {{ logsData.count }} líneas</div>
            <pre class="logs-pre">{{ logsData.lines.join('\n') }}</pre>
          </template>
        </div>
      </BaseCard>
    </template>

    <BaseCard v-else>
      <EmptyState icon="exclamation-triangle" title="Dominio no encontrado" description="No se pudo cargar este dominio.">
        <BaseButton tag="router-link" v-bind="{ to: '/domains' }" variant="primary">Volver a dominios</BaseButton>
      </EmptyState>
    </BaseCard>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseTabs from '../components/ui/BaseTabs.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'

export default {
  name: 'DomainDetail',
  components: { BaseCard, BaseButton, BaseTabs, StatusBadge, EmptyState, SSLManager, IPv6Manager },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const store = useMainStore()

    const domainId = computed(() => parseInt(route.params.id))
    const domain = ref(null)
    const loading = ref(true)
    const tab = ref('overview')
    const phpVersions = ref([])

    const tabList = [
      { key: 'overview', label: 'Resumen', icon: 'grid-1x2' },
      { key: 'ssl',      label: 'SSL',     icon: 'shield-lock' },
      { key: 'php',      label: 'PHP',     icon: 'filetype-php' },
      { key: 'ipv6',     label: 'IPv6',    icon: 'diagram-3' },
      { key: 'logs',     label: 'Logs',    icon: 'journal-text' },
    ]

    const formatMB = (mb) => {
      if (!mb) return '0 MB'
      if (mb >= 1024) return (mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1) + ' GB'
      return mb + ' MB'
    }
    const formatDate = (d) => d ? new Date(d).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

    const loadDomain = async () => {
      loading.value = true
      try {
        domain.value = await api.getDomain(domainId.value)
      } catch (e) {
        store.showNotification('Error al cargar el dominio', 'danger')
        domain.value = null
      } finally { loading.value = false }
    }
    const reloadDomain = async () => { domain.value = await api.getDomain(domainId.value) }

    // ── Disco ──
    const disk = ref(null)
    const diskLoading = ref(false)
    const loadDisk = async () => {
      diskLoading.value = true
      try { disk.value = await api.getDomainDisk(domainId.value) }
      catch { store.showNotification('Error midiendo disco', 'danger') }
      finally { diskLoading.value = false }
    }

    // ── Cache ──
    const cacheSaving = ref(false)
    const toggleCache = async () => {
      cacheSaving.value = true
      try {
        const enabled = !domain.value.fastcgi_cache_enabled
        await api.setDomainCache(domainId.value, enabled, domain.value.fastcgi_cache_ttl_minutes || 60)
        store.showNotification(enabled ? 'Cache activada' : 'Cache desactivada', 'success')
        await reloadDomain()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { cacheSaving.value = false }
    }
    const purgeCache = async () => {
      if (!confirm(`¿Purgar la cache de ${domain.value.domain_name}?`)) return
      cacheSaving.value = true
      try { const r = await api.purgeDomainCache(domainId.value); store.showNotification(`Cache purgada — ${r.freed_mb} MB`, 'success') }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { cacheSaving.value = false }
    }

    // ── PHP ──
    const phpLoading = ref(false), phpSaving = ref(false)
    const phpDirectives = ref({}), phpDefaults = ref({}), phpForm = ref({}), phpHasPool = ref(false)
    const loadPhp = async () => {
      phpLoading.value = true
      try {
        const cfg = await api.getDomainPhpConfig(domainId.value)
        phpDirectives.value = cfg.directives || {}
        phpDefaults.value = cfg.server_defaults || {}
        phpHasPool.value = cfg.has_pool
        const form = {}
        for (const key of Object.keys(phpDirectives.value)) {
          form[key] = (cfg.overrides && cfg.overrides[key] != null) ? cfg.overrides[key] : ''
        }
        phpForm.value = form
      } catch (e) { store.showNotification('Error config PHP: ' + e.message, 'danger') }
      finally { phpLoading.value = false }
    }
    const savePhp = async () => {
      phpSaving.value = true
      try {
        const overrides = {}
        for (const [k, v] of Object.entries(phpForm.value)) if (String(v).trim() !== '') overrides[k] = String(v).trim()
        await api.setDomainPhpConfig(domainId.value, overrides)
        store.showNotification('Configuración PHP aplicada', 'success')
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { phpSaving.value = false }
    }
    const changePHP = async (version) => {
      try {
        await api.changePHPVersion(domainId.value, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await reloadDomain(); await loadPhp()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger'); await reloadDomain() }
    }

    // ── Logs ──
    const logTab = ref('access'), logLines = ref(200), logsLoading = ref(false)
    const logsData = ref({ exists: false, lines: [], path: '' })
    const loadLogs = async () => {
      logsLoading.value = true
      try { logsData.value = await api.getDomainLogs(domainId.value, logTab.value, logLines.value) }
      catch (e) { logsData.value = { exists: false, lines: [], path: '', message: e.message } }
      finally { logsLoading.value = false }
    }
    const switchLog = (t) => { logTab.value = t; loadLogs() }

    // ── Acciones ──
    const downloading = ref(false)
    const downloadSite = async () => {
      downloading.value = true
      try {
        const { blob, filename } = await api.downloadDomainSite(domainId.value)
        const url = URL.createObjectURL(blob); const a = document.createElement('a')
        a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      } catch (e) { store.showNotification('Error al descargar: ' + e.message, 'danger') }
      finally { downloading.value = false }
    }
    const suspend = async () => {
      if (!confirm(`¿Suspender ${domain.value.domain_name}?`)) return
      try { await api.suspendDomain(domainId.value); store.showNotification('Dominio suspendido', 'warning'); await reloadDomain() }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const unsuspend = async () => {
      try { await api.unsuspendDomain(domainId.value); store.showNotification('Dominio reactivado', 'success'); await reloadDomain() }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const remove = async () => {
      if (!confirm('¿Eliminar este dominio? Se borrarán todos sus archivos.')) return
      try { await api.deleteDomain(domainId.value); store.showNotification('Dominio eliminado', 'success'); router.push('/domains') }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const goFiles = () => router.push({ path: '/files', query: { domain: domainId.value } })

    // ── Autoinstalador de apps ──
    const appForm = ref({ app: 'wordpress', admin_user: 'admin', admin_password: '', admin_email: '' })
    const installing = ref(false)
    const installResult = ref(null)
    // wordpress/nextcloud/prestashop tienen cuenta admin; wordpress y prestashop piden email
    const appNeedsAdmin = computed(() => ['wordpress', 'nextcloud', 'prestashop'].includes(appForm.value.app))
    const appNeedsEmail = computed(() => ['wordpress', 'prestashop'].includes(appForm.value.app))
    const doInstallApp = async () => {
      if (appNeedsAdmin.value) {
        if (!appForm.value.admin_password || appForm.value.admin_password.length < 8) {
          store.showNotification('La contraseña admin debe tener al menos 8 caracteres', 'danger'); return
        }
        if (appNeedsEmail.value && !appForm.value.admin_email) {
          store.showNotification('Indica un email de administrador', 'danger'); return
        }
      }
      // Solo enviamos los campos relevantes para cada app
      const payload = { app: appForm.value.app, admin_user: appForm.value.admin_user }
      if (appNeedsAdmin.value) payload.admin_password = appForm.value.admin_password
      if (appNeedsEmail.value) payload.admin_email = appForm.value.admin_email
      installing.value = true
      installResult.value = null
      try {
        const r = await api.installApp(domainId.value, payload)
        installResult.value = r
        store.showNotification(r.message || 'Aplicación instalada', 'success')
        await reloadDomain()
      } catch (e) {
        store.showNotification('Error instalando: ' + e.message, 'danger')
      } finally {
        installing.value = false
      }
    }

    onMounted(async () => {
      await loadDomain()
      try { const d = await api.getPHPVersions(); phpVersions.value = d?.versions?.length ? d.versions : ['8.2'] }
      catch { phpVersions.value = ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4'] }
      if (domain.value) { loadDisk(); loadPhp(); loadLogs() }
    })

    return {
      domain, loading, tab, tabList, phpVersions, reloadDomain,
      formatMB, formatDate,
      disk, diskLoading, loadDisk,
      cacheSaving, toggleCache, purgeCache,
      phpLoading, phpSaving, phpDirectives, phpDefaults, phpForm, phpHasPool, savePhp, changePHP,
      logTab, logLines, logsLoading, logsData, loadLogs, switchLog,
      downloading, downloadSite, suspend, unsuspend, remove, goFiles,
      appForm, installing, installResult, doInstallApp, appNeedsAdmin, appNeedsEmail,
    }
  },
}
</script>

<style scoped>
.domain-detail { max-width: var(--content-max); margin: 0 auto; display: flex; flex-direction: column; gap: var(--sp-5); }

.dd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); flex-wrap: wrap; }
.dd-head__left { display: flex; align-items: center; gap: var(--sp-3); }
.dd-back { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: var(--r-md); color: var(--text-secondary); text-decoration: none; transition: all var(--t-fast); flex-shrink: 0; }
.dd-back:hover { background: var(--surface-inset); color: var(--text); }
.dd-title { margin: 0; font-size: var(--fs-2xl); font-weight: var(--fw-bold); letter-spacing: -.02em; color: var(--text); display: flex; align-items: center; gap: var(--sp-2); }
.dd-title .bi { color: var(--color-primary); }
.dd-sub { margin: var(--sp-1) 0 0; display: flex; align-items: center; gap: var(--sp-2); color: var(--text-secondary); }
.dd-sub__sep { color: var(--text-muted); }
.dd-head__actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
.mono { font-family: var(--font-mono); }
.dd-muted { color: var(--text-muted); font-size: var(--fs-sm); margin: 0 0 var(--sp-3); }
.dd-php { font-weight: var(--fw-semibold); color: var(--text); }

.dd-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-4); align-items: start; }
.dd-span2 { grid-column: span 2; }

.kv { display: flex; flex-direction: column; }
.kv__row { display: flex; justify-content: space-between; gap: var(--sp-3); padding: 7px 0; border-bottom: 1px solid var(--border); }
.kv__row:last-child { border-bottom: none; }
.kv__k { color: var(--text-muted); font-size: var(--fs-sm); }
.kv__v { color: var(--text); font-size: var(--fs-sm); font-weight: var(--fw-medium); text-align: right; word-break: break-all; }

.dd-actions-row { display: flex; gap: var(--sp-2); }
.quick-col { display: flex; flex-direction: column; gap: var(--sp-2); }

/* Autoinstalador */
.app-install { display: flex; flex-direction: column; gap: var(--sp-3); }
.app-install__row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
.app-field { display: flex; flex-direction: column; gap: 4px; }
.app-field > span { font-size: var(--fs-sm); color: var(--text-secondary); font-weight: var(--fw-medium); }
.app-install__foot { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; }
.app-result { border-top: 1px solid var(--border); padding-top: var(--sp-3); display: flex; flex-direction: column; gap: 6px; }
.app-result__title { margin: 0 0 var(--sp-2); color: var(--success); font-weight: var(--fw-semibold); display: flex; align-items: center; gap: 6px; }
.app-result__row { display: flex; gap: var(--sp-3); font-size: var(--fs-sm); }
.app-result__row > span:first-child { min-width: 70px; color: var(--text-muted); }
@media (max-width: 680px) { .app-install__row { grid-template-columns: 1fr; } }

.disk-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); }
.disk-item { background: var(--surface-inset); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); }
.disk-k { display: block; font-size: var(--fs-sm); color: var(--text-muted); }
.disk-v { font-size: var(--fs-lg); font-weight: var(--fw-bold); color: var(--text); }

/* select / input */
.svq-select, .svq-input {
  height: 38px; padding: 0 var(--sp-3); width: 100%;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-md); font-size: var(--fs-base);
}
.svq-select { cursor: pointer; }
.svq-select--sm { height: 32px; width: auto; font-size: var(--fs-sm); }
.svq-input:focus, .svq-select:focus { outline: none; border-color: var(--color-primary); box-shadow: var(--shadow-focus); }

/* PHP table */
.php-table { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; }
.php-row { display: grid; grid-template-columns: 1.4fr 1fr 0.8fr; gap: var(--sp-3); align-items: center; padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); }
.php-row:last-child { border-bottom: none; }
.php-row--head { background: var(--surface-inset); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); font-weight: var(--fw-semibold); }
.php-label { font-size: var(--fs-sm); color: var(--text); }
.php-code { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.php-server { font-size: var(--fs-sm); color: var(--text-muted); }
.dd-form-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-top: var(--sp-4); }

/* Logs */
.logs-controls { display: flex; align-items: center; gap: var(--sp-2); }
.seg { display: inline-flex; background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--r-md); padding: 2px; }
.seg button { border: none; background: transparent; color: var(--text-muted); padding: 4px 12px; border-radius: var(--r-sm); cursor: pointer; font-size: var(--fs-sm); font-family: var(--font-mono); }
.seg button.active { background: var(--surface); color: var(--color-primary); box-shadow: var(--shadow-xs); }
.icon-act { width: 32px; height: 32px; border: 1px solid var(--border); background: var(--surface); border-radius: var(--r-sm); color: var(--text-secondary); cursor: pointer; }
.icon-act:hover { background: var(--surface-inset); color: var(--text); }
.logs-meta { padding: var(--sp-3) var(--sp-5); font-size: var(--fs-sm); color: var(--text-muted); border-bottom: 1px solid var(--border); }
.logs-pre {
  margin: 0; padding: var(--sp-4) var(--sp-5);
  background: var(--surface-inset); color: var(--text-secondary);
  font-family: var(--font-mono); font-size: 12px; line-height: 1.6;
  max-height: 60vh; overflow: auto; white-space: pre-wrap; word-break: break-all;
}

@media (max-width: 1000px) { .dd-grid { grid-template-columns: 1fr 1fr; } .dd-span2 { grid-column: span 2; } }
@media (max-width: 680px) { .dd-grid { grid-template-columns: 1fr; } .dd-span2 { grid-column: auto; } .disk-grid { grid-template-columns: 1fr; } }
</style>
