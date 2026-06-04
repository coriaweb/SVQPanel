<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="sv-head">
      <div>
        <h1 class="sv-title"><i class="bi bi-hdd-rack"></i> Sistema</h1>
        <p class="sv-sub">Monitorización de servicios y estadísticas del servidor</p>
      </div>
      <button class="btn btn-outline-secondary btn-sm" @click="reload" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
        <i v-else class="bi bi-arrow-repeat me-1"></i>
        Actualizar
      </button>
    </div>

    <!-- Banner info servidor -->
    <div v-if="stats" class="sv-server-banner">
      <div class="sv-server-item">
        <span class="sv-server-label">Sistema Operativo</span>
        <span class="sv-server-val">{{ stats.os_name || '—' }}</span>
      </div>
      <div class="sv-server-item">
        <span class="sv-server-label">Tiempo Activo</span>
        <span class="sv-server-val">{{ stats.uptime_str }}</span>
      </div>
      <div class="sv-server-item">
        <span class="sv-server-label">Carga (1m / 5m / 15m)</span>
        <span class="sv-server-val mono">{{ stats.load_1 }} / {{ stats.load_5 }} / {{ stats.load_15 }}</span>
      </div>
      <div class="sv-server-item">
        <span class="sv-server-label">CPUs</span>
        <span class="sv-server-val">{{ stats.cpu_count }} núcleos</span>
      </div>
    </div>

    <!-- Contadores -->
    <div v-if="stats" class="sv-counters">
      <div class="sv-counter">
        <span class="sv-counter-icon" style="background:var(--ac-soft);color:var(--ac)"><i class="bi bi-people"></i></span>
        <div>
          <div class="sv-counter-label">USUARIOS</div>
          <div class="sv-counter-val">{{ stats.total_users }}</div>
          <div class="sv-counter-hint">{{ stats.suspended_users }} suspendidos</div>
        </div>
      </div>
      <div class="sv-counter">
        <span class="sv-counter-icon" style="background:var(--success-bg);color:var(--success)"><i class="bi bi-globe"></i></span>
        <div>
          <div class="sv-counter-label">WEB</div>
          <div class="sv-counter-val">{{ stats.total_domains }}</div>
          <div class="sv-counter-hint">{{ stats.active_domains }} activos</div>
        </div>
      </div>
      <div class="sv-counter">
        <span class="sv-counter-icon" style="background:var(--info-bg);color:var(--info)"><i class="bi bi-diagram-3"></i></span>
        <div>
          <div class="sv-counter-label">DNS</div>
          <div class="sv-counter-val">{{ stats.total_dns_zones }}</div>
          <div class="sv-counter-hint">{{ stats.total_dns_records }} registros</div>
        </div>
      </div>
      <div class="sv-counter">
        <span class="sv-counter-icon" style="background:var(--warning-bg);color:var(--warning)"><i class="bi bi-hdd-stack"></i></span>
        <div>
          <div class="sv-counter-label">PANEL</div>
          <div class="sv-counter-val" style="color:var(--success)">Activo</div>
          <div class="sv-counter-hint">SVQPanel</div>
        </div>
      </div>
    </div>

    <!-- Tabla servicios -->
    <div class="card">
      <div class="card-header" style="display:flex;align-items:center;justify-content:space-between">
        <span style="font-weight:600"><i class="bi bi-toggles me-2"></i>Servicios del sistema</span>
        <span class="badge bg-secondary">{{ services.length }} detectados</span>
      </div>
      <div class="card-body" style="padding:0">

        <div v-if="loadingServices" class="sv-empty">
          <div class="spinner-border text-primary"></div>
          <p class="text-muted mt-2">Detectando servicios...</p>
        </div>

        <div v-else-if="!services.length" class="sv-empty text-muted">
          <i class="bi bi-hdd-rack" style="font-size:2.5rem"></i>
          <p class="mt-2">No se detectaron servicios</p>
        </div>

        <div v-else class="table-responsive">
          <table class="table table-hover mb-0 align-middle">
            <thead class="table-light">
              <tr>
                <th>Servicio</th>
                <th>Descripción</th>
                <th>Tiempo activo</th>
                <th class="text-end">CPU %</th>
                <th class="text-end">Memoria</th>
                <th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="svc in services" :key="svc.name">
                <td>
                  <div style="display:flex;align-items:center;gap:8px">
                    <span :style="`display:inline-block;width:9px;height:9px;border-radius:50%;flex-shrink:0;background:${svc.is_running ? 'var(--success)' : svc.state === 'failed' ? 'var(--danger)' : 'var(--text-muted)'}`"></span>
                    <span class="fw-semibold font-monospace small">{{ svc.name }}</span>
                    <span v-if="!svc.is_running" :class="svc.state === 'failed' ? 'badge bg-danger' : 'badge bg-secondary'">{{ svc.state }}</span>
                  </div>
                </td>
                <td class="text-muted small">{{ svc.description }}</td>
                <td class="small text-muted">{{ svc.uptime }}</td>
                <td class="text-end small">
                  <span :style="svc.cpu > 50 ? 'color:var(--danger);font-weight:700' : svc.cpu > 10 ? 'color:var(--warning);font-weight:700' : ''">
                    {{ svc.cpu.toFixed(1) }}
                  </span>
                </td>
                <td class="text-end small">
                  <span v-if="svc.memory_mb > 0">{{ svc.memory_mb }} MB</span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="text-end">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button v-if="!svc.is_running" class="btn btn-sm btn-outline-success" @click="doAction(svc, 'start')" :disabled="svc._loading" title="Iniciar">
                      <span v-if="svc._loading" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-play-fill"></i>
                    </button>
                    <button v-if="svc.is_running" class="btn btn-sm btn-outline-warning" @click="doAction(svc, 'restart')" :disabled="svc._loading" title="Reiniciar">
                      <span v-if="svc._loading" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-arrow-repeat"></i>
                    </button>
                    <button v-if="svc.is_running" class="btn btn-sm btn-outline-danger" @click="confirmStop(svc)" :disabled="svc._loading" title="Detener">
                      <i class="bi bi-stop-fill"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" @click="openConfig(svc)" title="Editar configuración">
                      <i class="bi bi-file-code"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal: Editor de configuración -->
    <div v-if="showConfigModal" class="modal" tabindex="-1" @click.self="showConfigModal = false">
      <div class="modal-dialog modal-dialog-lg">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title">
                <i class="bi bi-file-code me-2"></i>Configuración — <strong>{{ configService?.name }}</strong>
              </h5>
              <small class="text-muted">{{ configService?.description }}</small>
            </div>
            <button class="btn-close" @click="showConfigModal = false"></button>
          </div>
          <div class="modal-body">
            <div v-if="!loadingConfigs && !configFiles.length" class="alert alert-warning">
              <i class="bi bi-exclamation-triangle me-2"></i>No hay ficheros de configuración disponibles.
            </div>
            <div v-if="loadingConfigs" style="text-align:center;padding:1rem">
              <div class="spinner-border spinner-border-sm text-primary me-2"></div>Cargando ficheros...
            </div>
            <template v-else-if="configFiles.length">
              <ul class="nav nav-tabs mb-3">
                <li class="nav-item" v-for="f in configFiles" :key="f.label">
                  <button class="nav-link" :class="{ active: selectedConfigFile?.label === f.label }" @click="loadConfigContent(f)">
                    <i class="bi bi-file-text me-1"></i>{{ f.label }}
                  </button>
                </li>
              </ul>
              <div v-if="selectedConfigFile" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <code class="text-muted small">{{ selectedConfigFile.path }}</code>
                <span class="text-muted small">{{ selectedConfigFile.comment }}</span>
              </div>
              <div v-if="loadingConfigContent" style="text-align:center;padding:1rem">
                <div class="spinner-border spinner-border-sm text-primary"></div>
              </div>
              <textarea v-else-if="configContent !== null" v-model="configContent" class="form-control font-monospace"
                style="min-height:450px;font-size:13px;white-space:pre;tab-size:4" spellcheck="false"
                @keydown.tab.prevent="insertTab"></textarea>
              <div v-if="saveResult" class="mt-3">
                <div :class="saveResult.success ? 'alert alert-success' : 'alert alert-danger'" class="mb-0">
                  <i :class="saveResult.success ? 'bi bi-check-circle' : 'bi bi-x-circle'" class="me-2"></i>
                  {{ saveResult.success ? 'Guardado correctamente' : 'Error al guardar' }}
                  <pre v-if="saveResult.detail" class="mb-0 small" style="white-space:pre-wrap">{{ saveResult.detail }}</pre>
                </div>
              </div>
            </template>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showConfigModal = false">Cerrar</button>
            <button v-if="configContent !== null" class="btn btn-primary" :disabled="savingConfig" @click="saveConfig">
              <span v-if="savingConfig" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-floppy me-2"></i>
              Guardar y recargar servicio
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: confirmar parada -->
    <div v-if="serviceToStop" class="modal" @click.self="serviceToStop = null">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header" style="background:var(--danger);color:#fff">
            <h5 class="modal-title"><i class="bi bi-stop-circle me-2"></i>Detener servicio</h5>
            <button class="btn-close" style="filter:invert(1)" @click="serviceToStop = null"></button>
          </div>
          <div class="modal-body">
            ¿Seguro que quieres detener <strong>{{ serviceToStop.name }}</strong>?
            <p class="small mt-2 mb-0" style="color:var(--danger)">
              <i class="bi bi-exclamation-triangle me-1"></i>Esto puede dejar sin servicio a los dominios que dependen de él.
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="serviceToStop = null">Cancelar</button>
            <button class="btn btn-danger" @click="doAction(serviceToStop, 'stop'); serviceToStop = null">Detener</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'SystemServices',
  setup() {
    const store          = useMainStore()
    const stats          = ref(null)
    const services       = ref([])
    const loading        = ref(false)
    const loadingServices = ref(false)
    const serviceToStop  = ref(null)

    const showConfigModal      = ref(false)
    const configService        = ref(null)
    const configFiles          = ref([])
    const selectedConfigFile   = ref(null)
    const configContent        = ref(null)
    const loadingConfigs       = ref(false)
    const loadingConfigContent = ref(false)
    const savingConfig         = ref(false)
    const saveResult           = ref(null)

    const loadStats = async () => {
      try { stats.value = await api.getSystemStats() }
      catch (e) { store.showNotification('Error al cargar estadísticas: ' + e.message, 'danger') }
    }

    const loadServices = async () => {
      loadingServices.value = true
      try {
        const data = await api.getSystemServices()
        services.value = data.map(s => ({ ...s, _loading: false }))
      } catch (e) {
        store.showNotification('Error al cargar servicios: ' + e.message, 'danger')
      } finally { loadingServices.value = false }
    }

    const reload = async () => {
      loading.value = true
      await Promise.all([loadStats(), loadServices()])
      loading.value = false
    }

    const doAction = async (svc, action) => {
      svc._loading = true
      try {
        await api.controlService(svc.name, action)
        const labels = { start: 'iniciado', stop: 'detenido', restart: 'reiniciado', reload: 'recargado' }
        store.showNotification(`${svc.name} ${labels[action] || action}`, 'success')
        await loadServices()
      } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'danger')
        svc._loading = false
      }
    }

    const confirmStop = (svc) => { serviceToStop.value = svc }

    const openConfig = async (svc) => {
      configService.value = svc
      configFiles.value = []
      selectedConfigFile.value = null
      configContent.value = null
      saveResult.value = null
      showConfigModal.value = true
      loadingConfigs.value = true
      try {
        configFiles.value = await api.getServiceConfigs(svc.name)
        if (configFiles.value.length) await loadConfigContent(configFiles.value[0])
      } catch (e) {
        store.showNotification('Error al cargar configuraciones: ' + e.message, 'danger')
      } finally { loadingConfigs.value = false }
    }

    const loadConfigContent = async (file) => {
      selectedConfigFile.value = file
      configContent.value = null
      saveResult.value = null
      loadingConfigContent.value = true
      try {
        const data = await api.readServiceConfig(configService.value.name, file.label)
        configContent.value = data.content
      } catch (e) {
        store.showNotification('Error al leer fichero: ' + e.message, 'danger')
      } finally { loadingConfigContent.value = false }
    }

    const saveConfig = async () => {
      if (!configService.value || !selectedConfigFile.value || configContent.value === null) return
      savingConfig.value = true
      saveResult.value = null
      try {
        const result = await api.writeServiceConfig(configService.value.name, selectedConfigFile.value.label, configContent.value)
        saveResult.value = { success: true, ...result }
        store.showNotification('Configuración guardada y servicio recargado', 'success')
        await loadServices()
      } catch (e) {
        saveResult.value = { success: false, detail: e.message }
      } finally { savingConfig.value = false }
    }

    const insertTab = (e) => {
      const start = e.target.selectionStart
      const end = e.target.selectionEnd
      configContent.value = configContent.value.substring(0, start) + '    ' + configContent.value.substring(end)
      e.target.selectionStart = e.target.selectionEnd = start + 4
    }

    onMounted(reload)

    return {
      stats, services, loading, loadingServices, serviceToStop,
      reload, doAction, confirmStop,
      showConfigModal, configService, configFiles, selectedConfigFile,
      configContent, loadingConfigs, loadingConfigContent, savingConfig, saveResult,
      openConfig, loadConfigContent, saveConfig, insertTab,
    }
  }
}
</script>

