<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="sec-head">
      <div>
        <h2 class="sec-title"><i class="bi bi-shield-lock"></i> Seguridad</h2>
        <p class="sec-subtitle">Firewall (nftables), fail2ban, listas IP, conexiones y auditoría</p>
      </div>
      <div class="sec-head-right">
        <div class="sec-score" v-if="fwStatus || f2bStatus">
          <svg viewBox="0 0 60 60" class="sec-score__ring">
            <circle cx="30" cy="30" r="26" class="sec-score__track" />
            <circle cx="30" cy="30" r="26" class="sec-score__fill"
                    :stroke="scoreColor" :stroke-dasharray="scoreDash" />
            <text x="30" y="34" class="sec-score__num">{{ securityScore }}</text>
          </svg>
          <div class="sec-score__meta">
            <span class="sec-score__label" :style="{ color: scoreColor }">Postura {{ scoreLabel }}</span>
            <span class="sec-score__sub">de 100 puntos</span>
          </div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <span v-if="fwStatus" class="sec-badge" :class="fwStatus.table_present ? 'sec-badge--on' : 'sec-badge--danger'">
            nftables {{ fwStatus.table_present ? 'activo' : 'inactivo' }}
          </span>
          <span v-if="f2bStatus" class="sec-badge" :class="f2bStatus.running ? 'sec-badge--on' : 'sec-badge--warn'">
            fail2ban {{ f2bStatus.running ? 'ok' : 'parado' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Contadores -->
    <div class="sv-counters" v-if="fwStatus">
      <div class="sec-counter"><div class="sec-counter-val">{{ fwStatus.rule_count }}</div><div class="sec-counter-lbl">Reglas activas</div></div>
      <div class="sec-counter"><div class="sec-counter-val">{{ fwStatus.whitelist_count }}</div><div class="sec-counter-lbl">Whitelist</div></div>
      <div class="sec-counter"><div class="sec-counter-val">{{ fwStatus.banned_count }}</div><div class="sec-counter-lbl">IPs baneadas</div></div>
      <div class="sec-counter"><div class="sec-counter-val">{{ f2bStatus?.jails?.length || 0 }}</div><div class="sec-counter-lbl">Jails fail2ban</div></div>
    </div>

    <!-- Aislamiento PHP -->
    <div class="sec-card iso-card" :class="isoCardTone">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
        <div style="display:flex;gap:.75rem;align-items:flex-start">
          <div class="iso-icon" :class="isoCardTone">
            <i class="bi" :class="isoAllOk ? 'bi-shield-fill-check' : 'bi-shield-fill-exclamation'"></i>
          </div>
          <div>
            <div style="font-weight:600;font-size:1rem;margin-bottom:.25rem">Aislamiento PHP por dominio</div>
            <p style="font-size:.82rem;color:var(--text-muted);margin:0 0 .5rem;max-width:560px">
              Cada dominio debe tener un pool PHP-FPM con <code>open_basedir</code> para que su PHP no pueda leer archivos de otros clientes.
            </p>
            <div v-if="isoLoading" style="font-size:.82rem;color:var(--text-muted)">
              <span class="spinner-border spinner-border-sm"></span> Auditando…
            </div>
            <div v-else-if="isoAudit" style="display:flex;gap:6px;flex-wrap:wrap">
              <span class="sec-badge sec-badge--on">{{ isoAudit.secure }} protegidos</span>
              <span class="sec-badge" :class="isoAudit.insecure ? 'sec-badge--danger' : 'sec-badge--off'">{{ isoAudit.insecure }} desprotegidos</span>
              <span class="sec-badge sec-badge--off">{{ isoAudit.total }} dominios</span>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0">
          <button class="sec-btn sec-btn--ghost sec-btn--sm" @click="loadIsolation" :disabled="isoLoading || isoRepairing">
            <i class="bi bi-arrow-repeat"></i> Reauditar
          </button>
          <button v-if="isoAudit && isoAudit.insecure > 0" class="sec-btn sec-btn--danger sec-btn--sm" @click="repairIsolation" :disabled="isoRepairing">
            <span v-if="isoRepairing" class="spinner-border spinner-border-sm"></span>
            <i v-else class="bi bi-wrench-adjustable"></i> Reparar {{ isoAudit.insecure }}
          </button>
        </div>
      </div>
      <div v-if="isoAudit && isoAudit.insecure > 0" class="iso-issues" style="margin-top:1rem">
        <div v-for="d in isoInsecureList" :key="d.domain" class="iso-issue">
          <span class="iso-issue__domain"><i class="bi bi-globe2"></i>{{ d.domain }}</span>
          <span class="iso-issue__owner">{{ d.owner }}</span>
          <span class="iso-issue__msg">{{ d.issues[0] }}</span>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="sec-tabs">
      <button v-for="t in [
        {key:'firewall',    icon:'brick',          label:'Firewall'},
        {key:'fail2ban',    icon:'lock',            label:'Fail2ban'},
        {key:'iplists',     icon:'list-task',       label:'Listas IP'},
        {key:'crowdsec',    icon:'shield-check',    label:'CrowdSec'},
        {key:'connections', icon:'broadcast',       label:'Conexiones'},
        {key:'audit',       icon:'journal-text',    label:'Auditoría'},
        {key:'badbots',     icon:'robot',           label:'Bad Bots'},
      ]" :key="t.key"
        class="sec-tab" :class="{'sec-tab--active': tab===t.key}"
        @click="changeTab(t.key)">
        <i :class="'bi bi-'+t.icon"></i> {{ t.label }}
      </button>
    </div>

    <!-- Firewall -->
    <div v-if="tab==='firewall'" style="display:flex;flex-direction:column;gap:16px">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title"><i class="bi bi-hdd-network"></i> Puertos del sistema</span>
          <span v-if="sysPorts.policy" class="sec-badge" :class="sysPorts.policy==='drop'?'sec-badge--on':'sec-badge--warn'">
            Política: {{ sysPorts.policy==='drop' ? 'DROP (seguro)' : sysPorts.policy }}
          </span>
        </div>
        <div class="sec-card-body">
          <p class="sec-hint">Puertos abiertos de serie. Política <strong>DROP</strong> = todo lo demás bloqueado.</p>
          <div v-if="!sysPorts.available" class="sec-hint">No se pudo leer el firewall del sistema.</div>
          <div v-else style="display:flex;flex-wrap:wrap;gap:6px">
            <span v-for="p in sysPorts.ports" :key="p.proto+p.port" class="sec-badge sec-badge--off">
              <i class="bi bi-door-open"></i>{{ p.port }}/{{ p.proto }}
              <span v-if="p.service !== '—'" style="color:var(--text-muted)">· {{ p.service }}</span>
            </span>
          </div>
        </div>
      </div>

      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title">Reglas personalizadas</span>
          <div style="display:flex;gap:6px">
            <button class="sec-icon-btn" @click="loadFirewall"><i class="bi bi-arrow-clockwise"></i></button>
            <button class="sec-btn sec-btn--success sec-btn--sm" @click="openRuleForm()">
              <i class="bi bi-plus-lg"></i> Nueva regla
            </button>
          </div>
        </div>
        <div v-if="loadingFw" class="sec-loading"><div class="spinner-border spinner-border-sm"></div></div>
        <div v-else-if="!rules.length" class="sec-empty"><i class="bi bi-shield"></i><span>No hay reglas.</span></div>
        <div v-else class="sec-table-wrap">
          <table class="sec-table">
            <thead><tr><th>Prio</th><th>Acción</th><th>Proto</th><th>Puerto</th><th>Origen</th><th>Whitelist</th><th>Activa</th><th>Descripción</th><th style="text-align:right">Acciones</th></tr></thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ r.priority }}</td>
                <td><span class="sec-badge" :class="ruleActionBadge(r.action)">{{ r.action }}</span></td>
                <td style="font-family:var(--font-mono)">{{ r.protocol }}</td>
                <td style="font-family:var(--font-mono)">{{ r.port_range || '*' }}</td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ r.source_ip || 'any' }}</td>
                <td><span v-if="r.is_whitelist" class="sec-badge sec-badge--blue">whitelist</span></td>
                <td><span class="sec-badge" :class="r.is_active?'sec-badge--on':'sec-badge--off'">{{ r.is_active?'sí':'no' }}</span></td>
                <td style="font-size:.8rem;color:var(--text-muted)">{{ r.description || '—' }}</td>
                <td style="text-align:right">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="sec-icon-btn" @click="openRuleForm(r)"><i class="bi bi-pencil"></i></button>
                    <button class="sec-icon-btn sec-icon-btn--danger" @click="deleteRule(r)"><i class="bi bi-trash"></i></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Fail2ban -->
    <div v-if="tab==='fail2ban'" class="sec-2col">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title">Jails</span>
          <button class="sec-icon-btn" @click="loadFail2ban"><i class="bi bi-arrow-clockwise"></i></button>
        </div>
        <div class="sec-table-wrap">
          <table class="sec-table">
            <thead><tr><th>Jail</th><th>Failed</th><th>Banned</th><th style="text-align:right">Acción</th></tr></thead>
            <tbody>
              <tr v-for="j in jails" :key="j.name">
                <td><strong>{{ j.name }}</strong></td>
                <td>{{ j.currently_failed }} / {{ j.total_failed }}</td>
                <td>{{ j.currently_banned }} / {{ j.total_banned }}</td>
                <td style="text-align:right">
                  <button class="sec-icon-btn" @click="toggleJail(j, false)" title="Deshabilitar"><i class="bi bi-pause-fill"></i></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">IPs baneadas</span>
            <button class="sec-btn sec-btn--success sec-btn--sm" @click="openManualBan"><i class="bi bi-plus-lg"></i> Banear IP</button>
          </div>
          <div v-if="!banned.length" class="sec-empty"><i class="bi bi-unlock"></i><span>No hay IPs baneadas.</span></div>
          <div v-else class="sec-table-wrap">
            <table class="sec-table">
              <thead><tr><th>IP</th><th>Jail</th><th>Por</th><th style="text-align:right">Acción</th></tr></thead>
              <tbody>
                <tr v-for="b in banned" :key="(b.jail||'-')+b.ip">
                  <td style="font-family:var(--font-mono)">{{ b.ip }}</td>
                  <td>{{ b.jail || '—' }}</td>
                  <td>{{ b.banned_by }}</td>
                  <td style="text-align:right">
                    <button class="sec-icon-btn" @click="unbanIp(b)" title="Desbanear"><i class="bi bi-unlock"></i></button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">Whitelist permanente</span>
            <button class="sec-btn sec-btn--success sec-btn--sm" @click="openAddIgnore"><i class="bi bi-plus-lg"></i> Añadir IP</button>
          </div>
          <div class="sec-card-body">
            <div v-if="!ignoreip.length" class="sec-hint">Vacío.</div>
            <div v-else style="display:flex;flex-wrap:wrap;gap:6px">
              <span v-for="ip in ignoreip" :key="ip" class="sec-badge sec-badge--blue" style="gap:6px">
                {{ ip }}
                <button type="button" style="background:none;border:none;cursor:pointer;color:inherit;padding:0;font-size:.7rem;line-height:1" @click="removeIgnore(ip)">✕</button>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- IP Lists -->
    <div v-if="tab==='iplists'">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title"><i class="bi bi-list-task"></i> Listas IP desde URL</span>
          <div style="display:flex;gap:6px">
            <button class="sec-icon-btn" @click="loadIpLists"><i class="bi bi-arrow-clockwise"></i></button>
            <button class="sec-btn sec-btn--success sec-btn--sm" @click="openIpListForm()"><i class="bi bi-plus-lg"></i> Nueva lista</button>
          </div>
        </div>
        <div v-if="!ipLists.length" class="sec-empty"><i class="bi bi-list-task"></i><span>No hay listas.</span></div>
        <div v-else class="sec-table-wrap">
          <table class="sec-table">
            <thead><tr><th>Nombre</th><th>Acción</th><th>Familia</th><th>Entradas</th><th>Última act.</th><th>Estado</th><th style="text-align:right">Acciones</th></tr></thead>
            <tbody>
              <tr v-for="l in ipLists" :key="l.id">
                <td>
                  <strong>{{ l.name }}</strong>
                  <div style="font-size:.75rem;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="l.url">{{ l.url }}</div>
                </td>
                <td><span class="sec-badge" :class="l.action==='allow'?'sec-badge--on':'sec-badge--danger'">{{ l.action }}</span></td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ l.address_family }}</td>
                <td>
                  <span class="sec-badge sec-badge--off">{{ l.entry_count_v4 }} v4</span>
                  <span class="sec-badge sec-badge--off" style="margin-left:3px">{{ l.entry_count_v6 }} v6</span>
                </td>
                <td style="font-size:.8rem">{{ l.last_success_at ? formatDate(l.last_success_at) : '—' }}</td>
                <td>
                  <span class="sec-badge" :class="l.last_error?'sec-badge--warn':l.enabled?'sec-badge--on':'sec-badge--off'">
                    {{ l.last_error ? '⚠ error' : l.enabled ? 'OK' : 'deshabilitada' }}
                  </span>
                </td>
                <td style="text-align:right">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="sec-icon-btn" @click="refreshIpList(l)" title="Refrescar"><i class="bi bi-arrow-repeat"></i></button>
                    <button class="sec-icon-btn" @click="openIpListForm(l)" title="Editar"><i class="bi bi-pencil"></i></button>
                    <button class="sec-icon-btn sec-icon-btn--danger" @click="deleteIpList(l)" title="Eliminar"><i class="bi bi-trash"></i></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- CrowdSec -->
    <div v-if="tab==='crowdsec'" style="display:flex;flex-direction:column;gap:16px">
      <div v-if="csStatus && !csStatus.installed" class="sec-alert sec-alert--warn">
        <i class="bi bi-exclamation-triangle-fill"></i>
        <div><strong>CrowdSec no está instalado.</strong> Vuelve a ejecutar el instalador con CrowdSec activado.</div>
      </div>
      <div v-else-if="csStatus && !csStatus.running" class="sec-alert sec-alert--danger">
        <i class="bi bi-x-octagon-fill"></i>
        <div><strong>CrowdSec instalado pero no está corriendo.</strong> Revisa <code>journalctl -u crowdsec</code>.</div>
      </div>

      <div v-if="csStatus && csStatus.running" class="sv-counters">
        <div class="sec-counter"><div class="sec-counter-val" style="font-family:var(--font-mono);font-size:1.2rem">{{ csStatus.version || '—' }}</div><div class="sec-counter-lbl">Versión</div></div>
        <div class="sec-counter"><div class="sec-counter-val">{{ csStatus.decisions }}</div><div class="sec-counter-lbl">Decisiones</div></div>
        <div class="sec-counter"><div class="sec-counter-val">{{ csStatus.bouncers }}</div><div class="sec-counter-lbl">Bouncers</div></div>
        <div class="sec-counter"><div class="sec-counter-val">{{ csStatus.collections }}</div><div class="sec-counter-lbl">Colecciones</div></div>
      </div>

      <div v-if="csStatus && csStatus.running">
        <div class="sec-tabs" style="margin-bottom:16px">
          <button v-for="t in [{key:'decisions',icon:'slash-circle',label:'Decisiones'},{key:'alerts',icon:'bell',label:'Alertas'},{key:'bouncers',icon:'shield-shaded',label:'Bouncers'},{key:'collections',icon:'collection',label:'Colecciones'}]"
                  :key="t.key" class="sec-tab" :class="{'sec-tab--active':csTab===t.key}" @click="changeCsTab(t.key)">
            <i :class="'bi bi-'+t.icon"></i> {{ t.label }}
          </button>
        </div>

        <div v-if="csTab==='decisions'" class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">Decisiones activas</span>
            <div style="display:flex;gap:6px">
              <button class="sec-icon-btn" @click="loadCsDecisions"><i class="bi bi-arrow-clockwise"></i></button>
              <button class="sec-btn sec-btn--success sec-btn--sm" @click="openCsBan"><i class="bi bi-plus-lg"></i> Decisión manual</button>
            </div>
          </div>
          <div v-if="!csDecisions.length" class="sec-empty"><i class="bi bi-shield-check"></i><span>No hay decisiones activas.</span></div>
          <div v-else class="sec-table-wrap">
            <table class="sec-table">
              <thead><tr><th>IP / valor</th><th>Tipo</th><th>Escenario</th><th>Origen</th><th>Duración</th><th>País</th><th style="text-align:right">Acción</th></tr></thead>
              <tbody>
                <tr v-for="d in csDecisions" :key="d.id">
                  <td style="font-family:var(--font-mono)">{{ d.value }}</td>
                  <td><span class="sec-badge" :class="d.type==='ban'?'sec-badge--danger':'sec-badge--warn'">{{ d.type }}</span></td>
                  <td style="font-size:.8rem">{{ d.scenario || '—' }}</td>
                  <td style="font-size:.8rem">{{ d.origin || '—' }}</td>
                  <td style="font-family:var(--font-mono);font-size:.8rem">{{ d.duration || '—' }}</td>
                  <td style="font-size:.8rem">{{ d.country || '—' }}</td>
                  <td style="text-align:right"><button class="sec-icon-btn" @click="deleteCsDecision(d)" title="Eliminar"><i class="bi bi-unlock"></i></button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="csTab==='alerts'" class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">Alertas recientes</span>
            <button class="sec-icon-btn" @click="loadCsAlerts"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
          <div v-if="!csAlerts.length" class="sec-empty"><i class="bi bi-bell"></i><span>No hay alertas.</span></div>
          <div v-else class="sec-table-wrap">
            <table class="sec-table">
              <thead><tr><th>Fecha</th><th>IP origen</th><th>Escenario</th><th>Eventos</th><th>País</th><th>Mensaje</th></tr></thead>
              <tbody>
                <tr v-for="a in csAlerts" :key="a.id">
                  <td style="font-size:.8rem">{{ formatDate(a.created_at) }}</td>
                  <td style="font-family:var(--font-mono);font-size:.8rem">{{ a.source_ip || '—' }}</td>
                  <td style="font-size:.8rem">{{ a.scenario }}</td>
                  <td style="text-align:center;font-size:.8rem">{{ a.events_count || 0 }}</td>
                  <td style="font-size:.8rem">{{ a.source_country || '—' }}</td>
                  <td style="font-size:.8rem;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="a.message">{{ a.message || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="csTab==='bouncers'" class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">Bouncers registrados</span>
            <button class="sec-icon-btn" @click="loadCsBouncers"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
          <div v-if="!csBouncers.length" class="sec-empty"><i class="bi bi-shield-shaded"></i><span>No hay bouncers.</span></div>
          <div v-else class="sec-table-wrap">
            <table class="sec-table">
              <thead><tr><th>Nombre</th><th>Tipo</th><th>Versión</th><th>IP</th><th>Último pull</th><th>Estado</th></tr></thead>
              <tbody>
                <tr v-for="b in csBouncers" :key="b.name">
                  <td><strong>{{ b.name }}</strong></td>
                  <td style="font-family:var(--font-mono);font-size:.8rem">{{ b.type || '—' }}</td>
                  <td style="font-size:.8rem">{{ b.version || '—' }}</td>
                  <td style="font-family:var(--font-mono);font-size:.8rem">{{ b.ip_address || '—' }}</td>
                  <td style="font-size:.8rem">{{ formatDate(b.last_pull) }}</td>
                  <td><span class="sec-badge" :class="b.revoked?'sec-badge--danger':'sec-badge--on'">{{ b.revoked ? 'revoked' : 'activo' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="csTab==='collections'" class="sec-card">
          <div class="sec-card-head">
            <span class="sec-card-title">Colecciones instaladas</span>
            <button class="sec-icon-btn" @click="loadCsCollections"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
          <div v-if="!csCollections.length" class="sec-empty"><i class="bi bi-collection"></i><span>No hay colecciones.</span></div>
          <div v-else class="sec-table-wrap">
            <table class="sec-table">
              <thead><tr><th>Nombre</th><th>Versión</th><th>Estado</th><th>Descripción</th></tr></thead>
              <tbody>
                <tr v-for="c in csCollections" :key="c.name">
                  <td style="font-family:var(--font-mono);font-size:.8rem">{{ c.name }}</td>
                  <td style="font-size:.8rem">{{ c.version || '—' }}</td>
                  <td style="font-size:.8rem">{{ c.status || '—' }}</td>
                  <td style="font-size:.8rem;color:var(--text-muted)">{{ c.description || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Conexiones -->
    <div v-if="tab==='connections'">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title">{{ connListening ? 'Puertos en escucha (LISTEN)' : 'Conexiones activas' }}</span>
          <div style="display:flex;gap:6px;align-items:center">
            <div style="display:flex;border:1px solid var(--border);border-radius:var(--r-sm,6px);overflow:hidden">
              <button class="sec-btn sec-btn--sm" :class="!connListening?'sec-btn--primary':'sec-btn--ghost'" style="border-radius:0;border:none" @click="connListening=false;loadConnections()">Activas</button>
              <button class="sec-btn sec-btn--sm" :class="connListening?'sec-btn--primary':'sec-btn--ghost'" style="border-radius:0;border:none;border-left:1px solid var(--border)" @click="connListening=true;loadConnections()">LISTEN</button>
            </div>
            <button class="sec-icon-btn" @click="loadConnections"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
        </div>
        <div v-if="!connections.length" class="sec-empty"><i class="bi bi-broadcast"></i><span>Sin datos.</span></div>
        <div v-else class="sec-table-wrap">
          <table class="sec-table">
            <thead><tr><th>Proto</th><th>Estado</th><th>Local</th><th>Remoto</th><th>Proceso</th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in connections" :key="i">
                <td style="font-family:var(--font-mono)">{{ c.protocol }}</td>
                <td><span class="sec-badge sec-badge--off">{{ c.state }}</span></td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ c.local_addr }}:{{ c.local_port }}</td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ c.remote_addr }}:{{ c.remote_port }}</td>
                <td style="font-size:.85rem">{{ c.process || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Auditoría -->
    <div v-if="tab==='audit'">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title"><i class="bi bi-journal-text"></i> Auditoría de seguridad</span>
          <div style="display:flex;gap:6px;align-items:center">
            <select v-model="auditCategory" @change="loadAudit" class="form-select form-select-sm" style="width:160px">
              <option value="">Todas</option>
              <option value="firewall">firewall</option>
              <option value="fail2ban">fail2ban</option>
              <option value="iplist">iplist</option>
              <option value="whitelist">whitelist</option>
            </select>
            <button class="sec-icon-btn" @click="loadAudit"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
        </div>
        <div v-if="!audit.length" class="sec-empty"><i class="bi bi-journal-text"></i><span>No hay eventos.</span></div>
        <div v-else class="sec-table-wrap">
          <table class="sec-table">
            <thead><tr><th>Fecha</th><th>Usuario</th><th>Categoría</th><th>Acción</th><th>Target</th><th>IP origen</th><th>OK</th></tr></thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id" :style="!a.success ? 'background:color-mix(in srgb,var(--warning) 6%,transparent)' : ''">
                <td style="font-size:.8rem">{{ formatDate(a.created_at) }}</td>
                <td>{{ a.user_label || '—' }}</td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ a.category }}</td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ a.action }}</td>
                <td style="font-size:.8rem;color:var(--text-muted)">{{ a.target || '—' }}</td>
                <td style="font-family:var(--font-mono);font-size:.8rem">{{ a.ip_origin || '—' }}</td>
                <td>
                  <i v-if="a.success" class="bi bi-check-circle" style="color:var(--success)"></i>
                  <i v-else class="bi bi-x-circle" style="color:var(--danger)" :title="a.error"></i>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ Modal regla firewall ═══════════════════════════ -->
    <Modal :isOpen="showRuleForm" @close="showRuleForm=false" :title="ruleForm.id ? 'Editar regla' : 'Nueva regla'">
      <form @submit.prevent="saveRule">
        <div class="row g-2">
          <div class="col-md-4">
            <label class="form-label small">Acción</label>
            <select class="form-select form-select-sm" v-model="ruleForm.action" required>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
              <option value="reject">reject</option>
            </select>
          </div>
          <div class="col-md-4">
            <label class="form-label small">Protocolo</label>
            <select class="form-select form-select-sm" v-model="ruleForm.protocol">
              <option value="tcp">tcp</option>
              <option value="udp">udp</option>
              <option value="icmp">icmp</option>
              <option value="any">any</option>
            </select>
          </div>
          <div class="col-md-4">
            <label class="form-label small">Puerto (o rango)</label>
            <input class="form-control form-control-sm" v-model="ruleForm.port_range" placeholder="80 o 8000-9000">
          </div>
          <div class="col-md-6">
            <label class="form-label small">IP origen (CIDR)</label>
            <input class="form-control form-control-sm" v-model="ruleForm.source_ip" placeholder="1.2.3.4 o 10.0.0.0/8">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Prioridad</label>
            <input type="number" class="form-control form-control-sm" v-model.number="ruleForm.priority" min="1" max="10000">
          </div>
          <div class="col-md-3 d-flex align-items-end">
            <div class="form-check me-3">
              <input class="form-check-input" type="checkbox" v-model="ruleForm.is_whitelist" id="rf-wl">
              <label class="form-check-label small" for="rf-wl">Whitelist</label>
            </div>
            <div class="form-check">
              <input class="form-check-input" type="checkbox" v-model="ruleForm.is_active" id="rf-ac">
              <label class="form-check-label small" for="rf-ac">Activa</label>
            </div>
          </div>
          <div class="col-12">
            <label class="form-label small">Descripción</label>
            <input class="form-control form-control-sm" v-model="ruleForm.description" maxlength="255">
          </div>
        </div>
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showRuleForm=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
            Guardar y aplicar
          </button>
        </div>
      </form>
    </Modal>

    <!-- ═══════════════════════════ Modal lista IP ═══════════════════════════ -->
    <Modal :isOpen="showIpListForm" @close="showIpListForm=false" :title="ipListForm.id ? 'Editar lista' : 'Nueva lista IP'">
      <form @submit.prevent="saveIpList">
        <div class="row g-2">
          <div class="col-md-6">
            <label class="form-label small">Nombre (slug)</label>
            <input class="form-control form-control-sm" v-model="ipListForm.name"
                   :disabled="!!ipListForm.id" required pattern="^[a-z][a-z0-9_]+$">
            <div class="form-text small">a-z, 0-9, _ (no se puede cambiar después)</div>
          </div>
          <div class="col-md-3">
            <label class="form-label small">Acción</label>
            <select class="form-select form-select-sm" v-model="ipListForm.action">
              <option value="block">block</option>
              <option value="allow">allow</option>
            </select>
          </div>
          <div class="col-md-3">
            <label class="form-label small">Familia</label>
            <select class="form-select form-select-sm" v-model="ipListForm.address_family">
              <option value="both">ambas</option>
              <option value="ipv4">IPv4</option>
              <option value="ipv6">IPv6</option>
            </select>
          </div>
          <div class="col-12">
            <label class="form-label small">URL (http/https)</label>
            <input class="form-control form-control-sm" v-model="ipListForm.url" required type="url"
                   placeholder="https://raw.githubusercontent.com/...">
          </div>
          <div class="col-md-6">
            <label class="form-label small">Refresco (horas)</label>
            <input type="number" class="form-control form-control-sm" v-model.number="ipListForm.refresh_interval_hours" min="1" max="720">
          </div>
          <div class="col-md-6">
            <label class="form-label small">Máx. entradas</label>
            <input type="number" class="form-control form-control-sm" v-model.number="ipListForm.max_entries" min="1">
          </div>
          <div class="col-12">
            <label class="form-label small">Descripción</label>
            <input class="form-control form-control-sm" v-model="ipListForm.description" maxlength="255">
          </div>
          <div class="col-12">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" v-model="ipListForm.enabled" id="il-en">
              <label class="form-check-label small" for="il-en">Habilitada</label>
            </div>
          </div>
        </div>
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showIpListForm=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
            Guardar y aplicar
          </button>
        </div>
      </form>
    </Modal>

    <!-- ═══════════════════════════ Modal banear manual / añadir ignoreip ═══════════════════════════ -->
    <Modal :isOpen="showManualBan" @close="showManualBan=false" title="Banear IP manualmente">
      <form @submit.prevent="submitManualBan">
        <div class="row g-2">
          <div class="col-md-6">
            <label class="form-label small">IP</label>
            <input class="form-control form-control-sm" v-model="banForm.ip" required placeholder="1.2.3.4">
          </div>
          <div class="col-md-6">
            <label class="form-label small">Duración (s — vacío = permanente)</label>
            <input type="number" class="form-control form-control-sm" v-model.number="banForm.duration_seconds" min="60">
          </div>
          <div class="col-12">
            <label class="form-label small">Razón</label>
            <input class="form-control form-control-sm" v-model="banForm.reason" maxlength="255">
          </div>
        </div>
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showManualBan=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-danger" :disabled="saving">Banear</button>
        </div>
      </form>
    </Modal>

    <!-- ═══════════════════════════ Modal CrowdSec ban manual ═══════════════════════════ -->
    <Modal :isOpen="showCsBan" @close="showCsBan=false" title="Decisión manual CrowdSec">
      <form @submit.prevent="submitCsBan">
        <div class="row g-2">
          <div class="col-md-6">
            <label class="form-label small">IP o CIDR</label>
            <input class="form-control form-control-sm" v-model="csBanForm.ip" required placeholder="1.2.3.4 o 10.0.0.0/24">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Duración</label>
            <input class="form-control form-control-sm" v-model="csBanForm.duration" placeholder="4h, 1d, 30m">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Tipo</label>
            <select class="form-select form-select-sm" v-model="csBanForm.type">
              <option value="ban">ban</option>
              <option value="captcha">captcha</option>
            </select>
          </div>
          <div class="col-12">
            <label class="form-label small">Razón (escenario)</label>
            <input class="form-control form-control-sm" v-model="csBanForm.reason" maxlength="255" placeholder="manual / abuso reportado">
          </div>
        </div>
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showCsBan=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-danger" :disabled="saving">Crear decisión</button>
        </div>
      </form>
    </Modal>

    <Modal :isOpen="showAddIgnore" @close="showAddIgnore=false" title="Añadir IP a whitelist permanente">
      <form @submit.prevent="submitAddIgnore">
        <label class="form-label small">IP o CIDR</label>
        <input class="form-control form-control-sm" v-model="ignoreForm.ip" required placeholder="1.2.3.4 o 10.0.0.0/8">
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showAddIgnore=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="saving">Añadir</button>
        </div>
      </form>
    </Modal>

    <!-- Bad Bots -->
    <div v-if="tab==='badbots'">
      <div class="sec-card">
        <div class="sec-card-head">
          <span class="sec-card-title"><i class="bi bi-robot"></i> Bloqueo de User-Agents maliciosos</span>
          <button class="sec-btn sec-btn--primary sec-btn--sm" @click="saveBadBots" :disabled="botsSaving">
            <span v-if="botsSaving" class="spinner-border spinner-border-sm"></span>
            <i v-else class="bi bi-save"></i> Guardar y recargar nginx
          </button>
        </div>
        <div class="sec-card-body">
          <p class="sec-hint">Los user-agents activados se bloquean en nginx con HTTP 444 (cierra conexión sin respuesta).</p>
          <div v-if="botsLoading" class="sec-loading"><div class="spinner-border spinner-border-sm"></div></div>
          <div v-else style="display:flex;flex-direction:column;gap:1.25rem">
            <div>
              <div style="font-weight:600;font-size:.875rem;margin-bottom:.75rem">Bots conocidos</div>
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.75rem">
                <div v-for="bot in knownBots" :key="bot.id"
                     style="padding:.75rem;border-radius:var(--r-sm,6px);border:1px solid var(--border);cursor:pointer;transition:all .15s"
                     :style="bot.enabled ? 'border-color:var(--danger);background:color-mix(in srgb,var(--danger) 6%,transparent)' : ''"
                     @click="bot.enabled = !bot.enabled">
                  <div style="display:flex;gap:.5rem;align-items:flex-start">
                    <input class="form-check-input" type="checkbox" :id="'bot-'+bot.id" v-model="bot.enabled" @click.stop style="flex-shrink:0;margin-top:.15rem" />
                    <label :for="'bot-'+bot.id" style="cursor:pointer;flex:1">
                      <div style="font-weight:600;font-size:.875rem">{{ bot.label }}</div>
                      <div style="font-size:.75rem;color:var(--text-muted)">{{ bot.description }}</div>
                      <code style="font-size:.72rem">~*{{ bot.pattern }}</code>
                    </label>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div style="font-weight:600;font-size:.875rem;margin-bottom:.75rem">Patrones personalizados</div>
              <div style="display:flex;flex-direction:column;gap:.4rem;max-width:420px">
                <div v-for="(p, i) in customPatterns" :key="i" style="display:flex;gap:.4rem;align-items:center">
                  <span style="font-family:var(--font-mono);font-size:.85rem;color:var(--text-muted)">~*</span>
                  <input v-model="customPatterns[i]" type="text" class="form-control form-control-sm font-monospace" placeholder="patron-del-bot" style="flex:1" />
                  <button class="sec-icon-btn sec-icon-btn--danger" type="button" @click="customPatterns.splice(i,1)"><i class="bi bi-trash"></i></button>
                </div>
                <button class="sec-btn sec-btn--ghost sec-btn--sm" style="align-self:flex-start;margin-top:.25rem" @click="customPatterns.push('')">
                  <i class="bi bi-plus"></i> Añadir patrón
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'
import Modal from '../components/Modal.vue'

