<template>
  <div class="sv-view">

    <!-- ── Cabecera ── -->
    <div class="sv-page-head">
      <div>
        <div v-if="selectedDomain" class="sv-breadcrumb">
          <button class="sv-back-btn" @click="selectedDomain = null">
            <i class="bi bi-arrow-left"></i> Dominios
          </button>
          <i class="bi bi-chevron-right sv-chevron"></i>
          <span class="sv-domain-name">{{ selectedDomain.domain_name }}</span>
          <span class="sv-badge" :class="selectedDomain.is_active ? 'sv-badge--on' : 'sv-badge--off'">
            {{ selectedDomain.is_active ? 'Activo' : 'Suspendido' }}
          </span>
        </div>
        <h2 class="sv-title">
          <i class="bi bi-envelope"></i>
          {{ selectedDomain ? selectedDomain.domain_name : 'Correo Electrónico' }}
        </h2>
        <p class="sv-subtitle">
          {{ selectedDomain
            ? `${selectedDomain.mailbox_count} buzones · ${selectedDomain.alias_count} alias`
            : 'Gestión de dominios de correo, buzones y alias' }}
        </p>
      </div>
      <div class="sv-head-actions">
        <button v-if="!selectedDomain" class="sv-btn sv-btn--ghost" @click="loadDomains" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm"></span>
          <i v-else class="bi bi-arrow-repeat"></i> Actualizar
        </button>
        <button v-if="!selectedDomain && mailEnabled !== false" class="sv-btn sv-btn--primary" @click="openNewDomain">
          <i class="bi bi-plus-lg"></i> Añadir dominio
        </button>
      </div>
    </div>

    <!-- ══════════ CORREO NO INSTALADO ══════════ -->
    <div v-if="mailEnabled === false" class="sv-card sv-empty-state">
      <i class="bi bi-envelope-x sv-empty-icon"></i>
      <h4>Servidor de correo no instalado</h4>
      <p>Para usar el módulo de correo necesitas reinstalar SVQPanel con la opción de correo activada.</p>
      <div class="sv-info-box">
        <strong>Stack necesario:</strong><br>
        Postfix (SMTP) · Dovecot (IMAP/POP3) · Rspamd (antispam + DKIM) · Redis
      </div>
    </div>

    <!-- ══════════ LISTA DE DOMINIOS ══════════ -->
    <template v-else-if="!selectedDomain">
      <div v-if="loading" class="sv-loading">
        <div class="spinner-border spinner-border-sm"></div>
      </div>

      <div v-else-if="!mailDomains.length" class="sv-card sv-empty-state">
        <i class="bi bi-envelope sv-empty-icon"></i>
        <p>No hay dominios de correo configurados</p>
        <button class="sv-btn sv-btn--primary" @click="openNewDomain">
          <i class="bi bi-plus-lg"></i> Añadir primer dominio
        </button>
      </div>

      <div v-else class="sv-card">
        <div class="sv-card-head">
          <span class="sv-card-title"><i class="bi bi-envelope-check"></i> Dominios de correo</span>
          <span class="sv-count">{{ mailDomains.length }}</span>
        </div>
        <div class="sv-table-wrap">
          <table class="sv-table">
            <thead>
              <tr>
                <th>Dominio</th>
                <th style="text-align:center">Buzones</th>
                <th style="text-align:center">Alias</th>
                <th style="text-align:center">DKIM</th>
                <th>Catch-all</th>
                <th style="text-align:center">Estado</th>
                <th style="text-align:right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="md in mailDomains" :key="md.id">
                <td>
                  <div style="font-weight:600">{{ md.domain_name }}</div>
                  <div v-if="md.max_mailboxes > 0" style="font-size:.8rem;color:var(--text-muted)">
                    Límite: {{ md.mailbox_count }}/{{ md.max_mailboxes }} buzones
                  </div>
                </td>
                <td style="text-align:center">
                  <span class="sv-badge sv-badge--blue">{{ md.mailbox_count }}</span>
                </td>
                <td style="text-align:center">
                  <span class="sv-badge sv-badge--teal">{{ md.alias_count }}</span>
                </td>
                <td style="text-align:center">
                  <i v-if="md.dkim_enabled" class="bi bi-shield-check" style="color:var(--success);font-size:1.1rem" title="DKIM activo"></i>
                  <i v-else class="bi bi-shield-x" style="color:var(--text-muted);font-size:1.1rem" title="DKIM inactivo"></i>
                </td>
                <td style="font-size:.85rem;color:var(--text-muted)">{{ md.catch_all || '—' }}</td>
                <td style="text-align:center">
                  <span class="sv-badge" :class="md.is_active ? 'sv-badge--on' : 'sv-badge--off'">
                    {{ md.is_active ? 'Activo' : 'Suspendido' }}
                  </span>
                </td>
                <td style="text-align:right">
                  <div style="display:flex;gap:6px;justify-content:flex-end">
                    <button class="sv-icon-btn" @click="openDetail(md)" title="Gestionar">
                      <i class="bi bi-gear"></i>
                    </button>
                    <button v-if="md.can_edit" class="sv-icon-btn sv-icon-btn--danger"
                            @click="confirmDelete('domain', md, `¿Eliminar el dominio de correo '${md.domain_name}'? Se borrarán todos los buzones y datos.`)"
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

      <!-- Contadores rápidos -->
      <div class="sv-counters">
        <div class="sv-counter">
          <span class="sv-counter-val" style="color:var(--accent)">{{ mailboxes.length }}</span>
          <span class="sv-counter-lbl">Buzones
            <span v-if="selectedDomain.max_mailboxes > 0" style="color:var(--text-muted)"> / {{ selectedDomain.max_mailboxes }}</span>
          </span>
        </div>
        <div class="sv-counter">
          <span class="sv-counter-val" style="color:var(--info)">{{ aliases.length }}</span>
          <span class="sv-counter-lbl">Alias</span>
        </div>
        <div class="sv-counter">
          <span class="sv-counter-val" :style="selectedDomain.dkim_enabled ? 'color:var(--success)' : 'color:var(--text-muted)'">
            <i :class="selectedDomain.dkim_enabled ? 'bi bi-shield-check' : 'bi bi-shield-x'"></i>
          </span>
          <span class="sv-counter-lbl">DKIM</span>
        </div>
        <div class="sv-counter">
          <span class="sv-counter-val" style="font-size:1rem;font-weight:500;color:var(--text-secondary)">
            {{ selectedDomain.catch_all || '—' }}
          </span>
          <span class="sv-counter-lbl">Catch-all</span>
        </div>
      </div>

      <!-- Tabs -->
      <div class="sv-card">
        <div class="sv-tabs">
          <button v-for="t in [
            { key:'mailboxes', icon:'person-lines-fill', label:'Buzones', count: mailboxes.length },
            { key:'aliases',   icon:'arrow-right-circle', label:'Alias', count: aliases.length },
            { key:'dkim',      icon:'shield-lock', label:'DKIM' },
            { key:'webmail',   icon:'envelope-at', label:'Webmail' },
            { key:'relay',     icon:'arrow-up-right-circle', label:'Relay SMTP' },
            { key:'logs',      icon:'activity', label:'Monitoreo' },
            { key:'settings',  icon:'sliders', label:'Ajustes' },
          ]" :key="t.key" class="sv-tab" :class="{ 'sv-tab--active': activeTab === t.key }"
             @click="switchTab(t.key)">
            <i :class="'bi bi-' + t.icon"></i>
            {{ t.label }}
            <span v-if="t.count !== undefined" class="sv-tab-count">{{ t.count }}</span>
          </button>
        </div>

        <div class="sv-tab-body">

          <!-- ── TAB: Buzones ── -->
          <div v-if="activeTab === 'mailboxes'">
            <div class="sv-tab-head">
              <span class="sv-tab-section-title">Buzones de correo</span>
              <button class="sv-btn sv-btn--primary sv-btn--sm" @click="showNewMailbox = true">
                <i class="bi bi-plus-lg"></i> Nuevo buzón
              </button>
            </div>
            <div v-if="loadingMailboxes" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <div v-else-if="!mailboxes.length" class="sv-empty-inline">
              <i class="bi bi-inbox"></i><span>No hay buzones. Crea el primero.</span>
            </div>
            <div v-else class="mbx-grid">
              <article v-for="mb in mailboxes" :key="mb.id" class="mbx" :class="{ 'mbx--off': !mb.is_active }">
                <div class="mbx__top">
                  <span class="mbx__avatar">{{ (mb.full_email || '?').slice(0,1).toUpperCase() }}</span>
                  <div class="mbx__id">
                    <span class="mbx__email" :title="mb.full_email">{{ mb.full_email }}</span>
                    <span class="mbx__quota">
                      <i class="bi bi-hdd"></i>
                      {{ mb.quota_mb === 0 ? 'Sin límite' : mb.quota_mb + ' MB' }}
                      <span style="margin-left:8px"><i class="bi bi-send"></i>
                        {{ mb.send_limit_hour === 0 ? 'envío libre' : mb.send_limit_hour + '/h' }}</span>
                    </span>
                  </div>
                  <span class="mbx__status" :class="mb.is_active ? 'is-on' : 'is-off'">
                    <span class="dot"></span>{{ mb.is_active ? 'Activo' : 'Suspendido' }}
                  </span>
                </div>
                <div class="mbx__actions">
                  <button v-if="roundcubeEnabled" class="mbx__btn mbx__btn--primary"
                          @click="openWebmail(mb)" :disabled="openingWebmail === mb.id" title="Webmail">
                    <span v-if="openingWebmail === mb.id" class="spinner-border spinner-border-sm"></span>
                    <template v-else><i class="bi bi-envelope-open"></i> Webmail</template>
                  </button>
                  <button class="mbx__btn" @click="openChangePassword(mb)" title="Cambiar contraseña"><i class="bi bi-key"></i></button>
                  <button class="mbx__btn" :class="{ 'mbx__btn--active': mb.forward_to }" @click="openForwardModal(mb)" title="Reenvío">
                    <i class="bi bi-forward"></i>
                  </button>
                  <button class="mbx__btn" :class="{ 'mbx__btn--active': mb.autoreply_enabled }" @click="openAutoreplyModal(mb)" title="Auto-respuesta">
                    <i class="bi bi-reply-all"></i>
                  </button>
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
            <div class="sv-tab-head">
              <span class="sv-tab-section-title">Alias y redirecciones</span>
              <button class="sv-btn sv-btn--primary sv-btn--sm" @click="showNewAlias = true">
                <i class="bi bi-plus-lg"></i> Nuevo alias
              </button>
            </div>
            <div v-if="loadingAliases" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <div v-else-if="!aliases.length" class="sv-empty-inline">
              <i class="bi bi-arrow-right-circle"></i><span>No hay alias configurados.</span>
            </div>
            <div v-else class="sv-table-wrap">
              <table class="sv-table">
                <thead>
                  <tr>
                    <th>Origen</th>
                    <th></th>
                    <th>Destino</th>
                    <th style="text-align:right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="al in aliases" :key="al.id">
                    <td>
                      <code>{{ al.full_source }}</code>
                      <span v-if="al.source === '@'" class="sv-badge sv-badge--warn" style="margin-left:6px">catch-all</span>
                    </td>
                    <td style="color:var(--text-muted);text-align:center">→</td>
                    <td>{{ al.destination }}</td>
                    <td style="text-align:right">
                      <button class="sv-icon-btn sv-icon-btn--danger"
                              @click="confirmDelete('alias', al, `¿Eliminar el alias '${al.full_source}'?`)">
                        <i class="bi bi-trash"></i>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- ── TAB: DKIM ── -->
          <div v-if="activeTab === 'dkim'">
            <div v-if="loadingDkim" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <template v-else>
              <div v-if="!dkimInfo || !dkimInfo.enabled" class="sv-empty-inline" style="flex-direction:column;gap:12px;padding:2rem">
                <i class="bi bi-shield-x" style="font-size:2.5rem;color:var(--text-muted)"></i>
                <strong>DKIM no configurado</strong>
                <p style="color:var(--text-muted);font-size:.875rem;margin:0;max-width:400px;text-align:center">
                  DKIM firma criptográficamente el correo saliente para evitar que se marque como spam.
                </p>
                <button class="sv-btn sv-btn--primary" @click="generateDkim" :disabled="generatingDkim">
                  <span v-if="generatingDkim" class="spinner-border spinner-border-sm"></span>
                  <i v-else class="bi bi-shield-plus"></i> Generar clave DKIM
                </button>
              </div>
              <div v-else style="display:flex;flex-direction:column;gap:1rem">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <div style="display:flex;align-items:center;gap:.75rem">
                    <i class="bi bi-shield-check" style="color:var(--success);font-size:1.5rem"></i>
                    <div>
                      <div style="font-weight:600">DKIM activo</div>
                      <div style="font-size:.8rem;color:var(--text-muted)">Selector: <code>{{ dkimInfo.selector }}</code></div>
                    </div>
                  </div>
                  <div style="display:flex;gap:8px">
                    <button class="sv-btn sv-btn--ghost sv-btn--sm" @click="rotateDkim" :disabled="generatingDkim">
                      <span v-if="generatingDkim" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-arrow-repeat"></i> Rotar clave
                    </button>
                    <button class="sv-btn sv-btn--danger sv-btn--sm"
                            @click="confirmDelete('dkim', null, '¿Eliminar la clave DKIM? El correo dejará de estar firmado.')">
                      <i class="bi bi-shield-x"></i> Eliminar DKIM
                    </button>
                  </div>
                </div>
                <div v-if="dkimJustGenerated && dkimInfo.dns_auto_added" class="sv-alert sv-alert--success">
                  <i class="bi bi-check-circle-fill"></i> Registro TXT añadido automáticamente a la zona DNS.
                </div>
                <div style="display:flex;flex-direction:column;gap:.5rem">
                  <label style="font-weight:600;font-size:.875rem">Registro DNS TXT
                    <span v-if="!dkimInfo.dns_auto_added" class="sv-badge sv-badge--warn" style="margin-left:6px">Añadir manualmente</span>
                  </label>
                  <div class="sv-input-copy">
                    <span class="sv-input-label">Nombre</span>
                    <input type="text" class="form-control form-control-sm font-monospace" :value="dkimInfo.dns_record_name" readonly>
                    <button class="sv-icon-btn" @click="copyText(dkimInfo.dns_record_name, 'name')">
                      <i :class="copied === 'name' ? 'bi bi-check' : 'bi bi-clipboard'"></i>
                    </button>
                  </div>
                  <div class="sv-input-copy">
                    <span class="sv-input-label">Valor</span>
                    <textarea class="form-control form-control-sm font-monospace" :value="dkimInfo.dns_record_value" readonly rows="3" style="font-size:12px;resize:none"></textarea>
                    <button class="sv-icon-btn" @click="copyText(dkimInfo.dns_record_value, 'value')">
                      <i :class="copied === 'value' ? 'bi bi-check' : 'bi bi-clipboard'"></i>
                    </button>
                  </div>
                </div>
                <div class="sv-info-box">
                  <div style="font-weight:600;margin-bottom:.5rem"><i class="bi bi-info-circle"></i> Registros DNS recomendados para {{ selectedDomain.domain_name }}</div>
                  <table style="font-family:var(--font-mono);font-size:.78rem;border-collapse:collapse;width:100%">
                    <tr><td style="padding-right:1rem;white-space:nowrap;color:var(--text-muted)">MX 10</td><td>mail.{{ selectedDomain.domain_name }}</td></tr>
                    <tr><td style="padding-right:1rem;white-space:nowrap;color:var(--text-muted)">A mail</td><td>IP_DEL_SERVIDOR</td></tr>
                    <tr><td style="padding-right:1rem;white-space:nowrap;color:var(--text-muted)">TXT @</td><td>v=spf1 a mx ip4:IP_DEL_SERVIDOR -all</td></tr>
                    <tr><td style="padding-right:1rem;white-space:nowrap;color:var(--text-muted)">TXT _dmarc</td><td>v=DMARC1; p=none; rua=mailto:dmarc@{{ selectedDomain.domain_name }}</td></tr>
                  </table>
                </div>
              </div>
            </template>
          </div>

          <!-- ── TAB: Webmail ── -->
          <div v-if="activeTab === 'webmail'">
            <div v-if="loadingWebmail" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <template v-else-if="webmail">
              <div v-if="!webmail.roundcube_installed" class="sv-alert sv-alert--warn">
                <i class="bi bi-exclamation-triangle"></i> Roundcube no está instalado en el servidor.
              </div>
              <template v-else>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem">
                  <div>
                    <div style="font-weight:600;margin-bottom:.25rem"><i class="bi bi-envelope-at"></i> Webmail propio del dominio</div>
                    <p style="font-size:.85rem;color:var(--text-muted);margin:0">
                      Acceso desde <a :href="webmail.url" target="_blank"><code>{{ webmail.host }}</code></a> (Roundcube compartido).
                    </p>
                  </div>
                  <label class="form-switch" style="margin:0">
                    <input class="form-check-input" type="checkbox" :checked="webmail.enabled" :disabled="webmailSaving"
                           @change="toggleWebmail($event.target.checked)" style="width:3em;height:1.5em;cursor:pointer">
                  </label>
                </div>
                <div v-if="webmail.enabled" class="sv-info-box" style="display:grid;grid-template-columns:1fr auto auto;gap:1rem;align-items:center">
                  <div>
                    <div style="font-size:.75rem;color:var(--text-muted)">URL</div>
                    <a :href="webmail.url" target="_blank" style="font-weight:600">{{ webmail.url }}</a>
                  </div>
                  <div>
                    <div style="font-size:.75rem;color:var(--text-muted)">HTTPS</div>
                    <span class="sv-badge" :class="webmail.ssl ? 'sv-badge--on' : 'sv-badge--warn'">
                      {{ webmail.ssl ? 'Activo' : 'Sin SSL' }}
                    </span>
                  </div>
                  <div>
                    <div style="font-size:.75rem;color:var(--text-muted)">DNS</div>
                    <span class="sv-badge" :class="webmail.dns_managed ? 'sv-badge--on' : 'sv-badge--off'">
                      {{ webmail.dns_managed ? 'Gestionado' : 'Externo' }}
                    </span>
                  </div>
                </div>
                <div v-if="webmail.enabled && !webmail.ssl" style="margin-top:.75rem">
                  <button class="sv-btn sv-btn--ghost sv-btn--sm" @click="issueWebmailSsl" :disabled="webmailSslIssuing">
                    <span v-if="webmailSslIssuing" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-lock"></i> Activar HTTPS (Let's Encrypt)
                  </button>
                </div>
                <p v-if="!webmail.enabled" style="font-size:.85rem;color:var(--text-muted);margin-top:.5rem">
                  Actívalo para crear <code>{{ webmail.host }}</code> automáticamente.
                </p>
              </template>
            </template>
          </div>

          <!-- ── TAB: Monitoreo ── -->
          <div v-if="activeTab === 'logs'">
            <div class="sv-tab-head">
              <div>
                <span class="sv-tab-section-title"><i class="bi bi-activity"></i> Monitoreo de envío</span>
                <p style="font-size:.82rem;color:var(--text-muted);margin:.25rem 0 0">Últimos correos de <strong>{{ selectedDomain.domain_name }}</strong></p>
              </div>
              <button class="sv-btn sv-btn--ghost sv-btn--sm" @click="loadMailLogs(selectedDomain.id)" :disabled="loadingLogs">
                <span v-if="loadingLogs" class="spinner-border spinner-border-sm"></span>
                <i v-else class="bi bi-arrow-repeat"></i> Actualizar
              </button>
            </div>
            <div v-if="loadingLogs" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <div v-else-if="mailLogs && !mailLogs.available" class="sv-alert sv-alert--warn">
              <i class="bi bi-exclamation-triangle"></i> {{ mailLogs.message }}
            </div>
            <template v-else-if="mailLogs">
              <div class="sv-counters" style="margin-bottom:1rem">
                <div class="sv-counter" v-for="(val, key) in {sent:mailLogs.counts.sent, received:mailLogs.counts.received, rejected:mailLogs.counts.rejected, bounced:mailLogs.counts.bounced, deferred:mailLogs.counts.deferred}" :key="key">
                  <span class="sv-counter-val" style="font-size:1.5rem">{{ val }}</span>
                  <span class="sv-counter-lbl">{{ {sent:'Enviados',received:'Recibidos',rejected:'Rechazados',bounced:'Rebotados',deferred:'Diferidos'}[key] }}</span>
                </div>
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1rem;align-items:center">
                <button v-for="f in logFilters" :key="f.val"
                        class="sv-btn sv-btn--sm" :class="logFilter === f.val ? 'sv-btn--primary' : 'sv-btn--ghost'"
                        @click="logFilter = f.val">{{ f.label }}</button>
                <span style="margin-left:auto;font-size:.8rem;color:var(--text-muted)">
                  {{ filteredLogEvents.length }} eventos · {{ mailLogs.log_lines_read }} líneas
                </span>
              </div>
              <div v-if="!filteredLogEvents.length" class="sv-empty-inline">
                <i class="bi bi-inbox"></i><span>Sin eventos para el filtro seleccionado</span>
              </div>
              <div v-else class="sv-table-wrap">
                <table class="sv-table" style="font-size:.82rem">
                  <thead>
                    <tr>
                      <th style="width:140px">Fecha/hora</th>
                      <th style="width:90px;text-align:center">Tipo</th>
                      <th>De</th>
                      <th>Para</th>
                      <th>Relay / Motivo</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(ev, i) in filteredLogEvents" :key="i">
                      <td style="white-space:nowrap;font-family:var(--font-mono);color:var(--text-muted);font-size:.78rem">{{ ev.ts }}</td>
                      <td style="text-align:center"><span :class="logBadge(ev.status)">{{ logLabel(ev.status) }}</span></td>
                      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono)" :title="ev.from">{{ ev.from || '—' }}</td>
                      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono)" :title="ev.to">{{ ev.to || '—' }}</td>
                      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)" :title="ev.reason || ev.relay">{{ ev.reason || ev.relay || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <div v-else class="sv-empty-inline">
              <i class="bi bi-activity"></i><span>Pulsa Actualizar para cargar el monitoreo</span>
            </div>
          </div>

          <!-- ── TAB: Relay SMTP ── -->
          <div v-if="activeTab === 'relay'">
            <div v-if="loadingRelay" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <template v-else-if="relay">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem">
                <div>
                  <div style="font-weight:600;margin-bottom:.25rem"><i class="bi bi-arrow-up-right-circle"></i> Relay SMTP del dominio</div>
                  <p style="font-size:.85rem;color:var(--text-muted);margin:0">
                    Envía el correo de <strong>{{ selectedDomain.domain_name }}</strong> por un smarthost en vez de directo.
                  </p>
                </div>
                <label class="form-switch" style="margin:0">
                  <input class="form-check-input" type="checkbox" v-model="relayForm.enabled" style="width:3em;height:1.5em;cursor:pointer">
                </label>
              </div>
              <div class="sv-alert" :class="relay.global_relay_active ? 'sv-alert--info' : 'sv-alert--muted'" style="margin-bottom:1rem">
                <i class="bi bi-info-circle"></i>
                <span v-if="relay.global_relay_active">Relay <strong>global</strong> activo (<code>{{ relay.global_relay_host }}</code>). Sin relay propio, este dominio lo usa.</span>
                <span v-else>No hay relay global. Sin relay propio, el correo sale <strong>directo</strong> (puerto 25).</span>
              </div>
              <div v-if="relayForm.enabled" class="sv-form-grid" style="margin-bottom:1rem">
                <div class="sv-field">
                  <label>Host del smarthost</label>
                  <input v-model="relayForm.host" class="form-control form-control-sm font-monospace" placeholder="pmg.midominio.com">
                </div>
                <div class="sv-field">
                  <label>Puerto</label>
                  <input v-model.number="relayForm.port" type="number" class="form-control form-control-sm" placeholder="587">
                </div>
                <div class="sv-field">
                  <label>Usuario <span style="color:var(--text-muted)">(vacío = sin auth)</span></label>
                  <input v-model="relayForm.username" class="form-control form-control-sm" autocomplete="off">
                </div>
                <div class="sv-field">
                  <label>Contraseña</label>
                  <input v-model="relayForm.password" type="password" class="form-control form-control-sm" autocomplete="new-password" :placeholder="relay.username ? '(sin cambios)' : ''">
                </div>
              </div>
              <button class="sv-btn sv-btn--primary sv-btn--sm" @click="saveDomainRelay" :disabled="relaySaving">
                <span v-if="relaySaving" class="spinner-border spinner-border-sm"></span>
                <i v-else class="bi bi-save"></i>
                {{ relayForm.enabled ? 'Guardar relay' : 'Desactivar relay' }}
              </button>
            </template>
          </div>

          <!-- ── TAB: Ajustes ── -->
          <div v-if="activeTab === 'settings'" style="display:flex;flex-direction:column;gap:1.5rem">

            <!-- Configuración general -->
            <div>
              <h6 style="font-weight:600;font-size:.95rem;margin-bottom:1rem">Configuración general</h6>
              <form @submit.prevent="saveSettings" class="sv-form-grid">
                <div class="sv-field sv-field--full">
                  <label>Catch-all <span style="color:var(--text-muted);font-weight:400">(correo para direcciones no existentes)</span></label>
                  <input type="email" class="form-control" v-model="settingsForm.catch_all" placeholder="catchall@example.com (vacío = desactivado)">
                </div>
                <div class="sv-field">
                  <label>Límite de buzones <span style="color:var(--text-muted);font-weight:400">(0 = sin límite)</span></label>
                  <input type="number" class="form-control" v-model.number="settingsForm.max_mailboxes" min="0">
                </div>
                <div class="sv-field">
                  <label>Envío del dominio <span style="color:var(--text-muted);font-weight:400">(correos/hora)</span></label>
                  <input type="number" class="form-control" v-model.number="settingsForm.send_limit_hour" min="0" placeholder="1000">
                </div>
                <div class="sv-field">
                  <label>Estado</label>
                  <select class="form-select" v-model="settingsForm.is_active">
                    <option :value="true">Activo</option>
                    <option :value="false">Suspendido</option>
                  </select>
                </div>
                <div class="sv-field sv-field--full">
                  <button type="submit" class="sv-btn sv-btn--primary sv-btn--sm" :disabled="savingSettings">
                    <span v-if="savingSettings" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-floppy"></i> Guardar cambios
                  </button>
                </div>
              </form>
            </div>

            <div style="border-top:1px solid var(--border)"></div>

            <!-- Antispam -->
            <div>
              <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:1rem">
                <h6 style="font-weight:600;font-size:.95rem;margin:0"><i class="bi bi-shield-check" style="color:var(--danger)"></i> Antispam</h6>
                <span v-if="loadingSpam" class="spinner-border spinner-border-sm"></span>
              </div>
              <div v-if="spamSettings.stats" class="sv-counters" style="margin-bottom:1rem">
                <div class="sv-counter" v-for="(val, key) in {scanned:spamSettings.stats.scanned, clean:spamSettings.stats.clean, tagged:spamSettings.stats.tagged, greylisted:spamSettings.stats.greylisted, rejected:spamSettings.stats.rejected}" :key="key">
                  <span class="sv-counter-val" style="font-size:1.25rem">{{ val }}</span>
                  <span class="sv-counter-lbl">{{ {scanned:'Analizados',clean:'Limpios',tagged:'Etiquetados',greylisted:'Greylisted',rejected:'Rechazados'}[key] }}</span>
                </div>
              </div>
              <form @submit.prevent="saveSpamSettings" class="sv-form-grid">
                <div class="sv-field">
                  <label>Umbral etiquetado <span style="color:var(--text-muted);font-weight:400;display:block;font-size:.8rem">Score → añade cabecera spam</span></label>
                  <div style="display:flex;gap:6px">
                    <input type="number" class="form-control" step="0.5" min="1" max="20" v-model.number="spamForm.spam_tag_threshold">
                    <span class="sv-input-suffix">pts</span>
                  </div>
                </div>
                <div class="sv-field">
                  <label>Umbral rechazo <span style="color:var(--text-muted);font-weight:400;display:block;font-size:.8rem">Score → rechazar mensaje</span></label>
                  <div style="display:flex;gap:6px">
                    <input type="number" class="form-control" step="0.5" min="3" max="100" v-model.number="spamForm.spam_reject_threshold">
                    <span class="sv-input-suffix">pts</span>
                  </div>
                </div>
                <div class="sv-field">
                  <label><i class="bi bi-check-circle" style="color:var(--success)"></i> Whitelist <span style="color:var(--text-muted);font-weight:400;display:block;font-size:.8rem">Siempre permitidos</span></label>
                  <textarea class="form-control font-monospace" rows="4" v-model="spamForm.whitelist_senders" placeholder="usuario@dominio.com&#10;@dominio.com" style="font-size:.8rem"></textarea>
                </div>
                <div class="sv-field">
                  <label><i class="bi bi-x-circle" style="color:var(--danger)"></i> Blacklist <span style="color:var(--text-muted);font-weight:400;display:block;font-size:.8rem">Siempre bloqueados</span></label>
                  <textarea class="form-control font-monospace" rows="4" v-model="spamForm.blacklist_senders" placeholder="spam@ejemplo.com&#10;@dominiomalicioso.com" style="font-size:.8rem"></textarea>
                </div>
                <div class="sv-field sv-field--full">
                  <button type="submit" class="sv-btn sv-btn--danger sv-btn--sm" :disabled="savingSpam">
                    <span v-if="savingSpam" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-shield-check"></i> Guardar antispam
                  </button>
                </div>
              </form>
              <div v-if="spamSettings.stats?.history?.length" style="margin-top:1rem">
                <div style="font-weight:600;font-size:.875rem;margin-bottom:.75rem">
                  <i class="bi bi-clock-history"></i> Últimos mensajes
                  <span class="sv-count" style="margin-left:6px">{{ spamSettings.stats.history.length }}</span>
                </div>
                <div class="sv-table-wrap">
                  <table class="sv-table" style="font-size:.82rem">
                    <thead><tr><th>Remitente</th><th>Asunto</th><th style="text-align:center">Acción</th><th style="text-align:center">Score</th><th style="text-align:right">Fecha</th></tr></thead>
                    <tbody>
                      <tr v-for="msg in spamSettings.stats.history" :key="msg.id">
                        <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono)" :title="msg.from_addr">{{ msg.from_addr || '—' }}</td>
                        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="msg.subject">{{ msg.subject || '—' }}</td>
                        <td style="text-align:center">
                          <span :class="{
                            'sv-badge sv-badge--danger': msg.action==='reject',
                            'sv-badge sv-badge--warn':   msg.action==='add header',
                            'sv-badge sv-badge--off':    msg.action==='greylist',
                            'sv-badge sv-badge--on':     msg.action==='no action',
                          }">{{ msg.action==='add header'?'spam':msg.action==='no action'?'limpio':msg.action||'?' }}</span>
                        </td>
                        <td style="text-align:center;font-family:var(--font-mono)">{{ msg.score.toFixed(2) }}</td>
                        <td style="text-align:right;color:var(--text-muted);white-space:nowrap">{{ msg.timestamp }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div style="border-top:1px solid var(--border)"></div>

            <!-- TLS del correo -->
            <div>
              <h6 style="font-weight:600;font-size:.95rem;margin-bottom:1rem"><i class="bi bi-shield-lock" style="color:var(--success)"></i> Seguridad TLS del correo</h6>
              <div v-if="mailtls" class="sv-info-box">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                  <div>
                    <div style="font-weight:600">Certificado en <code>{{ mailtls.host }}</code></div>
                    <p style="font-size:.85rem;color:var(--text-muted);margin:.25rem 0 0">
                      Clientes IMAP/SMTP usan <strong>{{ mailtls.host }}</strong> con certificado válido de su dominio.
                    </p>
                  </div>
                  <label class="form-switch" style="margin:0;flex-shrink:0">
                    <input class="form-check-input" type="checkbox" :checked="mailtls.enabled" :disabled="mailtlsSaving"
                           @change="toggleMailTls($event.target.checked)" style="width:3em;height:1.5em;cursor:pointer">
                  </label>
                </div>
                <div v-if="mailtls.enabled" style="margin-top:.75rem">
                  <span class="sv-badge" :class="mailtls.cert_valid ? 'sv-badge--on' : 'sv-badge--warn'">
                    <i :class="mailtls.cert_valid ? 'bi bi-shield-check' : 'bi bi-exclamation-triangle'"></i>
                    {{ mailtls.cert_valid ? 'Certificado válido' : 'Certificado pendiente' }}
                  </span>
                </div>
                <p v-if="mailtlsSaving" style="font-size:.85rem;color:var(--text-muted);margin:.5rem 0 0">
                  <span class="spinner-border spinner-border-sm"></span> Emitiendo certificado…
                </p>
              </div>
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

    <!-- ══════════ Modal: Reenvío ══════════ -->
    <div v-if="showForwardModal" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)" @click.self="showForwardModal = false">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-forward me-2"></i>Reenvío — {{ forwardTarget?.full_email }}</h5>
            <button class="btn-close" @click="showForwardModal = false"></button>
          </div>
          <div class="modal-body" style="display:flex;flex-direction:column;gap:1rem">
            <p class="text-muted small mb-0">Reenvía los correos recibidos a una o más direcciones externas.</p>
            <div>
              <label class="form-label fw-semibold">Reenviar a <span class="text-muted fw-normal">(una por línea)</span></label>
              <textarea v-model="forwardForm.forward_to_text" class="form-control form-control-sm font-monospace"
                        rows="3" placeholder="otro@ejemplo.com&#10;segundo@ejemplo.com"></textarea>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="fwd-keep-copy"
                     v-model="forwardForm.forward_keep_copy">
              <label class="form-check-label" for="fwd-keep-copy">
                Guardar copia en este buzón
                <span class="text-muted small d-block">Si lo desmarcas, el correo se reenvía y no se almacena aquí.</span>
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary btn-sm" @click="showForwardModal = false">Cancelar</button>
            <button class="btn btn-danger btn-sm" v-if="forwardTarget?.forward_to" @click="clearForward">
              <i class="bi bi-x-circle me-1"></i>Desactivar reenvío
            </button>
            <button class="btn btn-primary btn-sm" @click="saveForward" :disabled="saving">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-save me-1"></i>Guardar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════════ Modal: Auto-respuesta ══════════ -->
    <div v-if="showAutoreplyModal" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)" @click.self="showAutoreplyModal = false">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-reply-all me-2"></i>Auto-respuesta — {{ autoreplyTarget?.full_email }}</h5>
            <button class="btn-close" @click="showAutoreplyModal = false"></button>
          </div>
          <div class="modal-body" style="display:flex;flex-direction:column;gap:1rem">
            <p class="text-muted small mb-0">Responde automáticamente a los correos recibidos (útil para vacaciones o fuera de oficina).</p>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="ar-enabled"
                     v-model="autoreplyForm.autoreply_enabled">
              <label class="form-check-label fw-semibold" for="ar-enabled">
                Auto-respuesta activa
              </label>
            </div>
            <div>
              <label class="form-label fw-semibold">Asunto</label>
              <input v-model="autoreplyForm.autoreply_subject" type="text" class="form-control form-control-sm"
                     placeholder="Ej: Fuera de la oficina hasta el 10 de junio">
            </div>
            <div>
              <label class="form-label fw-semibold">Mensaje</label>
              <textarea v-model="autoreplyForm.autoreply_body" class="form-control form-control-sm"
                        rows="4" placeholder="Ej: Estoy fuera hasta el 10 de junio. Te responderé en cuanto vuelva."></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary btn-sm" @click="showAutoreplyModal = false">Cancelar</button>
            <button class="btn btn-primary btn-sm" @click="saveAutoreply" :disabled="saving">
              <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-save me-1"></i>Guardar
            </button>
          </div>
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
import { ref, computed, onMounted } from 'vue'
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
    const showForwardModal  = ref(false)
    const showAutoreplyModal = ref(false)
    const deleteTarget     = ref(null)
    const saving           = ref(false)
    const showPwd          = ref(false)

    // ── Formularios ───────────────────────────────────────────────────
    const newDomainForm  = ref({ domain_name: '', catch_all: '', max_mailboxes: 0 })
    const newMailboxForm = ref({ username: '', password: '', quota_mb: 1024, send_limit_hour: 200 })
    const newAliasForm   = ref({ source: '', destination: '' })
    const passwordTarget  = ref(null)
    const newPassword     = ref('')
    const forwardTarget   = ref(null)
    const forwardForm     = ref({ forward_to_text: '', forward_keep_copy: true })
    const autoreplyTarget = ref(null)
    const autoreplyForm   = ref({ autoreply_enabled: false, autoreply_subject: '', autoreply_body: '' })

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
      relay.value = null
      mailtls.value = null
      mailLogs.value = null
      logFilter.value = 'all'
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
      if (tab === 'settings') {
        if (!spamSettings.value.spam_tag_threshold) {
          await loadSpamSettings(selectedDomain.value.id)
        }
        await loadMailTls(selectedDomain.value.id)
      }
      if (tab === 'webmail') {
        await loadWebmail(selectedDomain.value.id)
      }
      if (tab === 'relay') {
        await loadRelay(selectedDomain.value.id)
      }
      if (tab === 'logs' && mailLogs.value === null) {
        await loadMailLogs(selectedDomain.value.id)
      }
    }

    // ── Monitoreo de envío (logs) ──
    const mailLogs     = ref(null)
    const loadingLogs  = ref(false)
    const logFilter    = ref('all')
    const logFilters   = [
      { val: 'all',      label: 'Todos' },
      { val: 'sent',     label: 'Enviados' },
      { val: 'received', label: 'Recibidos' },
      { val: 'rejected', label: 'Rechazados' },
      { val: 'bounced',  label: 'Rebotados' },
      { val: 'deferred', label: 'Diferidos' },
    ]

    const loadMailLogs = async (domainId) => {
      loadingLogs.value = true
      try {
        const data = await api.get(`/api/mail/domains/${domainId}/logs?lines=500`)
        mailLogs.value = data
      } catch (e) {
        store.showNotification('Error cargando logs: ' + e.message, 'danger')
        mailLogs.value = { available: false, message: e.message, counts: {}, events: [] }
      } finally {
        loadingLogs.value = false
      }
    }

    const filteredLogEvents = computed(() => {
      if (!mailLogs.value || !mailLogs.value.events) return []
      if (logFilter.value === 'all') return mailLogs.value.events
      return mailLogs.value.events.filter(e =>
        logFilter.value === 'sent'     ? e.type === 'sent' && e.status === 'sent' :
        logFilter.value === 'received' ? e.type === 'received' :
        logFilter.value === 'rejected' ? e.status === 'rejected' :
        logFilter.value === 'bounced'  ? e.status === 'bounced' :
        logFilter.value === 'deferred' ? e.status === 'deferred' : true
      )
    })

    const logBadge = (status) => ({
      'badge bg-success':               status === 'sent',
      'badge bg-primary':               status === 'received',
      'badge bg-danger':                status === 'rejected',
      'badge bg-warning text-dark':     status === 'bounced',
      'badge bg-secondary':             status === 'deferred',
      'badge bg-light text-dark border': !['sent','received','rejected','bounced','deferred'].includes(status),
    })

    const logLabel = (status) => ({
      sent: 'enviado', received: 'recibido', rejected: 'rechazado',
      bounced: 'rebotado', deferred: 'diferido',
    }[status] || status)

    // ── SMTP relay por dominio ──
    const relay        = ref(null)
    const relayForm    = ref({ enabled: false, host: '', port: 587, username: '', password: '' })
    const loadingRelay = ref(false)
    const relaySaving  = ref(false)

    // ── TLS propio del dominio (SNI) ──
    const mailtls       = ref(null)
    const mailtlsSaving = ref(false)

    const loadMailTls = async (domainId) => {
      try {
        mailtls.value = await api.getMailTls(domainId)
      } catch (e) {
        mailtls.value = null
      }
    }

    const toggleMailTls = async (enabled) => {
      mailtlsSaving.value = true
      try {
        const r = await api.setMailTls(selectedDomain.value.id, enabled)
        store.showNotification(r.message || (enabled ? 'TLS activado' : 'TLS desactivado'), 'success')
        await loadMailTls(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
        await loadMailTls(selectedDomain.value.id)
      } finally {
        mailtlsSaving.value = false
      }
    }

    const loadRelay = async (domainId) => {
      loadingRelay.value = true
      try {
        const r = await api.getDomainRelay(domainId)
        relay.value = r
        relayForm.value = {
          enabled: r.enabled, host: r.host || '', port: r.port || 587,
          username: r.username || '', password: '',
        }
      } catch (e) {
        relay.value = null
      } finally {
        loadingRelay.value = false
      }
    }

    const saveDomainRelay = async () => {
      if (relayForm.value.enabled && !relayForm.value.host) {
        store.showNotification('Indica el host del smarthost', 'danger'); return
      }
      relaySaving.value = true
      try {
        await api.setDomainRelay(selectedDomain.value.id, { ...relayForm.value })
        store.showNotification(relayForm.value.enabled ? 'Relay del dominio guardado' : 'Relay del dominio desactivado', 'success')
        await loadRelay(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        relaySaving.value = false
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
    // Reenvío
    // ─────────────────────────────────────────────────────────────────

    const openForwardModal = (mb) => {
      forwardTarget.value = mb
      forwardForm.value = {
        forward_to_text: (mb.forward_to || '').split(',').map(e => e.trim()).filter(Boolean).join('\n'),
        forward_keep_copy: mb.forward_keep_copy !== false,
      }
      showForwardModal.value = true
    }

    const saveForward = async () => {
      saving.value = true
      try {
        const emails = forwardForm.value.forward_to_text
          .split('\n').map(e => e.trim()).filter(Boolean)
        await api.updateMailbox(selectedDomain.value.id, forwardTarget.value.id, {
          forward_to: emails.join(','),
          forward_keep_copy: forwardForm.value.forward_keep_copy,
        })
        forwardTarget.value.forward_to = emails.join(',')
        forwardTarget.value.forward_keep_copy = forwardForm.value.forward_keep_copy
        showForwardModal.value = false
        store.showNotification('Reenvío configurado', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    const clearForward = async () => {
      saving.value = true
      try {
        await api.updateMailbox(selectedDomain.value.id, forwardTarget.value.id, {
          forward_to: '',
          forward_keep_copy: true,
        })
        forwardTarget.value.forward_to = null
        showForwardModal.value = false
        store.showNotification('Reenvío desactivado', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        saving.value = false
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Auto-respuesta
    // ─────────────────────────────────────────────────────────────────

    const openAutoreplyModal = (mb) => {
      autoreplyTarget.value = mb
      autoreplyForm.value = {
        autoreply_enabled: mb.autoreply_enabled || false,
        autoreply_subject: mb.autoreply_subject || '',
        autoreply_body:    mb.autoreply_body    || '',
      }
      showAutoreplyModal.value = true
    }

    const saveAutoreply = async () => {
      saving.value = true
      try {
        await api.updateMailbox(selectedDomain.value.id, autoreplyTarget.value.id, {
          autoreply_enabled: autoreplyForm.value.autoreply_enabled,
          autoreply_subject: autoreplyForm.value.autoreply_subject,
          autoreply_body:    autoreplyForm.value.autoreply_body,
        })
        autoreplyTarget.value.autoreply_enabled = autoreplyForm.value.autoreply_enabled
        autoreplyTarget.value.autoreply_subject = autoreplyForm.value.autoreply_subject
        autoreplyTarget.value.autoreply_body    = autoreplyForm.value.autoreply_body
        showAutoreplyModal.value = false
        store.showNotification(
          autoreplyForm.value.autoreply_enabled ? 'Auto-respuesta activada' : 'Auto-respuesta desactivada',
          'success'
        )
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
      showForwardModal, forwardTarget, forwardForm, openForwardModal, saveForward, clearForward,
      showAutoreplyModal, autoreplyTarget, autoreplyForm, openAutoreplyModal, saveAutoreply,
      // Roundcube
      roundcubeEnabled, roundcubeUrl, openingWebmail,
      // Webmail por dominio
      webmail, loadingWebmail, webmailSaving, webmailSslIssuing,
      loadWebmail, toggleWebmail, issueWebmailSsl,
      relay, relayForm, loadingRelay, relaySaving, loadRelay, saveDomainRelay,
      mailtls, mailtlsSaving, toggleMailTls,
      // Monitoreo de envío
      mailLogs, loadingLogs, logFilter, logFilters,
      loadMailLogs, filteredLogEvents, logBadge, logLabel,
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
/* ── Layout base ── */
.sv-view { display:flex; flex-direction:column; gap:20px; }

/* ── Cabecera ── */
.sv-page-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; }
.sv-title { font-size:1.5rem; font-weight:700; margin:0 0 .25rem; display:flex; align-items:center; gap:.5rem; }
.sv-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }
.sv-head-actions { display:flex; gap:8px; flex-shrink:0; }
.sv-breadcrumb { display:flex; align-items:center; gap:8px; margin-bottom:.5rem; font-size:.875rem; }
.sv-chevron { color:var(--text-muted); font-size:.75rem; }
.sv-domain-name { font-weight:600; }
.sv-back-btn { background:none; border:1px solid var(--border); border-radius:var(--radius-sm,6px); padding:.25rem .75rem; font-size:.82rem; cursor:pointer; color:var(--text-secondary); transition:all .15s; }
.sv-back-btn:hover { background:var(--surface-2); color:var(--text); }

/* ── Botones ── */
.sv-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--radius-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.sv-btn--primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.sv-btn--primary:hover { opacity:.9; }
.sv-btn--ghost { background:var(--surface); color:var(--text-secondary); border-color:var(--border); }
.sv-btn--ghost:hover { background:var(--surface-2); color:var(--text); }
.sv-btn--danger { background:color-mix(in srgb,var(--danger) 10%,transparent); color:var(--danger); border-color:color-mix(in srgb,var(--danger) 30%,transparent); }
.sv-btn--danger:hover { background:var(--danger); color:#fff; }
.sv-btn--sm { padding:.3rem .7rem; font-size:.82rem; }
.sv-btn:disabled { opacity:.5; cursor:not-allowed; }
.sv-icon-btn { width:32px; height:32px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:var(--radius-sm,6px); background:var(--surface); color:var(--text-secondary); cursor:pointer; transition:all .15s; }
.sv-icon-btn:hover { background:var(--surface-2); color:var(--text); }
.sv-icon-btn--danger:hover { background:var(--danger); color:#fff; border-color:var(--danger); }

/* ── Card ── */
.sv-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md,10px); overflow:hidden; }
.sv-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); }
.sv-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
.sv-count { background:var(--surface-2); border:1px solid var(--border); border-radius:999px; padding:.1rem .5rem; font-size:.75rem; font-weight:600; }

/* ── Badges ── */
.sv-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }
.sv-badge--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.sv-badge--off { background:var(--surface-2); color:var(--text-muted); }
.sv-badge--blue { background:color-mix(in srgb,var(--accent) 15%,transparent); color:var(--accent); }
.sv-badge--teal { background:color-mix(in srgb,var(--info,#06b6d4) 15%,transparent); color:var(--info,#06b6d4); }
.sv-badge--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 15%,transparent); color:var(--warning,#f59e0b); }
.sv-badge--danger { background:color-mix(in srgb,var(--danger) 15%,transparent); color:var(--danger); }

/* ── Contadores ── */
.sv-counters { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px; }
.sv-counter { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md,10px); padding:.875rem 1rem; display:flex; flex-direction:column; align-items:center; gap:.25rem; }
.sv-counter-val { font-size:1.75rem; font-weight:700; line-height:1; }
.sv-counter-lbl { font-size:.78rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; }

/* ── Tabla ── */
.sv-table-wrap { overflow-x:auto; }
.sv-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.sv-table th { padding:.65rem 1rem; text-align:left; font-size:.78rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); }
.sv-table td { padding:.7rem 1rem; border-bottom:1px solid var(--border); }
.sv-table tr:last-child td { border-bottom:none; }
.sv-table tbody tr:hover { background:var(--surface-2); }

/* ── Tabs ── */
.sv-tabs { display:flex; gap:2px; padding:.75rem 1rem .5rem; border-bottom:1px solid var(--border); flex-wrap:wrap; }
.sv-tab { display:inline-flex; align-items:center; gap:6px; padding:.45rem .85rem; border-radius:var(--radius-sm,6px); font-size:.85rem; font-weight:500; cursor:pointer; border:1px solid transparent; color:var(--text-muted); background:none; transition:all .15s; }
.sv-tab:hover { background:var(--surface-2); color:var(--text); }
.sv-tab--active { background:var(--surface-2); color:var(--text); border-color:var(--border); }
.sv-tab-count { background:var(--accent); color:#fff; border-radius:999px; font-size:.68rem; padding:.1rem .4rem; line-height:1.4; }
.sv-tab-body { padding:1.25rem; }
.sv-tab-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; }
.sv-tab-section-title { font-weight:600; font-size:.95rem; }

/* ── Formularios ── */
.sv-form-grid { display:grid; grid-template-columns:1fr 1fr; gap:.875rem; }
.sv-field { display:flex; flex-direction:column; gap:.35rem; }
.sv-field label { font-size:.82rem; font-weight:600; color:var(--text-secondary); }
.sv-field--full { grid-column:1/-1; }
.sv-input-copy { display:flex; align-items:stretch; gap:0; border:1px solid var(--border); border-radius:var(--radius-sm,6px); overflow:hidden; }
.sv-input-label { padding:.4rem .65rem; background:var(--surface-2); color:var(--text-muted); font-size:.78rem; display:flex; align-items:center; white-space:nowrap; border-right:1px solid var(--border); }
.sv-input-copy .form-control { border:none; border-radius:0; flex:1; }
.sv-input-copy .sv-icon-btn { border:none; border-left:1px solid var(--border); border-radius:0; width:36px; }
.sv-input-suffix { display:flex; align-items:center; padding:.4rem .65rem; background:var(--surface-2); border:1px solid var(--border); border-left:none; border-radius:0 var(--radius-sm,6px) var(--radius-sm,6px) 0; font-size:.82rem; color:var(--text-muted); }

/* ── Alertas e info ── */
.sv-alert { display:flex; align-items:flex-start; gap:.5rem; padding:.65rem .85rem; border-radius:var(--radius-sm,6px); font-size:.875rem; }
.sv-alert--success { background:color-mix(in srgb,var(--success) 10%,transparent); color:var(--success); border:1px solid color-mix(in srgb,var(--success) 25%,transparent); }
.sv-alert--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 10%,transparent); color:var(--warning,#d97706); border:1px solid color-mix(in srgb,var(--warning,#f59e0b) 25%,transparent); }
.sv-alert--info { background:color-mix(in srgb,var(--accent) 8%,transparent); color:var(--accent); border:1px solid color-mix(in srgb,var(--accent) 20%,transparent); }
.sv-alert--muted { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); }
.sv-info-box { background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-md,10px); padding:1rem; font-size:.875rem; }

/* ── Vacíos y loading ── */
.sv-empty-state { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:.75rem; padding:3rem 1rem; text-align:center; }
.sv-empty-icon { font-size:2.5rem; color:var(--text-muted); }
.sv-empty-inline { display:flex; align-items:center; justify-content:center; gap:.75rem; padding:2rem; color:var(--text-muted); font-size:.875rem; }
.sv-empty-inline i { font-size:1.5rem; }
.sv-loading { display:flex; justify-content:center; padding:2rem; }

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
.mbx__btn--active { background: color-mix(in srgb, var(--accent) 10%, transparent); color: var(--accent); border-color: color-mix(in srgb, var(--accent) 30%, transparent); }
</style>
