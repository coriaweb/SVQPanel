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
        <div v-if="!selectedDomain" class="mail-search">
          <i class="bi bi-search"></i>
          <input v-model="mailSearch" type="search" class="svq-input" placeholder="Buscar dominio…" />
        </div>
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

      <template v-else>
      <!-- Greylisting global (solo admin) -->
      <div v-if="isAdminOrReseller && !selectedDomain" class="sv-card" style="margin-bottom:1rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 1.1rem;flex-wrap:wrap">
          <div>
            <div style="font-weight:600"><i class="bi bi-hourglass-split" style="color:var(--warning)"></i> Lista gris (greylisting) global</div>
            <div style="font-size:.82rem;color:var(--text-muted);margin-top:.2rem">
              Si la desactivas, ningún dominio hará greylisting (entrega inmediata para todos).
              Si está activa, cada dominio puede excluirse en sus Ajustes.
            </div>
          </div>
          <label class="form-check form-switch" style="display:flex;align-items:center;gap:.5rem;white-space:nowrap">
            <input class="form-check-input" type="checkbox" :checked="globalGreylist"
                   :disabled="globalGreylistSaving" @change="toggleGlobalGreylist($event.target.checked)" />
            <span>{{ globalGreylist ? 'Activada' : 'Desactivada' }}</span>
            <span v-if="globalGreylistSaving" class="spinner-border spinner-border-sm"></span>
          </label>
        </div>
      </div>

      <!-- Mover spam a la carpeta Junk — global (solo admin) -->
      <div v-if="isAdminOrReseller && !selectedDomain" class="sv-card" style="margin-bottom:1rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 1.1rem;flex-wrap:wrap">
          <div>
            <div style="font-weight:600"><i class="bi bi-inboxes" style="color:var(--warning)"></i> Mover spam a la carpeta Junk</div>
            <div style="font-size:.82rem;color:var(--text-muted);margin-top:.2rem">
              El spam detectado (no el rechazado) se mueve a la carpeta Junk en vez de a la
              bandeja de entrada. Si la desactivas, ese correo llega a la bandeja. Cada dominio
              puede excluirse en sus Ajustes.
            </div>
          </div>
          <label class="form-check form-switch" style="display:flex;align-items:center;gap:.5rem;white-space:nowrap">
            <input class="form-check-input" type="checkbox" :checked="globalSpamJunk"
                   :disabled="globalSpamJunkSaving" @change="toggleGlobalSpamJunk($event.target.checked)" />
            <span>{{ globalSpamJunk ? 'Activado' : 'Desactivado' }}</span>
            <span v-if="globalSpamJunkSaving" class="spinner-border spinner-border-sm"></span>
          </label>
        </div>
      </div>

      <!-- Salud de correo del SERVIDOR (deliverability de reenvíos) — solo admin -->
      <div v-if="isAdminOrReseller && !selectedDomain" class="sv-card" style="margin-bottom:1rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 1.1rem;flex-wrap:wrap;cursor:pointer"
             @click="deliv.open = !deliv.open">
          <div>
            <div style="font-weight:600">
              <i class="bi bi-send-check" :style="{color: delivStatusColor}"></i>
              Salud de correo del servidor
              <span v-if="deliv.data" class="sv-badge" :class="deliv.data.all_ok ? 'sv-badge--on' : 'sv-badge--off'" style="margin-left:.4rem">
                {{ deliv.data.all_ok ? 'Correcto' : 'Faltan registros' }}
              </span>
            </div>
            <div style="font-size:.82rem;color:var(--text-muted);margin-top:.2rem">
              Autenticación (SPF/DKIM/DMARC/PTR) del dominio del servidor
              <strong v-if="deliv.data">{{ deliv.data.domain }}</strong>.
              Necesaria para que los <strong>reenvíos</strong> de alias lleguen a Gmail/Outlook sin rebotar.
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:.6rem">
            <button class="sv-btn sv-btn--ghost" @click.stop="loadDeliverability" :disabled="deliv.loading">
              <span v-if="deliv.loading" class="spinner-border spinner-border-sm"></span>
              <i v-else class="bi bi-arrow-repeat"></i> Verificar
            </button>
            <i class="bi" :class="deliv.open ? 'bi-chevron-up' : 'bi-chevron-down'"></i>
          </div>
        </div>

        <div v-if="deliv.open" style="border-top:1px solid var(--border);padding:1rem 1.1rem">
          <div v-if="deliv.loading && !deliv.data" class="sv-loading"><div class="spinner-border spinner-border-sm"></div></div>
          <div v-else-if="deliv.error" class="alert alert-danger" style="font-size:.85rem">{{ deliv.error }}</div>
          <template v-else-if="deliv.data">
            <div v-if="deliv.data.dns_external" class="sv-info-box" style="margin-bottom:.9rem">
              <i class="bi bi-info-circle"></i>
              El DNS de <strong>{{ deliv.data.domain }}</strong> es <strong>externo</strong> a este panel:
              copia los registros que falten (❌) en el panel DNS de tu proveedor.
            </div>
            <div v-else class="sv-info-box" style="margin-bottom:.9rem">
              <i class="bi bi-info-circle"></i>
              El DNS de <strong>{{ deliv.data.domain }}</strong> lo gestiona este panel: los registros se publican solos.
            </div>

            <button v-if="!deliv.data.dkim_key_present" class="sv-btn sv-btn--primary" style="margin-bottom:.9rem"
                    @click="generateServerDkim" :disabled="deliv.genDkim">
              <span v-if="deliv.genDkim" class="spinner-border spinner-border-sm"></span>
              <i v-else class="bi bi-key"></i> Generar clave DKIM del servidor
            </button>

            <div class="sv-table-wrap">
              <table class="sv-table">
                <thead>
                  <tr>
                    <th style="width:1%"></th>
                    <th>Registro</th>
                    <th>Valor a publicar (TXT)</th>
                    <th style="text-align:right">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in deliv.data.records" :key="i">
                    <td style="text-align:center">
                      <i v-if="r.ok" class="bi bi-check-circle-fill" style="color:var(--success)" :title="'Correcto'"></i>
                      <i v-else-if="r.severity==='warn'" class="bi bi-exclamation-triangle-fill" style="color:var(--warning)" title="Recomendado"></i>
                      <i v-else class="bi bi-x-circle-fill" style="color:var(--danger,#e5484d)" title="Falta"></i>
                    </td>
                    <td>
                      <div style="font-weight:600;font-family:var(--font-mono,monospace);font-size:.82rem">{{ r.name }}</div>
                      <div style="font-size:.76rem;color:var(--text-muted)">{{ r.help }}</div>
                      <div v-if="r.found && !r.ok" style="font-size:.74rem;color:var(--warning);margin-top:.2rem">
                        Publicado ahora: <code>{{ r.found }}</code>
                      </div>
                    </td>
                    <td>
                      <code v-if="r.expected" style="font-size:.74rem;word-break:break-all;display:block;max-width:46ch">{{ r.expected }}</code>
                      <span v-else style="font-size:.78rem;color:var(--text-muted)">—</span>
                    </td>
                    <td style="text-align:right;white-space:nowrap">
                      <button v-if="r.expected" class="sv-btn sv-btn--ghost sv-btn--sm" @click="copyText(r.expected)" title="Copiar valor">
                        <i class="bi bi-clipboard"></i>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <div v-else style="font-size:.85rem;color:var(--text-muted)">
            Pulsa «Verificar» para comprobar el estado.
          </div>
        </div>
      </div>

      <div class="sv-card">
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
                <th style="text-align:center">Tamaño</th>
                <th style="text-align:center">DKIM</th>
                <th style="text-align:center">SSL correo</th>
                <th>Catch-all</th>
                <th style="text-align:center">Estado</th>
                <th style="text-align:right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="md in filteredMailDomains" :key="md.id" :class="{ 'sv-row--suspended': md.is_suspended }">
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
                <td style="text-align:center;font-variant-numeric:tabular-nums">
                  {{ fmtMailSize(md.mail_used_mb) }}
                </td>
                <td style="text-align:center">
                  <i v-if="md.dkim_enabled" class="bi bi-shield-check" style="color:var(--success);font-size:1.1rem" title="DKIM activo"></i>
                  <i v-else class="bi bi-shield-x" style="color:var(--text-muted);font-size:1.1rem" title="DKIM inactivo"></i>
                </td>
                <td style="text-align:center">
                  <div style="display:inline-flex;gap:.4rem;align-items:center">
                    <span class="ssl-chip" :class="md.webmail_ssl ? 'ssl-chip--on' : 'ssl-chip--off'"
                          :title="'webmail.' + md.domain_name + (md.webmail_ssl ? ': SSL emitido' : ': sin SSL')">
                      <i class="bi" :class="md.webmail_ssl ? 'bi-lock-fill' : 'bi-unlock'"></i> webmail
                    </span>
                    <span class="ssl-chip" :class="md.mail_ssl ? 'ssl-chip--on' : 'ssl-chip--off'"
                          :title="'mail.' + md.domain_name + (md.mail_ssl ? ': SSL emitido' : ': sin SSL')">
                      <i class="bi" :class="md.mail_ssl ? 'bi-lock-fill' : 'bi-unlock'"></i> mail
                    </span>
                  </div>
                </td>
                <td style="font-size:.85rem;color:var(--text-muted)">{{ md.catch_all || '—' }}</td>
                <td style="text-align:center">
                  <span v-if="md.is_suspended" class="sv-badge sv-badge--suspended">
                    <i class="bi bi-pause-circle-fill"></i> Suspendido
                  </span>
                  <span v-else class="sv-badge" :class="md.is_active ? 'sv-badge--on' : 'sv-badge--off'">
                    {{ md.is_active ? 'Activo' : 'Inactivo' }}
                  </span>
                </td>
                <td style="text-align:right">
                  <div style="display:flex;gap:6px;justify-content:flex-end">
                    <button class="sv-icon-btn" @click="openDetail(md)" title="Gestionar">
                      <i class="bi bi-gear"></i>
                    </button>
                    <button v-if="!md.is_suspended" class="sv-icon-btn sv-icon-btn--warn"
                            @click="suspendMailDomain(md)" title="Suspender el correo de este dominio">
                      <i class="bi bi-pause-circle"></i>
                    </button>
                    <button v-else class="sv-icon-btn sv-icon-btn--ok"
                            @click="unsuspendMailDomain(md)" title="Reactivar el correo">
                      <i class="bi bi-play-circle"></i>
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
    </template>

    <!-- ══════════ DETALLE DE DOMINIO ══════════ -->
    <template v-else>

      <!-- Contadores rápidos -->
      <div class="sv-counters">
        <div class="sv-counter">
          <span class="sv-counter-val" style="color:var(--ac)">{{ mailboxes.length }}</span>
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

                    <!-- Métrica: espacio -->
                    <div class="mbx__metric">
                      <div class="mbx__metric-row">
                        <i class="bi bi-hdd"></i>
                        <span class="mbx__metric-label">Espacio</span>
                        <span class="mbx__metric-val">
                          <template v-if="mb.quota_mb === 0">{{ fmtMB(mb.disk_usage_mb) }} · sin límite</template>
                          <template v-else>
                            {{ fmtMB(mb.disk_usage_mb) }} / {{ fmtMB(mb.quota_mb) }}
                            <span class="mbx__pct" :class="usageClass(mb)">{{ usagePct(mb) }}%</span>
                          </template>
                        </span>
                      </div>
                      <div v-if="mb.quota_mb > 0" class="mbx__bar">
                        <div class="mbx__bar-fill" :class="usageClass(mb)" :style="{ width: Math.min(usagePct(mb),100) + '%' }"></div>
                      </div>
                    </div>

                    <!-- Métrica: envío -->
                    <div class="mbx__metric">
                      <div class="mbx__metric-row">
                        <i class="bi bi-send"></i>
                        <span class="mbx__metric-label">Envío/h</span>
                        <span class="mbx__metric-val">
                          <template v-if="mb.send_limit_hour === 0">sin límite</template>
                          <template v-else-if="sendUsage[mb.id] != null">
                            {{ sendUsage[mb.id].sent }} / {{ mb.send_limit_hour }}
                            <span class="mbx__pct" :class="sendClass(mb)">{{ sendPct(mb) }}%</span>
                          </template>
                          <template v-else>
                            máx. {{ mb.send_limit_hour }}
                            <button class="mbx__inline-link" :disabled="loadingSend" @click="loadSendUsage(mb.mail_domain_id)">
                              {{ loadingSend ? '…' : 'ver uso' }}
                            </button>
                          </template>
                        </span>
                      </div>
                      <div v-if="mb.send_limit_hour > 0 && sendUsage[mb.id] != null" class="mbx__bar">
                        <div class="mbx__bar-fill" :class="sendClass(mb)" :style="{ width: Math.min(sendPct(mb),100) + '%' }"></div>
                      </div>
                    </div>
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
                  <button class="mbx__btn" @click="openEditMailbox(mb)" title="Editar cuota y límite de envío"><i class="bi bi-sliders"></i></button>
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
                    <span v-if="webmailSslIssuing" class="sv-spin"></span>
                    <i v-else class="bi bi-lock"></i>
                    {{ webmailSslIssuing ? 'Emitiendo…' : 'Activar HTTPS (Let\'s Encrypt)' }}
                  </button>
                  <!-- Progreso real del job de emisión (fases + salida de certbot) -->
                  <div v-if="webmailSslIssuing && !webmailSslJob" class="sv-ssl-progress">
                    <span class="sv-spin sv-spin--lg"></span>
                    <div><strong>Iniciando la emisión…</strong></div>
                  </div>
                  <div v-if="webmailSslJob" class="sv-ssl-progress sv-ssl-progress--steps">
                    <div class="sv-ssl-steps">
                      <div v-for="(s, i) in webmailSslJob.steps" :key="i" class="sv-ssl-step" :class="'is-' + webmailSslStepState(i)">
                        <i v-if="webmailSslStepState(i) === 'done'" class="bi bi-check-circle-fill"></i>
                        <i v-else-if="webmailSslStepState(i) === 'failed'" class="bi bi-x-circle-fill"></i>
                        <span v-else-if="webmailSslStepState(i) === 'running'" class="sv-spin" style="margin:0"></span>
                        <i v-else class="bi bi-circle"></i>
                        <span>{{ s }}</span>
                      </div>
                    </div>
                    <div v-if="webmailSslJob.status === 'running' && webmailSslJob.detail" class="sv-ssl-step-live" :title="webmailSslJob.detail">
                      {{ webmailSslJob.detail }}
                    </div>
                    <div v-if="webmailSslJob.status === 'failed'" class="sv-ssl-step-error">
                      <strong><i class="bi bi-x-circle-fill"></i> La emisión falló</strong>
                      <pre class="sv-ssl-error-text">{{ webmailSslJob.error }}</pre>
                    </div>
                    <div v-if="webmailSslJob.status === 'running'" style="font-size:.75rem;color:var(--text-muted)">
                      Suele tardar ~30 segundos. Puedes salir de esta página: la emisión continúa en el servidor.
                    </div>
                  </div>
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
              <button v-if="relayForm.enabled || relay.enabled"
                      class="sv-btn sv-btn--sm" :disabled="relaySaving"
                      :class="relayForm.enabled ? 'sv-btn--primary' : 'sv-btn--danger'"
                      @click="saveDomainRelay">
                <span v-if="relaySaving" class="spinner-border spinner-border-sm"></span>
                <i v-else :class="relayForm.enabled ? 'bi bi-save' : 'bi bi-x-circle'"></i>
                {{ relayForm.enabled ? 'Guardar relay' : 'Desactivar relay' }}
              </button>

              <!-- ── IP de salida del correo ── -->
              <div v-if="outIp" style="margin-top:2rem;border-top:1px solid var(--border);padding-top:1.5rem">
                <h6 style="font-weight:600;font-size:.95rem;margin-bottom:.5rem">IP de salida del correo</h6>
                <p style="font-size:.85rem;color:var(--text-muted);margin-bottom:1rem">
                  Por qué IP sale el correo de este dominio al enviarlo directo (sin relay).
                </p>
                <div class="sv-info-box" style="display:flex;gap:.5rem;align-items:stretch;flex-wrap:wrap">
                  <button class="sv-btn sv-btn--sm" style="flex-direction:column;align-items:flex-start;gap:.15rem;text-align:left"
                          :class="outIp.pref==='ipv4' ? 'sv-btn--primary' : 'sv-btn--ghost'"
                          :disabled="outIpSaving || outIp.pref==='ipv4'" @click="setOutIp('ipv4')">
                    <span><i class="bi bi-shield-check"></i> Predeterminada (recomendada)</span>
                    <small style="font-weight:400;opacity:.8">
                      <template v-if="outIpV4Dedicated">IPv4 dedicada del dominio + IPv6 del servidor:</template>
                      <template v-else>IP del servidor — PTR/SPF/DKIM ya OK<template v-if="outIpV4 || outIp.server_ipv6">:</template></template>
                    </small>
                    <small v-if="outIpV4" style="font-weight:400;opacity:.85">IPv4 <code>{{ outIpV4 }}</code><template v-if="outIpV4Dedicated"> (dedicada)</template></small>
                    <small v-if="outIp.server_ipv6" style="font-weight:400;opacity:.85">IPv6 <code>{{ outIp.server_ipv6 }}</code></small>
                  </button>
                  <button class="sv-btn sv-btn--sm" style="flex-direction:column;align-items:flex-start;gap:.15rem;text-align:left"
                          :class="outIp.pref==='ipv6' ? 'sv-btn--primary' : 'sv-btn--ghost'"
                          :disabled="outIpSaving || !outIp.ipv6_available || outIp.pref==='ipv6'"
                          :title="!outIp.ipv6_available ? 'El dominio no tiene IPv6 asignada' : ''"
                          @click="setOutIp('ipv6')">
                    <span><i class="bi bi-hdd-network"></i> IPv6 dedicada del dominio</span>
                    <small v-if="outIp.ipv6" style="font-weight:400;opacity:.8"><code>{{ outIp.ipv6 }}</code> — requiere PTR</small>
                    <small v-else style="font-weight:400;opacity:.8">Sin IPv6 asignada</small>
                  </button>
                </div>
                <div v-if="!outIp.ipv6_available" class="sv-alert sv-alert--muted" style="margin-top:.75rem;font-size:.82rem">
                  El correo sale por la <strong>IP del servidor</strong> (con PTR/SPF/DKIM correctos).
                  Para enviar por la IPv6 dedicada del dominio, actívala primero en la pestaña del dominio.
                </div>
                <div v-else-if="outIp.pref==='ipv6'" class="sv-alert sv-alert--warn" style="margin-top:.75rem;font-size:.82rem">
                  <i class="bi bi-exclamation-triangle"></i>
                  El correo sale por la <strong>IPv6 dedicada</strong>. Debes configurar su
                  <strong>rDNS (PTR)</strong> con tu proveedor, o Gmail/Outlook lo rechazarán
                  (550 5.7.25). Si no lo controlas, usa la opción <strong>Predeterminada</strong>.
                </div>
                <div v-else class="sv-alert sv-alert--muted" style="margin-top:.75rem;font-size:.82rem">
                  <template v-if="outIpV4Dedicated">
                    El correo sale por la <strong>IPv4 dedicada del dominio</strong>
                    (<code>{{ outIpV4 }}</code>)<template v-if="outIp.server_ipv6"> y, hacia destinos IPv6,
                    por la IPv6 del servidor (<code>{{ outIp.server_ipv6 }}</code>)</template>.
                    Recuerda que el <strong>PTR de la IP dedicada</strong> corre de tu cuenta
                    (debe apuntar a <code>mail.{{ outIp.domain }}</code>) y que su SPF la autorice.
                  </template>
                  <template v-else>
                    El correo sale por la <strong>IP del servidor</strong><template v-if="outIpV4 || outIp.server_ipv6">
                      (<template v-if="outIpV4">IPv4 <code>{{ outIpV4 }}</code></template><template v-if="outIpV4 && outIp.server_ipv6"> · </template><template v-if="outIp.server_ipv6">IPv6 <code>{{ outIp.server_ipv6 }}</code></template>)</template>,
                    que ya tiene PTR/SPF/DKIM. Es lo recomendado salvo que necesites una IP de envío propia (y controles su PTR).
                  </template>
                </div>
              </div>
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

            <!-- Lista gris (greylisting) -->
            <div>
              <h6 style="font-weight:600;font-size:.95rem;margin-bottom:.6rem">
                <i class="bi bi-hourglass-split" style="color:var(--warning)"></i> Lista gris (greylisting)
              </h6>
              <p style="font-size:.83rem;color:var(--text-muted);margin-bottom:.8rem">
                El greylisting rechaza temporalmente el primer intento de correos desconocidos
                (el servidor legítimo reintenta a los minutos). Frena mucho spam, pero
                <strong>retrasa</strong> la primera entrega. Desactívalo si este dominio necesita
                recibir al instante (confirmaciones, códigos 2FA…). El resto del filtrado anti-spam no cambia.
              </p>
              <div v-if="greylist.global_enabled === false" class="sv-info-box" style="margin-bottom:.8rem">
                <i class="bi bi-info-circle"></i> El greylisting está <strong>desactivado a nivel de servidor</strong>, así que ya no se aplica a ningún dominio.
              </div>
              <label class="form-check form-switch" style="display:flex;align-items:center;gap:.6rem">
                <input class="form-check-input" type="checkbox" :checked="greylist.enabled"
                       :disabled="greylistSaving || greylist.global_enabled === false"
                       @change="toggleGreylist($event.target.checked)" />
                <span>{{ greylist.enabled ? 'Activado para este dominio' : 'Desactivado (entrega inmediata)' }}</span>
                <span v-if="greylistSaving" class="spinner-border spinner-border-sm"></span>
              </label>
            </div>

            <div style="border-top:1px solid var(--border)"></div>

            <!-- Mover spam a Junk (por dominio) -->
            <div>
              <h6 style="font-weight:600;font-size:.95rem;margin-bottom:.4rem">
                <i class="bi bi-inboxes" style="color:var(--warning)"></i> Mover spam a la carpeta Junk
              </h6>
              <p style="font-size:.83rem;color:var(--text-muted);margin-bottom:.8rem">
                Cuando un correo se detecta como spam (sin llegar a ser rechazado), se entrega en
                la carpeta <strong>Junk</strong> en vez de la bandeja de entrada. Desactívalo si este
                dominio prefiere recibir todo en la bandeja y filtrar por su cuenta. El rechazo de
                spam evidente no cambia.
              </p>
              <div v-if="spamJunk.global_enabled === false" class="sv-info-box" style="margin-bottom:.8rem">
                <i class="bi bi-info-circle"></i> El envío de spam a Junk está <strong>desactivado a nivel de servidor</strong>, así que no se aplica a ningún dominio.
              </div>
              <label class="form-check form-switch" style="display:flex;align-items:center;gap:.6rem">
                <input class="form-check-input" type="checkbox" :checked="spamJunk.enabled"
                       :disabled="spamJunkSaving || spamJunk.global_enabled === false"
                       @change="toggleSpamJunk($event.target.checked)" />
                <span>{{ spamJunk.enabled ? 'Activado para este dominio' : 'Desactivado (el spam llega a la bandeja)' }}</span>
                <span v-if="spamJunkSaving" class="spinner-border spinner-border-sm"></span>
              </label>
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

            <!-- Antivirus ClamAV -->
            <div style="margin-top:1.5rem">
              <h6 style="font-weight:600;font-size:.95rem;margin-bottom:1rem"><i class="bi bi-bug" style="color:var(--svq-orange)"></i> Antivirus de correo (ClamAV)</h6>
              <div v-if="antivirus" class="sv-info-box">
                <!-- Modo por dominio (Rspamd) -->
                <div v-if="antivirus.per_domain" style="display:flex;justify-content:space-between;align-items:flex-start">
                  <div>
                    <div style="font-weight:600">Escaneo de adjuntos</div>
                    <p style="font-size:.85rem;color:var(--text-muted);margin:.25rem 0 0">
                      Analiza los adjuntos del correo entrante y <strong>rechaza</strong> los que contengan malware.
                    </p>
                  </div>
                  <label class="form-switch" style="margin:0;flex-shrink:0">
                    <input class="form-check-input" type="checkbox" :checked="antivirus.enabled"
                           :disabled="antivirusSaving"
                           @change="toggleAntivirus($event.target.checked)" style="width:3em;height:1.5em;cursor:pointer">
                  </label>
                </div>
                <!-- Modo global (clamav-milter, sin SSSE3) -->
                <div v-else-if="antivirus.method === 'milter'">
                  <div style="font-weight:600">Escaneo de adjuntos (global)</div>
                  <p style="font-size:.85rem;color:var(--text-muted);margin:.25rem 0 .25rem">
                    Este servidor escanea el correo con ClamAV de forma <strong>global</strong> (no por dominio).
                    Se gestiona desde <strong>Administración → Seguridad</strong>.
                  </p>
                </div>
                <!-- No disponible -->
                <p v-else style="font-size:.85rem;color:var(--warning);margin:0">
                  <i class="bi bi-exclamation-triangle"></i> ClamAV no está disponible en el servidor.
                </p>
                <p v-if="antivirusSaving" style="font-size:.85rem;color:var(--text-muted);margin:.5rem 0 0">
                  <span class="spinner-border spinner-border-sm"></span> Aplicando…
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
              <!-- Propietario: obligatorio para admin/reseller -->
              <div v-if="isAdminOrReseller" class="mb-3">
                <label class="form-label">Usuario (cliente propietario) <span class="text-danger">*</span></label>
                <select class="form-select" v-model.number="newDomainForm.user_id" required>
                  <option :value="null">Selecciona un cliente</option>
                  <option v-for="u in clientUsers" :key="u.id" :value="u.id">
                    {{ u.username }} ({{ u.email }})
                  </option>
                </select>
                <div v-if="clientUsers.length === 0" class="form-text text-warning">
                  No hay cuentas de cliente. El dominio de correo pertenece a un cliente,
                  no al administrador; crea primero un usuario en la sección Usuarios.
                </div>
                <div v-else class="form-text">El dominio de correo se asignará a este cliente.</div>
              </div>
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
                <PasswordField v-model="newMailboxForm.password" placeholder="Contraseña del buzón" />
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
              <PasswordField v-model="newPassword" placeholder="Nueva contraseña del buzón" />
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

    <!-- ══════════ Modal: Editar buzón (cuota + límite envío) ══════════ -->
    <div v-if="showEditModal" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.5)" @click.self="showEditModal = false">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-sliders me-2"></i>Editar buzón
              <small class="text-muted fw-normal"> — {{ editTarget?.full_email }}</small>
            </h5>
            <button class="btn-close" @click="showEditModal = false"></button>
          </div>
          <form @submit.prevent="saveEditMailbox">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Cuota (MB)</label>
                <select class="form-select" v-model.number="editForm.quota_mb">
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
                <select class="form-select" v-model.number="editForm.send_limit_hour">
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
              <button type="button" class="btn btn-secondary" @click="showEditModal = false">Cancelar</button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
                Guardar cambios
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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import PasswordField from '../components/PasswordField.vue'