// ─── State ──────────────────────────────────────────────────────────────────
const tab = ref('firewall')

const fwStatus  = ref(null)
const f2bStatus = ref(null)

// ─── Aislamiento PHP (open_basedir por dominio) ──────────────────────────────
const isoAudit     = ref(null)
const isoLoading   = ref(false)
const isoRepairing = ref(false)

const isoAllOk = computed(() => !isoAudit.value || isoAudit.value.all_ok)
const isoCardTone = computed(() => {
  if (!isoAudit.value) return ''
  return isoAudit.value.insecure > 0 ? 'is-danger' : 'is-ok'
})
const isoInsecureList = computed(() =>
  (isoAudit.value?.domains || []).filter(d => !d.ok))

async function loadIsolation() {
  isoLoading.value = true
  try { isoAudit.value = await api.auditPhpIsolation() }
  catch (e) { console.error('Error auditando aislamiento:', e) }
  finally { isoLoading.value = false }
}

async function repairIsolation() {
  if (!confirm('Se reescribirán los pools PHP-FPM de los dominios desprotegidos para aplicar open_basedir y el hardening. ¿Continuar?')) return
  isoRepairing.value = true
  try {
    const r = await api.repairPhpIsolation()
    alert(`Reparados ${r.repaired} de ${r.attempted} dominio(s).` + (r.failed ? ` ${r.failed} fallaron.` : ''))
    await loadIsolation()
  } catch (e) {
    alert('Error reparando: ' + e.message)
  } finally {
    isoRepairing.value = false
  }
}

