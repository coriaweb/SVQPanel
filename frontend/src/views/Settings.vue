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
        <div class="card">
          <div class="card-header">
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
              readonly
              style="background: var(--surface-inset, #f2f4f7); cursor: not-allowed;"
            />
            <div class="form-text">
              Es la IP que el panel usa para los <strong>DNS y vhosts</strong> de los dominios.
              <strong>No cambia la IP del sistema.</strong> Para migrar a una IP nueva
              (p. ej. tu proveedor te la cambió), usa por SSH como root:
              <code>python -m api.cli change_server_ip &lt;IP_actual&gt; &lt;IP_nueva&gt;</code>
              — es una operación delicada (ver guía <code>docs/CAMBIO_IP_SERVIDOR.md</code>).
            </div>
          </div>
        </div>
      </div>

      <!-- SMTP Relay global (ancho completo, fila propia) -->
      <div class="sv-full" v-show="tab==='red'">
        <div class="card">
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
              <div class="col-md-8">
                <label class="form-label small mb-1">Host</label>
                <input v-model="relay.host" class="form-control form-control-sm font-monospace" placeholder="smtp-relay.brevo.com">
              </div>
              <div class="col-md-4">
                <label class="form-label small mb-1">Puerto</label>
                <input v-model.number="relay.port" type="number" class="form-control form-control-sm" placeholder="587">
              </div>
              <div class="col-md-6">
                <label class="form-label small mb-1">Usuario <span class="text-muted">(vacío = sin auth)</span></label>
                <input v-model="relay.username" class="form-control form-control-sm" autocomplete="off">
              </div>
              <div class="col-md-6">
                <label class="form-label small mb-1">Contraseña</label>
                <input v-model="relay.password" type="password" class="form-control form-control-sm"
                       autocomplete="new-password" :placeholder="relay.has_password ? '(sin cambios)' : ''">
              </div>
            </div>
            <button class="btn btn-primary btn-sm mt-3" @click="saveRelay" :disabled="relaySaving">
              <span v-if="relaySaving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-save me-1"></i>
              {{ relay.enabled ? 'Guardar relay' : 'Guardar (envío directo)' }}
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
              <option v-for="php in installedPhpVersions" :key="php.version" :value="php.version">
                PHP {{ php.version }}{{ php.version === recommendedPhp ? ' (recomendada)' : '' }}{{ !php.running ? ' — detenida' : '' }}
              </option>
              <!-- Si la actual no está instalada, mostrarla igualmente para no perder el valor -->
              <option v-if="form.php_default_version && !installedPhpVersions.some(p => p.version === form.php_default_version)"
                      :value="form.php_default_version">
                PHP {{ form.php_default_version }} — no instalada
              </option>
            </select>
            <div class="form-text">
              Se usará al crear nuevos dominios. Solo se listan las versiones instaladas.
              <span v-if="!installedPhpVersions.length" class="text-warning">
                <i class="bi bi-exclamation-triangle"></i> No hay ninguna versión PHP instalada todavía.
              </span>
            </div>
            <div v-if="defaultPhpNotInstalled" class="alert alert-warning py-2 small mt-2 mb-0">
              <i class="bi bi-exclamation-triangle me-1"></i>
              La versión por defecto (<strong>PHP {{ form.php_default_version }}</strong>) no está instalada.
              Instálala en "Versiones PHP" o elige otra para que los dominios nuevos funcionen.
            </div>
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
                      <span v-if="php.deprecated" class="php-tag php-tag--eol"
                            title="Versión sin soporte de seguridad oficial (EOL). Úsala solo para sitios antiguos que la requieran.">
                        <i class="bi bi-exclamation-triangle"></i> Sin soporte
                      </span>
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
      <!-- Política de contraseñas -->
      <div class="sv-full" v-show="tab==='sistema'">
        <div class="card">
          <div class="card-header">
            <i class="bi bi-key me-2"></i> Política de contraseñas
          </div>
          <div class="card-body">
            <p class="form-text" style="margin-top:0">
              Requisitos mínimos para las contraseñas que se establecen desde el panel
              (usuarios, buzones de correo…). Se valida también en el servidor y el
              generador del panel los respeta.
            </p>
            <div class="row g-3">
              <div class="sv-half">
                <label class="form-label">Longitud mínima</label>
                <input v-model.number="form.pwd_min_length" type="number" min="6" max="128" class="form-control" />
                <div class="form-text">Recomendado: 12 o más.</div>
              </div>
              <div class="sv-half">
                <label class="form-label">Composición obligatoria</label>
                <div class="form-check form-switch">
                  <input id="pwd_up" v-model="form.pwd_require_upper" class="form-check-input" type="checkbox" role="switch" />
                  <label for="pwd_up" class="form-check-label">Al menos una mayúscula</label>
                </div>
                <div class="form-check form-switch">
                  <input id="pwd_lo" v-model="form.pwd_require_lower" class="form-check-input" type="checkbox" role="switch" />
                  <label for="pwd_lo" class="form-check-label">Al menos una minúscula</label>
                </div>
                <div class="form-check form-switch">
                  <input id="pwd_di" v-model="form.pwd_require_digit" class="form-check-input" type="checkbox" role="switch" />
                  <label for="pwd_di" class="form-check-label">Al menos un número</label>
                </div>
                <div class="form-check form-switch">
                  <input id="pwd_sy" v-model="form.pwd_require_symbol" class="form-check-input" type="checkbox" role="switch" />
                  <label for="pwd_sy" class="form-check-label">Al menos un símbolo</label>
                </div>
              </div>
              <div class="sv-full">
                <label class="form-label">Probar la política</label>
                <PasswordField v-model="pwdTest" placeholder="Escribe o genera una contraseña de prueba" />
              </div>
            </div>
            <div style="margin-top:1rem">
              <button class="btn btn-primary" :disabled="saving" @click="saveSettings">
                <i class="bi bi-save me-1"></i> Guardar política
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="sv-full" v-show="tab==='sistema'">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
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
                    Forzar HTTPS (HSTS)
                  </label>
                </div>
                <div class="form-text small mt-1">
                  <i class="bi bi-info-circle me-1"></i>
                  La redirección <strong>HTTP → HTTPS ya está activa</strong> automáticamente.
                  Esta opción añade además <strong>HSTS</strong>, que <strong>no se recomienda</strong>
                  si el panel se sirve en un puerto no estándar (p. ej. 8083): el navegador
                  intentaría usar HTTPS en el puerto 443 y podría dejarte sin acceso al panel.
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

      <!-- Backup del propio panel -->
      <div class="sv-full" v-show="tab==='sistema'">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-database-fill-down me-2"></i> Backup del panel</span>
            <button class="btn btn-sm btn-outline-primary" @click="runPanelBackup" :disabled="pbRunning">
              <span v-if="pbRunning" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-play-circle me-1"></i> Backup ahora
            </button>
          </div>
          <div class="card-body">
            <p class="text-muted small mb-3">
              Copia de seguridad de la base de datos del panel (usuarios, dominios, DNS, correo,
              planes, configuración) y los ficheros críticos (<code>.env</code>, claves DKIM, etc.).
              Se ejecuta <strong>automáticamente cada día a las 03:30</strong> y se conservan las
              <strong>{{ pbRetention }}</strong> copias más recientes.
            </p>

            <!-- Retención configurable -->
            <div class="d-flex align-items-center gap-2 mb-3">
              <label class="small text-muted mb-0">Copias a conservar:</label>
              <input type="number" min="1" max="365" v-model.number="pbRetention"
                     class="form-control form-control-sm" style="width:90px" />
              <button class="btn btn-outline-secondary btn-sm" @click="savePbRetention" :disabled="pbSavingRet">
                <span v-if="pbSavingRet" class="spinner-border spinner-border-sm"></span>
                <span v-else>Guardar</span>
              </button>
            </div>

            <div v-if="!panelBackups.length" class="text-muted small">
              No hay backups todavía. Pulsa «Backup ahora» para crear el primero.
            </div>
            <template v-else>
              <div class="d-flex justify-content-between align-items-end mb-1">
                <span class="small text-muted">{{ panelBackups.length }} {{ panelBackups.length === 1 ? 'copia' : 'copias' }}</span>
              </div>
              <div class="pb-list">
                <div class="pb-row pb-row--head">
                  <span>Fecha</span><span>Tamaño</span><span class="text-end">Acciones</span>
                </div>
                <div v-for="b in panelBackups" :key="b.timestamp" class="pb-row">
                  <span>{{ formatBackupDate(b.created_at) }}</span>
                  <span>{{ fmtBytes(b.size) }}</span>
                  <span class="pb-actions">
                    <a v-if="b.db_file" :href="downloadUrl(b.db_file)" class="pb-dl" title="Descargar base de datos">
                      <i class="bi bi-filetype-sql"></i> BD
                    </a>
                    <a v-if="b.config_file" :href="downloadUrl(b.config_file)" class="pb-dl" title="Descargar configuración">
                      <i class="bi bi-file-zip"></i> Config
                    </a>
                    <button v-if="b.db_file" class="pb-restore"
                            @click="askRestore(b)" title="Restaurar la BD desde esta copia">
                      <i class="bi bi-arrow-counterclockwise"></i> Restaurar
                    </button>
                  </span>
                </div>
              </div>
            </template>

            <details class="mt-3">
              <summary class="small text-muted" style="cursor:pointer">Restaurar manualmente por SSH</summary>
              <div class="alert alert-secondary py-2 small mt-2 mb-0 font-monospace">
                # Por SSH, en el servidor:<br>
                gunzip -c panel_db_FECHA.sql.gz | psql -U panel_user panel_db<br>
                tar xzf config_FECHA.tar.gz -C /   # revisa antes de sobrescribir<br>
                systemctl restart svqpanel
              </div>
            </details>

            <!-- Modal de confirmación de restauración -->
            <div v-if="pbRestoreTarget" class="pb-modal-backdrop" @click.self="cancelRestore">
              <div class="pb-modal-card">
                <h5 class="text-danger"><i class="bi bi-exclamation-triangle-fill"></i> Restaurar el panel</h5>
                <p class="small mb-2">
                  Vas a restaurar la base de datos del panel desde la copia del
                  <strong>{{ formatBackupDate(pbRestoreTarget.created_at) }}</strong>.
                </p>
                <ul class="small text-muted">
                  <li>Se <strong>sobrescribirá TODO</strong> el estado actual (usuarios, dominios, planes…).</li>
                  <li>Antes se crea un <strong>backup de seguridad automático</strong>.</li>
                  <li>El panel <strong>se reiniciará</strong> al terminar (unos segundos de corte).</li>
                </ul>
                <p class="small mb-1">Para confirmar, escribe <code>RESTAURAR</code>:</p>
                <input v-model="pbRestoreConfirm" class="form-control form-control-sm mb-3"
                       placeholder="RESTAURAR" @keyup.enter="doRestore" />
                <div class="d-flex justify-content-end gap-2">
                  <button class="btn btn-secondary btn-sm" @click="cancelRestore">Cancelar</button>
                  <button class="btn btn-danger btn-sm" :disabled="pbRestoreConfirm.trim().toUpperCase() !== 'RESTAURAR' || pbRestoring" @click="doRestore">
                    <span v-if="pbRestoring" class="spinner-border spinner-border-sm me-1"></span>
                    Restaurar y reiniciar
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Whitelist de IPs del panel -->
      <div class="sv-full" v-show="tab==='sistema'">
        <div class="card" :class="wl.enabled ? 'border-warning' : ''">
          <div class="card-header d-flex justify-content-between align-items-center"
               :class="wl.enabled ? 'bg-warning text-dark' : ''">
            <span><i class="bi bi-shield-lock-fill me-2"></i> Acceso al panel por IP (whitelist)</span>
            <span class="badge" :class="wl.enabled ? 'bg-dark' : 'bg-light text-muted border'">
              {{ wl.enabled ? 'Activa' : 'Desactivada' }}
            </span>
          </div>
          <div class="card-body">
            <p class="text-muted small mb-3">
              Restringe el acceso al panel a IPs concretas. Cualquier otra IP recibirá
              <strong>403</strong> y no podrá ni ver el login. La validación ACME (<code>.well-known</code>)
              siempre se permite para que el SSL del panel pueda renovarse.
            </p>

            <div class="alert alert-warning py-2 small mb-3" v-if="!wl.enabled">
              <i class="bi bi-exclamation-triangle me-1"></i>
              <strong>Cuidado:</strong> si activas esto y tu IP no está en la lista, te quedarás fuera.
              Tu IP actual (<code>{{ wl.your_ip || '—' }}</code>) se añadirá automáticamente.
              Rescate por SSH: <code>python -m api.cli panel_whitelist_disable</code>
            </div>

            <div class="form-check form-switch mb-3">
              <input class="form-check-input" type="checkbox" role="switch" id="wlSw" v-model="wl.enabled">
              <label class="form-check-label fw-semibold" for="wlSw">Activar whitelist de IPs</label>
            </div>

            <div :class="{ 'opacity-50': !wl.enabled }">
              <label class="form-label small mb-1">IPs y rangos permitidos <span class="text-muted">(una por línea)</span></label>
              <textarea v-model="wl.ips" class="form-control form-control-sm font-monospace" rows="4"
                        :disabled="!wl.enabled"
                        placeholder="88.1.2.3&#10;10.0.0.0/8&#10;2a01:abc::/64"></textarea>
              <small class="text-muted">Acepta IPs sueltas y rangos CIDR (IPv4 e IPv6). Tu IP actual: <code>{{ wl.your_ip || '—' }}</code></small>
            </div>

            <button class="btn btn-warning btn-sm mt-3" @click="confirmSaveWhitelist" :disabled="wlSaving">
              <span v-if="wlSaving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-shield-check me-1"></i>
              {{ wl.enabled ? 'Aplicar whitelist' : 'Desactivar whitelist' }}
            </button>
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

    <!-- Modal de confirmación para activar whitelist -->
    <div v-if="showWlConfirm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)" @click.self="showWlConfirm=false">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header bg-warning text-dark">
            <h5 class="modal-title"><i class="bi bi-shield-lock me-2"></i> Confirmar whitelist del panel</h5>
            <button type="button" class="btn-close" @click="showWlConfirm=false"></button>
          </div>
          <div class="modal-body">
            <template v-if="wl.enabled">
              <p>Solo estas IPs podrán acceder al panel. El resto recibirá <strong>403</strong>:</p>
              <ul class="font-monospace small mb-3" style="max-height:160px;overflow:auto">
                <li v-for="(ip, i) in previewIps" :key="i">
                  {{ ip }}
                  <span v-if="ip === wl.your_ip" class="badge bg-success ms-1">tu IP</span>
                </li>
              </ul>
              <div class="alert alert-warning py-2 small mb-0">
                <i class="bi bi-info-circle me-1"></i>
                Tu IP actual (<code>{{ wl.your_ip }}</code>) está incluida, así que no te bloquearás.
                Si tu IP cambia luego, usa el rescate por SSH.
              </div>
            </template>
            <p v-else>Se desactivará la whitelist y el panel volverá a ser accesible desde cualquier IP.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showWlConfirm=false">Cancelar</button>
            <button class="btn btn-warning" @click="saveWhitelist" :disabled="wlSaving">
              <span v-if="wlSaving" class="spinner-border spinner-border-sm me-1"></span>
              {{ wl.enabled ? 'Sí, activar whitelist' : 'Sí, desactivar' }}
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
import PasswordField from '../components/PasswordField.vue'

