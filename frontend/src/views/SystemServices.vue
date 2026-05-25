<template>
  <div class="container-fluid py-4">

    <!-- Cabecera -->
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1"><i class="bi bi-hdd-rack me-2"></i>Sistema</h2>
        <p class="text-muted mb-0">Monitorización de servicios y estadísticas del servidor</p>
      </div>
      <button class="btn btn-outline-secondary btn-sm" @click="reload" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
        <i v-else class="bi bi-arrow-repeat me-1"></i>
        Actualizar
      </button>
    </div>

    <!-- ── Stats del sistema ── -->
    <div class="row g-3 mb-4" v-if="stats">

      <!-- Info servidor -->
      <div class="col-12">
        <div class="card shadow-sm border-0 bg-dark text-white">
          <div class="card-body py-3">
            <div class="row text-center g-3">
              <div class="col-md-3">
                <div class="small text-white-50 mb-1">Sistema Operativo</div>
                <div class="fw-semibold">{{ stats.os_name || '—' }}</div>
              </div>
              <div class="col-md-3">
                <div class="small text-white-50 mb-1">Tiempo Activo</div>
                <div class="fw-semibold">{{ stats.uptime_str }}</div>
              </div>
              <div class="col-md-3">
                <div class="small text-white-50 mb-1">Promedio Carga (1m / 5m / 15m)</div>
                <div class="fw-semibold font-monospace">
                  {{ stats.load_1 }} / {{ stats.load_5 }} / {{ stats.load_15 }}
                </div>
              </div>
              <div class="col-md-3">
                <div class="small text-white-50 mb-1">CPUs</div>
                <div class="fw-semibold">{{ stats.cpu_count }} núcleos</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Contadores panel -->
      <div class="col-6 col-md-3">
        <div class="card shadow-sm border-0 h-100">
          <div class="card-body">
            <div class="d-flex align-items-center gap-3">
              <div class="rounded-circle bg-primary bg-opacity-10 p-3">
                <i class="bi bi-people fs-4 text-primary"></i>
              </div>
              <div>
                <div class="text-muted small">USUARIOS</div>
                <div class="fs-4 fw-bold">{{ stats.total_users }}</div>
                <div class="text-muted small">{{ stats.suspended_users }} suspendidos</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 col-md-3">
        <div class="card shadow-sm border-0 h-100">
          <div class="card-body">
            <div class="d-flex align-items-center gap-3">
              <div class="rounded-circle bg-success bg-opacity-10 p-3">
                <i class="bi bi-globe fs-4 text-success"></i>
              </div>
              <div>
                <div class="text-muted small">WEB</div>
                <div class="fs-4 fw-bold">{{ stats.total_domains }}</div>
                <div class="text-muted small">{{ stats.active_domains }} activos</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 col-md-3">
        <div class="card shadow-sm border-0 h-100">
          <div class="card-body">
            <div class="d-flex align-items-center gap-3">
              <div class="rounded-circle bg-info bg-opacity-10 p-3">
                <i class="bi bi-diagram-3 fs-4 text-info"></i>
              </div>
              <div>
                <div class="text-muted small">DNS</div>
                <div class="fs-4 fw-bold">{{ stats.total_dns_zones }}</div>
                <div class="text-muted small">{{ stats.total_dns_records }} registros</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 col-md-3">
        <div class="card shadow-sm border-0 h-100">
          <div class="card-body">
            <div class="d-flex align-items-center gap-3">
              <div class="rounded-circle bg-warning bg-opacity-10 p-3">
                <i class="bi bi-hdd-stack fs-4 text-warning"></i>
              </div>
              <div>
                <div class="text-muted small">PANEL</div>
                <div class="fs-5 fw-bold text-success">Activo</div>
                <div class="text-muted small">SVQPanel</div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- ── Tabla de servicios ── -->
    <div class="card shadow-sm">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0"><i class="bi bi-toggles me-2"></i>Servicios del sistema</h5>
        <span class="badge bg-secondary">{{ services.length }} detectados</span>
      </div>
      <div class="card-body p-0">

        <div v-if="loadingServices" class="text-center py-5">
          <div class="spinner-border text-primary"></div>
          <p class="text-muted mt-2">Detectando servicios...</p>
        </div>

        <div v-else-if="!services.length" class="text-center py-5 text-muted">
          <i class="bi bi-hdd-rack display-4"></i>
          <p class="mt-2">No se detectaron servicios</p>
        </div>

        <table v-else class="table table-hover mb-0 align-middle">
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
                <div class="d-flex align-items-center gap-2">
                  <span
                    :class="svc.is_running ? 'bg-success' : (svc.state === 'failed' ? 'bg-danger' : 'bg-secondary')"
                    style="display:inline-block;width:9px;height:9px;border-radius:50%;flex-shrink:0"
                    :title="svc.state"
                  ></span>
                  <span class="fw-semibold font-monospace small">{{ svc.name }}</span>
                  <span v-if="!svc.is_running" :class="svc.state === 'failed' ? 'badge bg-danger' : 'badge bg-secondary'" class="ms-1">
                    {{ svc.state }}
                  </span>
                </div>
              </td>

              <td class="text-muted small">{{ svc.description }}</td>
              <td class="small text-muted">{{ svc.uptime }}</td>

              <td class="text-end small">
                <span :class="svc.cpu > 50 ? 'text-danger fw-bold' : svc.cpu > 10 ? 'text-warning fw-bold' : ''">
                  {{ svc.cpu.toFixed(1) }}
                </span>
              </td>

              <td class="text-end small">
                <span v-if="svc.memory_mb > 0">{{ svc.memory_mb }} MB</span>
                <span v-else class="text-muted">—</span>
              </td>

              <td class="text-end">
                <div class="d-flex gap-1 justify-content-end">
                  <button
                    v-if="!svc.is_running"
                    class="btn btn-sm btn-outline-success"
                    @click="doAction(svc, 'start')"
                    :disabled="svc._loading"
                    title="Iniciar"
                  >
                    <span v-if="svc._loading" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-play-fill"></i>
                  </button>
                  <button
                    v-if="svc.is_running"
                    class="btn btn-sm btn-outline-warning"
                    @click="doAction(svc, 'restart')"
                    :disabled="svc._loading"
                    title="Reiniciar"
                  >
                    <span v-if="svc._loading" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-arrow-repeat"></i>
                  </button>
                  <button
                    v-if="svc.is_running"
                    class="btn btn-sm btn-outline-danger"
                    @click="confirmStop(svc)"
                    :disabled="svc._loading"
                    title="Detener"
                  >
                    <i class="bi bi-stop-fill"></i>
                  </button>
                  <button
                    class="btn btn-sm btn-outline-secondary"
                    @click="openConfig(svc)"
                    title="Editar configuración"
                  >
                    <i class="bi bi-file-code"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════ Modal: Editor de configuración ══════════ -->
    <div v-if="showConfigModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.6)">
      <div class="modal-dialog modal-xl modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">
                <i class="bi bi-file-code me-2"></i>
                Configuración — <strong>{{ configService?.name }}</strong>
              </h5>
              <small class="text-muted">{{ configService?.description }}</small>
            </div>
            <button class="btn-close" @click="showConfigModal = false"></button>
          </div>
          <div class="modal-body">

            <!-- Sin ficheros disponibles -->
            <div v-if="!loadingConfigs && !configFiles.length" class="alert alert-warning">
              <i class="bi bi-exclamation-triangle me-2"></i>
              No hay ficheros de configuración disponibles para este servicio.
            </div>

            <!-- Cargando lista -->
            <div v-if="loadingConfigs" class="text-center py-3">
              <div class="spinner-border spinner-border-sm text-primary me-2"></div>
              Cargando ficheros...
            </div>

            <template v-else-if="configFiles.length">
              <!-- Tabs de ficheros -->
              <ul class="nav nav-tabs mb-3">
                <li class="nav-item" v-for="f in configFiles" :key="f.label">
                  <button
                    class="nav-link"
                    :class="{ active: selectedConfigFile?.label === f.label }"
                    @click="loadConfigContent(f)"
                  >
                    <i class="bi bi-file-text me-1"></i>{{ f.label }}
                  </button>
                </li>
              </ul>

              <!-- Info del fichero -->
              <div v-if="selectedConfigFile" class="d-flex justify-content-between align-items-center mb-2">
                <code class="text-muted small">{{ selectedConfigFile.path }}</code>
                <span class="text-muted small">{{ selectedConfigFile.comment }}</span>
              </div>

              <!-- Editor -->
              <div v-if="loadingConfigContent" class="text-center py-3">
                <div class="spinner-border spinner-border-sm text-primary"></div>
              </div>
              <textarea
                v-else-if="configContent !== null"
                v-model="configContent"
                class="form-control font-monospace"
                style="min-height: 450px; font-size: 13px; white-space: pre; tab-size: 4;"
                spellcheck="false"
                @keydown.tab.prevent="insertTab"
              ></textarea>

              <!-- Resultado del guardado -->
              <div v-if="saveResult" class="mt-3">
                <div :class="saveResult.success ? 'alert alert-success' : 'alert alert-danger'" class="mb-0">
                  <div class="fw-semibold mb-1">
                    <i :class="saveResult.success ? 'bi bi-check-circle' : 'bi bi-x-circle'" class="me-2"></i>
                    {{ saveResult.success ? 'Guardado correctamente' : 'Error al guardar' }}
                  </div>
                  <pre v-if="saveResult.detail" class="mb-0 small" style="white-space:pre-wrap">{{ saveResult.detail }}</pre>
                  <div v-if="saveResult.test_output" class="mt-1 small text-muted">
                    <strong>Test:</strong> {{ saveResult.test_output }}
                  </div>
                  <div v-if="saveResult.backup" class="mt-1 small text-muted">
                    <i class="bi bi-archive me-1"></i>Backup: <code>{{ saveResult.backup }}</code>
                  </div>
                </div>
              </div>
            </template>

          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showConfigModal = false">Cerrar</button>
            <button
              v-if="configContent !== null"
              class="btn btn-primary"
              :disabled="savingConfig"
              @click="saveConfig"
            >
              <span v-if="savingConfig" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-floppy me-2"></i>
              Guardar y recargar servicio
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: confirmar parada de servicio -->
    <div v-if="serviceToStop" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-stop-circle me-2"></i>Detener servicio</h5>
            <button class="btn-close btn-close-white" @click="serviceToStop = null"></button>
          </div>
          <div class="modal-body">
            ¿Seguro que quieres detener <strong>{{ serviceToStop.name }}</strong>?
            <p class="text-danger small mt-2 mb-0">
              <i class="bi bi-exclamation-triangle me-1"></i>
              Esto puede dejar sin servicio a los dominios que dependen de él.
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="serviceToStop = null">Cancelar</button>
            <button class="btn btn-danger" @click="doAction(serviceToStop, 'stop'); serviceToStop = null">
              Detener
            </button>
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

    // Config editor
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
      try {
        stats.value = await api.getSystemStats()
      } catch (e) {
        store.showNotification('Error al cargar estadísticas: ' + e.message, 'danger')
      }
    }

    const loadServices = async () => {
      loadingServices.value = true
      try {
        const data = await api.getSystemServices()
        // Añadir campo _loading reactivo a cada servicio
        services.value = data.map(s => ({ ...s, _loading: false }))
      } catch (e) {
        store.showNotification('Error al cargar servicios: ' + e.message, 'danger')
      } finally {
        loadingServices.value = false
      }
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
        const actionLabels = { start: 'iniciado', stop: 'detenido', restart: 'reiniciado', reload: 'recargado' }
        store.showNotification(`${svc.name} ${actionLabels[action] || action}`, 'success')
        // Recargar solo el estado de los servicios
        await loadServices()
      } catch (e) {
        store.showNotification(`Error: ${e.message}`, 'danger')
        svc._loading = false
      }
    }

    const confirmStop = (svc) => { serviceToStop.value = svc }

    // ── Config editor ──────────────────────────────────────────────
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
      } finally {
        loadingConfigs.value = false
      }
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
      } finally {
        loadingConfigContent.value = false
      }
    }

    const saveConfig = async () => {
      if (!configService.value || !selectedConfigFile.value || configContent.value === null) return
      savingConfig.value = true
      saveResult.value = null
      try {
        const result = await api.writeServiceConfig(
          configService.value.name,
          selectedConfigFile.value.label,
          configContent.value
        )
        saveResult.value = { success: true, ...result }
        store.showNotification('Configuración guardada y servicio recargado', 'success')
        await loadServices()
      } catch (e) {
        saveResult.value = { success: false, detail: e.message }
      } finally {
        savingConfig.value = false
      }
    }

    const insertTab = (e) => {
      const start = e.target.selectionStart
      const end = e.target.selectionEnd
      configContent.value =
        configContent.value.substring(0, start) + '    ' + configContent.value.substring(end)
      // Mover cursor después de los 4 espacios
      e.target.selectionStart = e.target.selectionEnd = start + 4
    }

    onMounted(reload)

    return {
      stats, services, loading, loadingServices, serviceToStop,
      reload, doAction, confirmStop,
      // Config editor
      showConfigModal, configService, configFiles, selectedConfigFile,
      configContent, loadingConfigs, loadingConfigContent, savingConfig, saveResult,
      openConfig, loadConfigContent, saveConfig, insertTab,
    }
  }
}
</script>