<style scoped>
.sv-view { display: flex; flex-direction: column; gap: 20px; }
.sv-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.sv-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
.sv-sub { margin: 0; font-size: 13px; color: var(--text-muted); }

.sv-server-banner {
  display: grid; grid-template-columns: repeat(4, 1fr);
  background: var(--svq-navy); border-radius: 8px;
  padding: 18px 24px; gap: 16px;
}
.sv-server-item { display: flex; flex-direction: column; gap: 4px; }
.sv-server-label { font-size: 11px; color: rgba(255,255,255,.5); text-transform: uppercase; letter-spacing: .06em; }
.sv-server-val { font-size: 14px; font-weight: 600; color: #fff; }

.sv-counters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.sv-counter {
  display: flex; align-items: center; gap: 14px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px;
  box-shadow: var(--shadow-md);
}
.sv-counter-icon {
  width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 20px;
}
.sv-counter-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
.sv-counter-val { font-size: 22px; font-weight: 700; color: var(--text); line-height: 1.2; }
.sv-counter-hint { font-size: 12px; color: var(--text-muted); }

.sv-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 48px 24px; text-align: center; }
.mono { font-family: var(--font-mono); }

@media (max-width: 900px) {
  .sv-server-banner { grid-template-columns: repeat(2, 1fr); }
  .sv-counters { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .sv-server-banner { grid-template-columns: 1fr; }
  .sv-counters { grid-template-columns: 1fr; }
}
</style>