// ─── Score de seguridad (derivado de datos ya cargados) ──────────────────────
const securityScore = computed(() => {
  let score = 0
  const fw = fwStatus.value, f2b = f2bStatus.value
  if (fw?.table_present) score += 35                         // firewall activo
  // La política por defecto la reporta /firewall/system-ports (sysPorts.policy),
  // no /firewall/status. 'drop' = cierra todo lo no permitido (más seguro).
  if (sysPorts.value?.policy === 'drop') score += 15
  if ((fw?.whitelist_count || 0) > 0) score += 10            // whitelist configurada
  if ((fw?.rule_count || 0) > 0) score += 10                 // reglas definidas
  if (f2b?.running) score += 25                              // fail2ban activo
  if ((f2b?.jails?.length || 0) > 0) score += 5              // jails activos
  return Math.min(100, score)
})
const scoreTone = computed(() =>
  securityScore.value >= 80 ? 'success' : securityScore.value >= 50 ? 'warning' : 'danger')
const scoreLabel = computed(() =>
  securityScore.value >= 80 ? 'Buena' : securityScore.value >= 50 ? 'Mejorable' : 'Débil')
const scoreColor = computed(() => `var(--${scoreTone.value})`)
const scoreDash = computed(() => {
  const c = 2 * Math.PI * 26
  return `${c * securityScore.value / 100} ${c}`
})

