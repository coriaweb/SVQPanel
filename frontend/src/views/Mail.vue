<template>
  <div class="container-fluid py-4">

    <!-- ── Cabecera ── -->
    <div class="page-head-row">
      <div>
        <div v-if="selectedDomain" class="d-flex align-items-center gap-2 mb-1">
          <button class="btn btn-sm btn-outline-secondary" @click="selectedDomain = null">
            <i class="bi bi-arrow-left me-1"></i>Dominios
          </button>
          <i class="bi bi-chevron-right text-muted small"></i>
          <span class="fw-semibold">{{ selectedDomain.domain_name }}</span>
          <span :class="selectedDomain.is_active ? 'badge bg-success' : 'badge bg-secondary'">
            {{ selectedDomain.is_active ? 'Activo' : 'Suspendido' }}
          </span>
        </div>
        <h2 class="mb-1">
          <i class="bi bi-envelope me-2"></i>
          {{ selectedDomain ? selectedDomain.domain_name : 'Correo Electrónico' }}
        </h2>
        <p class="text-muted mb-0">
          {{ selectedDomain
            ? `${selectedDomain.mailbox_count} buzones · ${selectedDomain.alias_count} alias`
            : 'Gestión de dominios de correo, buzones y alias' }}
        </p>
      </div>
      <div class="d-flex gap-2">
        <button v-if="!selectedDomain" class="btn btn-outline-secondary btn-sm"
                @click="loadDomains" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
          <i v-else class="bi bi-arrow-repeat me-1"></i>Actualizar
        </button>
        <button v-if="!selectedDomain && mailEnabled !== false"
                class="btn btn-primary btn-sm" @click="openNewDomain">
          <i class="bi bi-plus-lg me-1"></i>Añadir dominio
        </button>
      </div>
    </div>

    <!-- ══════════ CORREO NO INSTALADO ══════════ -->
    <div v-if="mailEnabled === false" class="card border-0 shadow-sm">
      <div class="card-body text-center py-5">
        <i class="bi bi-envelope-x display-3 text-muted"></i>
        <h4 class="mt-3">Servidor de correo no instalado</h4>
        <p class="text-muted mb-4">
          Para usar el módulo de correo necesitas reinstalar SVQPanel
          con la opción de correo activada.
        </p>
        <div class="alert alert-info text-start d-inline-block">
          <strong>Stack necesario:</strong><br>
          Postfix (SMTP) · Dovecot (IMAP/POP3) · Rspamd (antispam + DKIM) · Redis
        </div>
      </div>
    </div>

    <!-- ══════════ LISTA DE DOMINIOS ══════════ -->
    <template v-else-if="!selectedDomain">

      <div v-if="loading" class="text-center py-5">
        <div class="spinner-border text-primary"></div>
      </div>

      <div v-else-if="!mailDomains.length" class="card shadow-sm border-0">
        <div class="card-body text-center py-5 text-muted">
          <i class="bi bi-envelope display-4"></i>
          <p class="mt-2 mb-3">No hay dominios de correo configurados</p>
          <button class="btn btn-primary btn-sm" @click="openNewDomain">
            <i class="bi bi-plus-lg me-1"></i>Añadir primer dominio
          </button>
        </div>
      </div>

      <div v-else class="card shadow-sm border-0">
        <div class="card-header d-flex justify-content-between align-items-center">
          <h5 class="mb-0"><i class="bi bi-envelope-check me-2"></i>Dominios de correo</h5>
          <span class="badge bg-secondary">{{ mailDomains.length }}</span>
        </div>
        <div class="card-body p-0">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Dominio</th>
                <th class="text-center">Buzones</th>
                <th class="text-center">Alias</th>
                <th class="text-center">DKIM</th>
                <th>Catch-all</th>
                <th class="text-center">Estado</th>
                <th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="md in mailDomains" :key="md.id">
                <td>
                  <div class="fw-semibold">{{ md.domain_name }}</div>
                  <div v-if="md.max_mailboxes > 0" class="text-muted small">
                    Límite: {{ md.mailbox_count }}/{{ md.max_mailboxes }} buzones
                  </div>
                </td>
                <td class="text-center">
                  <span class="badge bg-primary bg-opacity-75">{{ md.mailbox_count }}</span>
                </td>
                <td class="text-center">
                  <span class="badge bg-info bg-opacity-75 text-dark">{{ md.alias_count }}</span>
                </td>
                <td class="text-center">
                  <i v-if="md.dkim_enabled" class="bi bi-shield-check text-success fs-5"
                     title="DKIM activo"></i>
                  <i v-else class="bi bi-shield-x text-muted fs-5" title="DKIM inactivo"></i>
                </td>
                <td class="small text-muted">{{ md.catch_all || '—' }}</td>
                <td class="text-center">
                  <span :class="md.is_active ? 'badge bg-success' : 'badge bg-secondary'">
                    {{ md.is_active ? 'Activo' : 'Suspendido' }}
                  </span>
                </td>
                <td class="text-end">
                  <div class="d-flex gap-1 justify-content-end">
                    <button class="btn btn-sm btn-outline-primary"
                            @click="openDetail(md)" title="Gestionar">
                      <i class="bi bi-gear"></i>
                    </button>
                    <button v-if="md.can_edit" class="btn btn-sm btn-outline-danger"
                            @click="confirmDelete('domain', md,
                              `¿Eliminar el dominio de correo '${md.domain_name}'? Se borrarán todos los buzones y datos.`)"
                            title="Eliminar">
                      <i class="bi bi-trash"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ══════════ DETALLE DE DOMINIO ══════════ -->
    <template v-else>

      <!-- Info rápida del dominio -->
      <div class="row g-3 mb-4">
        <div class="col-md-3">
          <div class="card shadow-sm border-0 h-100">
            <div class="card-body text-center py-3">
              <div class="text-muted small mb-1">BUZONES</div>
              <div class="fs-3 fw-bold text-primary">{{ mailboxes.length }}</div>
              <div v-if="selectedDomain.max_mailboxes > 0" class="text-muted small">
                de {{ selectedDomain.max_mailboxes }} permitidos
              </div>
            </div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card shadow-sm border-0 h-100">
            <div class="card-body text-center py-3">
              <div class="text-muted small mb-1">ALIAS</div>
              <div class="fs-3 fw-bold text-info">{{ aliases.length }}</div>
            </div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card shadow-sm border-0 h-100">
            <div class="card-body text-center py-3">
              <div class="text-muted small mb-1">DKIM</div>
              <div class="fs-5 fw-bold" :class="selectedDomain.dkim_enabled ? 'text-success' : 'text-muted'">
                <i :class="selectedDomain.dkim_enabled ? 'bi bi-shield-check' : 'bi bi-shield-x'"></i>
                {{ selectedDomain.dkim_enabled ? 'Activo' : 'Inactivo' }}
              </div>
            </div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card shadow-sm border-0 h-100">
            <div class="card-body text-center py-3">
              <div class="text-muted small mb-1">CATCH-ALL</div>
              <div class="small fw-semibold text-truncate" :title="selectedDomain.catch_all">
                {{ selectedDomain.catch_all || '—' }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Tabs -->
      <div class="card shadow-sm border-0">
        <div class="card-header p-0">
          <ul class="nav nav-tabs border-0 px-3 pt-2">
            <li class="nav-item">
              <button class="nav-link" :class="{ active: activeTab === 'mailboxes' }"
                      @click="switchTab('mailboxes')">
                <i class="bi bi-person-lines-fill me-1"></i>Buzones
                <span class="badge bg-primary ms-1">{{ mailboxes.length }}</span>
              </button>
            </li>
            <li class="nav-item">
              <button class="nav-link" :class="{ active: activeTab === 'aliases' }"
                      @click="switchTab('aliases')">
                <i class="bi bi-arrow-right-circle me-1"></i>Alias
                <span class="badge bg-info ms-1">{{ aliases.length }}</span>
              </button>
            </li>
            <li class="nav-item">
              <button class="nav-link" :class="{ active: activeTab === 'dkim' }"
                      @click="switchTab('dkim')">
                <i class="bi bi-shield-lock me-1"></i>DKIM
              </button>
            </li>
            <li class="nav-item">
              <button class="nav-link" :class="{ active: activeTab === 'webmail' }"
                      @click="switchTab('webmail')">
                <i class="bi bi-envelope-at me-1"></i>Webmail
              </button>
            </li>
            <li class="nav-item">
              <button class="nav-link" :class="{ active: activeTab === 'settings' }"
                      @click="switchTab('settings')">
                <i class="bi bi-sliders me-1"></i>Ajustes
              </button>
            </li>
          </ul>
        </div>
        <div class="card-body">

          <!-- ── TAB: Buzones ── -->
          <div v-if="activeTab === 'mailboxes'">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <h6 class="mb-0">Buzones de correo</h6>
              <button class="btn btn-primary btn-sm" @click="showNewMailbox = true">
                <i class="bi bi-plus-lg me-1"></i>Nuevo buzón
              </button>
            </div>

            <div v-if="loadingMailboxes" class="text-center py-4">
              <div class="spinner-border spinner-border-sm text-primary"></div>
            </div>

            <div v-else-if="!mailboxes.length" class="text-center py-4 text-muted">
              <i class="bi bi-inbox display-6"></i>
              <p class="mt-2 mb-0">No hay buzones. Crea el primero.</p>
            </div>

            <div v-else class="mbx-grid">
              <article v-for="mb in mailboxes" :key="mb.id" class="mbx" :class="{ 'mbx--off': !mb.is_active }">
                <div class="mbx__top">
                  <span class="mbx__avatar">{{ (mb.full_email || '?').slice(0,1).toUpperCase() }}</span>
                  <div class="mbx__id">
                    <span class="mbx__email" :title="mb.full_email">{{ mb.full_email }}</span>
                    <span class="mbx__quota">
                      <i class="bi bi-hdd"></i>
                      {{ mb.quota_mb === 0 ? 'Sin límite de cuota' : 'Cuota ' + mb.quota_mb + ' MB' }}
                      <span class="ms-2"><i class="bi bi-send"></i>
                        {{ mb.send_limit_hour === 0 ? 'envío libre' : mb.send_limit_hour + '/h' }}</span>
                    </span>
                  </div>
                  <span class="mbx__status" :class="mb.is_active ? 'is-on' : 'is-off'">
                    <span class="dot"></span>{{ mb.is_active ? 'Activo' : 'Suspendido' }}
                  </span>
                </div>
                <div class="mbx__actions">
                  <button v-if="roundcubeEnabled" class="mbx__btn mbx__btn--primary"
                          @click="openWebmail(mb)" :disabled="openingWebmail === mb.id" title="Abrir Webmail">
                    <span v-if="openingWebmail === mb.id" class="spinner-border spinner-border-sm"></span>
                    <template v-else><i class="bi bi-envelope-open"></i> Webmail</template>
                  </button>
                  <button class="mbx__btn" @click="openChangePassword(mb)" title="Cambiar contraseña"><i class="bi bi-key"></i></button>
                  <button class="mbx__btn" @click="toggleMailbox(mb)" :title="mb.is_active ? 'Suspender' : 'Activar'">
                    <i :class="mb.is_active ? 'bi bi-pause-fill' : 'bi bi-play-fill'"></i>
                  </button>
                  <button class="mbx__btn mbx__btn--danger"
                          @click="confirmDelete('mailbox', mb, `¿Eliminar el buzón '${mb.full_email}'? Se borrarán todos los correos.`)"
                          title="Eliminar"><i class="bi bi-trash"></i></button>
                </div>
              </article>
            </div>
          </div>

          <!-- ── TAB: Alias ── -->
          <div v-if="activeTab === 'aliases'">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <h6 class="mb-0">Alias y redirecciones</h6>
              <button class="btn btn-primary btn-sm" @click="showNewAlias = true">
                <i class="bi bi-plus-lg me-1"></i>Nuevo alias
              </button>
            </div>

            <div v-if="loadingAliases" class="text-center py-4">
              <div class="spinner-border spinner-border-sm text-primary"></div>
            </div>

            <div v-else-if="!aliases.length" class="text-center py-4 text-muted">
              <i class="bi bi-arrow-right-circle display-6"></i>
              <p class="mt-2 mb-0">No hay alias configurados.</p>
            </div>

            <table v-else class="table align-middle mb-0">
              <thead class="table-light">
                <tr>
                  <th>Origen</th>
                  <th></th>
                  <th>Destino</th>
                  <th class="text-end">Acciones</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="al in aliases" :key="al.id">
                  <td>
                    <code>{{ al.full_source }}</code>
                    <span v-if="al.source === '@'" class="badge bg-warning text-dark ms-2">
                      catch-all
                    </span>
                  </td>
                  <td class="text-muted text-center">→</td>
                  <td>{{ al.destination }}</td>
                  <td class="text-end">
                    <button class="btn btn-sm btn-outline-danger"
                            @click="confirmDelete('alias', al,
                              `¿Eliminar el alias '${al.full_source}'?`)">
                      <i class="bi bi-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- ── TAB: DKIM ── -->
          <div v-if="activeTab === 'dkim'">
            <div v-if="loadingDkim" class="text-center py-4">
              <div class="spinner-border spinner-border-sm text-primary"></div>
            </div>

            <template v-else>

              <!-- DKIM no configurado -->
              <div v-if="!dkimInfo || !dkimInfo.enabled" class="text-center py-4">
                <i class="bi bi-shield-x display-4 text-muted"></i>
                <h5 class="mt-3">DKIM no configurado</h5>
                <p class="text-muted mb-4">
                  DKIM firma criptográficamente tu correo saliente para evitar que se
                  marque como spam y mejorar la entregabilidad.
                </p>
                <button class="btn btn-primary" @click="generateDkim" :disabled="generatingDkim">
                  <span v-if="generatingDkim" class="spinner-border spinner-border-sm me-2"></span>
                  <i v-else class="bi bi-shield-plus me-2"></i>
                  Generar clave DKIM
                </button>
              </div>

              <!-- DKIM configurado -->
              <div v-else>
                <div class="d-flex justify-content-between align-items-center mb-3">
                  <div class="d-flex align-items-center gap-2">
                    <i class="bi bi-shield-check text-success fs-4"></i>
                    <div>
                      <div class="fw-semibold">DKIM activo</div>
                      <div class="text-muted small">Selector: <code>{{ dkimInfo.selector }}</code></div>
                    </div>
                  </div>
                  <div class="d-flex gap-2">
                    <button class="btn btn-sm btn-outline-warning"
                            @click="rotateDkim" :disabled="generatingDkim"
                            title="Generar nueva clave (rota el par actual)">
                      <span v-if="generatingDkim" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-arrow-repeat"></i>
                      Rotar clave
                    </button>
                    <button class="btn btn-sm btn-outline-danger"
                            @click="confirmDelete('dkim', null,
                              '¿Eliminar la clave DKIM? El correo dejará de estar firmado.')">
                      <i class="bi bi-shield-x me-1"></i>Eliminar DKIM
                    </button>
                  </div>
                </div>

                <!-- Alerta si el DNS se añadió automáticamente -->
                <div v-if="dkimJustGenerated && dkimInfo.dns_auto_added"
                     class="alert alert-success d-flex align-items-center mb-3">
                  <i class="bi bi-check-circle-fill me-2"></i>
                  Registro TXT añadido automáticamente a la zona DNS de SVQPanel.
                </div>

                <!-- Registro DNS -->
                <div class="mb-3">
                  <label class="form-label fw-semibold">
                    Registro DNS TXT a configurar
                    <span v-if="!dkimInfo.dns_auto_added"
                          class="badge bg-warning text-dark ms-1">
                      Añadir manualmente
                    </span>
                  </label>

                  <div class="mb-2">
                    <div class="input-group">
                      <span class="input-group-text text-muted small">Nombre</span>
                      <input type="text" class="form-control form-control-sm font-monospace"
                             :value="dkimInfo.dns_record_name" readonly>
                      <button class="btn btn-outline-secondary btn-sm"
                              @click="copyText(dkimInfo.dns_record_name, 'name')">
                        <i :class="copied === 'name' ? 'bi bi-check text-success' : 'bi bi-clipboard'"></i>
                      </button>
                    </div>
                  </div>

                  <div>
                    <div class="input-group">
                      <span class="input-group-text text-muted small">Valor</span>
                      <textarea class="form-control form-control-sm font-monospace"
                                :value="dkimInfo.dns_record_value" readonly
                                rows="3" style="font-size:12px; resize:none;"></textarea>
                      <button class="btn btn-outline-secondary btn-sm"
                              @click="copyText(dkimInfo.dns_record_value, 'value')">
                        <i :class="copied === 'value' ? 'bi bi-check text-success' : 'bi bi-clipboard'"></i>
                      </button>
                    </div>
                  </div>
                </div>

                <!-- Recordatorio otros registros -->
                <div class="alert alert-info small mb-0">
                  <div class="fw-semibold mb-2">
                    <i class="bi bi-info-circle me-1"></i>
                    Registros DNS recomendados para {{ selectedDomain.domain_name }}
                  </div>
                  <table class="table table-sm table-borderless mb-0 font-monospace"
                         style="font-size:12px">
                    <tr>
                      <td class="text-nowrap pe-3">MX&nbsp;10</td>
                      <td>mail.{{ selectedDomain.domain_name }}</td>
                    </tr>
                    <tr>
                      <td class="text-nowrap pe-3">A mail</td>
                      <td>IP_DEL_SERVIDOR</td>
                    </tr>
                    <tr>
                      <td class="text-nowrap pe-3">TXT&nbsp;@</td>
                      <td>v=spf1 a mx ip4:IP_DEL_SERVIDOR -all</td>
                    </tr>
                    <tr>
                      <td class="text-nowrap pe-3">TXT _dmarc</td>
                      <td>v=DMARC1; p=none; rua=mailto:dmarc@{{ selectedDomain.domain_name }}</td>
                    </tr>
                  </table>
                </div>

              </div>
            </template>
          </div>

          <!-- ── TAB: Webmail ── -->
          <div v-if="activeTab === 'webmail'">
            <div v-if="loadingWebmail" class="text-center py-4">
              <div class="spinner-border spinner-border-sm text-primary"></div>
            </div>
            <template v-else-if="webmail">
              <div v-if="!webmail.roundcube_installed" class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-1"></i>
                Roundcube no está instalado en el servidor. Instálalo para ofrecer webmail por dominio.
              </div>
              <template v-else>
                <div class="d-flex justify-content-between align-items-center mb-3">
                  <div>
                    <h6 class="mb-1"><i class="bi bi-envelope-at me-1"></i>Webmail propio del dominio</h6>
                    <p class="text-muted small mb-0">
                      Tus usuarios acceden a su correo desde
                      <a :href="webmail.url" target="_blank"><code>{{ webmail.host }}</code></a>
                      (Roundcube compartido).
                    </p>
                  </div>
                  <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" role="switch"
                           :checked="webmail.enabled" :disabled="webmailSaving"
                           @change="toggleWebmail($event.target.checked)" style="width:3em;height:1.5em">
                  </div>
                </div>

                <div v-if="webmail.enabled" class="border rounded p-3">
                  <div class="row g-3">
                    <div class="col-md-6">
                      <div class="text-muted small">URL del webmail</div>
                      <a :href="webmail.url" target="_blank" class="fw-semibold">{{ webmail.url }}</a>
                    </div>
                    <div class="col-md-3">
                      <div class="text-muted small">HTTPS</div>
                      <span v-if="webmail.ssl" class="badge bg-success"><i class="bi bi-lock-fill me-1"></i>Activo</span>
                      <span v-else class="badge bg-warning text-dark">Sin SSL</span>
                    </div>
                    <div class="col-md-3">
                      <div class="text-muted small">DNS</div>
                      <span v-if="webmail.dns_managed" class="badge bg-success">Gestionado</span>
                      <span v-else class="badge bg-secondary" title="Añade webmail.dominio en tu DNS externo">Externo</span>
                    </div>
                  </div>

                  <div v-if="!webmail.ssl" class="mt-3">
                    <button class="btn btn-sm btn-outline-primary" @click="issueWebmailSsl" :disabled="webmailSslIssuing">
                      <span v-if="webmailSslIssuing" class="spinner-border spinner-border-sm me-1"></span>
                      <i v-else class="bi bi-lock me-1"></i>
                      Activar HTTPS (Let's Encrypt)
                    </button>
                    <p class="text-muted small mt-2 mb-0">
                      Requiere que <code>{{ webmail.host }}</code> ya resuelva hacia este servidor.
                      <span v-if="!webmail.dns_managed">Como tu DNS es externo, crea primero el registro
                      <code>webmail</code> apuntando a la IP del servidor.</span>
                    </p>
                  </div>
                </div>
                <p v-else class="text-muted small">
                  Actívalo para crear <code>{{ webmail.host }}</code> automáticamente
                  (registro DNS + servidor web). El correo se gestiona en Roundcube.
                </p>
              </template>
            </template>
          </div>

          <!-- ── TAB: Ajustes ── -->
          <div v-if="activeTab === 'settings'">

            <!-- Configuración general -->
            <h6 class="mb-3">Configuración general</h6>
            <form @submit.prevent="saveSettings" class="row g-3 mb-4">
              <div class="col-md-6">
                <label class="form-label">Catch-all
                  <small class="text-muted">(correo para direcciones no existentes)</small>
                </label>
                <input type="email" class="form-control"
                       v-model="settingsForm.catch_all"
                       placeholder="catchall@example.com (vacío para desactivar)">
              </div>
              <div class="col-md-3">
                <label class="form-label">Límite de buzones
                  <small class="text-muted">(0 = sin límite)</small>
                </label>
                <input type="number" class="form-control" v-model.number="settingsForm.max_mailboxes"
                       min="0" max="9999">
              </div>
              <div class="col-md-3">
                <label class="form-label">Envío del dominio
                  <small class="text-muted">(correos/hora, 0 = sin límite)</small>
                </label>
                <input type="number" class="form-control" v-model.number="settingsForm.send_limit_hour"
                       min="0" max="1000000" placeholder="1000">
              </div>
              <div class="col-md-3">
                <label class="form-label">Estado</label>
                <select class="form-select" v-model="settingsForm.is_active">
                  <option :value="true">Activo</option>
                  <option :value="false">Suspendido</option>
                </select>
              </div>
              <div class="col-12">
                <button type="submit" class="btn btn-primary" :disabled="savingSettings">
                  <span v-if="savingSettings" class="spinner-border spinner-border-sm me-2"></span>
                  <i v-else class="bi bi-floppy me-1"></i>Guardar cambios
                </button>
              </div>
            </form>

            <hr />

            <!-- Antispam (Rspamd) -->
            <div class="d-flex align-items-center mb-3">
              <h6 class="mb-0"><i class="bi bi-shield-check me-2 text-danger"></i>Antispam</h6>
              <span v-if="loadingSpam" class="spinner-border spinner-border-sm ms-2"></span>
            </div>

            <!-- Estadísticas de spam -->
            <div v-if="spamSettings.stats" class="row g-2 mb-4">
              <div class="col-6 col-md-2">
                <div class="card text-center border-0 bg-light">
                  <div class="card-body py-2">
                    <div class="fs-5 fw-bold">{{ spamSettings.stats.scanned }}</div>
                    <div class="small text-muted">Analizados</div>
                  </div>
                </div>
              </div>
              <div class="col-6 col-md-2">
                <div class="card text-center border-0 bg-success bg-opacity-10">
                  <div class="card-body py-2">
                    <div class="fs-5 fw-bold text-success">{{ spamSettings.stats.clean }}</div>
                    <div class="small text-muted">Limpios</div>
                  </div>
                </div>
              </div>
              <div class="col-6 col-md-2">
                <div class="card text-center border-0 bg-warning bg-opacity-10">
                  <div class="card-body py-2">
                    <div class="fs-5 fw-bold text-warning">{{ spamSettings.stats.tagged }}</div>
                    <div class="small text-muted">Etiquetados</div>
                  </div>
                </div>
              </div>
              <div class="col-6 col-md-2">
                <div class="card text-center border-0 bg-secondary bg-opacity-10">
                  <div class="card-body py-2">
                    <div class="fs-5 fw-bold text-secondary">{{ spamSettings.stats.greylisted }}</div>
                    <div class="small text-muted">Greylisted</div>
                  </div>
                </div>
              </div>
              <div class="col-6 col-md-2">
                <div class="card text-center border-0 bg-danger bg-opacity-10">
                  <div class="card-body py-2">
                    <div class="fs-5 fw-bold text-danger">{{ spamSettings.stats.rejected }}</div>
                    <div class="small text-muted">Rechazados</div>
                  </div>
                </div>
              </div>
            </div>

            <form @submit.prevent="saveSpamSettings" class="row g-3">
              <!-- Umbrales -->
              <div class="col-md-3">
                <label class="form-label">
                  Umbral etiquetado
                  <small class="text-muted d-block">Score → añade cabecera spam</small>
                </label>
                <div class="input-group">
                  <input type="number" class="form-control" step="0.5" min="1" max="20"
                         v-model.number="spamForm.spam_tag_threshold">
                  <span class="input-group-text">pts</span>
                </div>
              </div>
              <div class="col-md-3">
                <label class="form-label">
                  Umbral rechazo
                  <small class="text-muted d-block">Score → rechazar mensaje</small>
                </label>
                <div class="input-group">
                  <input type="number" class="form-control" step="0.5" min="3" max="100"
                         v-model.number="spamForm.spam_reject_threshold">
                  <span class="input-group-text">pts</span>
                </div>
              </div>
              <div class="col-md-3">
                <label class="form-label">
                  <i class="bi bi-check-circle text-success me-1"></i>Whitelist
                  <small class="text-muted d-block">Remitentes siempre permitidos</small>
                </label>
                <textarea class="form-control font-monospace" rows="5"
                          v-model="spamForm.whitelist_senders"
                          placeholder="usuario@dominio.com&#10;@dominio.com&#10;otro@ejemplo.org"
                          style="font-size:.8rem"></textarea>
                <small class="text-muted">Un email o @dominio por línea</small>
              </div>
              <div class="col-md-3">
                <label class="form-label">
                  <i class="bi bi-x-circle text-danger me-1"></i>Blacklist
                  <small class="text-muted d-block">Remitentes siempre bloqueados</small>
                </label>
                <textarea class="form-control font-monospace" rows="5"
                          v-model="spamForm.blacklist_senders"
                          placeholder="spam@ejemplo.com&#10;@dominiomalicioso.com"
                          style="font-size:.8rem"></textarea>
                <small class="text-muted">Un email o @dominio por línea</small>
              </div>

              <div class="col-12">
                <button type="submit" class="btn btn-danger" :disabled="savingSpam">
                  <span v-if="savingSpam" class="spinner-border spinner-border-sm me-2"></span>
                  <i v-else class="bi bi-shield-check me-1"></i>Guardar configuración antispam
                </button>
              </div>
            </form>

            <!-- ── Historial reciente de mensajes ── -->
            <div v-if="spamSettings.stats && spamSettings.stats.history && spamSettings.stats.history.length" class="mt-4">
              <h6 class="mb-3">
                <i class="bi bi-clock-history me-2 text-secondary"></i>Últimos mensajes analizados
                <span class="badge bg-secondary ms-2">{{ spamSettings.stats.history.length }}</span>
              </h6>
              <div class="table-responsive">
                <table class="table table-sm table-hover align-middle mb-0" style="font-size:.82rem">
                  <thead class="table-light">
                    <tr>
                      <th>Remitente</th>
                      <th>Asunto</th>
                      <th class="text-center">Acción</th>
                      <th class="text-center">Score</th>
                      <th class="text-end">Fecha</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="msg in spamSettings.stats.history" :key="msg.id">
                      <td class="font-monospace text-truncate" style="max-width:160px" :title="msg.from_addr">
                        {{ msg.from_addr || '—' }}
                      </td>
                      <td class="text-truncate" style="max-width:180px" :title="msg.subject">
                        {{ msg.subject || '—' }}
                      </td>
                      <td class="text-center">
                        <span :class="{
                          'badge bg-danger':    msg.action === 'reject',
                          'badge bg-warning text-dark': msg.action === 'add header',
                          'badge bg-secondary': msg.action === 'greylist',
                          'badge bg-success':   msg.action === 'no action',
                          'badge bg-light text-dark border': !['reject','add header','greylist','no action'].includes(msg.action),
                        }">
                          {{ msg.action === 'add header' ? 'spam' :
                             msg.action === 'no action'  ? 'limpio' :
                             msg.action || '?' }}
                        </span>
                      </td>
                      <td class="text-center font-monospace">
                        {{ msg.score.toFixed(2) }}
                      </td>
                      <td class="text-end text-muted text-nowrap">{{ msg.timestamp }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else-if="spamSettings.stats && spamSettings.stats.scanned === 0 && !loadingSpam"
                 class="mt-3 text-muted small">
              <i class="bi bi-info-circle me-1"></i>
              Aún no hay mensajes registrados para este dominio.
            </div>

          </div>

        </div>
      </div>
    </template>


    <!-- ══════════ Modal: Nuevo dominio ══════════ -->
    <div v-if="showNewDomain" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-envelope-plus me-2"></i>Añadir dominio de correo
            </h5>
            <button class="btn-close" @click="showNewDomain = false"></button>
          </div>
          <form @submit.prevent="createDomain">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Nombre de dominio <span class="text-danger">*</span></label>
                <input type="text" class="form-control font-monospace"
                       v-model="newDomainForm.domain_name"
                       placeholder="ejemplo.com" required autofocus>
                <div class="form-text">El dominio debe tener MX apuntando a este servidor.</div>
              </div>
              <div class="mb-3">
                <label class="form-label">Catch-all
                  <small class="text-muted">(opcional)</small>
                </label>
                <input type="email" class="form-control"
                       v-model="newDomainForm.catch_all"
                       placeholder="admin@ejemplo.com">
                <div class="form-text">Todo correo a direcciones no existentes se redirigirá aquí.</div>
              </div>
              <div class="mb-0">
                <label class="form-label">Límite de buzones</label>
                <input type="number" class="form-control" v-model.number="newDomainForm.max_mailboxes"
                       min="0" placeholder="0 = sin límite">
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary"
                      @click="showNewDomain = false">Cancelar</button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
                Crear dominio
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- ══════════ Modal: Nuevo buzón ══════════ -->
    <div v-if="showNewMailbox" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-person-plus me-2"></i>Nuevo buzón
              <small class="text-muted fw-normal"> — {{ selectedDomain?.domain_name }}</small>
            </h5>
            <button class="btn-close" @click="showNewMailbox = false"></button>
          </div>
          <form @submit.prevent="createMailbox">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Nombre del buzón <span class="text-danger">*</span></label>
                <div class="input-group">
                  <input type="text" class="form-control font-monospace"
                         v-model="newMailboxForm.username"
                         placeholder="info" required autofocus>
                  <span class="input-group-text text-muted">
                    @{{ selectedDomain?.domain_name }}
                  </span>
                </div>
              </div>
              <div class="mb-3">
                <label class="form-label">Contraseña <span class="text-danger">*</span></label>
                <div class="input-group">
                  <input :type="showPwd ? 'text' : 'password'"
                         class="form-control"
                         v-model="newMailboxForm.password"
                         required minlength="8"
                         autocomplete="new-password">
                  <button type="button" class="btn btn-outline-secondary"
                          @click="showPwd = !showPwd">
                    <i :class="showPwd ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
                  </button>
                </div>
                <div class="form-text">Mínimo 8 caracteres.</div>
              </div>
              <div class="mb-3">
                <label class="form-label">Cuota (MB)</label>
                <select class="form-select" v-model.number="newMailboxForm.quota_mb">
                  <option :value="0">Sin límite</option>
                  <option :value="256">256 MB</option>
                  <option :value="512">512 MB</option>
                  <option :value="1024">1 GB</option>
                  <option :value="2048">2 GB</option>
                  <option :value="5120">5 GB</option>
                  <option :value="10240">10 GB</option>
                </select>
              </div>
              <div class="mb-0">
                <label class="form-label">Límite de envío (correos/hora)</label>
                <select class="form-select" v-model.number="newMailboxForm.send_limit_hour">
                  <option :value="0">Sin límite</option>
                  <option :value="50">50 / hora</option>
                  <option :value="100">100 / hora</option>
                  <option :value="200">200 / hora</option>
                  <option :value="500">500 / hora</option>
                  <option :value="1000">1000 / hora</option>
                </select>
                <div class="form-text">Anti-abuso: si la cuenta se ve comprometida, no podrá enviar spam masivo.</div>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary"
                      @click="showNewMailbox = false">Cancelar</button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
                Crear buzón
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- ══════════ Modal: Cambiar contraseña ══════════ -->
    <div v-if="showPasswordModal" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-key me-2"></i>Cambiar contraseña
              <small class="text-muted fw-normal"> — {{ passwordTarget?.full_email }}</small>
            </h5>
            <button class="btn-close" @click="showPasswordModal = false"></button>
          </div>
          <form @submit.prevent="changePassword">
            <div class="modal-body">
              <div class="input-group">
                <input :type="showPwd ? 'text' : 'password'"
                       class="form-control"
                       v-model="newPassword"
                       placeholder="Nueva contraseña (mín. 8 caracteres)"
                       required minlength="8"
                       autocomplete="new-password">
                <button type="button" class="btn btn-outline-secondary"
                        @click="showPwd = !showPwd">
                  <i :class="showPwd ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
                </button>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary"
                      @click="showPasswordModal = false">Cancelar</button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
                Cambiar contraseña
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- ══════════ Modal: Nuevo alias ══════════ -->
    <div v-if="showNewAlias" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-arrow-right-circle me-2"></i>Nuevo alias
              <small class="text-muted fw-normal"> — {{ selectedDomain?.domain_name }}</small>
            </h5>
            <button class="btn-close" @click="showNewAlias = false"></button>
          </div>
          <form @submit.prevent="createAlias">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Origen <span class="text-danger">*</span></label>
                <div class="input-group">
                  <input type="text" class="form-control font-monospace"
                         v-model="newAliasForm.source"
                         placeholder="info  (o @ para catch-all)"
                         required autofocus>
                  <span class="input-group-text text-muted">
                    @{{ selectedDomain?.domain_name }}
                  </span>
                </div>
                <div class="form-text">
                  Escribe <code>@</code> para crear un catch-all (captura todo).
                </div>
              </div>
              <div class="mb-0">
                <label class="form-label">Redirigir a <span class="text-danger">*</span></label>
                <input type="email" class="form-control"
                       v-model="newAliasForm.destination"
                       placeholder="destino@example.com" required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary"
                      @click="showNewAlias = false">Cancelar</button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
                Crear alias
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- ══════════ Modal: Confirmar eliminación ══════════ -->
    <div v-if="deleteTarget" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title">
              <i class="bi bi-exclamation-triangle me-2"></i>Confirmar eliminación
            </h5>
            <button class="btn-close btn-close-white"
                    @click="deleteTarget = null"></button>
          </div>
          <div class="modal-body">
            <p class="mb-0">{{ deleteTarget.message }}</p>
            <p v-if="deleteTarget.type === 'domain'" class="text-danger small mt-2 mb-0">
              <i class="bi bi-exclamation-circle me-1"></i>
              Esta acción eliminará todos los buzones, alias y correos almacenados del disco.
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="deleteTarget = null">Cancelar</button>
            <button class="btn btn-danger" @click="executeDelete" :disabled="saving">
              <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
              Eliminar
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
  name: 'Mail',
  setup() {
    const store = useMainStore()

    // ── Estado principal ──────────────────────────────────────────────
    const mailEnabled    = ref(null)   // null=cargando, true/false
    const mailDomains    = ref([])
    const selectedDomain = ref(null)
    const activeTab      = ref('mailboxes')
    const loading        = ref(false)

    // ── Roundcube / Webmail ───────────────────────────────────────────
    const roundcubeEnabled = ref(false)
    const roundcubeUrl     = ref(null)
    const openingWebmail   = ref(null)  // mailbox.id mientras se genera el token

    // ── Detalle ───────────────────────────────────────────────────────
    const mailboxes           = ref([])
    const aliases             = ref([])
    const dkimInfo            = ref(null)
    const loadingMailboxes    = ref(false)
    const loadingAliases      = ref(false)
    const loadingDkim         = ref(false)
    const generatingDkim      = ref(false)
    const dkimJustGenerated   = ref(false)
    const copied              = ref(null)  // 'name' | 'value' | null

    // ── Ajustes ───────────────────────────────────────────────────────
    const settingsForm   = ref({ catch_all: '', max_mailboxes: 0, send_limit_hour: 1000, is_active: true })
    const spamSettings   = ref({ stats: { scanned:0, clean:0, tagged:0, greylisted:0, rejected:0, history:[] } })
    const spamForm       = ref({ spam_tag_threshold: 6.0, spam_reject_threshold: 15.0, whitelist_senders: '', blacklist_senders: '' })
    const loadingSpam    = ref(false)
    const savingSpam     = ref(false)
    const savingSettings = ref(false)

    // ── Modales ───────────────────────────────────────────────────────
    const showNewDomain    = ref(false)
    const showNewMailbox   = ref(false)
    const showPasswordModal= ref(false)
    const showNewAlias     = ref(false)
    const deleteTarget     = ref(null)
    const saving           = ref(false)
    const showPwd          = ref(false)

    // ── Formularios ───────────────────────────────────────────────────
    const newDomainForm  = ref({ domain_name: '', catch_all: '', max_mailboxes: 0 })
    const newMailboxForm = ref({ username: '', password: '', quota_mb: 1024, send_limit_hour: 200 })
    const newAliasForm   = ref({ source: '', destination: '' })
    const passwordTarget = ref(null)
    const newPassword    = ref('')

    // ─────────────────────────────────────────────────────────────────
    // Carga de datos
    // ─────────────────────────────────────────────────────────────────

    const loadRoundcubeStatus = async () => {
      try {
        const status = await api.getRoundcubeStatus()
        roundcubeEnabled.value = status.enabled
        roundcubeUrl.value     = status.url
      } catch {
        roundcubeEnabled.value = false
      }
    }

    const loadDomains = async () => {
      loading.value = true
      try {
        mailDomains.value = await api.getMailDomains()
        mailEnabled.value = true
      } catch (e) {
        if (e.message && e.message.toLowerCase().includes('instalado')) {
          mailEnabled.value = false
        } else {
          store.showNotification('Error al cargar dominios de correo: ' + e.message, 'danger')
        }
      } finally {
        loading.value = false
      }
    }

    const loadMailboxes = async (domainId) => {
      loadingMailboxes.value = true
      try {
        mailboxes.value = await api.getMailboxes(domainId)
      } catch (e) {
        store.showNotification('Error al cargar buzones: ' + e.message, 'danger')
      } finally {
        loadingMailboxes.value = false
      }
    }

    const loadAliases = async (domainId) => {
      loadingAliases.value = true
      try {
        aliases.value = await api.getMailAliases(domainId)
      } catch (e) {
        store.showNotification('Error al cargar alias: ' + e.message, 'danger')
      } finally {
        loadingAliases.value = false
      }
    }

    const loadDkim = async (domainId) => {
      loadingDkim.value = true
      dkimJustGenerated.value = false
      try {
        dkimInfo.value = await api.getDkimInfo(domainId)
      } catch (e) {
        dkimInfo.value = null
      } finally {
        loadingDkim.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Navegación
    // ─────────────────────────────────────────────────────────────────

    const openDetail = async (md) => {
      selectedDomain.value = md
      activeTab.value = 'mailboxes'
      dkimInfo.value = null
      webmail.value = null
      settingsForm.value = {
        catch_all:     md.catch_all || '',
        max_mailboxes: md.max_mailboxes,
        send_limit_hour: md.send_limit_hour ?? 1000,
        is_active:     md.is_active,
      }
      await Promise.all([
        loadMailboxes(md.id),
        loadAliases(md.id),
      ])
    }

    const switchTab = async (tab) => {
      activeTab.value = tab
      if (!selectedDomain.value) return
      if (tab === 'dkim' && dkimInfo.value === null) {
        await loadDkim(selectedDomain.value.id)
      }
      if (tab === 'settings' && !spamSettings.value.spam_tag_threshold) {
        await loadSpamSettings(selectedDomain.value.id)
      }
      if (tab === 'webmail') {
        await loadWebmail(selectedDomain.value.id)
      }
    }

    // ── Webmail por dominio ──
    const webmail          = ref(null)
    const loadingWebmail   = ref(false)
    const webmailSaving    = ref(false)
    const webmailSslIssuing = ref(false)

    const loadWebmail = async (domainId) => {
      loadingWebmail.value = true
      try {
        webmail.value = await api.getWebmailStatus(domainId)
      } catch (e) {
        webmail.value = null
      } finally {
        loadingWebmail.value = false
      }
    }

    const toggleWebmail = async (enabled) => {
      webmailSaving.value = true
      try {
        await api.setWebmail(selectedDomain.value.id, enabled)
        store.showNotification(enabled ? 'Webmail activado' : 'Webmail desactivado', 'success')
        await loadWebmail(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
        await loadWebmail(selectedDomain.value.id)
      } finally {
        webmailSaving.value = false
      }
    }

    const issueWebmailSsl = async () => {
      webmailSslIssuing.value = true
      try {
        const r = await api.issueWebmailSsl(selectedDomain.value.id)
        store.showNotification(r.message || 'HTTPS activado en el webmail', 'success')
        await loadWebmail(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('No se pudo activar HTTPS: ' + (e.message || e), 'danger')
      } finally {
        webmailSslIssuing.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Dominio de correo
    // ─────────────────────────────────────────────────────────────────

    const openNewDomain = () => {
      newDomainForm.value = { domain_name: '', catch_all: '', max_mailboxes: 0 }
      showNewDomain.value = true
    }

    const createDomain = async () => {
      saving.value = true
      try {
        const payload = { ...newDomainForm.value }
        if (!payload.catch_all) delete payload.catch_all
        await api.createMailDomain(payload)
        showNewDomain.value = false
        store.showNotification('Dominio de correo creado', 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    const saveSettings = async () => {
      savingSettings.value = true
      try {
        const payload = {
          catch_all:     settingsForm.value.catch_all || null,
          max_mailboxes: settingsForm.value.max_mailboxes,
          send_limit_hour: settingsForm.value.send_limit_hour,
          is_active:     settingsForm.value.is_active,
        }
        const updated = await api.updateMailDomain(selectedDomain.value.id, payload)
        selectedDomain.value = { ...selectedDomain.value, ...updated }
        store.showNotification('Configuración guardada', 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingSettings.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Antispam
    // ─────────────────────────────────────────────────────────────────

    const loadSpamSettings = async (domainId) => {
      loadingSpam.value = true
      try {
        const data = await api.get(`/api/mail/domains/${domainId}/spam`)
        spamSettings.value = data
        spamForm.value = {
          spam_tag_threshold:    data.spam_tag_threshold,
          spam_reject_threshold: data.spam_reject_threshold,
          whitelist_senders:     data.whitelist_senders || '',
          blacklist_senders:     data.blacklist_senders || '',
        }
      } catch { /* si Rspamd no está instalado no bloqueamos */ }
      finally { loadingSpam.value = false }
    }

    const saveSpamSettings = async () => {
      savingSpam.value = true
      try {
        const data = await api.put(
          `/api/mail/domains/${selectedDomain.value.id}/spam`,
          spamForm.value
        )
        spamSettings.value = data
        store.showNotification('Configuración antispam guardada', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingSpam.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // DKIM
    // ─────────────────────────────────────────────────────────────────

    const generateDkim = async () => {
      generatingDkim.value = true
      try {
        const result = await api.generateDkim(selectedDomain.value.id,
                                              selectedDomain.value.dkim_selector || 'mail')
        dkimInfo.value = result
        dkimJustGenerated.value = true
        selectedDomain.value = { ...selectedDomain.value, dkim_enabled: true }
        store.showNotification('Clave DKIM generada correctamente', 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error generando DKIM: ' + e.message, 'danger')
      } finally {
        generatingDkim.value = false
      }
    }

    const rotateDkim = async () => {
      if (!confirm('¿Rotar la clave DKIM? Deberás actualizar el registro TXT en tu DNS.')) return
      await generateDkim()
    }

    const deleteDkim = async () => {
      try {
        await api.deleteDkim(selectedDomain.value.id)
        dkimInfo.value = { enabled: false, selector: 'mail' }
        selectedDomain.value = { ...selectedDomain.value, dkim_enabled: false }
        store.showNotification('Clave DKIM eliminada', 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    const copyText = async (text, key) => {
      try {
        await navigator.clipboard.writeText(text)
        copied.value = key
        setTimeout(() => { copied.value = null }, 2000)
      } catch {
        store.showNotification('No se pudo copiar al portapapeles', 'warning')
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Buzones
    // ─────────────────────────────────────────────────────────────────

    const createMailbox = async () => {
      saving.value = true
      try {
        await api.createMailbox(selectedDomain.value.id, newMailboxForm.value)
        showNewMailbox.value = false
        newMailboxForm.value = { username: '', password: '', quota_mb: 1024, send_limit_hour: 200 }
        showPwd.value = false
        store.showNotification('Buzón creado', 'success')
        await loadMailboxes(selectedDomain.value.id)
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    const toggleMailbox = async (mb) => {
      try {
        await api.updateMailbox(selectedDomain.value.id, mb.id,
                                { is_active: !mb.is_active })
        store.showNotification(
          `Buzón ${!mb.is_active ? 'activado' : 'suspendido'}`, 'success'
        )
        await loadMailboxes(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    const openChangePassword = (mb) => {
      passwordTarget.value = mb
      newPassword.value = ''
      showPwd.value = false
      showPasswordModal.value = true
    }

    const changePassword = async () => {
      saving.value = true
      try {
        await api.updateMailbox(selectedDomain.value.id, passwordTarget.value.id,
                                { password: newPassword.value })
        showPasswordModal.value = false
        store.showNotification('Contraseña actualizada', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Webmail (Roundcube autologin)
    // ─────────────────────────────────────────────────────────────────

    const openWebmail = async (mb) => {
      if (openingWebmail.value === mb.id) return
      openingWebmail.value = mb.id
      try {
        const result = await api.getWebmailToken(selectedDomain.value.id, mb.id)
        // Abrir en nueva pestaña — el token solo dura 60s, hay que usarlo de inmediato
        window.open(result.url, '_blank', 'noopener,noreferrer')
      } catch (e) {
        store.showNotification(
          'No se pudo abrir el webmail: ' + e.message,
          'danger'
        )
      } finally {
        openingWebmail.value = null
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Alias
    // ─────────────────────────────────────────────────────────────────

    const createAlias = async () => {
      saving.value = true
      try {
        await api.createMailAlias(selectedDomain.value.id, newAliasForm.value)
        showNewAlias.value = false
        newAliasForm.value = { source: '', destination: '' }
        store.showNotification('Alias creado', 'success')
        await loadAliases(selectedDomain.value.id)
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Eliminación (modal unificado)
    // ─────────────────────────────────────────────────────────────────

    const confirmDelete = (type, item, message) => {
      deleteTarget.value = { type, item, message }
    }

    const executeDelete = async () => {
      if (!deleteTarget.value) return
      saving.value = true
      const { type, item } = deleteTarget.value
      try {
        if (type === 'domain') {
          await api.deleteMailDomain(item.id)
          deleteTarget.value = null
          selectedDomain.value = null
          store.showNotification('Dominio de correo eliminado', 'success')
          await loadDomains()

        } else if (type === 'mailbox') {
          await api.deleteMailbox(selectedDomain.value.id, item.id)
          deleteTarget.value = null
          store.showNotification('Buzón eliminado', 'success')
          await loadMailboxes(selectedDomain.value.id)
          await loadDomains()

        } else if (type === 'alias') {
          await api.deleteMailAlias(selectedDomain.value.id, item.id)
          deleteTarget.value = null
          store.showNotification('Alias eliminado', 'success')
          await loadAliases(selectedDomain.value.id)
          await loadDomains()

        } else if (type === 'dkim') {
          await deleteDkim()
          deleteTarget.value = null
        }
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    onMounted(() => {
      loadDomains()
      loadRoundcubeStatus()
    })

    return {
      mailEnabled, mailDomains, selectedDomain, activeTab, loading,
      mailboxes, aliases, dkimInfo,
      loadingMailboxes, loadingAliases, loadingDkim,
      generatingDkim, dkimJustGenerated, copied,
      settingsForm, savingSettings,
      spamSettings, spamForm, loadingSpam, savingSpam,
      showNewDomain, showNewMailbox, showPasswordModal, showNewAlias,
      deleteTarget, saving, showPwd,
      newDomainForm, newMailboxForm, newAliasForm, passwordTarget, newPassword,
      // Roundcube
      roundcubeEnabled, roundcubeUrl, openingWebmail,
      // Webmail por dominio
      webmail, loadingWebmail, webmailSaving, webmailSslIssuing,
      loadWebmail, toggleWebmail, issueWebmailSsl,
      loadDomains, openDetail, switchTab,
      openNewDomain, createDomain, saveSettings,
      loadSpamSettings, saveSpamSettings,
      generateDkim, rotateDkim, copyText,
      createMailbox, toggleMailbox, openChangePassword, changePassword,
      openWebmail,
      createAlias,
      confirmDelete, executeDelete,
    }
  }
}
</script>

<style scoped>
.mbx-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-3); }
.mbx {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-md); padding: var(--sp-4);
  display: flex; flex-direction: column; gap: var(--sp-3);
  transition: box-shadow var(--t-base) var(--ease), border-color var(--t-base);
}
.mbx:hover { box-shadow: var(--shadow-sm); border-color: var(--border-strong); }
.mbx--off { opacity: .72; }
.mbx__top { display: flex; align-items: center; gap: var(--sp-3); }
.mbx__avatar {
  width: 40px; height: 40px; flex-shrink: 0; border-radius: var(--r-md);
  display: grid; place-items: center; font-weight: var(--fw-bold); color: #fff;
  background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); font-size: var(--fs-md);
}
.mbx__id { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.mbx__email { font-weight: var(--fw-semibold); color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mbx__quota { font-size: var(--fs-sm); color: var(--text-muted); display: flex; align-items: center; gap: 5px; }
.mbx__status { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-sm); font-weight: var(--fw-medium); flex-shrink: 0; }
.mbx__status .dot { width: 7px; height: 7px; border-radius: 50%; }
.mbx__status.is-on { color: var(--success); } .mbx__status.is-on .dot { background: var(--success); }
.mbx__status.is-off { color: var(--text-muted); } .mbx__status.is-off .dot { background: var(--text-muted); }
.mbx__actions { display: flex; gap: var(--sp-2); padding-top: var(--sp-3); border-top: 1px solid var(--border); }
.mbx__btn {
  height: 34px; min-width: 34px; padding: 0 10px;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary);
  border-radius: var(--r-sm); cursor: pointer; font-size: var(--fs-sm); font-weight: var(--fw-medium);
  transition: all var(--t-fast) var(--ease);
}
.mbx__btn:hover { background: var(--surface-inset); color: var(--text); }
.mbx__btn--primary { color: var(--color-primary); border-color: var(--brand-200); margin-right: auto; }
.mbx__btn--primary:hover { background: var(--brand-50); }
[data-theme="dark"] .mbx__btn--primary { border-color: var(--border-strong); }
[data-theme="dark"] .mbx__btn--primary:hover { background: var(--surface-2); }
.mbx__btn--danger:hover { background: var(--danger-bg); color: var(--danger); border-color: var(--danger-border); }
</style>
