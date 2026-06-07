<template>
  <div class="sv-view">
    <div class="sv-head">
      <div>
        <h1 class="sv-title"><i class="bi bi-gear"></i> Configuración</h1>
        <p class="sv-sub">Ajustes generales del panel SVQPanel</p>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:48px">
      <div class="spinner-border"></div>
    </div>

    <!-- Pestañas -->
    <div v-if="!loading" class="set-tabs">
      <button v-for="t in [
        {key:'red',     icon:'hdd-network', label:'Red'},
        {key:'php',     icon:'filetype-php', label:'PHP'},
        {key:'archivos',icon:'file-arrow-up', label:'Archivos'},
        {key:'email',   icon:'envelope-at', label:'Email'},
        {key:'sistema', icon:'sliders', label:'SSL y Sistema'},
      ]" :key="t.key" class="set-tab" :class="{'set-tab--active': tab===t.key}" @click="tab=t.key">
        <i :class="'bi bi-'+t.icon"></i> {{ t.label }}
      </button>
    </div>

    <div v-if="!loading" class="sv-grid">

      <!-- ══ RED ══ -->
      <!-- IPv6 - ancho completo -->
      <div class="sv-full" v-show="tab==='red'">
        <div class="card" style="border-color:var(--ac)">
          <div class="card-header" style="background:var(--ac);color:#fff">
            <i class="bi bi-diagram-3 me-2"></i> Red IPv6
          </div>
          <div class="card-body">
            <div class="row g-3">

              <div class="sv-half">
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

                <!-- IPv6 dedicada del panel -->
                <div class="mt-3 border rounded p-3" :class="{ 'opacity-50': !form.ipv6_enabled }">
                  <div class="d-flex align-items-center justify-content-between mb-2">
                    <div>
                      <div class="fw-semibold"><i class="bi bi-shield-lock me-1"></i> IPv6 del panel</div>
                      <div class="text-muted small">
                        Primera IP del rango (::1), reservada exclusivamente para el panel.
                        Las IPs de clientes se asignan desde ::2 en adelante.
                      </div>
                    </div>
                  </div>
                  <div v-if="settings?.panel_ipv6" class="d-flex align-items-center gap-2 mb-2">
                    <span class="badge bg-success font-monospace">{{ settings.panel_ipv6 }}</span>
                    <span class="text-success small"><i class="bi bi-check-circle me-1"></i>Asignada</span>
                  </div>
                  <div v-else class="text-muted small mb-2">
                    <i class="bi bi-exclamation-circle me-1"></i>No asignada aún
                  </div>
                  <button
                    class="btn btn-sm btn-outline-primary"
                    :disabled="!form.ipv6_enabled || !settings?.ipv6_range || assigningPanelIpv6"
                    @click="assignPanelIpv6"
                  >
                    <span v-if="assigningPanelIpv6" class="spinner-border spinner-border-sm me-1"></span>
                    <i v-else class="bi bi-lightning me-1"></i>
                    {{ settings?.panel_ipv6 ? 'Reasignar IPv6 al panel' : 'Asignar IPv6 al panel' }}
                  </button>
                  <div v-if="panelIpv6Msg" class="mt-2 small" :class="panelIpv6Ok ? 'text-success' : 'text-danger'">
                    {{ panelIpv6Msg }}
                  </div>
                </div>
              </div>

              <!-- Preview del rango -->
              <div class="sv-half">
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
      <div class="sv-half" v-show="tab==='red'">
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

      <!-- ══ PHP ══ -->
      <!-- PHP Default -->
      <div class="sv-half" v-show="tab==='php'">
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

      <!-- ══ ARCHIVOS ══ -->
      <!-- File Manager - Límites de upload -->
      <div class="sv-full" v-show="tab==='archivos'">
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
      <div class="sv-full" v-show="tab==='php'">
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
              <div class="php-list">
                <div v-for="php in phpVersions" :key="php.version" class="php-row">
                  <div class="php-row__main">
                    <div class="php-row__ver">
                      <strong class="font-monospace">PHP {{ php.version }}</strong>
                      <span v-if="php.version === form.php_default_version" class="php-tag php-tag--default">por defecto</span>
                    </div>
                    <span v-if="php.running" class="php-tag php-tag--on"><i class="bi bi-check-circle"></i> Activo</span>
                    <span v-else-if="php.installed" class="php-tag php-tag--warn"><i class="bi bi-pause-circle"></i> Detenido</span>
                    <span v-else class="php-tag php-tag--off"><i class="bi bi-x-circle"></i> No instalado</span>
                  </div>
                  <div class="php-row__socket font-monospace">{{ php.socket || '—' }}</div>
                  <div class="php-row__actions">
                    <button v-if="!php.installed" class="btn btn-sm btn-outline-primary"
                      @click="installPHP(php.version)" :disabled="phpActionLoading === php.version">
                      <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                      <i v-else class="bi bi-download me-1"></i>Instalar
                    </button>
                    <template v-else-if="!php.running">
                      <button class="btn btn-sm btn-outline-success" @click="enablePHP(php.version)" :disabled="phpActionLoading === php.version">
                        <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                        <i v-else class="bi bi-play-circle me-1"></i>Habilitar
                      </button>
                      <button class="btn btn-sm btn-outline-danger" @click="confirmUninstall(php.version)" :disabled="phpActionLoading === php.version">
                        <i class="bi bi-trash me-1"></i>Desinstalar
                      </button>
                    </template>
                    <template v-else>
                      <button class="btn btn-sm btn-outline-warning" @click="disablePHP(php.version)" :disabled="phpActionLoading === php.version">
                        <span v-if="phpActionLoading === php.version" class="spinner-border spinner-border-sm me-1"></span>
                        <i v-else class="bi bi-pause-circle me-1"></i>Deshabilitar
                      </button>
                      <button class="btn btn-sm btn-outline-danger" @click="confirmUninstall(php.version)" :disabled="phpActionLoading === php.version">
                        <i class="bi bi-trash me-1"></i>Desinstalar
                      </button>
                    </template>
                  </div>
                </div>
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

      <!-- ══ SSL Y SISTEMA ══ -->
      <!-- SSL del Panel -->
      <div class="sv-full" v-show="tab==='sistema'">
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
              <div class="sv-half">
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
              <div class="sv-half">
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
      <div class="sv-half" v-show="tab==='sistema'">
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
      <div class="sv-half" v-show="tab==='sistema'">
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

      <!-- ══ EMAIL (SMTP del panel) ══ -->
      <div class="sv-full" v-show="tab==='email'">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-envelope-at me-2"></i> Email saliente del panel (SMTP)</span>
            <span class="badge" :class="smtp.enabled ? 'bg-success' : 'bg-light text-muted border'">
              {{ smtp.enabled ? 'Activo' : 'Desactivado' }}
            </span>
          </div>
          <div class="card-body">
            <p class="text-muted small mb-3">
              Configura un SMTP externo para que <strong>todos los avisos del panel</strong>
              (recuperación de contraseña, alertas de cuota, expiración de SSL, etc.) se envíen
              desde un remitente real en lugar de <code>root@localhost</code>.
            </p>

            <div class="form-check form-switch mb-3">
              <input class="form-check-input" type="checkbox" role="switch" id="smtpSw" v-model="smtp.enabled">
              <label class="form-check-label" for="smtpSw">Activar envío por SMTP externo</label>
            </div>

            <div :class="{ 'opacity-50': !smtp.enabled }">
              <div class="row g-3">
                <div class="col-md-8">
                  <label class="form-label small mb-1">Servidor SMTP <span class="text-danger">*</span></label>
                  <input v-model="smtp.host" class="form-control form-control-sm font-monospace"
                         placeholder="smtp.tudominio.com" :disabled="!smtp.enabled">
                </div>
                <div class="col-md-2">
                  <label class="form-label small mb-1">Puerto</label>
                  <input v-model.number="smtp.port" type="number" class="form-control form-control-sm"
                         placeholder="587" :disabled="!smtp.enabled">
                </div>
                <div class="col-md-2">
                  <label class="form-label small mb-1">Seguridad</label>
                  <select v-model="smtp.security" class="form-select form-select-sm" :disabled="!smtp.enabled">
                    <option value="starttls">STARTTLS</option>
                    <option value="ssl">SSL/TLS</option>
                    <option value="none">Ninguna</option>
                  </select>
                </div>

                <div class="col-md-6">
                  <label class="form-label small mb-1">Usuario <span class="text-muted">(vacío = sin auth)</span></label>
                  <input v-model="smtp.username" class="form-control form-control-sm" autocomplete="off"
                         placeholder="avisos@tudominio.com" :disabled="!smtp.enabled">
                </div>
                <div class="col-md-6">
                  <label class="form-label small mb-1">Contraseña</label>
                  <input v-model="smtp.password" type="password" class="form-control form-control-sm"
                         autocomplete="new-password" :disabled="!smtp.enabled"
                         :placeholder="smtp.has_password ? '(sin cambios)' : ''">
                </div>

                <div class="col-md-7">
                  <label class="form-label small mb-1">Dirección "From" <span class="text-danger">*</span></label>
                  <input v-model="smtp.from_email" type="email" class="form-control form-control-sm font-monospace"
                         placeholder="avisos@tudominio.com" :disabled="!smtp.enabled">
                </div>
                <div class="col-md-5">
                  <label class="form-label small mb-1">Nombre del remitente</label>
                  <input v-model="smtp.from_name" class="form-control form-control-sm"
                         placeholder="SVQPanel" :disabled="!smtp.enabled">
                </div>
              </div>

              <div class="d-flex gap-2 align-items-center mt-3 flex-wrap">
                <button class="btn btn-primary btn-sm" @click="saveSmtp" :disabled="smtpSaving">
                  <span v-if="smtpSaving" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-save me-1"></i>Guardar configuración
                </button>
                <button class="btn btn-outline-secondary btn-sm" @click="openSmtpTest" :disabled="!smtp.enabled || smtpTesting">
                  <span v-if="smtpTesting" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-send me-1"></i>Enviar email de prueba
                </button>
                <span v-if="smtpTestMsg" :class="smtpTestOk ? 'text-success' : 'text-danger'" class="small">
                  {{ smtpTestMsg }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Guardar configuración general (solo pestañas con campos del form) -->
      <div class="sv-full" v-show="['red','php','archivos'].includes(tab)">
        <button class="btn btn-primary px-4" @click="saveSettings" :disabled="saving">
          <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
          <i v-else class="bi bi-floppy me-2"></i>
          Guardar configuración
        </button>
      </div>
    </div>

    <!-- Modal: email de prueba -->
    <div v-if="showSmtpTest" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)" @click.self="showSmtpTest=false">
      <div class="modal-dialog modal-dialog-centered modal-sm">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-send me-2"></i>Email de prueba</h5>
            <button type="button" class="btn-close" @click="showSmtpTest=false"></button>
          </div>
          <div class="modal-body">
            <label class="form-label small">Enviar a</label>
            <input v-model="smtpTestTo" type="email" class="form-control" placeholder="tu@email.com" autofocus>
            <p class="text-muted small mt-2 mb-0">Se usará la configuración actual (guárdala primero si la cambiaste).</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary btn-sm" @click="showSmtpTest=false">Cancelar</button>
            <button class="btn btn-primary btn-sm" @click="sendSmtpTest" :disabled="smtpTesting || !smtpTestTo">
              <span v-if="smtpTesting" class="spinner-border spinner-border-sm me-1"></span>
              Enviar
            </button>
          </div>
        </div>
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
    const tab = ref('red')

    // ─── SMTP del panel ───
    const smtp = reactive({
      enabled: false, host: '', port: 587, security: 'starttls',
      username: '', password: '', from_email: '', from_name: 'SVQPanel',
      has_password: false,
    })
    const smtpSaving  = ref(false)
    const smtpTesting = ref(false)
    const smtpTestMsg = ref('')
    const smtpTestOk  = ref(false)
    const showSmtpTest = ref(false)
    const smtpTestTo  = ref('')

    const loadSmtp = async () => {
      try {
        const r = await api.get('/api/settings/panel-smtp')
        smtp.enabled = r.enabled
        smtp.host = r.host || ''
        smtp.port = r.port || 587
        smtp.security = r.security || 'starttls'
        smtp.username = r.username || ''
        smtp.password = ''
        smtp.from_email = r.from_email || ''
        smtp.from_name = r.from_name || 'SVQPanel'
        smtp.has_password = r.has_password || false
      } catch { /* silencioso */ }
    }

    const saveSmtp = async () => {
      if (smtp.enabled && (!smtp.host || !smtp.from_email)) {
        store.showNotification('Indica al menos el host y la dirección From', 'danger'); return
      }
      smtpSaving.value = true
      try {
        await api.post('/api/settings/panel-smtp', {
          enabled: smtp.enabled, host: smtp.host, port: smtp.port,
          security: smtp.security, username: smtp.username, password: smtp.password,
          from_email: smtp.from_email, from_name: smtp.from_name,
        })
        store.showNotification('Configuración SMTP guardada', 'success')
        smtp.password = ''
        await loadSmtp()
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        smtpSaving.value = false
      }
    }

    const openSmtpTest = () => {
      smtpTestMsg.value = ''
      smtpTestTo.value = smtp.from_email || ''
      showSmtpTest.value = true
    }

    const sendSmtpTest = async () => {
      smtpTesting.value = true
      smtpTestMsg.value = ''
      try {
        await api.post('/api/settings/panel-smtp/test', {
          to: smtpTestTo.value,
          host: smtp.host, port: smtp.port, security: smtp.security,
          username: smtp.username, password: smtp.password || null,
          from_email: smtp.from_email, from_name: smtp.from_name,
        })
        smtpTestOk.value = true
        smtpTestMsg.value = `✓ Email enviado a ${smtpTestTo.value}`
        showSmtpTest.value = false
        store.showNotification('Email de prueba enviado correctamente', 'success')
      } catch (e) {
        smtpTestOk.value = false
        smtpTestMsg.value = '✕ ' + (e.message || 'Error al enviar')
        store.showNotification('Error al enviar: ' + (e.message || e), 'danger')
      } finally {
        smtpTesting.value = false
      }
    }

    // SSL del panel
    const sslLoading = ref(false)
    const showRevokeConfirm = ref(false)
    const sslForm = reactive({
      hostname: '',
      email: '',
      force_https: true,
    })

    // IPv6 del panel
    const assigningPanelIpv6 = ref(false)
    const panelIpv6Msg = ref('')
    const panelIpv6Ok = ref(false)

    const assignPanelIpv6 = async () => {
      assigningPanelIpv6.value = true
      panelIpv6Msg.value = ''
      try {
        const res = await api.assignPanelIpv6()
        panelIpv6Ok.value = true
        panelIpv6Msg.value = res.message || `IPv6 ${res.panel_ipv6} asignada correctamente`
        // Recargar settings para reflejar la nueva IP
        await loadSettings()
      } catch (e) {
        panelIpv6Ok.value = false
        panelIpv6Msg.value = e.message || 'Error asignando IPv6 al panel'
      } finally {
        assigningPanelIpv6.value = false
      }
    }

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
      loadSmtp()
    })

    return {
      tab,
      smtp, smtpSaving, smtpTesting, smtpTestMsg, smtpTestOk,
      showSmtpTest, smtpTestTo, saveSmtp, openSmtpTest, sendSmtpTest,
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
      assigningPanelIpv6, panelIpv6Msg, panelIpv6Ok, assignPanelIpv6,
    }
  }
}
</script>

