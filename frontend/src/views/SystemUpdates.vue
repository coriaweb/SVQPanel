<template>
  <div class="container-fluid py-3">
    <!-- Cabecera -->
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h4 class="mb-0">
        <i class="bi bi-gear me-2"></i>Sistema
      </h4>
    </div>

    <!-- Tabs -->
    <ul class="nav nav-tabs mb-3">
      <li class="nav-item">
        <button class="nav-link" :class="{ active: activeTab === 'versions' }"
                @click="activeTab = 'versions'">
          <i class="bi bi-tag me-1"></i>Versiones
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" :class="{ active: activeTab === 'updates' }"
                @click="activeTab = 'updates'">
          <i class="bi bi-arrow-repeat me-1"></i>Actualizaciones
        </button>
      </li>
    </ul>

    <!-- TAB: Versiones -->
    <div v-if="activeTab === 'versions'" class="tab-content">
      <div class="d-flex align-items-center justify-content-between mb-3">
        <h6 class="mb-0">Componentes instalados</h6>
        <button class="btn btn-outline-secondary btn-sm" @click="loadVersions" :disabled="loadingVersions">
          <span v-if="loadingVersions" class="spinner-border spinner-border-sm me-1"></span>
          <i v-else class="bi bi-arrow-repeat me-1"></i>Actualizar
        </button>
      </div>

      <div v-if="loadingVersions" class="text-center py-5">
        <div class="spinner-border text-primary me-2"></div>
        <span>Obteniendo versiones...</span>
      </div>

      <div v-else-if="versions && versions.components" class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Componente</th>
              <th>Versión instalada</th>
              <th>Última disponible</th>
              <th class="text-center">Estado</th>
              <th class="text-end">Documentación</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(info, key) in versions.components" :key="key"
                :class="{ 'table-warning': info.status === 'outdated' }">
              <td>
                <strong>{{ info.name }}</strong>
              </td>
              <td class="font-monospace small">
                <code>{{ info.version }}</code>
              </td>
              <td class="font-monospace small">
                <code v-if="info.latest && info.latest !== 'desconocida'" class="text-success">
                  {{ info.latest }}
                </code>
                <span v-else class="text-muted">—</span>
              </td>
              <td class="text-center">
                <span v-if="info.status === 'updated'" class="badge bg-success">
                  <i class="bi bi-check-circle me-1"></i>Actualizado
                </span>
                <span v-else-if="info.status === 'outdated'" class="badge bg-warning text-dark">
                  <i class="bi bi-exclamation-circle me-1"></i>Desactualizado
                </span>
                <span v-else class="badge bg-secondary">
                  <i class="bi bi-question-circle me-1"></i>Desconocido
                </span>
              </td>
              <td class="text-end">
                <a :href="info.docs" target="_blank" class="btn btn-outline-secondary btn-sm">
                  <i class="bi bi-box-arrow-up-right me-1"></i>Ver
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB: Actualizaciones -->
    <div v-if="activeTab === 'updates'" class="tab-content">
      <div class="d-flex align-items-center justify-content-between mb-3">
        <h6 class="mb-0">Paquetes disponibles</h6>
        <button class="btn btn-outline-primary btn-sm" @click="checkUpdates" :disabled="checking">
          <span v-if="checking" class="spinner-border spinner-border-sm me-1"></span>
          Comprobar actualizaciones
        </button>
      </div>

    <!-- Mensaje de estado -->
    <div v-if="statusMsg" class="alert" :class="statusError ? 'alert-danger' : 'alert-success'" role="alert">
      {{ statusMsg }}
    </div>

    <!-- No comprobado aún -->
    <div v-if="!checked && !checking" class="text-center text-muted py-5">
      <i class="bi bi-cloud-download fs-1 d-block mb-2"></i>
      Pulsa <strong>Comprobar actualizaciones</strong> para consultar los paquetes disponibles.
    </div>

    <!-- Comprobando -->
    <div v-if="checking" class="text-center py-5">
      <div class="spinner-border text-primary me-2"></div>
      <span>Actualizando índice APT, puede tardar unos segundos...</span>
    </div>

    <!-- Resultados -->
    <template v-if="checked && !checking">
      <div class="d-flex align-items-center justify-content-between mb-2">
        <span class="text-muted small">
          Última comprobación: {{ checkedAt }}
          — <strong>{{ packages.length }}</strong>
          {{ packages.length === 1 ? 'paquete disponible' : 'paquetes disponibles' }}
        </span>
        <button v-if="packages.length" class="btn btn-warning btn-sm" @click="upgradeAll" :disabled="upgrading">
          <span v-if="upgrading && upgradingPkg === 'all'" class="spinner-border spinner-border-sm me-1"></span>
          <i class="bi bi-cloud-arrow-up me-1"></i>Actualizar todo
        </button>
      </div>

      <div v-if="packages.length === 0" class="alert alert-success mb-0">
        <i class="bi bi-check-circle me-1"></i>El sistema está al día. No hay actualizaciones pendientes.
      </div>

      <div v-else class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Paquete</th>
              <th>Versión actual</th>
              <th>Nueva versión</th>
              <th>Origen</th>
              <th class="text-end">Acción</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pkg in packages" :key="pkg.name">
              <td class="font-monospace">{{ pkg.name }}</td>
              <td class="text-muted small">{{ pkg.current }}</td>
              <td class="text-success small fw-semibold">{{ pkg.available }}</td>
              <td class="text-muted small">{{ pkg.origin }}</td>
              <td class="text-end">
                <button class="btn btn-outline-success btn-sm"
                  @click="upgradePkg(pkg.name)"
                  :disabled="upgrading">
                  <span v-if="upgrading && upgradingPkg === pkg.name"
                    class="spinner-border spinner-border-sm me-1"></span>
                  Actualizar
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

      <!-- Log de salida del upgrade -->
      <div v-if="upgradeLog" class="mt-3">
        <h6 class="text-muted">Salida del proceso</h6>
        <pre class="bg-dark text-light p-3 rounded small"
          style="max-height:400px;overflow:auto;white-space:pre-wrap;">{{ upgradeLog }}</pre>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import api from '../services/api'