const rules     = ref([])
const loadingFw = ref(false)
const sysPorts  = ref({ available: false, policy: null, ports: [] })

const jails    = ref([])
const banned   = ref([])
const ignoreip = ref([])

const ipLists       = ref([])

const connections   = ref([])
const connListening = ref(true)

const audit         = ref([])
const auditCategory = ref('')

// CrowdSec
const csStatus      = ref(null)
const csTab         = ref('decisions')
const csDecisions   = ref([])
const csAlerts      = ref([])
const csBouncers    = ref([])
const csCollections = ref([])
const showCsBan     = ref(false)
const csBanForm     = ref({ ip: '', duration: '4h', reason: '', type: 'ban' })

const saving = ref(false)

// Modals
const showRuleForm   = ref(false)
const showIpListForm = ref(false)
const showManualBan  = ref(false)
const showAddIgnore  = ref(false)

const ruleForm   = ref(emptyRule())
const ipListForm = ref(emptyIpList())
const banForm    = ref({ ip: '', duration_seconds: null, reason: '' })
const ignoreForm = ref({ ip: '' })

function emptyRule() {
  return {
    id: null, action: 'allow', protocol: 'tcp',
    port_range: '', source_ip: '', description: '',
    is_whitelist: false, priority: 100, is_active: true,
  }
}