export default {
  name: 'Mail',
  components: { PasswordField },
  setup() {
    const store = useMainStore()

    // ── Estado principal ──────────────────────────────────────────────
    const mailEnabled    = ref(null)   // null=cargando, true/false
    const mailDomains    = ref([])
    const mailSearch     = ref('')
    const filteredMailDomains = computed(() => {
      const q = mailSearch.value.trim().toLowerCase()
      if (!q) return mailDomains.value
      return (mailDomains.value || []).filter(md =>
        (md.domain_name || '').toLowerCase().includes(q))
    })
    const selectedDomain = ref(null)
    const activeTab      = ref('mailboxes')
    const loading        = ref(false)

    // ── Usuarios (para asignar propietario al crear dominio de correo) ──
    const users = ref([])
    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role) || store.currentUser?.is_admin
    )
    // Las cuentas de correo son de clientes, nunca del admin
    const clientUsers = computed(() =>
      users.value.filter(u => u.role !== 'admin' && !u.is_admin)
    )
    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return
      try {
        const data = await api.getUsers(0, 1000)
        users.value = Array.isArray(data) ? data : []
      } catch (e) { /* no bloqueante */ }
    }

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
    const greylist       = ref({ enabled: true, global_enabled: true })
    const greylistSaving = ref(false)
    const spamJunk       = ref({ enabled: true, global_enabled: true })
    const spamJunkSaving = ref(false)
    const globalGreylist = ref(true)
    const globalGreylistSaving = ref(false)
    const globalSpamJunk = ref(true)
    const globalSpamJunkSaving = ref(false)
    const savingSettings = ref(false)

    // ── Modales ───────────────────────────────────────────────────────
    const showNewDomain    = ref(false)
    const showNewMailbox   = ref(false)
    const showPasswordModal= ref(false)
    const showNewAlias     = ref(false)
    const showForwardModal  = ref(false)
    const showAutoreplyModal = ref(false)
    const showEditModal    = ref(false)
    const deleteTarget     = ref(null)
    const saving           = ref(false)
    const showPwd          = ref(false)

    // ── Formularios ───────────────────────────────────────────────────
    const newDomainForm  = ref({ domain_name: '', catch_all: '', max_mailboxes: 0, user_id: null })
    const newMailboxForm = ref({ username: '', password: '', quota_mb: 1024, send_limit_hour: 200 })
    const newAliasForm   = ref({ source: '', destination: '' })
    const passwordTarget  = ref(null)
    const newPassword     = ref('')
    const forwardTarget   = ref(null)
    const forwardForm     = ref({ forward_to_text: '', forward_keep_copy: true })
    const autoreplyTarget = ref(null)
    const autoreplyForm   = ref({ autoreply_enabled: false, autoreply_subject: '', autoreply_body: '' })
    const editTarget      = ref(null)
    const editForm        = ref({ quota_mb: 1024, send_limit_hour: 200 })

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

    const suspendMailDomain = async (md) => {
      if (!confirm(`¿Suspender el correo de "${md.domain_name}"? Todos sus buzones dejarán de recibir/enviar (los emails se conservan). Reversible.`)) return
      try {
        await api.post(`/api/mail/domains/${md.id}/suspend`, {})
        store.showNotification('Correo suspendido', 'success')
        loadDomains()
      } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
    }
    const unsuspendMailDomain = async (md) => {
      try {
        await api.post(`/api/mail/domains/${md.id}/unsuspend`, {})
        store.showNotification('Correo reactivado', 'success')
        loadDomains()
      } catch (e) { store.showNotification('Error: ' + (e.message || e), 'danger') }
    }

    const loadDomains = async () => {
      loading.value = true
      try {
        mailDomains.value = await api.getMailDomains()
        mailEnabled.value = true
        // Estado del greylisting global (solo admin lo ve/cambia).
        if (isAdminOrReseller.value) {
          try { globalGreylist.value = (await api.getGlobalGreylisting()).enabled } catch { /* */ }
          try { globalSpamJunk.value = (await api.getGlobalSpamToJunk()).enabled } catch { /* */ }
        }
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

    const toggleGlobalGreylist = async (enabled) => {
      globalGreylistSaving.value = true
      try {
        await api.setGlobalGreylisting(enabled)
        globalGreylist.value = enabled
        store.showNotification(
          enabled ? 'Greylisting global activado'
                  : 'Greylisting global desactivado (entrega inmediata para todos)', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally { globalGreylistSaving.value = false }
    }

    const toggleGlobalSpamJunk = async (enabled) => {
      globalSpamJunkSaving.value = true
      try {
        await api.setGlobalSpamToJunk(enabled)
        globalSpamJunk.value = enabled
        store.showNotification(
          enabled ? 'Spam → carpeta Junk activado'
                  : 'Spam → Junk desactivado (el spam llegará a la bandeja)', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally { globalSpamJunkSaving.value = false }
    }

    // ── Salud de correo del servidor (deliverability de reenvíos) ──
    const deliv = reactive({ open: false, loading: false, error: '', data: null, genDkim: false })

    const delivStatusColor = computed(() => {
      if (!deliv.data) return 'var(--text-muted)'
      return deliv.data.all_ok ? 'var(--success)' : 'var(--warning)'
    })

    const loadDeliverability = async () => {
      deliv.loading = true; deliv.error = ''
      try {
        deliv.data = await api.getServerDeliverability()
        deliv.open = true
      } catch (e) {
        deliv.error = e.message || String(e)
      } finally { deliv.loading = false }
    }

    const generateServerDkim = async () => {
      deliv.genDkim = true
      try {
        await api.generateServerDkim()
        store.showNotification('Clave DKIM del servidor generada. Publica el TXT en tu DNS.', 'success')
        await loadDeliverability()
      } catch (e) {
        store.showNotification('Error generando DKIM: ' + (e.message || e), 'danger')
      } finally { deliv.genDkim = false }
    }

    const loadMailboxes = async (domainId) => {
      loadingMailboxes.value = true
      sendUsage.value = {}   // el uso de envío es por dominio; resetear al recargar
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
      antivirus.value = null
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
        await loadAntivirus(selectedDomain.value.id)
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
    // IP de salida del correo (IPv4/IPv6) del dominio
    const outIp        = ref(null)
    const outIpSaving  = ref(false)
    // IPv4 EFECTIVA de salida: si el dominio tiene IPv4 dedicada, Postfix hace
    // bind por ella aunque la preferencia sea "Predeterminada" — mostrar la del
    // servidor aquí sería mentir (visto con globatel.es y su IP dedicada).
    const outIpV4 = computed(() => outIp.value?.ipv4 || outIp.value?.server_ipv4 || '')
    const outIpV4Dedicated = computed(() =>
      !!(outIp.value?.ipv4 && outIp.value.ipv4 !== outIp.value.server_ipv4))

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

    // ── Antivirus ClamAV por dominio ──
    const antivirus       = ref(null)
    const antivirusSaving = ref(false)
    const loadAntivirus = async (domainId) => {
      try {
        antivirus.value = await api.getMailAntivirus(domainId)
      } catch (e) {
        antivirus.value = null
      }
    }
    const toggleAntivirus = async (enabled) => {
      antivirusSaving.value = true
      try {
        await api.setMailAntivirus(selectedDomain.value.id, enabled)
        store.showNotification(enabled ? 'Antivirus activado' : 'Antivirus desactivado', 'success')
        await loadAntivirus(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
        await loadAntivirus(selectedDomain.value.id)
      } finally {
        antivirusSaving.value = false
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
      // Cargar la preferencia de IP de salida (no bloquea el relay si falla)
      try {
        outIp.value = await api.get(`/api/mail/domains/${domainId}/out-ip`)
      } catch (e) {
        outIp.value = null
      }
    }

    const setOutIp = async (pref) => {
      if (!outIp.value || outIp.value.pref === pref) return
      outIpSaving.value = true
      try {
        const r = await api.post(`/api/mail/domains/${selectedDomain.value.id}/out-ip`, { pref })
        store.showNotification('IP de salida del correo actualizada', 'success')
        if (r && r.warning) store.showNotification(r.warning, 'warning')
        await loadRelay(selectedDomain.value.id)
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally {
        outIpSaving.value = false
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
      // Si hay una emisión SSL en curso (p. ej. se recargó la página a mitad,
      // o se cambió de dominio y se volvió), retomar checklist y polling.
      try {
        if (!webmailSslIssuing.value) {
          webmailSslJob.value = null   // no arrastrar el job de otro dominio
          const r = await api.getWebmailSslProgress(domainId)
          if (r.job?.status === 'running') {
            webmailSslIssuing.value = true
            webmailSslJob.value = r.job
            pollWebmailSsl(domainId)
          }
        }
      } catch { /* sin job previo */ }
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

    // Emisión con progreso real: POST lanza el job y aquí se hace polling
    // cada 2s (fases + última línea de certbot). Mismo patrón que SSLManager.
    const webmailSslJob = ref(null)
    let webmailSslPollAlive = false
    const _sleep = (ms) => new Promise(r => setTimeout(r, ms))

    const webmailSslStepState = (i) => {
      const j = webmailSslJob.value
      if (!j) return 'pending'
      if (j.status === 'success' || i < j.current) return 'done'
      if (i === j.current) return j.status === 'failed' ? 'failed' : 'running'
      return 'pending'
    }

    const pollWebmailSsl = async (domainId) => {
      webmailSslPollAlive = true
      while (webmailSslPollAlive) {
        await _sleep(2000)
        if (!webmailSslPollAlive) return
        try {
          const r = await api.getWebmailSslProgress(domainId)
          if (r.job) webmailSslJob.value = r.job
        } catch { /* transitorio */ }
        const st = webmailSslJob.value?.status
        if (st === 'success') {
          webmailSslIssuing.value = false
          webmailSslJob.value = null
          store.showNotification('HTTPS activado en el webmail', 'success')
          await loadWebmail(domainId)
          return
        }
        if (st === 'failed') {
          webmailSslIssuing.value = false  // el error queda visible en el checklist
          return
        }
      }
    }

    const issueWebmailSsl = async () => {
      webmailSslIssuing.value = true
      webmailSslJob.value = null
      try {
        const r = await api.issueWebmailSsl(selectedDomain.value.id)
        webmailSslJob.value = r.job
        await pollWebmailSsl(selectedDomain.value.id)
      } catch (e) {
        webmailSslIssuing.value = false
        store.showNotification('No se pudo iniciar la emisión: ' + (e.message || e), 'danger')
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Dominio de correo
    // ─────────────────────────────────────────────────────────────────

    const fmtMailSize = (mb) => {
      if (mb == null) return '—'        // sin dato
      if (mb === 0) return '0 MB'       // vacío real (no "—")
      return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
    }

    const openNewDomain = () => {
      newDomainForm.value = { domain_name: '', catch_all: '', max_mailboxes: 0, user_id: null }
      showNewDomain.value = true
    }

    const createDomain = async () => {
      // Admin/reseller debe asignar el dominio a un cliente (no al admin)
      if (isAdminOrReseller.value && !newDomainForm.value.user_id) {
        store.showNotification('Selecciona el usuario propietario del dominio de correo', 'danger')
        return
      }
      saving.value = true
      try {
        const payload = { ...newDomainForm.value }
        if (!payload.catch_all) delete payload.catch_all
        if (!payload.user_id) delete payload.user_id
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
      // Estado del greylisting del dominio (+ si está activo a nivel servidor).
      try { greylist.value = await api.getMailGreylist(domainId) } catch { /* */ }
      // Estado de 'mover spam a Junk' del dominio.
      try { spamJunk.value = await api.getMailSpamToJunk(domainId) } catch { /* */ }
    }

    const toggleGreylist = async (enabled) => {
      greylistSaving.value = true
      try {
        await api.setMailGreylist(selectedDomain.value.id, enabled)
        greylist.value = { ...greylist.value, enabled }
        store.showNotification(
          enabled ? 'Lista gris activada para este dominio'
                  : 'Lista gris desactivada (entrega inmediata)', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally { greylistSaving.value = false }
    }

    const toggleSpamJunk = async (enabled) => {
      spamJunkSaving.value = true
      try {
        await api.setMailSpamToJunk(selectedDomain.value.id, enabled)
        spamJunk.value = { ...spamJunk.value, enabled }
        store.showNotification(
          enabled ? 'Spam → Junk activado para este dominio'
                  : 'Spam → Junk desactivado (el spam llega a la bandeja)', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || e), 'danger')
      } finally { spamJunkSaving.value = false }
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
        store.showNotification('Buzón creado', 'success')
        await loadMailboxes(selectedDomain.value.id)
        await loadDomains()
        showNewMailbox.value = false
        newMailboxForm.value = { username: '', password: '', quota_mb: 1024, send_limit_hour: 200 }
        showPwd.value = false
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

    // ── Uso de disco del buzón ──
    const fmtMB = (mb) => {
      const v = Number(mb) || 0
      if (v >= 1024) return (v / 1024).toFixed(v % 1024 === 0 ? 0 : 1) + ' GB'
      return Math.round(v) + ' MB'
    }
    const usagePct = (mb) => {
      if (!mb.quota_mb) return 0
      return Math.round((Number(mb.disk_usage_mb) || 0) / mb.quota_mb * 100)
    }
    const usageClass = (mb) => {
      const p = usagePct(mb)
      if (p >= 90) return 'is-danger'
      if (p >= 75) return 'is-warn'
      return 'is-ok'
    }

    // ── Uso de envío en la última hora (bajo demanda) ──
    const sendUsage = ref({})       // { mailbox_id: {sent, limit} }
    const loadingSend = ref(false)
    const loadSendUsage = async (domainId) => {
      const did = domainId || selectedDomain.value?.id
      if (!did) return
      loadingSend.value = true
      try {
        const r = await api.getMailSendUsage(did)
        const map = {}
        for (const it of (r.data || [])) map[it.mailbox_id] = { sent: it.sent_last_hour, limit: it.send_limit_hour }
        sendUsage.value = map
      } catch (e) {
        store.showNotification('No pude leer el uso de envío: ' + e.message, 'danger')
      } finally { loadingSend.value = false }
    }
    const sendPct = (mb) => {
      const u = sendUsage.value[mb.id]
      if (!u || !mb.send_limit_hour) return 0
      return Math.round(u.sent / mb.send_limit_hour * 100)
    }
    const sendClass = (mb) => {
      const p = sendPct(mb)
      if (p >= 90) return 'is-danger'
      if (p >= 75) return 'is-warn'
      return 'is-ok'
    }

    // ─────────────────────────────────────────────────────────────────
    // Editar buzón (cuota + límite de envío)
    // ─────────────────────────────────────────────────────────────────
    const openEditMailbox = (mb) => {
      editTarget.value = mb
      editForm.value = {
        quota_mb: mb.quota_mb ?? 1024,
        send_limit_hour: mb.send_limit_hour ?? 200,
      }
      showEditModal.value = true
    }

    const saveEditMailbox = async () => {
      saving.value = true
      try {
        await api.updateMailbox(selectedDomain.value.id, editTarget.value.id, {
          quota_mb: editForm.value.quota_mb,
          send_limit_hour: editForm.value.send_limit_hour,
        })
        showEditModal.value = false
        store.showNotification('Buzón actualizado', 'success')
        await loadMailboxes(selectedDomain.value.id)
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
      loadUsers()
    })
    onUnmounted(() => { webmailSslPollAlive = false })

    return {
      isAdminOrReseller, clientUsers, fmtMailSize,
      mailEnabled, mailDomains, mailSearch, filteredMailDomains, selectedDomain, activeTab, loading,
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
      showEditModal, editTarget, editForm, openEditMailbox, saveEditMailbox,
      fmtMB, usagePct, usageClass,
      sendUsage, loadingSend, loadSendUsage, sendPct, sendClass,
      // Roundcube
      roundcubeEnabled, roundcubeUrl, openingWebmail,
      // Webmail por dominio
      webmail, loadingWebmail, webmailSaving, webmailSslIssuing,
      webmailSslJob, webmailSslStepState,
      loadWebmail, toggleWebmail, issueWebmailSsl,
      relay, relayForm, loadingRelay, relaySaving, loadRelay, saveDomainRelay,
      outIp, outIpSaving, setOutIp, outIpV4, outIpV4Dedicated,
      mailtls, mailtlsSaving, toggleMailTls,
      antivirus, antivirusSaving, toggleAntivirus,
      // Monitoreo de envío
      mailLogs, loadingLogs, logFilter, logFilters,
      loadMailLogs, filteredLogEvents, logBadge, logLabel,
      loadDomains, openDetail, switchTab, suspendMailDomain, unsuspendMailDomain,
      openNewDomain, createDomain, saveSettings,
      loadSpamSettings, saveSpamSettings,
      greylist, greylistSaving, toggleGreylist,
      spamJunk, spamJunkSaving, toggleSpamJunk,
      globalGreylist, globalGreylistSaving, toggleGlobalGreylist,
      globalSpamJunk, globalSpamJunkSaving, toggleGlobalSpamJunk,
      deliv, delivStatusColor, loadDeliverability, generateServerDkim,
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
.sv-title > .bi:first-child { color:var(--svq-orange); }
.sv-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }
.sv-head-actions { display:flex; gap:8px; flex-shrink:0; align-items:center; }
.mail-search { position:relative; display:flex; align-items:center; }
.mail-search i { position:absolute; left:.6rem; color:var(--text-muted); pointer-events:none; font-size:.85rem; }
.mail-search .svq-input { padding-left:1.9rem; min-width:200px; }
.sv-breadcrumb { display:flex; align-items:center; gap:8px; margin-bottom:.5rem; font-size:.875rem; }
.sv-chevron { color:var(--text-muted); font-size:.75rem; }
.sv-domain-name { font-weight:600; }
.sv-back-btn { background:none; border:1px solid var(--border); border-radius:var(--radius-sm,6px); padding:.25rem .75rem; font-size:.82rem; cursor:pointer; color:var(--text-secondary); transition:all .15s; }
.sv-back-btn:hover { background:var(--surface-2); color:var(--text); }

/* ── Botones ── */
.sv-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--radius-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.sv-btn--primary { background:var(--ac); color:#fff; border-color:var(--ac); }
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
.sv-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); background:var(--surface-inset); }
.sv-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
.sv-card-title > .bi:first-child { color:var(--svq-orange); }
.sv-count { background:var(--surface-2); border:1px solid var(--border); border-radius:999px; padding:.1rem .5rem; font-size:.75rem; font-weight:600; }

/* ── Badges ── */
.sv-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }
.sv-badge--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.sv-badge--off { background:var(--surface-2); color:var(--text-muted); }
.sv-badge--blue { background:color-mix(in srgb,var(--ac) 15%,transparent); color:var(--ac); }
.sv-badge--teal { background:color-mix(in srgb,var(--info,#06b6d4) 15%,transparent); color:var(--info,#06b6d4); }
.ssl-chip { display:inline-flex; align-items:center; gap:3px; padding:.12rem .4rem; border-radius:999px;
  font-size:.7rem; font-weight:600; white-space:nowrap; }
.ssl-chip--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.ssl-chip--off { background:var(--surface-2); color:var(--text-muted); }
.sv-badge--suspended { background:color-mix(in srgb,var(--warning) 18%,transparent); color:var(--warning); display:inline-flex; align-items:center; gap:4px; }
.sv-row--suspended > td { background:color-mix(in srgb,var(--warning) 7%,transparent); }
.sv-icon-btn--warn:hover { color:var(--warning); border-color:var(--warning); }
.sv-icon-btn--ok { color:var(--success); }
.sv-icon-btn--ok:hover { border-color:var(--success); }
/* Spinner propio (no depende del bootstrap-compat) para que SIEMPRE se vea */
.sv-spin { display:inline-block; width:.9rem; height:.9rem; vertical-align:-2px; margin-right:.4rem;
  border:2px solid currentColor; border-right-color:transparent; border-radius:50%; animation:sv-spin-kf .7s linear infinite; }
.sv-spin--lg { width:1.4rem; height:1.4rem; border-width:3px; color:var(--ac); margin:0; }
@keyframes sv-spin-kf { to { transform:rotate(360deg); } }
.sv-ssl-progress { display:flex; align-items:center; gap:.75rem; margin-top:.7rem; padding:.7rem 1rem;
  border-radius:var(--r-md,10px); background:color-mix(in srgb,var(--ac) 8%,transparent);
  border:1px solid color-mix(in srgb,var(--ac) 25%,transparent); }
/* Checklist de fases reales del job de emisión SSL del webmail */
.sv-ssl-progress--steps { flex-direction:column; align-items:stretch; gap:.55rem; }
.sv-ssl-steps { display:flex; flex-direction:column; gap:.45rem; }
.sv-ssl-step { display:flex; align-items:center; gap:.55rem; font-size:.85rem; color:var(--text-muted); }
.sv-ssl-step i { font-size:.95rem; }
.sv-ssl-step.is-done    { color:var(--success); }
.sv-ssl-step.is-running { color:var(--text-primary,inherit); font-weight:500; }
.sv-ssl-step.is-failed  { color:var(--danger); }
.sv-ssl-step .sv-spin   { flex-shrink:0; }
.sv-ssl-step-live { font-size:.72rem; color:var(--text-muted); background:var(--surface-2);
  border-radius:6px; padding:.35rem .55rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  font-family:var(--font-mono,monospace); }
.sv-ssl-step-error { font-size:.82rem; color:var(--danger); }
.sv-ssl-error-text { white-space:pre-wrap; word-break:break-word; margin:.35rem 0 0;
  font-size:.72rem; color:var(--danger); max-height:180px; overflow:auto; }
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
.sv-tab-count { background:var(--ac); color:#fff; border-radius:999px; font-size:.68rem; padding:.1rem .4rem; line-height:1.4; }
.sv-tab-body { padding:1.25rem; }
.sv-tab-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; }
.sv-tab-section-title { font-weight:600; font-size:.95rem; }

/* ── Formularios ── */
.sv-form-grid { display:grid; grid-template-columns:1fr 1fr; gap:.875rem; }
.sv-field { display:flex; flex-direction:column; gap:.35rem; }
.sv-field label { font-size:.82rem; font-weight:600; color:var(--text-secondary); }
.sv-field--full { grid-column:1/-1; }
.sv-field--full .sv-btn { width:fit-content; }
.sv-input-copy { display:flex; align-items:stretch; gap:0; border:1px solid var(--border); border-radius:var(--radius-sm,6px); overflow:hidden; }
.sv-input-label { padding:.4rem .65rem; background:var(--surface-2); color:var(--text-muted); font-size:.78rem; display:flex; align-items:center; white-space:nowrap; border-right:1px solid var(--border); }
.sv-input-copy .form-control { border:none; border-radius:0; flex:1; }
.sv-input-copy .sv-icon-btn { border:none; border-left:1px solid var(--border); border-radius:0; width:36px; }
.sv-input-suffix { display:flex; align-items:center; padding:.4rem .65rem; background:var(--surface-2); border:1px solid var(--border); border-left:none; border-radius:0 var(--radius-sm,6px) var(--radius-sm,6px) 0; font-size:.82rem; color:var(--text-muted); }

/* ── Alertas e info ── */
.sv-alert { display:flex; align-items:flex-start; gap:.5rem; padding:.65rem .85rem; border-radius:var(--radius-sm,6px); font-size:.875rem; }
.sv-alert--success { background:color-mix(in srgb,var(--success) 10%,transparent); color:var(--success); border:1px solid color-mix(in srgb,var(--success) 25%,transparent); }
/* Warning: texto en color normal (legible) — solo el icono y el borde en naranja,
   para que el cuerpo del mensaje tenga contraste suficiente sobre el fondo claro. */
.sv-alert--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 12%,var(--surface)); color:var(--text); border:1px solid color-mix(in srgb,var(--warning,#f59e0b) 40%,transparent); }
.sv-alert--warn > .bi:first-child, .sv-alert--warn i.bi { color:var(--warning,#d97706); }
.sv-alert--info { background:color-mix(in srgb,var(--ac) 8%,var(--surface)); color:var(--text); border:1px solid color-mix(in srgb,var(--ac) 25%,transparent); }
.sv-alert--muted { background:var(--surface-2); color:var(--text); border:1px solid var(--border); }
/* <code> dentro de alerts/botones de esta vista: fondo y color con contraste
   garantizado (el <code> global es de acento y quedaba ilegible sobre estos
   fondos). En el botón primario (azul), texto blanco sobre velo oscuro. */
.sv-alert code, .sv-info-box code {
  background:color-mix(in srgb,var(--text) 12%,transparent);
  color:var(--text); padding:.05rem .35rem; border-radius:4px;
  font-family:var(--font-mono,monospace); font-size:.9em;
}
.sv-btn--primary code {
  background:rgba(255,255,255,.22); color:#fff;
  padding:.05rem .35rem; border-radius:4px;
}
.sv-btn--ghost code {
  background:color-mix(in srgb,var(--text) 10%,transparent); color:var(--text);
  padding:.05rem .35rem; border-radius:4px;
}
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
.mbx__id { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 6px; }
.mbx__email { font-weight: var(--fw-semibold); color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* Métricas (espacio / envío): etiqueta a la izquierda, valor a la derecha, barra debajo */
.mbx__metric { display: flex; flex-direction: column; gap: 3px; }
.mbx__metric-row { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); color: var(--text-muted); }
.mbx__metric-row > .bi { font-size: 13px; width: 14px; text-align: center; flex-shrink: 0; }
.mbx__metric-label { flex-shrink: 0; }
.mbx__metric-val { margin-left: auto; text-align: right; color: var(--text); white-space: nowrap; }
.mbx__pct { font-weight: var(--fw-semibold); margin-left: 4px; }
.mbx__pct.is-ok { color: var(--text-muted); }
.mbx__pct.is-warn { color: var(--warning); }
.mbx__pct.is-danger { color: var(--danger); }
.mbx__bar { height: 5px; border-radius: 999px; background: var(--surface-inset); overflow: hidden; }
.mbx__bar-fill { height: 100%; border-radius: 999px; transition: width .3s ease; background: var(--svq-orange); }
.mbx__bar-fill.is-ok { background: var(--success, #2ea043); }
.mbx__bar-fill.is-warn { background: var(--warning); }
.mbx__bar-fill.is-danger { background: var(--danger); }
.mbx__inline-link { background: none; border: none; padding: 0 0 0 4px; color: var(--accent, var(--svq-orange)); cursor: pointer; font-size: inherit; text-decoration: underline; }
.mbx__inline-link:disabled { opacity: .5; cursor: default; }
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
.mbx__btn--active { background: color-mix(in srgb, var(--ac) 10%, transparent); color: var(--ac); border-color: color-mix(in srgb, var(--ac) 30%, transparent); }
</style>
