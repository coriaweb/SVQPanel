<template>
  <div class="container-fluid py-3">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h4 class="mb-0">
        <i class="bi bi-arrow-repeat me-2"></i>Actualizaciones del sistema
      </h4>
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
</template>

<script>
import { ref } from 'vue'
import api from '../services/api'

export default {
  name: 'SystemUpdates',
  setup() {
    const checking   = ref(false)
    const checked    = ref(false)
    const checkedAt  = ref('')
    const packages   = ref([])
    const upgrading  = ref(false)
    const upgradingPkg = ref('')
    const upgradeLog = ref('')
    const statusMsg  = ref('')
    const statusError = ref(false)

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
      checking, checked, checkedAt, packages,
      upgrading, upgradingPkg, upgradeLog,
      statusMsg, statusError,
      checkUpdates, upgradeAll, upgradePkg,
    }
  }
}
</script>