function emptyIpList() {
  return {
    id: null, name: '', description: '', url: '',
    action: 'block', address_family: 'both',
    refresh_interval_hours: 24, max_entries: 500000,
    enabled: true,
  }
}

function ruleActionBadge(action) {
  return { allow: 'bg-success', deny: 'bg-danger', reject: 'bg-warning text-dark' }[action] || 'bg-secondary'
}

function formatDate(s) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

// ─── Loaders ────────────────────────────────────────────────────────────────
async function loadStatus() {
  try { fwStatus.value  = await api.getFirewallStatus() } catch (e) { console.error(e) }
  try { f2bStatus.value = await api.getFail2banStatus() } catch (e) { console.error(e) }
}

async function loadFirewall() {
  loadingFw.value = true
  try { rules.value = await api.getFirewallRules() }
  catch (e) { alert('Error cargando reglas: ' + e.message) }
  finally  { loadingFw.value = false }
  loadStatus()
  try { sysPorts.value = await api.getFirewallSystemPorts() }
  catch (e) { console.error(e) }
}

async function loadFail2ban() {
  try {
    jails.value  = await api.getFail2banJails()
    banned.value = await api.getBannedIps()
    const wl = await api.getFail2banWhitelist()
    ignoreip.value = wl.ignoreip || []
  } catch (e) {
    if (!String(e.message).includes('503')) alert('Fail2ban: ' + e.message)
  }
  loadStatus()
}

