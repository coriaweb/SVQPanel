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

        <!-- SMTP Relay global -->
        <div class="card mt-3">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-arrow-up-right-circle me-1"></i> Relay SMTP global</span>
            <span v-if="relay.enabled" class="badge bg-success">Activo</span>
            <span v-else class="badge bg-light text-muted border">Envío directo</span>
          </div>
          <div class="card-body">
            <p class="text-muted small mb-3">
              Smarthost por el que sale TODO el correo del servidor — útil si tu proveedor
              bloquea el puerto 25 saliente. Cada dominio puede overridearlo con su propio relay.
            </p>
            <div class="form-check form-switch mb-3">
              <input class="form-check-input" type="checkbox" role="switch" v-model="relay.enabled" id="relaySw">
              <label class="form-check-label" for="relaySw">Usar relay global</label>
            </div>
            <div v-if="relay.enabled" class="row g-2">
              <div class="col-8">
                <label class="form-label small mb-1">Host</label>
                <input v-model="relay.host" class="form-control form-control-sm font-monospace" placeholder="smtp-relay.brevo.com">
              </div>
              <div class="col-4">
                <label class="form-label small mb-1">Puerto</label>
                <input v-model.number="relay.port" type="number" class="form-control form-control-sm" placeholder="587">
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">Usuario <span class="text-muted">(vacío = sin auth)</span></label>
                <input v-model="relay.username" class="form-control form-control-sm" autocomplete="off">
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">Contraseña</label>
                <input v-model="relay.password" type="password" class="form-control form-control-sm"
                       autocomplete="new-password" :placeholder="relay.has_password ? '(sin cambios)' : ''">
              </div>
            </div>
            <button class="btn btn-primary btn-sm mt-3" @click="saveRelay" :disabled="relaySaving">
              <span v-if="relaySaving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-save me-1"></i>
              {{ relay.enabled ? 'Guardar relay' : 'Desactivar relay' }}
            </button>
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

      <!-- SSL del Panel -->
      <div class="col-12">
        <div class="card border-success">
          <div class="card-header bg-success text-white d-flex justify-content-between align-items-center">
            <span><i class="bi bi-shield-lock me-2"></i> SSL del Panel</span>
            <span v-if="settings?.ssl_panel_enabled" class="badge bg-light text-success">
              <i class="bi bi-check-circle-fill me-1"></i> Activo
            </span>
            <span v-else class="badge bg-light text-secondary">
              <i class="bi bi-x-circle me-1"></i> Sin SSL
            </span>
          </div>
          <div class="card-body">
            <div class="row g-3">
              <div class="col-md-6">
                <label class="form-label fw-bold">Hostname del panel</label>
                <input
                  v-model="sslForm.hostname"
                  type="text"
                  class="form-control font-monospace"
                  placeholder="panel.tudominio.com"
                  :disabled="settings?.ssl_panel_enabled"
                />
                <div class="form-text">
                  El dominio (o subdominio) que apunta a la IP de este servidor. Debe tener el DNS ya configurado.
                </div>

                <label class="form-label fw-bold mt-3">Email para Let's Encrypt</label>
                <input
                  v-model="sslForm.email"
                  type="email"
                  class="form-control"
                  placeholder="admin@tudominio.com"
                  :disabled="settings?.ssl_panel_enabled"
                />
                <div class="form-text">
                  Se usa para notificaciones de renovación del certificado.
                </div>

                <div class="form-check form-switch mt-3">
                  <input
                    id="force_https"
                    v-model="sslForm.force_https"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                    :disabled="settings?.ssl_panel_enabled"
                  />
                  <label for="force_https" class="form-check-label">
                    Forzar HTTPS (redirigir HTTP → HTTPS automáticamente)
                  </label>
                </div>
              </div>

              <!-- Estado SSL -->
              <div class="col-md-6">
                <div v-if="settings?.ssl_panel_enabled" class="bg-success bg-opacity-10 border border-success rounded p-3 h-100">
                  <div class="fw-bold text-success mb-2">
                    <i class="bi bi-shield-check me-1"></i> Certificado activo
                  </div>
                  <div class="small">
                    <div class="mb-1">
                      <span class="text-muted">Hostname:</span>
                      <strong class="font-monospace ms-1">{{ settings.panel_hostname }}</strong>
                    </div>
                    <div class="mb-1">
                      <span class="text-muted">Expira:</span>
                      <strong class="ms-1">{{ formatExpiry(settings.ssl_panel_expires) }}</strong>
                    </div>
                    <div class="mb-1">
                      <span class="text-muted">Forzar HTTPS:</span>
                      <span :class="settings.force_https ? 'text-success' : 'text-secondary'" class="ms-1 fw-bold">
                        {{ settings.force_https ? 'Sí' : 'No' }}
                      </span>
                    </div>
                  </div>
                  <div class="mt-3">
                    <button
                      class="btn btn-sm btn-outline-danger"
                      @click="showRevokeConfirm = true"
                      :disabled="sslLoading"
                    >
                      <i class="bi bi-shield-x me-1"></i> Revocar certificado
                    </button>
                  </div>
                </div>
                <div v-else class="bg-light rounded p-3 d-flex flex-column align-items-center justify-content-center h-100 text-center">
                  <i class="bi bi-shield-exclamation fs-2 text-warning mb-2"></i>
                  <p class="mb-1 small text-muted">El panel funciona por <strong>HTTP</strong>.</p>
                  <p class="mb-0 small text-muted">Emite un certificado SSL para habilitarlo por HTTPS.</p>
                </div>
              </div>

              <!-- Botón emitir -->
              <div v-if="!settings?.ssl_panel_enabled" class="col-12">
                <button
                  class="btn btn-success"
                  @click="issueSSL"
                  :disabled="sslLoading || !sslForm.hostname || !sslForm.email"
                >
                  <span v-if="sslLoading" class="spinner-border spinner-border-sm me-2"></span>
                  <i v-else class="bi bi-shield-lock me-2"></i>
                  Emitir certificado SSL para el panel
                </button>
                <div class="form-text text-warning mt-1">
                  <i class="bi bi-exclamation-triangle me-1"></i>
                  El hostname debe apuntar a la IP <strong>{{ settings?.server_ipv4 || 'del servidor' }}</strong> antes de continuar.
                  Este proceso puede tardar unos segundos.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Zona Horaria del Servidor -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-clock-history me-1"></i> Zona Horaria del Servidor</span>
            <span v-if="tzCurrent" class="badge bg-secondary font-monospace">{{ tzCurrent }}</span>
          </div>
          <div class="card-body">
            <label class="form-label">Seleccionar zona horaria</label>
            <div class="input-group mb-2">
              <input
                v-model="tzSearch"
                type="text"
                class="form-control"
                placeholder="Filtrar... (ej: Europe, Madrid)"
              />
            </div>
            <select v-model="tzSelected" class="form-select" size="5" style="height:auto">
              <option v-for="tz in filteredTimezones" :key="tz" :value="tz">{{ tz }}</option>
            </select>
            <div class="form-text">Zona horaria actual del SO: <strong>{{ tzCurrent || '…' }}</strong></div>
            <button
              class="btn btn-sm btn-outline-primary mt-2"
              @click="saveTimezone"
              :disabled="!tzSelected || tzSaving"
            >
              <span v-if="tzSaving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-clock me-1"></i>
              Aplicar zona horaria
            </button>
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

    <!-- Modal de confirmación para revocar SSL del panel -->
    <div v-if="showRevokeConfirm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-shield-x me-2"></i> Revocar SSL del Panel</h5>
            <button type="button" class="btn-close btn-close-white" @click="showRevokeConfirm = false"></button>
          </div>
          <div class="modal-body">
            <p>¿Estás seguro de que quieres <strong>revocar el certificado SSL</strong> del panel?</p>
            <p class="text-muted small mb-0">
              El panel volverá a servirse solo por HTTP. Los certificados de Let's Encrypt se eliminarán del servidor.
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showRevokeConfirm = false">Cancelar</button>
            <button class="btn btn-danger" @click="revokeSSL" :disabled="sslLoading">
              <span v-if="sslLoading" class="spinner-border spinner-border-sm me-1"></span>
              Confirmar revocación
            </button>
          </div>
        </div>
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

    // SSL del panel
    const sslLoading = ref(false)
    const showRevokeConfirm = ref(false)
    const sslForm = reactive({
      hostname: '',
      email: '',
      force_https: true,
    })

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

    // ─── SMTP relay global ───
    const relay = reactive({
      enabled: false, host: '', port: 587, username: '', password: '', has_password: false,
    })
    const relaySaving = ref(false)

    const loadRelay = async () => {
      try {
        const r = await api.getGlobalRelay()
        relay.enabled = r.enabled
        relay.host = r.host || ''
        relay.port = r.port || 587
        relay.username = r.username || ''
        relay.password = ''
        relay.has_password = r.has_password || false
      } catch (e) { /* silencioso */ }
    }

    const saveRelay = async () => {
      if (relay.enabled && !relay.host) {
        store.showNotification('Indica el host del relay', 'danger'); return
      }
      relaySaving.value = true
      try {
        await api.setGlobalRelay({
          enabled: relay.enabled, host: relay.host, port: relay.port,
          username: relay.username, password: relay.password,
        })
        store.showNotification(relay.enabled ? 'Relay global guardado' : 'Relay global desactivado', 'success')
        await loadRelay()
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        relaySaving.value = false
      }
    }

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
        // SSL del panel
        sslForm.hostname = data.panel_hostname || ''
        sslForm.email = ''
        sslForm.force_https = data.force_https ?? true
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

    // ─── Timezone ─────────────────────────────────────────────────────────────

    const tzCurrent   = ref('')
    const tzSelected  = ref('')
    const tzSearch    = ref('')
    const tzList      = ref([])
    const tzSaving    = ref(false)

    const filteredTimezones = computed(() => {
      if (!tzSearch.value) return tzList.value
      const q = tzSearch.value.toLowerCase()
      return tzList.value.filter(tz => tz.toLowerCase().includes(q))
    })

    const loadTimezones = async () => {
      try {
        const r = await api.get('/api/settings/timezones')
        tzList.value = r?.timezones || []
      } catch { /* silencioso */ }
    }

    const loadCurrentTimezone = async () => {
      try {
        const r = await api.get('/api/settings/timezone-current')
        tzCurrent.value  = r?.timezone || 'UTC'
        tzSelected.value = tzCurrent.value
      } catch { /* silencioso */ }
    }

    const saveTimezone = async () => {
      if (!tzSelected.value) return
      tzSaving.value = true
      try {
        await api.post('/api/settings/timezone', { timezone: tzSelected.value })
        tzCurrent.value = tzSelected.value
        store.showNotification(`Zona horaria cambiada a ${tzSelected.value}`, 'success')
      } catch (e) {
        store.showNotification('Error al cambiar la zona horaria: ' + e.message, 'danger')
      } finally {
        tzSaving.value = false
      }
    }

    // ─── SSL del Panel ────────────────────────────────────────────────────────

    const formatExpiry = (isoDate) => {
      if (!isoDate) return '—'
      try {
        return new Date(isoDate).toLocaleDateString('es-ES', {
          day: '2-digit', month: 'long', year: 'numeric'
        })
      } catch {
        return isoDate
      }
    }

    const issueSSL = async () => {
      if (!sslForm.hostname || !sslForm.email) return
      sslLoading.value = true
      try {
        await api.issuePanelSSL({
          hostname: sslForm.hostname,
          email: sslForm.email,
          force_https: sslForm.force_https,
        })
        store.showNotification('Certificado SSL emitido correctamente. El panel ya está disponible por HTTPS.', 'success')
        await loadSettings()
      } catch (e) {
        store.showNotification('Error al emitir SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    const revokeSSL = async () => {
      sslLoading.value = true
      try {
        await api.revokePanelSSL()
        store.showNotification('Certificado SSL del panel revocado.', 'success')
        showRevokeConfirm.value = false
        await loadSettings()
      } catch (e) {
        store.showNotification('Error al revocar SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    onMounted(async () => {
      await loadSettings()
      await loadPHPStatus()
      loadTimezones()
      loadCurrentTimezone()
      loadRelay()
    })

    return {
      loading, saving, settings, form, parsedRange, saveSettings,
      phpVersions, phpLoading, phpError, phpActionLoading,
      uninstallTarget,
      loadPHPStatus, installPHP, enablePHP, disablePHP,
      confirmUninstall, uninstallPHP,
      sslForm, sslLoading, showRevokeConfirm,
      issueSSL, revokeSSL, formatExpiry,
      tzCurrent, tzSelected, tzSearch, tzList, tzSaving,
      filteredTimezones, saveTimezone,
      relay, relaySaving, saveRelay,
    }
  }
}
</script>