export default {
  name: 'SystemUpdates',
  setup() {
    // Tabs
    const activeTab = ref('versions')

    // Versiones
    const versions = ref(null)
    const loadingVersions = ref(false)

    // Actualizaciones
    const checking   = ref(false)
    const checked    = ref(false)
    const checkedAt  = ref('')
    const packages   = ref([])
    const upgrading  = ref(false)
    const upgradingPkg = ref('')
    const upgradeLog = ref('')
    const statusMsg  = ref('')
    const statusError = ref(false)

    const loadVersions = async () => {
      loadingVersions.value = true
      try {
        versions.value = await api.get('/api/system/versions')
      } catch (e) {
        console.error('Error cargando versiones:', e)
      } finally {
        loadingVersions.value = false
      }
    }

    onMounted(() => {
      loadVersions()
    })

    const checkUpdates = async () => {
      checking.value  = true
      statusMsg.value = ''
      statusError.value = false
      upgradeLog.value  = ''
      try {
        const data = await api.getSystemUpdates()
        packages.value = data.packages || []
        checkedAt.value = new Date(data.refreshed_at).toLocaleString('es-ES')
        checked.value   = true
      } catch (e) {
        statusError.value = true
        statusMsg.value   = 'Error al comprobar actualizaciones: ' + (e.message || String(e))
      } finally {
        checking.value = false
      }
    }

    const upgradeAll = () => runUpgrade(null)

    const upgradePkg = (name) => runUpgrade(name)

    const runUpgrade = async (pkg) => {
      upgrading.value    = true
      upgradingPkg.value = pkg || 'all'
      statusMsg.value    = ''
      statusError.value  = false
      upgradeLog.value   = ''
      try {
        const data = await api.runSystemUpgrade(pkg || null)
        upgradeLog.value  = (data.stdout || '') + (data.stderr ? '\n--- stderr ---\n' + data.stderr : '')
        if (data.success) {
          statusMsg.value   = pkg ? `Paquete "${pkg}" actualizado.` : 'Sistema actualizado.'
          statusError.value = false
          // Refrescar lista tras actualizar
          await checkUpdates()
        } else {
          statusMsg.value   = 'El proceso terminó con errores. Revisa la salida.'
          statusError.value = true
        }
      } catch (e) {
        statusError.value = true
        statusMsg.value   = 'Error durante la actualización: ' + (e.message || String(e))
      } finally {
        upgrading.value    = false
        upgradingPkg.value = ''
      }
    }

    return {
      activeTab,
      versions, loadingVersions, loadVersions,
      checking, checked, checkedAt, packages,
      upgrading, upgradingPkg, upgradeLog,
      statusMsg, statusError,
      checkUpdates, upgradeAll, upgradePkg,
    }
  }
}
</script>