async function loadIpLists() {
  try { ipLists.value = await api.getIpLists() }
  catch (e) { alert('Listas IP: ' + e.message) }
}

async function loadConnections() {
  try { connections.value = await api.getActiveConnections(connListening.value) }
  catch (e) { alert('Conexiones: ' + e.message) }
}

async function loadAudit() {
  try { audit.value = await api.getSecurityAudit(auditCategory.value || null, 200) }
  catch (e) { alert('Auditoría: ' + e.message) }
}

function changeTab(t) {
  tab.value = t
  if (t === 'firewall')    loadFirewall()
  if (t === 'fail2ban')    loadFail2ban()
  if (t === 'iplists')     loadIpLists()
  if (t === 'connections') loadConnections()
  if (t === 'audit')       loadAudit()
  if (t === 'crowdsec')    loadCrowdsec()
  if (t === 'badbots')     loadBadBots()
}

// ─── Bad Bots ─────────────────────────────────────────────────────────────────
const knownBots     = ref([])
const customPatterns = ref([])
const botsLoading   = ref(false)
const botsSaving    = ref(false)

async function loadBadBots() {
  botsLoading.value = true
  try {
    const data = await api.get('/api/security/bad-bots')
    knownBots.value      = data.known_bots || []
    customPatterns.value = data.custom_patterns || []
  } catch (e) {
    console.error('Error cargando bad bots:', e)
  } finally {
    botsLoading.value = false
  }
}

