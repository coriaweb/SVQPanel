<template>
  <div>
    <h2 class="mb-4"><i class="bi bi-gear"></i> Configuración del Panel</h2>

    <div v-if="loading" class="text-center py-5">
      <div class="spinner-border"></div>
    </div>

    <div v-else class="row g-4">

      <!-- IPv6 -->
      <div class="col-12">
        <div class="card border-primary">
          <div class="card-header bg-primary text-white">
            <i class="bi bi-diagram-3 me-2"></i> Red IPv6
          </div>
          <div class="card-body">
            <div class="row g-3">

              <div class="col-md-6">
                <div class="form-check form-switch mb-3">
                  <input
                    id="ipv6_enabled"
                    v-model="form.ipv6_enabled"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                  />
                  <label for="ipv6_enabled" class="form-check-label fw-bold">
                    Habilitar IPv6 en el panel
                  </label>
                </div>

                <div :class="{ 'opacity-50': !form.ipv6_enabled }">
                  <label class="form-label">
                    Rango IPv6 del servidor
                    <span class="text-muted small">(normalmente /64)</span>
                  </label>
                  <input
                    v-model="form.ipv6_range"
                    type="text"
                    class="form-control font-monospace"
                    placeholder="2a01:4f8:1:2::/64"
                    :disabled="!form.ipv6_enabled"
                  />
                  <div class="form-text">
                    El rango que te ha asignado tu proveedor de hosting.
                    Cada dominio recibirá una IP dedicada de este rango.
                  </div>
                </div>

                <div class="mt-3" :class="{ 'opacity-50': !form.ipv6_enabled }">
                  <label class="form-label">Interfaz de red</label>
                  <input
                    v-model="form.network_interface"
                    type="text"
                    class="form-control font-monospace"
                    placeholder="eth0"
                    :disabled="!form.ipv6_enabled"
                  />
                  <div class="form-text">
                    Interfaz donde se añadirán las IPs (<code>ip a</code> para verlas).
                    Normalmente <code>eth0</code> o <code>ens3</code>.
                  </div>
                </div>

                <div class="mt-3" :class="{ 'opacity-50': !form.ipv6_enabled }">
                  <label class="form-label">Gateway IPv6
                    <span class="text-muted small">(opcional)</span>
                  </label>
                  <input
                    v-model="form.ipv6_gateway"
                    type="text"
                    class="form-control font-monospace"
                    placeholder="fe80::1"
                    :disabled="!form.ipv6_enabled"
                  />
                </div>
              </div>

              <!-- Preview del rango -->
              <div class="col-md-6">
                <div v-if="form.ipv6_enabled && parsedRange" class="bg-dark text-success rounded p-3 font-monospace small h-100">
                  <div class="text-white mb-2 fw-bold"><i class="bi bi-broadcast me-1"></i> Rango configurado</div>
                  <div>Prefijo: <span class="text-info">{{ parsedRange.prefix }}</span></div>
                  <div>Máscara: <span class="text-info">/{{ parsedRange.prefixlen }}</span></div>
                  <div class="mt-2">IPs disponibles:
                    <span class="text-warning">~{{ parsedRange.totalFormatted }}</span>
                  </div>
                  <div v-if="settings?.ipv6_used_ips !== null" class="mt-1">
                    IPs asignadas: <span class="text-success">{{ settings.ipv6_used_ips }}</span>
                  </div>
                  <hr class="border-secondary my-2"/>
                  <div class="text-muted">Ejemplos de IPs que se asignarán:</div>
                  <div v-for="example in parsedRange.examples" :key="example" class="text-info">{{ example }}</div>
                </div>
                <div v-else-if="form.ipv6_enabled" class="bg-light rounded p-3 text-muted d-flex align-items-center justify-content-center h-100">
                  <div class="text-center">
                    <i class="bi bi-info-circle fs-3 mb-2"></i>
                    <p class="mb-0 small">Introduce un rango /64 para ver la vista previa</p>
                  </div>
                </div>
                <div v-else class="bg-light rounded p-3 text-muted d-flex align-items-center justify-content-center h-100">
                  <div class="text-center">
                    <i class="bi bi-toggle-off fs-3 mb-2"></i>
                    <p class="mb-0 small">IPv6 deshabilitado</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Red IPv4 -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header"><i class="bi bi-hdd-network me-1"></i> Red IPv4</div>
          <div class="card-body">
            <label class="form-label">IP pública del servidor</label>
            <input
              v-model="form.server_ipv4"
              type="text"
              class="form-control font-monospace"
              placeholder="185.104.188.71"
            />
            <div class="form-text">Dirección IPv4 principal del servidor.</div>
          </div>
        </div>
      </div>

      <!-- PHP Default -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header"><i class="bi bi-filetype-php me-1"></i> PHP por defecto</div>
          <div class="card-body">
            <label class="form-label">Versión PHP por defecto</label>
            <select v-model="form.php_default_version" class="form-select">
              <option value="8.5">PHP 8.5</option>
              <option value="8.4">PHP 8.4</option>
              <option value="8.3">PHP 8.3</option>
              <option value="8.2">PHP 8.2 (recomendado)</option>
              <option value="8.1">PHP 8.1</option>
              <option value="8.0">PHP 8.0</option>
              <option value="7.4">PHP 7.4</option>
            </select>
            <div class="form-text">Se usará al crear nuevos dominios.</div>
          </div>
        </div>
      </div>

      <!-- File Manager - Límites de upload -->
      <div class="col-12">
        <div class="card">
          <div class="card-header"><i class="bi bi-file-arrow-up me-2"></i> Gestor de Archivos - Límites</div>
          <div class="card-body">
            <div class="row g-3">
              <div class="col-md-4">
                <label class="form-label">Tamaño máximo de subida</label>
                <div class="input-group">
                  <input
                    v-model.number="form.max_upload_mb"
                    type="number"
                    class="form-control"
                    min="1"
                    max="2048"
                  />
                  <span class="input-group-text">MB</span>
                </div>
                <div class="form-text">Límite por archivo en subidas</div>
              </div>
              <div class="col-md-4">
                <label class="form-label">Máximo para editar en panel</label>
                <div class="input-group">
                  <input
                    v-model.number="form.max_text_file_mb"
                    type="number"
                    class="form-control"
                    min="1"
                    max="100"
                  />
                  <span class="input-group-text">MB</span>
                </div>
                <div class="form-text">Para editar archivos de texto</div>
              </div>
              <div class="col-md-4">
                <label class="form-label">Máximo para extraer ZIP</label>
                <div class="input-group">
                  <input
                    v-model.number="form.max_extract_mb"
                    type="number"
                    class="form-control"
                    min="1"
                    max="5120"
                  />
                  <span class="input-group-text">MB</span>
                </div>
                <div class="form-text">Para descomprimir archivos</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- PHP Versions Management -->
      <div class="col-12">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-filetype-php me-2"></i> Versiones PHP instaladas</span>
            <button class="btn btn-sm btn-outline-secondary" @click="loadPHPStatus" :disabled="phpLoading">
              <span v-if="phpLoading" class="spinner-border spinner-border-sm"></span>
              <i v-else class="bi bi-arrow-repeat"></i>
            </button>
          </div>
          <div class="card-body p-0">

            <div v-if="phpLoading" class="text-center py-4">
              <div class="spinner-border spinner-border-sm me-2"></div>
              <span class="text-muted small">Comprobando versiones PHP...</span>
            </div>

            <div v-else-if="phpError" class="alert alert-warning m-3 mb-2">
              <i class="bi bi-exclamation-triangle me-2"></i>
              {{ phpError }}
            </div>

            <div v-else>
              <div class="table-responsive">
                <table class="table table-hover mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Versión</th>
                      <th>Estado</th>
                      <th>FPM Socket</th>
                      <th class="text-end">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="php in phpVersions" :key="php.version">
                      <td>
                        <strong class="font-monospace">PHP {{ php.version }}</strong>
                        <span v-if="php.version === form.php_default_version" class="badge bg-info ms-2 small">por defecto</span>
                      </td>
                      <td>
                        <!-- Installed + Running -->
                        <span v-if="php.running" class="badge bg-success">
                          <i class="bi bi-check-circle me-1"></i> Activo
                        </span>
                        <!-- Installed but stopped -->
                        <span v-else-if="php.installed" class="badge bg-warning text-dark">
                          <i class="bi bi-pause-circle me-1"></i> Detenido
                        </span>
                        <!-- Not installed -->
                        <span v-else class="badge bg-secondary">
                          <i class="bi bi-x-circle me-1"></i> No instalado
                        </span>
                      </td>
                      <td class="font-monospace small text-muted">
                        {{ php.socket || '—' }}
                      </td>
                      <td class="text-end">
                        <!-- Not installed → install button -->
                        <button
                          v-if="!php.installed"
                          class="btn btn-sm btn-outline-primary"
                          @click="installPHP(php.version)"
                          :disabled="phpActionLoading === php.version"
                        >
                          <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                          <i v-else class="bi bi-download me-1"></i>
                          Instalar
                        </button>

                        <!-- Installed + stopped → enable button + uninstall -->
                        <template v-else-if="!php.running">
                          <button
                            class="btn btn-sm btn-outline-success me-1"
                            @click="enablePHP(php.version)"
                            :disabled="phpActionLoading === php.version"
                          >
                            <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                            <i v-else class="bi bi-play-circle me-1"></i>
                            Habilitar
                          </button>
                          <button
                            class="btn btn-sm btn-outline-danger"
                            @click="confirmUninstall(php.version)"
                            :disabled="phpActionLoading === php.version"
                          >
                            <i class="bi bi-trash me-1"></i>
                            Desinstalar
                          </button>
                        </template>

                        <!-- Installed + running → disable + uninstall -->
                        <template v-else>
                          <button
                            class="btn btn-sm btn-outline-warning me-1"
                            @click="disablePHP(php.version)"
                            :disabled="phpActionLoading === php.version"
                          >
                            <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                            <i v-else class="bi bi-pause-circle me-1"></i>
                            Deshabilitar
                          </button>
                          <button
                            class="btn btn-sm btn-outline-danger"
                            @click="confirmUninstall(php.version)"
                            :disabled="phpActionLoading === php.version"
                          >
                            <i class="bi bi-trash me-1"></i>
                            Desinstalar
                          </button>
                        </template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="p-3 border-top bg-light small text-muted">
                <i class="bi bi-info-circle me-1"></i>
                <strong>Habilitar</strong> = instala los paquetes y arranca PHP-FPM.
                <strong>Deshabilitar</strong> = para el servicio FPM (los paquetes se conservan).
                <strong>Desinstalar</strong> = elimina completamente los paquetes.
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Panel info -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header"><i class="bi bi-info-circle me-1"></i> Información del panel</div>
          <div class="card-body p-0">
            <ul class="list-group list-group-flush">
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Nombre</span>
                <strong>{{ settings?.panel_name }}</strong>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Versión</span>
                <span class="badge bg-secondary">{{ settings?.panel_version }}</span>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">API</span>
                <span class="badge bg-success">En línea</span>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">BD</span>
                <span class="badge bg-success">PostgreSQL</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Guardar configuración general -->
      <div class="col-12">
        <button class="btn btn-primary px-4" @click="saveSettings" :disabled="saving">
          <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
          <i v-else class="bi bi-floppy me-2"></i>
          Guardar configuración
        </button>
      </div>
    </div>

    <!-- Modal de confirmación para desinstalar PHP -->
    <div v-if="uninstallTarget" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2"></i> Desinstalar PHP {{ uninstallTarget }}</h5>
            <button type="button" class="btn-close btn-close-white" @click="uninstallTarget = null"></button>
          </div>
          <div class="modal-body">
            <p>¿Estás seguro de que quieres <strong>desinstalar PHP {{ uninstallTarget }}</strong>?</p>
            <p class="text-muted small mb-0">
              Esta acción eliminará todos los paquetes de PHP {{ uninstallTarget }} del servidor.
              Los dominios que usen esta versión dejarán de funcionar.
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="uninstallTarget = null">Cancelar</button>
            <button
              class="btn btn-danger"
              @click="uninstallPHP(uninstallTarget)"
              :disabled="phpActionLoading === uninstallTarget"
            >
              <span v-if="phpActionLoading === uninstallTarget" class="spinner-border spinner-border-sm me-1"></span>
              Confirmar desinstalación
            </button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, reactive, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'Settings',
  setup() {
    const store = useMainStore()
    const loading = ref(true)
    const saving = ref(false)
    const settings = ref(null)

    // PHP state
    const phpVersions = ref([])
    const phpLoading = ref(false)
    const phpError = ref(null)
    const phpActionLoading = ref(null)   // version string being acted on
    const uninstallTarget = ref(null)    // version pending uninstall confirmation

    const form = reactive({
      server_ipv4: '',
      ipv6_enabled: false,
      ipv6_range: '',
      ipv6_gateway: '',
      network_interface: 'eth0',
      php_default_version: '8.2',
      max_upload_mb: 100,
      max_text_file_mb: 2,
      max_extract_mb: 500,
    })

    const parsedRange = computed(() => {
      if (!form.ipv6_range) return null
      try {
        const parts = form.ipv6_range.split('/')
        if (parts.length !== 2) return null
        const prefixlen = parseInt(parts[1])
        if (isNaN(prefixlen) || prefixlen < 48 || prefixlen > 128) return null

        const prefix = parts[0]
        const available = Math.pow(2, 128 - prefixlen)
        const totalFormatted = prefixlen <= 64
          ? `${Math.pow(2, 64 - prefixlen).toLocaleString('es-ES')} × 10¹⁹`
          : available.toLocaleString('es-ES')

        const base = prefix.replace(/::$/, '')
        const examples = [
          `${base}::1`,
          `${base}::2`,
          `${base}::3`,
          '...',
        ]

        return { prefix, prefixlen, totalFormatted, examples }
      } catch {
        return null
      }
    })

    // ─── Settings ────────────────────────────────────────────────────────────

    const loadSettings = async () => {
      loading.value = true
      try {
        const data = await api.getSettings()
        settings.value = data
        form.server_ipv4 = data.server_ipv4 || ''
        form.ipv6_enabled = data.ipv6_enabled || false
        form.ipv6_range = data.ipv6_range || ''
        form.ipv6_gateway = data.ipv6_gateway || ''
        form.network_interface = data.network_interface || 'eth0'
        form.php_default_version = data.php_default_version || '8.2'
        form.max_upload_mb = data.max_upload_mb || 100
        form.max_text_file_mb = data.max_text_file_mb || 2
        form.max_extract_mb = data.max_extract_mb || 500
      } catch (e) {
        store.showNotification('Error al cargar configuración', 'danger')
      } finally {
        loading.value = false
      }
    }

    const saveSettings = async () => {
      saving.value = true
      try {
        const payload = {
          server_ipv4: form.server_ipv4 || null,
          ipv6_enabled: form.ipv6_enabled,
          ipv6_range: form.ipv6_range || null,
          ipv6_gateway: form.ipv6_gateway || null,
          network_interface: form.network_interface || 'eth0',
          php_default_version: form.php_default_version,
          max_upload_mb: form.max_upload_mb,
          max_text_file_mb: form.max_text_file_mb,
          max_extract_mb: form.max_extract_mb,
        }
        const data = await api.updateSettings(payload)
        settings.value = data
        store.showNotification('Configuración guardada correctamente', 'success')
      } catch (e) {
        store.showNotification('Error al guardar: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    // ─── PHP Management ───────────────────────────────────────────────────────

    const loadPHPStatus = async () => {
      phpLoading.value = true
      phpError.value = null
      try {
        const data = await api.getPHPVersionsStatus()
        phpVersions.value = data.versions
      } catch (e) {
        phpError.value = `No se pudo obtener el estado de PHP: ${e.message}`
      } finally {
        phpLoading.value = false
      }
    }

    const installPHP = async (version) => {
      phpActionLoading.value = version
      try {
        await api.installPHPVersion(version)
        store.showNotification(`PHP ${version} instalado correctamente`, 'success')
        await loadPHPStatus()
      } catch (e) {
        store.showNotification(`Error al instalar PHP ${version}: ${e.message}`, 'danger')
      } finally {
        phpActionLoading.value = null
      }
    }

    const enablePHP = async (version) => {
      phpActionLoading.value = version
      try {
        await api.enablePHPVersion(version)
        store.showNotification(`PHP ${version}-fpm habilitado`, 'success')
        await loadPHPStatus()
      } catch (e) {
        store.showNotification(`Error al habilitar PHP ${version}: ${e.message}`, 'danger')
      } finally {
        phpActionLoading.value = null
      }
    }

    const disablePHP = async (version) => {
      phpActionLoading.value = version
      try {
        await api.disablePHPVersion(version)
        store.showNotification(`PHP ${version}-fpm detenido`, 'success')
        await loadPHPStatus()
      } catch (e) {
        store.showNotification(`Error al deshabilitar PHP ${version}: ${e.message}`, 'danger')
      } finally {
        phpActionLoading.value = null
      }
    }

    const confirmUninstall = (version) => {
      uninstallTarget.value = version
    }

    const uninstallPHP = async (version) => {
      phpActionLoading.value = version
      try {
        await api.uninstallPHPVersion(version)
        store.showNotification(`PHP ${version} desinstalado`, 'success')
        uninstallTarget.value = null
        await loadPHPStatus()
      } catch (e) {
        store.showNotification(`Error al desinstalar PHP ${version}: ${e.message}`, 'danger')
      } finally {
        phpActionLoading.value = null
      }
    }

    onMounted(async () => {
      await loadSettings()
      await loadPHPStatus()
    })

    return {
      loading, saving, settings, form, parsedRange, saveSettings,
      phpVersions, phpLoading, phpError, phpActionLoading,
      uninstallTarget,
      loadPHPStatus, installPHP, enablePHP, disablePHP,
      confirmUninstall, uninstallPHP,
    }
  }
}
</script>
