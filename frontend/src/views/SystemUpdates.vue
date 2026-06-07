<template>
  <div class="sv-view">
    <!-- Cabecera page-head -->
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Sistema</h1>
        <p class="page-head__sub">Versiones de componentes y actualizaciones de paquetes del servidor</p>
      </div>
    </div>

    <BaseTabs v-model="activeTab" :tabs="tabs" class="su-tabs" />

    <!-- ===== TAB: Versiones ===== -->
    <BaseCard v-if="activeTab === 'versions'" title="Componentes instalados" icon="box-seam">
      <template #actions>
        <BaseButton variant="ghost" size="sm" :loading="loadingVersions" @click="loadVersions">
          <i class="bi bi-arrow-repeat"></i> Actualizar
        </BaseButton>
      </template>

      <div v-if="loadingVersions" class="svq-skeleton" style="height:180px"></div>

      <div v-else-if="versions && versions.components" class="su-table-wrap">
        <table class="su-table">
          <thead>
            <tr>
              <th>Componente</th>
              <th>Versión instalada</th>
              <th class="su-right">Documentación</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(info, key) in versions.components" :key="key">
              <td><strong>{{ info.name }}</strong></td>
              <td><code class="su-code">{{ info.version }}</code></td>
              <td class="su-right">
                <BaseButton tag="a" :href="info.docs" target="_blank" variant="ghost" size="sm">
                  <i class="bi bi-box-arrow-up-right"></i> Ver
                </BaseButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <!-- ===== TAB: Actualizaciones ===== -->
    <BaseCard v-if="activeTab === 'updates'" title="Paquetes disponibles" icon="arrow-repeat">
      <template #actions>
        <BaseButton variant="secondary" size="sm" :loading="checking" @click="checkUpdates">
          Comprobar actualizaciones
        </BaseButton>
      </template>

      <!-- Aviso de dpkg interrumpido (recuperable) -->
      <div v-if="dpkgInterrupted" class="su-alert su-alert--warn">
        <div class="su-alert__body">
          <i class="bi bi-tools"></i>
          <div>
            <strong>El gestor de paquetes está bloqueado</strong>
            <p>Una instalación anterior se quedó a medias (<code>dpkg</code> interrumpido). Hasta repararlo, no se pueden aplicar actualizaciones. Es una operación segura.</p>
          </div>
        </div>
        <BaseButton variant="primary" size="sm" :loading="repairing" @click="repairDpkg">
          <i class="bi bi-wrench-adjustable"></i> Reparar ahora
        </BaseButton>
      </div>

      <!-- Mensaje de estado -->
      <div v-if="statusMsg" class="su-alert" :class="statusError ? 'su-alert--danger' : 'su-alert--success'">
        <i class="bi" :class="statusError ? 'bi-exclamation-octagon' : 'bi-check-circle'"></i>
        <span>{{ statusMsg }}</span>
      </div>

      <!-- No comprobado aún -->
      <EmptyState v-if="!checked && !checking" icon="cloud-download"
                  title="Sin comprobar"
                  description="Pulsa «Comprobar actualizaciones» para consultar los paquetes disponibles." />

      <!-- Comprobando -->
      <div v-if="checking" class="su-loading">
        <div class="spinner-border spinner-border-sm"></div>
        <span>Actualizando índice APT, puede tardar unos segundos…</span>
      </div>

      <!-- Resultados -->
      <template v-if="checked && !checking">
        <div class="su-results-head">
          <span class="su-muted">
            Última comprobación: {{ checkedAt }}
            — <strong>{{ packages.length }}</strong>
            {{ packages.length === 1 ? 'paquete disponible' : 'paquetes disponibles' }}
          </span>
          <BaseButton v-if="packages.length" variant="primary" size="sm"
                      :loading="upgrading && upgradingPkg === 'all'" @click="upgradeAll">
            <i class="bi bi-cloud-arrow-up"></i> Actualizar todo
          </BaseButton>
        </div>

        <div v-if="packages.length === 0" class="su-alert su-alert--success">
          <i class="bi bi-check-circle"></i>
          <span>El sistema está al día. No hay actualizaciones pendientes.</span>
        </div>

        <div v-else class="su-table-wrap">
          <table class="su-table">
            <thead>
              <tr>
                <th>Paquete</th>
                <th>Versión actual</th>
                <th>Nueva versión</th>
                <th>Origen</th>
                <th class="su-right">Acción</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="pkg in packages" :key="pkg.name">
                <td><code class="su-code">{{ pkg.name }}</code></td>
                <td class="su-muted">{{ pkg.current }}</td>
                <td class="su-new">{{ pkg.available }}</td>
                <td class="su-muted">{{ pkg.origin }}</td>
                <td class="su-right">
                  <BaseButton variant="ghost" size="sm"
                              :loading="upgrading && upgradingPkg === pkg.name"
                              :disabled="upgrading"
                              @click="upgradePkg(pkg.name)">
                    Actualizar
                  </BaseButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Log de salida del proceso -->
      <div v-if="upgradeLog" class="su-log-wrap">
        <h6 class="su-log-title">Salida del proceso</h6>
        <pre class="su-log">{{ upgradeLog }}</pre>
      </div>
    </BaseCard>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseTabs from '../components/ui/BaseTabs.vue'