async function saveBadBots() {
  botsSaving.value = true
  try {
    const enabledIds = knownBots.value.filter(b => b.enabled).map(b => b.id)
    const custom = customPatterns.value.filter(p => p.trim())
    await api.put('/api/security/bad-bots', { enabled_ids: enabledIds, custom_patterns: custom })
    api.showNotification?.('Bad bots actualizados y nginx recargado', 'success')
    // Notificación via store
    const { useMainStore } = await import('../stores/useMainStore')
    useMainStore().showNotification('Bad bots actualizados y nginx recargado', 'success')
  } catch (e) {
    const { useMainStore } = await import('../stores/useMainStore')
    useMainStore().showNotification('Error: ' + e.message, 'danger')
  } finally {
    botsSaving.value = false
  }
}

// ─── CrowdSec ────────────────────────────────────────────────────────────────
async function loadCrowdsec() {
  try { csStatus.value = await api.getCrowdsecStatus() }
  catch (e) { console.error(e); csStatus.value = { installed: false, running: false } }
  if (csStatus.value?.running) {
    changeCsTab(csTab.value)
  }
}

function changeCsTab(t) {
  csTab.value = t
  if (t === 'decisions')   loadCsDecisions()
  if (t === 'alerts')      loadCsAlerts()
  if (t === 'bouncers')    loadCsBouncers()
  if (t === 'collections') loadCsCollections()
}

async function loadCsDecisions() {
  try { csDecisions.value = await api.getCrowdsecDecisions() }
  catch (e) { alert('CrowdSec decisiones: ' + e.message) }
}
async function loadCsAlerts() {
  try { csAlerts.value = await api.getCrowdsecAlerts(50) }
  catch (e) { alert('CrowdSec alertas: ' + e.message) }
}
async function loadCsBouncers() {
  try { csBouncers.value = await api.getCrowdsecBouncers() }
  catch (e) { alert('CrowdSec bouncers: ' + e.message) }
}
async function loadCsCollections() {
  try { csCollections.value = await api.getCrowdsecCollections() }
  catch (e) { alert('CrowdSec colecciones: ' + e.message) }
}

function openCsBan() {
  csBanForm.value = { ip: '', duration: '4h', reason: '', type: 'ban' }
  showCsBan.value = true
}
async function submitCsBan() {
  saving.value = true
  try {
    const payload = { ...csBanForm.value }
    if (!payload.reason) delete payload.reason
    await api.addCrowdsecDecision(payload)
    showCsBan.value = false
    await loadCsDecisions()
    csStatus.value = await api.getCrowdsecStatus()
  } catch (e) { alert('CrowdSec: ' + e.message) }
  finally { saving.value = false }
}
async function deleteCsDecision(d) {
  if (!confirm(`¿Eliminar decisión #${d.id} sobre ${d.value}?`)) return
  try {
    await api.deleteCrowdsecDecisionById(d.id)
    await loadCsDecisions()
    csStatus.value = await api.getCrowdsecStatus()
  } catch (e) { alert(e.message) }
}

// ─── Firewall actions ────────────────────────────────────────────────────────
function openRuleForm(r = null) {
  ruleForm.value = r ? { ...r } : emptyRule()
  showRuleForm.value = true
}
async function saveRule() {
  saving.value = true
  try {
    const payload = { ...ruleForm.value }
    if (payload.port_range === '')  payload.port_range = null
    if (payload.source_ip === '')   payload.source_ip = null
    if (payload.description === '') payload.description = null
    if (payload.id) await api.updateFirewallRule(payload.id, payload)
    else            await api.createFirewallRule(payload)
    showRuleForm.value = false
    await loadFirewall()
  } catch (e) { alert('Error: ' + e.message) }
  finally { saving.value = false }
}
async function deleteRule(r) {
  if (!confirm(`¿Eliminar regla #${r.id}? Esto regenera el firewall.`)) return
  try { await api.deleteFirewallRule(r.id); await loadFirewall() }
  catch (e) { alert('Error: ' + e.message) }
}

// ─── Fail2ban actions ────────────────────────────────────────────────────────
async function toggleJail(j, enabled) {
  if (!confirm(`¿${enabled ? 'Habilitar' : 'Deshabilitar'} jail ${j.name}?`)) return
  try { await api.toggleFail2banJail(j.name, enabled); await loadFail2ban() }
  catch (e) { alert(e.message) }
}
async function unbanIp(b) {
  if (!confirm(`¿Desbanear ${b.ip}${b.jail ? ' en jail ' + b.jail : ''}?`)) return
  try { await api.unbanIp(b.ip, b.jail); await loadFail2ban() }
  catch (e) { alert(e.message) }
}
function openManualBan() {
  banForm.value = { ip: '', duration_seconds: null, reason: '' }
  showManualBan.value = true
}
async function submitManualBan() {
  saving.value = true
  try {
    const payload = { ...banForm.value }
    if (!payload.duration_seconds) delete payload.duration_seconds
    if (!payload.reason) delete payload.reason
    await api.manualBanIp(payload)
    showManualBan.value = false
    await loadFail2ban()
  } catch (e) { alert(e.message) }
  finally { saving.value = false }
}
function openAddIgnore() {
  ignoreForm.value = { ip: '' }
  showAddIgnore.value = true
}
async function submitAddIgnore() {
  saving.value = true
  try {
    await api.addFail2banWhitelist(ignoreForm.value.ip)
    showAddIgnore.value = false
    await loadFail2ban()
  } catch (e) { alert(e.message) }
  finally { saving.value = false }
}
async function removeIgnore(ip) {
  if (!confirm(`¿Quitar ${ip} de la whitelist?`)) return
  try { await api.removeFail2banWhitelist(ip); await loadFail2ban() }
  catch (e) { alert(e.message) }
}

// ─── IP Lists actions ────────────────────────────────────────────────────────
function openIpListForm(l = null) {
  ipListForm.value = l ? { ...l } : emptyIpList()
  showIpListForm.value = true
}
async function saveIpList() {
  saving.value = true
  try {
    const payload = { ...ipListForm.value }
    if (payload.id) {
      const { id, name, ...update } = payload
      await api.updateIpList(id, update)
    } else {
      await api.createIpList(payload)
    }
    showIpListForm.value = false
    await loadIpLists()
  } catch (e) { alert('Error: ' + e.message) }
  finally { saving.value = false }
}
async function refreshIpList(l) {
  try { await api.refreshIpList(l.id); await loadIpLists() }
  catch (e) { alert(e.message) }
}
async function deleteIpList(l) {
  if (!confirm(`¿Eliminar lista "${l.name}"? Regenera firewall.`)) return
  try { await api.deleteIpList(l.id); await loadIpLists() }
  catch (e) { alert(e.message) }
}

// ─── Mount ───────────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadStatus()
  await loadFirewall()
  loadIsolation()
})
</script>

<style scoped>
.sv-view { display: flex; flex-direction: column; gap: 20px; }