export default {
  name: 'Settings',
  components: { PasswordField },
  setup() {
    const store = useMainStore()
    const loading = ref(true)
    const saving = ref(false)
    const settings = ref(null)
    const tab = ref('red')
    const pwdTest = ref('')

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

    // ─── Backup del panel ───
    const panelBackups = ref([])
    const pbRunning = ref(false)
    const pbRetention = ref(15)
    const pbSavingRet = ref(false)
    const pbRestoreTarget = ref(null)   // fila a restaurar (abre el modal)
    const pbRestoreConfirm = ref('')    // el admin debe escribir "RESTAURAR"
    const pbRestoring = ref(false)

    const loadPanelBackups = async () => {
      try {
        const r = await api.get('/api/settings/panel-backup')
        panelBackups.value = r.backups || []
        if (r.retention) pbRetention.value = r.retention
      } catch { /* silencioso */ }
    }
    const runPanelBackup = async () => {
      pbRunning.value = true
      try {
        await api.post('/api/settings/panel-backup', {})
        store.showNotification('Backup del panel creado', 'success')
        await loadPanelBackups()
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        pbRunning.value = false
      }
    }
    const savePbRetention = async () => {
      pbSavingRet.value = true
      try {
        const n = Math.max(1, Math.min(365, parseInt(pbRetention.value) || 15))
        pbRetention.value = n
        await api.put('/api/settings/panel-backup/retention', { retention: n })
        store.showNotification(`Se conservarán las ${n} copias más recientes`, 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        pbSavingRet.value = false
      }
    }
    const askRestore = (b) => {
      pbRestoreTarget.value = b
      pbRestoreConfirm.value = ''
    }
    const cancelRestore = () => {
      pbRestoreTarget.value = null
      pbRestoreConfirm.value = ''
    }
    const doRestore = async () => {
      if (!pbRestoreTarget.value || pbRestoreConfirm.value.trim().toUpperCase() !== 'RESTAURAR') return
      pbRestoring.value = true
      try {
        await api.post('/api/settings/panel-backup/restore', {
          filename: pbRestoreTarget.value.db_file,
        })
        cancelRestore()
        store.showNotification(
          'Restauración en marcha. El panel se reiniciará en unos segundos…', 'warning')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        pbRestoring.value = false
      }
    }
    const downloadUrl = (filename) => {
      const token = localStorage.getItem('token') || ''
      return `/api/settings/panel-backup/download/${filename}?token=${encodeURIComponent(token)}`
    }
    const fmtBytes = (b) => {
      if (!b) return '—'
      if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB'
      if (b >= 1024) return (b / 1024).toFixed(0) + ' KB'
      return b + ' B'
    }
    const formatBackupDate = (iso) => {
      if (!iso) return '—'
      try {
        return new Date(iso).toLocaleString('es-ES', {
          day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
        })
      } catch { return iso }
    }

    // ─── Whitelist de IPs del panel ───
    const wl = reactive({ enabled: false, ips: '', your_ip: '' })
    const wlSaving = ref(false)
    const showWlConfirm = ref(false)

    const previewIps = computed(() => {
      const list = (wl.ips || '').split('\n').map(s => s.trim()).filter(Boolean)
      // Si la IP actual no está, se mostrará añadida (como hace el backend)
      if (wl.your_ip && !list.includes(wl.your_ip)) list.unshift(wl.your_ip)
      return list
    })

    const loadWhitelist = async () => {
      try {
        const r = await api.get('/api/settings/panel-whitelist')
        wl.enabled = r.enabled
        wl.ips = r.ips || ''
        wl.your_ip = r.your_ip || ''
      } catch { /* silencioso */ }
    }

    const confirmSaveWhitelist = () => { showWlConfirm.value = true }

    const saveWhitelist = async () => {
      wlSaving.value = true
      try {
        const r = await api.post('/api/settings/panel-whitelist', {
          enabled: wl.enabled, ips: wl.ips,
        })
        wl.enabled = r.enabled
        wl.ips = r.ips || ''
        showWlConfirm.value = false
        store.showNotification(
          r.enabled ? `Whitelist activa (${r.count} IPs)` : 'Whitelist desactivada',
          'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        wlSaving.value = false
      }
    }
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
      max_upload_mb: 2048,
      max_text_file_mb: 2,
      max_extract_mb: 5120,
      pwd_min_length: 12,
      pwd_require_upper: true,
      pwd_require_lower: true,
      pwd_require_digit: true,
      pwd_require_symbol: false,
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

    // Versiones PHP instaladas (las que se pueden elegir como default), ordenadas desc
    const installedPhpVersions = computed(() =>
      phpVersions.value
        .filter(p => p.installed)
        .sort((a, b) => parseFloat(b.version) - parseFloat(a.version))
    )

    // Recomendada = la instalada y corriendo más reciente; si ninguna corre,
    // la instalada más reciente. Sin nada instalado, no recomienda.
    const recommendedPhp = computed(() => {
      const running = installedPhpVersions.value.filter(p => p.running)
      if (running.length) return running[0].version
      if (installedPhpVersions.value.length) return installedPhpVersions.value[0].version
      return null
    })

    // ¿El default elegido no está instalado? (aviso)
    const defaultPhpNotInstalled = computed(() =>
      !!form.php_default_version &&
      phpVersions.value.length > 0 &&
      !phpVersions.value.some(p => p.version === form.php_default_version && p.installed)
    )

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
        form.max_upload_mb = data.max_upload_mb || 2048
        form.max_text_file_mb = data.max_text_file_mb || 2
        form.max_extract_mb = data.max_extract_mb || 5120
        // Política de contraseñas
        form.pwd_min_length = data.pwd_min_length ?? 12
        form.pwd_require_upper = data.pwd_require_upper ?? true
        form.pwd_require_lower = data.pwd_require_lower ?? true
        form.pwd_require_digit = data.pwd_require_digit ?? true
        form.pwd_require_symbol = data.pwd_require_symbol ?? false
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
          pwd_min_length: form.pwd_min_length,
          pwd_require_upper: form.pwd_require_upper,
          pwd_require_lower: form.pwd_require_lower,
          pwd_require_digit: form.pwd_require_digit,
          pwd_require_symbol: form.pwd_require_symbol,
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
      loadWhitelist()
      loadPanelBackups()
    })

    return {
      tab,
      pwdTest,
      smtp, smtpSaving, smtpTesting, smtpTestMsg, smtpTestOk,
      showSmtpTest, smtpTestTo, saveSmtp, openSmtpTest, sendSmtpTest,
      wl, wlSaving, showWlConfirm, previewIps, confirmSaveWhitelist, saveWhitelist,
      panelBackups, pbRunning, runPanelBackup, downloadUrl, fmtBytes, formatBackupDate,
      pbRetention, pbSavingRet, savePbRetention,
      pbRestoreTarget, pbRestoreConfirm, pbRestoring, askRestore, cancelRestore, doRestore,
      loading, saving, settings, form, parsedRange, saveSettings,
      installedPhpVersions, recommendedPhp, defaultPhpNotInstalled,
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
.sv-title { margin: 0 0 4px; font-size: 1.5rem; font-weight: 700; letter-spacing: -.01em; display:flex; align-items:center; gap:.5rem; }
.sv-title .bi { color: var(--svq-orange); }
.sv-sub { margin: 0; font-size: 13px; color: var(--text-muted); }
.sv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* Tarjetas con look SVQ (esta vista usa markup .card de Bootstrap) */
.sv-grid :deep(.card),
.sv-full :deep(.card) {
  background: var(--surface);
  border: 1px solid var(--border) !important;
  border-radius: var(--r-lg, 12px);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.sv-grid :deep(.card-header),
.sv-full :deep(.card-header) {
  background: var(--surface-inset) !important;
  color: var(--text) !important;
  border-bottom: 1px solid var(--border);
  font-weight: var(--fw-semibold, 600);
  font-size: var(--fs-md, .95rem);
  padding: var(--sp-4, .9rem) var(--sp-5, 1.25rem);
}
.sv-grid :deep(.card-header .bi),
.sv-full :deep(.card-header .bi) { color: var(--svq-orange); }
.sv-grid :deep(.card-body),
.sv-full :deep(.card-body) { padding: var(--sp-5, 1.25rem); }
/* Conserva los badges de estado dentro de las cabeceras con su color propio */
.sv-grid :deep(.card-header .badge),
.sv-full :deep(.card-header .badge) { color: inherit; }

/* Pestañas */
.set-tabs { display:flex; gap:2px; flex-wrap:wrap; padding:.5rem; background:var(--surface-2); border-radius:var(--r-md,10px); }
.set-tab { display:inline-flex; align-items:center; gap:6px; padding:.45rem .9rem; border-radius:var(--r-sm,6px); font-size:.85rem; font-weight:500; cursor:pointer; border:none; background:none; color:var(--text-muted); transition:all .15s; }
.set-tab:hover { background:var(--surface); color:var(--text); }
.set-tab--active { background:var(--surface); color:var(--text); box-shadow:0 1px 3px rgba(0,0,0,.08); }

/* Lista de backups del panel */
.pb-list {
  display:flex; flex-direction:column;
  border:1px solid var(--border); border-radius:var(--r-md,8px);
  overflow-y:auto; overflow-x:hidden;
  max-height:340px;                 /* ~7 filas visibles; el resto con scroll */
}
.pb-row {
  display:grid; grid-template-columns:1fr 90px minmax(220px,auto);
  gap:1rem; padding:.6rem .85rem; align-items:center;
  font-size:.85rem; border-bottom:1px solid var(--border);
}
.pb-row:last-child { border-bottom:none; }
.pb-row--head {
  position:sticky; top:0; z-index:1;       /* la cabecera no se va al hacer scroll */
  background:var(--surface-2);
  font-size:.72rem; font-weight:600; text-transform:uppercase;
  letter-spacing:.04em; color:var(--text-muted);
}
.pb-actions { display:flex; align-items:center; justify-content:flex-end; gap:.75rem; }
.pb-dl { display:inline-flex; align-items:center; gap:4px; font-size:.8rem; color:var(--ac); text-decoration:none; white-space:nowrap; }
.pb-dl:hover { text-decoration:underline; }
.pb-restore {
  display:inline-flex; align-items:center; gap:4px;
  font-size:.8rem; color:var(--danger,#dc3545); background:none; border:none;
  padding:0; cursor:pointer; white-space:nowrap;
}
.pb-restore:hover { text-decoration:underline; }
@media (max-width:600px) {
  .pb-row { grid-template-columns:1fr auto; }
  .pb-row span:nth-child(2), .pb-row--head span:nth-child(2) { display:none; }
}
.pb-modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.5); display:flex; align-items:center; justify-content:center; z-index:1060; padding:1rem; }
.pb-modal-card { background:var(--surface,#fff); border-radius:var(--r-md,10px); padding:1.25rem 1.5rem; width:100%; max-width:460px; box-shadow:0 20px 60px rgba(0,0,0,.35); }

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
.php-tag--eol  { background: color-mix(in srgb, var(--danger,#dc2626) 13%, transparent); color: var(--danger,#dc2626); }

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

/* ─────────────────────────────────────────────────────────────────────────
   Formularios y botones con el look SVQ (esta vista usa markup tipo Bootstrap).
   Reestilamos aquí, scoped, para que NO dependa del bridge global y se vea
   igual que el resto del panel (Dashboard/Domains/Antispam).
   ───────────────────────────────────────────────────────────────────────── */
.sv-view :deep(.form-label) {
  font-size: .82rem; font-weight: 600; color: var(--text);
  margin-bottom: .35rem; display: block;
}
.sv-view :deep(.form-text) { font-size: .78rem; color: var(--text-muted); margin-top: .3rem; }

.sv-view :deep(.form-control),
.sv-view :deep(.form-select) {
  width: 100%;
  background: var(--surface-inset);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--r-sm, 8px);
  padding: .5rem .7rem;
  font-size: .9rem;
  transition: border-color .15s, box-shadow .15s;
}
.sv-view :deep(.form-select) {
  appearance: none; -webkit-appearance: none;
  padding-right: 2.25rem;
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3e%3cpath fill='none' stroke='%23667085' stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M2 5l6 6 6-6'/%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right .75rem center;
  background-size: 14px 14px;
}
/* select múltiple / con size: sin flecha (es una lista, no un desplegable) */
.sv-view :deep(.form-select[size]),
.sv-view :deep(.form-select[multiple]) { background-image: none; padding-right: .7rem; }
.sv-view :deep(.form-control::placeholder) { color: var(--text-muted); opacity: .7; }
.sv-view :deep(.form-control:focus),
.sv-view :deep(.form-select:focus) {
  outline: none;
  border-color: var(--ac);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ac) 18%, transparent);
}
.sv-view :deep(.form-control:disabled),
.sv-view :deep(.form-select:disabled) { opacity: .55; cursor: not-allowed; }
.sv-view :deep(.font-monospace),
.sv-view :deep(.font-mono) { font-family: var(--font-mono, monospace); }

/* Switches y checkboxes */
.sv-view :deep(.form-check) { display: flex; align-items: center; gap: .5rem; }
.sv-view :deep(.form-check-input) {
  appearance: none; -webkit-appearance: none;
  margin: 0; cursor: pointer; flex-shrink: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.sv-view :deep(.form-check-input:not([role="switch"])) {
  width: 1.1rem; height: 1.1rem; border-radius: var(--r-xs, 5px);
}
.sv-view :deep(.form-check-input:checked) {
  background: var(--ac); border-color: var(--ac);
}
/* Switch (role=switch): píldora con bolita */
.sv-view :deep(.form-check-input[role="switch"]) {
  width: 2.1rem; height: 1.15rem; border-radius: 999px; position: relative;
  transition: background .15s, border-color .15s;
}
.sv-view :deep(.form-check-input[role="switch"])::after {
  content: ""; position: absolute; top: 50%; left: 2px;
  width: .85rem; height: .85rem; border-radius: 50%;
  background: #fff; transform: translateY(-50%);
  transition: left .15s; box-shadow: 0 1px 2px rgba(0,0,0,.3);
}
.sv-view :deep(.form-check-input[role="switch"]:checked)::after { left: calc(100% - .95rem); }
.sv-view :deep(.form-check-label) { font-size: .88rem; color: var(--text); cursor: pointer; }

/* Botones */
.sv-view :deep(.btn) {
  display: inline-flex; align-items: center; justify-content: center; gap: .4rem;
  padding: .5rem .9rem; font-size: .85rem; font-weight: 600;
  border-radius: var(--r-sm, 8px); border: 1px solid transparent;
  cursor: pointer; transition: filter .15s, background .15s, border-color .15s;
  text-decoration: none; line-height: 1.2;
}
.sv-view :deep(.btn:disabled) { opacity: .55; cursor: not-allowed; }
.sv-view :deep(.btn-primary) { background: var(--ac); color: #fff; }
.sv-view :deep(.btn-primary:hover:not(:disabled)) { filter: brightness(1.08); }
.sv-view :deep(.btn-success) { background: var(--success); color: #fff; }
.sv-view :deep(.btn-danger)  { background: var(--danger); color: #fff; }
.sv-view :deep(.btn-warning) { background: var(--warning); color: #fff; }
.sv-view :deep(.btn-secondary) { background: var(--surface-2); color: var(--text); border-color: var(--border); }
.sv-view :deep(.btn-outline-primary),
.sv-view :deep(.btn-outline-secondary),
.sv-view :deep(.btn-outline-danger) {
  background: transparent; border-color: var(--border); color: var(--text);
}
.sv-view :deep(.btn-outline-primary:hover:not(:disabled)) { border-color: var(--ac); color: var(--ac); }
.sv-view :deep(.btn-outline-danger:hover:not(:disabled)) { border-color: var(--danger); color: var(--danger); }
.sv-view :deep(.btn-sm) { padding: .3rem .6rem; font-size: .78rem; }

/* Badges */
.sv-view :deep(.badge) {
  display: inline-flex; align-items: center; gap: .25rem;
  padding: .2rem .55rem; border-radius: 999px;
  font-size: .72rem; font-weight: 600;
}
.sv-view :deep(.bg-success), .sv-view :deep(.badge.bg-success) { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.sv-view :deep(.bg-danger),  .sv-view :deep(.badge.bg-danger)  { background: color-mix(in srgb, var(--danger) 16%, transparent); color: var(--danger); }
.sv-view :deep(.bg-warning), .sv-view :deep(.badge.bg-warning) { background: color-mix(in srgb, var(--warning) 16%, transparent); color: var(--warning); }
.sv-view :deep(.bg-secondary),.sv-view :deep(.badge.bg-secondary){ background: var(--surface-2); color: var(--text-muted); }

/* Alerts */
.sv-view :deep(.alert) {
  border-radius: var(--r-md, 10px); padding: .75rem 1rem;
  font-size: .85rem; border: 1px solid var(--border);
}
.sv-view :deep(.alert-success) { background: color-mix(in srgb, var(--success) 8%, transparent); border-color: color-mix(in srgb, var(--success) 30%, transparent); color: var(--text); }
.sv-view :deep(.alert-danger)  { background: color-mix(in srgb, var(--danger) 8%, transparent);  border-color: color-mix(in srgb, var(--danger) 30%, transparent);  color: var(--text); }
.sv-view :deep(.alert-warning) { background: color-mix(in srgb, var(--warning) 8%, transparent); border-color: color-mix(in srgb, var(--warning) 30%, transparent); color: var(--text); }
.sv-view :deep(.alert-info)    { background: color-mix(in srgb, var(--info) 8%, transparent);    border-color: color-mix(in srgb, var(--info) 30%, transparent);    color: var(--text); }

/* Input group (campo + botón pegados) */
.sv-view :deep(.input-group) { display: flex; align-items: stretch; }
.sv-view :deep(.input-group) > :deep(.form-control) { border-top-right-radius: 0; border-bottom-right-radius: 0; }
.sv-view :deep(.input-group) > :deep(.btn) { border-top-left-radius: 0; border-bottom-left-radius: 0; }
.sv-view :deep(.input-group-text) {
  display: flex; align-items: center; padding: 0 .7rem;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted);
  font-size: .85rem;
}

/* List group (listas de filas) */
.sv-view :deep(.list-group) { border: 1px solid var(--border); border-radius: var(--r-md, 10px); overflow: hidden; }
.sv-view :deep(.list-group-item) {
  background: var(--surface); color: var(--text);
  border: none; border-bottom: 1px solid var(--border);
  padding: .65rem .9rem; font-size: .88rem;
}
.sv-view :deep(.list-group-item:last-child) { border-bottom: none; }

/* Spinner */
.sv-view :deep(.spinner-border) {
  display: inline-block; width: 1.6rem; height: 1.6rem;
  border: 2px solid var(--border); border-top-color: var(--ac);
  border-radius: 50%; animation: sv-spin .6s linear infinite;
}
@keyframes sv-spin { to { transform: rotate(360deg); } }
</style>
