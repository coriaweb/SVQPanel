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

      <!-- PHP -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header"><i class="bi bi-filetype-php me-1"></i> PHP</div>
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

      <!-- Guardar -->
      <div class="col-12">
        <button class="btn btn-primary px-4" @click="saveSettings" :disabled="saving">
          <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
          <i v-else class="bi bi-floppy me-2"></i>
          Guardar configuración
        </button>
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

    const form = reactive({
      server_ipv4: '',
      ipv6_enabled: false,
      ipv6_range: '',
      ipv6_gateway: '',
      php_default_version: '8.2',
    })

    const parsedRange = computed(() => {
      if (!form.ipv6_range) return null
      try {
        // Validar formato básico
        const parts = form.ipv6_range.split('/')
        if (parts.length !== 2) return null
        const prefixlen = parseInt(parts[1])
        if (isNaN(prefixlen) || prefixlen < 48 || prefixlen > 128) return null

        const prefix = parts[0]
        const available = Math.pow(2, 128 - prefixlen)
        const totalFormatted = prefixlen <= 64
          ? `${Math.pow(2, 64 - prefixlen).toLocaleString('es-ES')} × 10¹⁹`
          : available.toLocaleString('es-ES')

        // Generar ejemplos de IPs
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

    const loadSettings = async () => {
      loading.value = true
      try {
        const data = await api.getSettings()
        settings.value = data
        form.server_ipv4 = data.server_ipv4 || ''
        form.ipv6_enabled = data.ipv6_enabled || false
        form.ipv6_range = data.ipv6_range || ''
        form.ipv6_gateway = data.ipv6_gateway || ''
        form.php_default_version = data.php_default_version || '8.2'
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
          php_default_version: form.php_default_version,
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

    onMounted(loadSettings)

    return { loading, saving, settings, form, parsedRange, saveSettings }
  }
}
</script>