/* Cabecera */
.sec-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap; }
.sec-title { font-size:1.5rem; font-weight:700; margin:0 0 .25rem; display:flex; align-items:center; gap:.5rem; }
.sec-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }
.sec-hint { font-size:.82rem; color:var(--text-muted); margin:0 0 .75rem; }

/* Contadores */
.sv-counters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.sec-counter { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); padding:.875rem 1rem; display:flex; flex-direction:column; align-items:center; gap:.25rem; }
.sec-counter-val { font-size:1.75rem; font-weight:700; line-height:1; color:var(--text); }
.sec-counter-lbl { font-size:.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; }
@media (max-width: 768px) { .sv-counters { grid-template-columns: repeat(2, 1fr); } }

/* Cards */
.sec-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); overflow:hidden; }
.sec-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:.5rem; }
.sec-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
.sec-card-body { padding:1rem 1.25rem; }

/* Botones */
.sec-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--r-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.sec-btn--primary { background:var(--ac); color:#fff; border-color:var(--ac); }
.sec-btn--primary:hover { opacity:.9; }
.sec-btn--ghost { background:var(--surface); color:var(--text-secondary); border-color:var(--border); }
.sec-btn--ghost:hover { background:var(--surface-2); color:var(--text); }
.sec-btn--success { background:color-mix(in srgb,var(--success) 12%,transparent); color:var(--success); border-color:color-mix(in srgb,var(--success) 30%,transparent); }
.sec-btn--success:hover { background:var(--success); color:#fff; }
.sec-btn--danger { background:color-mix(in srgb,var(--danger) 12%,transparent); color:var(--danger); border-color:color-mix(in srgb,var(--danger) 30%,transparent); }
.sec-btn--danger:hover { background:var(--danger); color:#fff; }
.sec-btn--sm { padding:.3rem .65rem; font-size:.82rem; }
.sec-btn:disabled { opacity:.5; cursor:not-allowed; }
.sec-icon-btn { width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:var(--r-sm,6px); background:var(--surface); color:var(--text-secondary); cursor:pointer; transition:all .15s; font-size:.875rem; flex-shrink:0; }
.sec-icon-btn:hover { background:var(--surface-2); color:var(--text); }
.sec-icon-btn--danger:hover { background:var(--danger); color:#fff; border-color:var(--danger); }

/* Badges */
.sec-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; white-space:nowrap; }
.sec-badge--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.sec-badge--off { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); }
.sec-badge--danger { background:color-mix(in srgb,var(--danger) 15%,transparent); color:var(--danger); }
.sec-badge--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 15%,transparent); color:var(--warning,#d97706); }
.sec-badge--blue { background:color-mix(in srgb,var(--ac) 15%,transparent); color:var(--ac); }

/* Tabs */
.sec-tabs { display:flex; gap:2px; flex-wrap:wrap; padding:.5rem; background:var(--surface-2); border-radius:var(--r-md,10px); }
.sec-tab { display:inline-flex; align-items:center; gap:6px; padding:.4rem .8rem; border-radius:var(--r-sm,6px); font-size:.82rem; font-weight:500; cursor:pointer; border:none; background:none; color:var(--text-muted); transition:all .15s; }
.sec-tab:hover { background:var(--surface); color:var(--text); }
.sec-tab--active { background:var(--surface); color:var(--text); box-shadow:0 1px 3px rgba(0,0,0,.08); }

/* Tabla */
.sec-table-wrap { overflow-x:auto; }
.sec-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.sec-table th { padding:.6rem 1rem; text-align:left; font-size:.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); }
.sec-table td { padding:.6rem 1rem; border-bottom:1px solid var(--border); }
.sec-table tr:last-child td { border-bottom:none; }
.sec-table tbody tr:hover { background:var(--surface-2); }

/* Alertas */
.sec-alert { display:flex; align-items:flex-start; gap:.75rem; padding:.875rem 1.25rem; border-radius:var(--r-md,10px); font-size:.875rem; }
.sec-alert--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 10%,transparent); color:var(--warning,#d97706); border:1px solid color-mix(in srgb,var(--warning,#f59e0b) 25%,transparent); }
.sec-alert--danger { background:color-mix(in srgb,var(--danger) 10%,transparent); color:var(--danger); border:1px solid color-mix(in srgb,var(--danger) 25%,transparent); }

/* Empty / loading */
.sec-empty { display:flex; align-items:center; gap:.75rem; padding:2rem; color:var(--text-muted); font-size:.875rem; justify-content:center; }
.sec-loading { display:flex; justify-content:center; padding:2rem; }

/* Grid 2 columnas */
.sec-2col { display:grid; grid-template-columns:1fr 1fr; gap:16px; }

/* Responsive */
@media (max-width: 820px) {
  .sec-head-right { width:100%; justify-content:space-between; }
  .sec-2col { grid-template-columns:1fr; }
}

.sec-head-right { display: flex; align-items: center; gap: var(--sp-5); flex-wrap: wrap; }
.sec-score { display: flex; align-items: center; gap: var(--sp-3); }
.sec-score__ring { width: 56px; height: 56px; transform: rotate(-90deg); }
.sec-score__track { fill: none; stroke: var(--surface-inset); stroke-width: 6; }
.sec-score__fill { fill: none; stroke-width: 6; stroke-linecap: round; transition: stroke-dasharray var(--t-slow) var(--ease-out), stroke var(--t-base); }
.sec-score__num { transform: rotate(90deg); transform-origin: 30px 30px; text-anchor: middle; fill: var(--text); font-weight: var(--fw-bold); font-size: 18px; font-family: var(--font-sans); }
.sec-score__meta { display: flex; flex-direction: column; line-height: 1.25; }
.sec-score__label { font-weight: var(--fw-semibold); font-size: var(--fs-base); }
.sec-score__sub { font-size: var(--fs-sm); color: var(--text-muted); }

/* Aislamiento PHP */
.iso-card { border-left: 4px solid var(--border-strong) !important; }
.iso-card.is-ok { border-left-color: var(--success) !important; }
.iso-card.is-danger { border-left-color: var(--danger) !important; }
.iso-icon {
  width: 48px; height: 48px; flex-shrink: 0;
  display: grid; place-items: center; border-radius: var(--r-md);
  font-size: 22px; background: var(--surface-inset); color: var(--text-muted);
}
.iso-icon.is-ok { background: var(--success-bg); color: var(--success); }
.iso-icon.is-danger { background: var(--danger-bg); color: var(--danger); }
.iso-issues { border-top: 1px solid var(--border); padding-top: var(--sp-3); display: flex; flex-direction: column; gap: 6px; }
.iso-issue { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; font-size: var(--fs-sm); }
.iso-issue__domain { font-weight: var(--fw-semibold); color: var(--text); font-family: var(--font-mono); }
.iso-issue__owner { min-width: 80px; }
.iso-issue__msg { flex: 1; }
</style>