<style scoped>
.sv-view { display: flex; flex-direction: column; gap: 20px; }
.sv-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.sv-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
.sv-sub { margin: 0; font-size: 13px; color: var(--text-muted); }
.sv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* Pestañas */
.set-tabs { display:flex; gap:2px; flex-wrap:wrap; padding:.5rem; background:var(--surface-2); border-radius:var(--r-md,10px); }
.set-tab { display:inline-flex; align-items:center; gap:6px; padding:.45rem .9rem; border-radius:var(--r-sm,6px); font-size:.85rem; font-weight:500; cursor:pointer; border:none; background:none; color:var(--text-muted); transition:all .15s; }
.set-tab:hover { background:var(--surface); color:var(--text); }
.set-tab--active { background:var(--surface); color:var(--text); box-shadow:0 1px 3px rgba(0,0,0,.08); }

/* Lista de versiones PHP — fila en desktop, tarjeta apilada en móvil */
.php-list { display: flex; flex-direction: column; }
.php-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.php-row:last-child { border-bottom: none; }
.php-row__main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.php-row__ver { display: flex; align-items: center; gap: 8px; }
.php-row__socket { font-size: .78rem; color: var(--text-muted); }
.php-row__actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }

.php-tag {
  display: inline-flex; align-items: center; gap: .25rem;
  padding: .2rem .55rem; border-radius: 999px;
  font-size: .72rem; font-weight: 600; white-space: nowrap;
}
.php-tag--default { background: color-mix(in srgb, var(--ac) 15%, transparent); color: var(--ac); }
.php-tag--on   { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.php-tag--warn { background: color-mix(in srgb, var(--warning,#f59e0b) 15%, transparent); color: var(--warning,#d97706); }
.php-tag--off  { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }

@media (max-width: 640px) {
  .php-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .php-row__socket { font-size: .72rem; }
  .php-row__actions { justify-content: flex-start; }
}
.sv-full { grid-column: 1 / -1; }
@media (max-width: 768px) { .sv-grid { grid-template-columns: 1fr; } .sv-half { grid-column: 1 / -1; } }
</style>