import EmptyState from '../components/ui/EmptyState.vue'

export default {
  name: 'SystemUpdates',
  components: { BaseCard, BaseButton, BaseTabs, EmptyState },
  setup() {
    const activeTab = ref('versions')
    const tabs = [
      { key: 'versions', label: 'Versiones',       icon: 'tag' },
      { key: 'updates',  label: 'Actualizaciones', icon: 'arrow-repeat' },
    ]

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
    const dpkgInterrupted = ref(false)
    const repairing  = ref(false)

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

    onMounted(loadVersions)

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
      dpkgInterrupted.value = false
      try {
        const data = await api.runSystemUpgrade(pkg || null)
        upgradeLog.value  = (data.stdout || '') + (data.stderr ? '\n--- stderr ---\n' + data.stderr : '')
        if (data.success) {
          statusMsg.value   = pkg ? `Paquete "${pkg}" actualizado.` : 'Sistema actualizado.'
          statusError.value = false
          await checkUpdates()
        } else if (data.dpkg_interrupted) {
          // Caso recuperable: ofrecer reparación en vez de error en crudo
          dpkgInterrupted.value = true
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

    const repairDpkg = async () => {
      repairing.value = true
      statusMsg.value = ''
      statusError.value = false
      try {
        const data = await api.repairDpkg()
        upgradeLog.value = (data.stdout || '') + (data.stderr ? '\n--- stderr ---\n' + data.stderr : '')
        if (data.success) {
          dpkgInterrupted.value = false
          statusMsg.value   = 'Gestor de paquetes reparado. Ya puedes aplicar las actualizaciones.'
          statusError.value = false
          await checkUpdates()
        } else {
          statusMsg.value   = 'La reparación terminó con errores. Revisa la salida.'
          statusError.value = true
        }
      } catch (e) {
        statusError.value = true
        statusMsg.value   = 'Error reparando dpkg: ' + (e.message || String(e))
      } finally {
        repairing.value = false
      }
    }

    return {
      activeTab, tabs,
      versions, loadingVersions, loadVersions,
      checking, checked, checkedAt, packages,
      upgrading, upgradingPkg, upgradeLog,
      statusMsg, statusError, dpkgInterrupted, repairing,
      checkUpdates, upgradeAll, upgradePkg, repairDpkg,
    }
  }
}
</script>

<style scoped>
/* Cabecera */
.page-head { margin-bottom: var(--sp-5); }
.page-head__title { font-size: 1.5rem; font-weight: var(--fw-bold, 700); margin: 0; letter-spacing: -.01em; }
.page-head__sub { color: var(--text-muted); margin: .25rem 0 0; font-size: var(--fs-sm); }

.su-tabs { margin-bottom: var(--sp-5); }

/* Tablas */
.su-table-wrap { overflow-x: auto; }
.su-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.su-table thead th {
  text-align: left; padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .04em;
  color: var(--text-muted); font-weight: var(--fw-semibold);
  border-bottom: 1px solid var(--border); background: var(--surface-inset);
}
.su-table tbody td { padding: var(--sp-3); border-bottom: 1px solid var(--border); vertical-align: middle; }
.su-table tbody tr:last-child td { border-bottom: none; }
.su-table tbody tr:hover { background: var(--surface-inset); }
.su-right { text-align: right; }
.su-code { font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-secondary); }
.su-muted { color: var(--text-muted); font-size: var(--fs-sm); }
.su-new { color: var(--success); font-weight: var(--fw-semibold); }

/* Cabecera de resultados */
.su-results-head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-bottom: var(--sp-3); flex-wrap: wrap; }

/* Avisos */
.su-alert {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md);
  border: 1px solid var(--border); margin-bottom: var(--sp-4); font-size: var(--fs-sm);
}
.su-alert--success { background: var(--success-bg); border-color: var(--success-border); color: var(--success); }
.su-alert--danger  { background: var(--danger-bg);  border-color: var(--danger-border);  color: var(--danger); }
.su-alert--warn    {
  background: var(--warning-bg); border-color: var(--warning-border);
  justify-content: space-between; gap: var(--sp-4); align-items: center; flex-wrap: wrap;
}
.su-alert__body { display: flex; gap: var(--sp-3); align-items: flex-start; }
.su-alert__body i { font-size: 1.25rem; color: var(--warning); margin-top: 2px; }
.su-alert__body strong { color: var(--text); }
.su-alert__body p { margin: 2px 0 0; color: var(--text-secondary); font-size: var(--fs-sm); line-height: 1.45; }

/* Cargando */
.su-loading { display: flex; align-items: center; gap: var(--sp-2); justify-content: center; padding: var(--sp-6) 0; color: var(--text-muted); }

/* Log */
.su-log-wrap { margin-top: var(--sp-4); }
.su-log-title { font-size: var(--fs-sm); color: var(--text-muted); margin: 0 0 var(--sp-2); }
.su-log {
  background: var(--svq-navy, #0f172a); color: #e2e8f0;
  padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md);
  font-size: var(--fs-xs); font-family: var(--font-mono);
  max-height: 400px; overflow: auto; white-space: pre-wrap; margin: 0;
}
</style>
