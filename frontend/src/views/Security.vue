<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h2 class="mb-1"><i class="bi bi-shield-lock me-2"></i>Seguridad</h2>
        <p class="text-muted mb-0">Firewall (nftables), fail2ban, listas IP, conexiones y auditoría</p>
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
        <div class="d-flex gap-2">
          <span v-if="fwStatus" class="badge"
                :class="fwStatus.table_present ? 'bg-success' : 'bg-danger'">
            nftables {{ fwStatus.table_present ? 'activo' : 'inactivo' }}
          </span>
          <span v-if="f2bStatus" class="badge"
                :class="f2bStatus.running ? 'bg-success' : 'bg-warning text-dark'">
            fail2ban {{ f2bStatus.running ? 'ok' : 'parado' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Resumen -->
    <div class="sv-counters" v-if="fwStatus">
      <div class="card text-center"><div class="card-body">
        <div class="text-muted small">Reglas activas</div>
        <div class="sv-stat-num">{{ fwStatus.rule_count }}</div>
      </div></div>
      <div class="card text-center"><div class="card-body">
        <div class="text-muted small">Whitelist</div>
        <div class="sv-stat-num">{{ fwStatus.whitelist_count }}</div>
      </div></div>
      <div class="card text-center"><div class="card-body">
        <div class="text-muted small">IPs baneadas</div>
        <div class="sv-stat-num">{{ fwStatus.banned_count }}</div>
      </div></div>
      <div class="card text-center"><div class="card-body">
        <div class="text-muted small">Jails fail2ban</div>
        <div class="sv-stat-num">{{ f2bStatus?.jails?.length || 0 }}</div>
      </div></div>
    </div>

    <!-- ── Aislamiento PHP (open_basedir por dominio) ── -->
    <div class="card shadow-sm mb-4 iso-card" :class="isoCardTone">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">
          <div class="d-flex gap-3">
            <div class="iso-icon" :class="isoCardTone">
              <i class="bi" :class="isoAllOk ? 'bi-shield-fill-check' : 'bi-shield-fill-exclamation'"></i>
            </div>
            <div>
              <h5 class="mb-1">Aislamiento PHP por dominio</h5>
              <p class="text-muted mb-2 small" style="max-width:560px">
                Cada dominio debe tener un pool PHP-FPM dedicado con
                <code>open_basedir</code>, de modo que su PHP no pueda leer los
                archivos de otros clientes. Sin él, un sitio podría leer
                <code>wp-config.php</code> y secretos de los demás.
              </p>
              <div v-if="isoLoading" class="text-muted small">
                <span class="spinner-border spinner-border-sm me-1"></span> Auditando dominios…
              </div>
              <div v-else-if="isoAudit" class="d-flex gap-2 flex-wrap">
                <span class="badge bg-success">{{ isoAudit.secure }} protegidos</span>
                <span class="badge" :class="isoAudit.insecure ? 'bg-danger' : 'bg-secondary'">
                  {{ isoAudit.insecure }} desprotegidos
                </span>
                <span class="badge bg-secondary">{{ isoAudit.total }} dominios</span>
              </div>
            </div>
          </div>
          <div class="d-flex gap-2 align-items-center">
            <button class="btn btn-sm btn-outline-secondary" @click="loadIsolation" :disabled="isoLoading || isoRepairing">
              <i class="bi bi-arrow-repeat me-1"></i> Reauditar
            </button>
            <button v-if="isoAudit && isoAudit.insecure > 0"
                    class="btn btn-sm btn-danger" @click="repairIsolation" :disabled="isoRepairing">
              <span v-if="isoRepairing" class="spinner-border spinner-border-sm me-1"></span>
              <i v-else class="bi bi-wrench-adjustable me-1"></i>
              Reparar {{ isoAudit.insecure }} dominio(s)
            </button>
          </div>
        </div>

        <!-- Detalle de dominios desprotegidos -->
        <div v-if="isoAudit && isoAudit.insecure > 0" class="iso-issues mt-3">
          <div v-for="d in isoInsecureList" :key="d.domain" class="iso-issue">
            <span class="iso-issue__domain"><i class="bi bi-globe2 me-1"></i>{{ d.domain }}</span>
            <span class="iso-issue__owner text-muted">{{ d.owner }}</span>
            <span class="iso-issue__msg text-danger small">{{ d.issues[0] }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <ul class="nav nav-tabs mb-3">
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='firewall'}" href="#" @click.prevent="changeTab('firewall')">
          <i class="bi bi-brick me-1"></i> Firewall
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='fail2ban'}" href="#" @click.prevent="changeTab('fail2ban')">
          <i class="bi bi-lock me-1"></i> Fail2ban
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='iplists'}" href="#" @click.prevent="changeTab('iplists')">
          <i class="bi bi-list-task me-1"></i> Listas IP
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='crowdsec'}" href="#" @click.prevent="changeTab('crowdsec')">
          <i class="bi bi-shield-check me-1"></i> CrowdSec
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='connections'}" href="#" @click.prevent="changeTab('connections')">
          <i class="bi bi-broadcast me-1"></i> Conexiones
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='audit'}" href="#" @click.prevent="changeTab('audit')">
          <i class="bi bi-journal-text me-1"></i> Auditoría
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='badbots'}" href="#" @click.prevent="changeTab('badbots')">
          <i class="bi bi-robot me-1"></i> Bad Bots
        </a>
      </li>
    </ul>

    <!-- ═══════════════════════════ Firewall ═══════════════════════════ -->
    <div v-if="tab==='firewall'">
      <!-- Puertos del sistema (firewall real del kernel) -->
      <div class="card shadow-sm mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <h5 class="mb-0"><i class="bi bi-hdd-network me-1"></i> Puertos del sistema</h5>
          <span v-if="sysPorts.policy" class="badge"
                :class="sysPorts.policy === 'drop' ? 'bg-success' : 'bg-warning text-dark'">
            Política: {{ sysPorts.policy === 'drop' ? 'DROP (seguro)' : sysPorts.policy }}
          </span>
        </div>
        <div class="card-body">
          <p class="text-muted small mb-2">
            Puertos que el firewall deja abiertos de serie para los servicios del panel.
            Se leen del firewall activo del sistema. La política <strong>DROP</strong> significa que
            todo lo que no esté aquí (ni en tus reglas) queda bloqueado.
          </p>
          <div v-if="!sysPorts.available" class="text-muted small">No se pudo leer el firewall del sistema.</div>
          <div v-else class="d-flex flex-wrap gap-2">
            <span v-for="p in sysPorts.ports" :key="p.proto + p.port"
                  class="badge bg-light text-dark border">
              <i class="bi bi-door-open me-1"></i>{{ p.port }}/{{ p.proto }}
              <span v-if="p.service !== '—'" class="text-muted">· {{ p.service }}</span>
            </span>
          </div>
        </div>
      </div>

      <div class="card shadow-sm mb-3">
        <div class="card-header d-flex justify-content-between">
          <h5 class="mb-0">Reglas personalizadas</h5>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" @click="loadFirewall">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
            <button class="btn btn-sm btn-success" @click="openRuleForm()">
              <i class="bi bi-plus-lg me-1"></i> Nueva regla
            </button>
          </div>
        </div>
        <div class="card-body p-0">
          <div v-if="loadingFw" class="text-center py-4"><div class="spinner-border text-primary"></div></div>
          <div v-else-if="!rules.length" class="text-center py-4 text-muted">No hay reglas.</div>
          <table v-else class="table table-sm table-hover mb-0">
            <thead class="table-light">
              <tr>
                <th>Prio</th><th>Acción</th><th>Proto</th><th>Puerto</th><th>Origen</th>
                <th>Whitelist</th><th>Activa</th><th>Descripción</th><th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td><code class="small">{{ r.priority }}</code></td>
                <td>
                  <span class="badge" :class="ruleActionBadge(r.action)">{{ r.action }}</span>
                </td>
                <td><code>{{ r.protocol }}</code></td>
                <td><code>{{ r.port_range || '*' }}</code></td>
                <td class="font-monospace small">{{ r.source_ip || 'any' }}</td>
                <td>
                  <span v-if="r.is_whitelist" class="badge bg-info">whitelist</span>
                </td>
                <td>
                  <span class="badge" :class="r.is_active ? 'bg-success' : 'bg-secondary'">
                    {{ r.is_active ? 'sí' : 'no' }}
                  </span>
                </td>
                <td class="small text-muted">{{ r.description || '—' }}</td>
                <td class="text-end">
                  <button class="btn btn-sm btn-outline-secondary me-1" @click="openRuleForm(r)" title="Editar">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-danger" @click="deleteRule(r)" title="Eliminar">
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ Fail2ban ═══════════════════════════ -->
    <div v-if="tab==='fail2ban'">
      <div class="row g-3">
        <div class="col-lg-6">
          <div class="card shadow-sm">
            <div class="card-header d-flex justify-content-between">
              <h5 class="mb-0">Jails</h5>
              <button class="btn btn-sm btn-outline-secondary" @click="loadFail2ban">
                <i class="bi bi-arrow-clockwise"></i>
              </button>
            </div>
            <div class="card-body p-0">
              <table class="table table-sm mb-0">
                <thead class="table-light">
                  <tr><th>Jail</th><th>Failed</th><th>Banned</th><th class="text-end">Acción</th></tr>
                </thead>
                <tbody>
                  <tr v-for="j in jails" :key="j.name">
                    <td><strong>{{ j.name }}</strong></td>
                    <td>{{ j.currently_failed }} / {{ j.total_failed }}</td>
                    <td>{{ j.currently_banned }} / {{ j.total_banned }}</td>
                    <td class="text-end">
                      <button class="btn btn-sm btn-outline-warning" @click="toggleJail(j, false)" title="Deshabilitar">
                        <i class="bi bi-pause-fill"></i>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="col-lg-6">
          <div class="card shadow-sm">
            <div class="card-header d-flex justify-content-between">
              <h5 class="mb-0">IPs baneadas</h5>
              <button class="btn btn-sm btn-success" @click="openManualBan">
                <i class="bi bi-plus-lg me-1"></i> Banear IP
              </button>
            </div>
            <div class="card-body p-0">
              <div v-if="!banned.length" class="text-center py-3 text-muted">No hay IPs baneadas.</div>
              <table v-else class="table table-sm table-hover mb-0">
                <thead class="table-light">
                  <tr><th>IP</th><th>Jail</th><th>Por</th><th class="text-end">Acción</th></tr>
                </thead>
                <tbody>
                  <tr v-for="b in banned" :key="(b.jail||'-')+b.ip">
                    <td class="font-monospace">{{ b.ip }}</td>
                    <td>{{ b.jail || '—' }}</td>
                    <td>{{ b.banned_by }}</td>
                    <td class="text-end">
                      <button class="btn btn-sm btn-outline-success" @click="unbanIp(b)" title="Desbanear">
                        <i class="bi bi-unlock"></i>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="card shadow-sm mt-3">
            <div class="card-header d-flex justify-content-between">
              <h5 class="mb-0">Whitelist permanente (ignoreip)</h5>
              <button class="btn btn-sm btn-success" @click="openAddIgnore">
                <i class="bi bi-plus-lg me-1"></i> Añadir IP
              </button>
            </div>
            <div class="card-body">
              <div v-if="!ignoreip.length" class="text-muted">Vacío.</div>
              <span v-for="ip in ignoreip" :key="ip" class="badge bg-info me-1 mb-1">
                {{ ip }}
                <button type="button" class="btn-close btn-close-white btn-sm ms-1"
                        @click="removeIgnore(ip)" :aria-label="'quitar ' + ip"></button>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ IP Lists ═══════════════════════════ -->
    <div v-if="tab==='iplists'">
      <div class="card shadow-sm">
        <div class="card-header d-flex justify-content-between">
          <h5 class="mb-0">Listas IP desde URL</h5>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" @click="loadIpLists">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
            <button class="btn btn-sm btn-success" @click="openIpListForm()">
              <i class="bi bi-plus-lg me-1"></i> Nueva lista
            </button>
          </div>
        </div>
        <div class="card-body p-0">
          <div v-if="!ipLists.length" class="text-center py-4 text-muted">No hay listas.</div>
          <table v-else class="table table-sm table-hover mb-0">
            <thead class="table-light">
              <tr>
                <th>Nombre</th><th>Acción</th><th>Familia</th><th>Entradas</th>
                <th>Última act.</th><th>Estado</th><th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in ipLists" :key="l.id">
                <td>
                  <strong>{{ l.name }}</strong>
                  <div class="small text-muted text-truncate" style="max-width: 350px;" :title="l.url">{{ l.url }}</div>
                </td>
                <td>
                  <span class="badge" :class="l.action === 'allow' ? 'bg-success' : 'bg-danger'">
                    {{ l.action }}
                  </span>
                </td>
                <td><code>{{ l.address_family }}</code></td>
                <td>
                  <span class="badge bg-secondary">{{ l.entry_count_v4 }} v4</span>
                  <span class="badge bg-secondary ms-1">{{ l.entry_count_v6 }} v6</span>
                </td>
                <td class="small">
                  <span v-if="l.last_success_at">{{ formatDate(l.last_success_at) }}</span>
                  <span v-else class="text-muted">nunca</span>
                </td>
                <td>
                  <span v-if="l.last_error" class="badge bg-warning text-dark" :title="l.last_error">⚠ error</span>
                  <span v-else-if="l.enabled" class="badge bg-success">OK</span>
                  <span v-else class="badge bg-secondary">deshabilitada</span>
                </td>
                <td class="text-end">
                  <button class="btn btn-sm btn-outline-primary me-1" @click="refreshIpList(l)" title="Refrescar ahora">
                    <i class="bi bi-arrow-repeat"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-secondary me-1" @click="openIpListForm(l)" title="Editar">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-danger" @click="deleteIpList(l)" title="Eliminar">
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ CrowdSec ═══════════════════════════ -->
    <div v-if="tab==='crowdsec'">
      <!-- Banner: no instalado / no corriendo -->
      <div v-if="csStatus && !csStatus.installed" class="alert alert-warning d-flex align-items-center">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <div>
          <strong>CrowdSec no está instalado.</strong>
          Vuelve a ejecutar el instalador con la opción CrowdSec activada, o instala manualmente:
          <code>curl -s https://install.crowdsec.net | bash &amp;&amp; apt install crowdsec crowdsec-firewall-bouncer-nftables</code>
        </div>
      </div>
      <div v-else-if="csStatus && !csStatus.running" class="alert alert-danger d-flex align-items-center">
        <i class="bi bi-x-octagon-fill me-2"></i>
        <div>
          <strong>CrowdSec instalado pero no está corriendo.</strong>
          Revisa <code>journalctl -u crowdsec</code> y arranca con <code>systemctl start crowdsec</code>.
        </div>
      </div>

      <!-- Resumen -->
      <div v-if="csStatus && csStatus.running" class="row g-3 mb-3">
        <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
          <div class="text-muted small">Versión</div>
          <div class="h5 mb-0 font-monospace">{{ csStatus.version || '—' }}</div>
        </div></div></div>
        <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
          <div class="text-muted small">Decisiones activas</div>
          <div class="display-6">{{ csStatus.decisions }}</div>
        </div></div></div>
        <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
          <div class="text-muted small">Bouncers</div>
          <div class="display-6">{{ csStatus.bouncers }}</div>
        </div></div></div>
        <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
          <div class="text-muted small">Colecciones</div>
          <div class="display-6">{{ csStatus.collections }}</div>
        </div></div></div>
      </div>

      <!-- Sub-tabs CrowdSec -->
      <div v-if="csStatus && csStatus.running">
        <ul class="nav nav-pills mb-3">
          <li class="nav-item">
            <a class="nav-link" :class="{active: csTab==='decisions'}" href="#" @click.prevent="changeCsTab('decisions')">
              <i class="bi bi-slash-circle me-1"></i> Decisiones
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" :class="{active: csTab==='alerts'}" href="#" @click.prevent="changeCsTab('alerts')">
              <i class="bi bi-bell me-1"></i> Alertas
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" :class="{active: csTab==='bouncers'}" href="#" @click.prevent="changeCsTab('bouncers')">
              <i class="bi bi-shield-shaded me-1"></i> Bouncers
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" :class="{active: csTab==='collections'}" href="#" @click.prevent="changeCsTab('collections')">
              <i class="bi bi-collection me-1"></i> Colecciones
            </a>
          </li>
        </ul>

        <!-- Decisiones -->
        <div v-if="csTab==='decisions'" class="card shadow-sm">
          <div class="card-header d-flex justify-content-between">
            <h5 class="mb-0">Decisiones activas (bans CrowdSec)</h5>
            <div class="d-flex gap-2">
              <button class="btn btn-sm btn-outline-secondary" @click="loadCsDecisions">
                <i class="bi bi-arrow-clockwise"></i>
              </button>
              <button class="btn btn-sm btn-success" @click="openCsBan">
                <i class="bi bi-plus-lg me-1"></i> Decisión manual
              </button>
            </div>
          </div>
          <div class="card-body p-0">
            <div v-if="!csDecisions.length" class="text-center py-4 text-muted">
              No hay decisiones activas. Buena señal — o nada ha llegado a CrowdSec todavía.
            </div>
            <table v-else class="table table-sm table-hover mb-0">
              <thead class="table-light">
                <tr>
                  <th>IP / valor</th><th>Tipo</th><th>Escenario</th>
                  <th>Origen</th><th>Duración</th><th>Country</th>
                  <th class="text-end">Acción</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in csDecisions" :key="d.id">
                  <td class="font-monospace">{{ d.value }}</td>
                  <td>
                    <span class="badge" :class="d.type === 'ban' ? 'bg-danger' : 'bg-warning text-dark'">
                      {{ d.type }}
                    </span>
                  </td>
                  <td class="small">{{ d.scenario || '—' }}</td>
                  <td class="small">{{ d.origin || '—' }}</td>
                  <td class="small font-monospace">{{ d.duration || '—' }}</td>
                  <td class="small">{{ d.country || '—' }}</td>
                  <td class="text-end">
                    <button class="btn btn-sm btn-outline-success" @click="deleteCsDecision(d)" title="Eliminar decisión">
                      <i class="bi bi-unlock"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Alertas -->
        <div v-if="csTab==='alerts'" class="card shadow-sm">
          <div class="card-header d-flex justify-content-between">
            <h5 class="mb-0">Alertas recientes</h5>
            <button class="btn btn-sm btn-outline-secondary" @click="loadCsAlerts">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
          <div class="card-body p-0">
            <div v-if="!csAlerts.length" class="text-center py-4 text-muted">No hay alertas.</div>
            <table v-else class="table table-sm table-hover mb-0">
              <thead class="table-light">
                <tr>
                  <th>Fecha</th><th>IP origen</th><th>Escenario</th>
                  <th>Eventos</th><th>País</th><th>Mensaje</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in csAlerts" :key="a.id">
                  <td class="small">{{ formatDate(a.created_at) }}</td>
                  <td class="font-monospace small">{{ a.source_ip || '—' }}</td>
                  <td class="small">{{ a.scenario }}</td>
                  <td class="text-center small">{{ a.events_count || 0 }}</td>
                  <td class="small">{{ a.source_country || '—' }}</td>
                  <td class="small text-muted text-truncate" style="max-width: 350px;" :title="a.message">
                    {{ a.message || '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Bouncers -->
        <div v-if="csTab==='bouncers'" class="card shadow-sm">
          <div class="card-header d-flex justify-content-between">
            <h5 class="mb-0">Bouncers registrados</h5>
            <button class="btn btn-sm btn-outline-secondary" @click="loadCsBouncers">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
          <div class="card-body p-0">
            <div v-if="!csBouncers.length" class="text-center py-4 text-muted">
              No hay bouncers. Sin bouncer las decisiones se almacenan pero no se aplican.
            </div>
            <table v-else class="table table-sm mb-0">
              <thead class="table-light">
                <tr>
                  <th>Nombre</th><th>Tipo</th><th>Versión</th>
                  <th>IP</th><th>Último pull</th><th>Estado</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="b in csBouncers" :key="b.name">
                  <td><strong>{{ b.name }}</strong></td>
                  <td><code class="small">{{ b.type || '—' }}</code></td>
                  <td class="small">{{ b.version || '—' }}</td>
                  <td class="font-monospace small">{{ b.ip_address || '—' }}</td>
                  <td class="small">{{ formatDate(b.last_pull) }}</td>
                  <td>
                    <span class="badge" :class="b.revoked ? 'bg-danger' : 'bg-success'">
                      {{ b.revoked ? 'revoked' : 'activo' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Colecciones -->
        <div v-if="csTab==='collections'" class="card shadow-sm">
          <div class="card-header d-flex justify-content-between">
            <h5 class="mb-0">Colecciones instaladas (parsers + escenarios)</h5>
            <button class="btn btn-sm btn-outline-secondary" @click="loadCsCollections">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
          <div class="card-body p-0">
            <div v-if="!csCollections.length" class="text-center py-4 text-muted">
              No hay colecciones. Instala con <code>cscli collections install crowdsecurity/nginx</code>.
            </div>
            <table v-else class="table table-sm mb-0">
              <thead class="table-light">
                <tr>
                  <th>Nombre</th><th>Versión</th><th>Estado</th><th>Descripción</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in csCollections" :key="c.name">
                  <td><code class="small">{{ c.name }}</code></td>
                  <td class="small">{{ c.version || '—' }}</td>
                  <td class="small">{{ c.status || '—' }}</td>
                  <td class="small text-muted">{{ c.description || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ Conexiones ═══════════════════════════ -->
    <div v-if="tab==='connections'">
      <div class="card shadow-sm">
        <div class="card-header d-flex justify-content-between align-items-center">
          <h5 class="mb-0">{{ connListening ? 'Puertos en escucha (LISTEN)' : 'Conexiones activas' }}</h5>
          <div class="d-flex gap-2">
            <div class="btn-group btn-group-sm" role="group">
              <input type="radio" class="btn-check" id="cn1" v-model="connListening" :value="false" @change="loadConnections">
              <label class="btn btn-outline-secondary" for="cn1">Activas</label>
              <input type="radio" class="btn-check" id="cn2" v-model="connListening" :value="true" @change="loadConnections">
              <label class="btn btn-outline-secondary" for="cn2">LISTEN</label>
            </div>
            <button class="btn btn-sm btn-outline-secondary" @click="loadConnections">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
        </div>
        <div class="card-body p-0">
          <div v-if="!connections.length" class="text-center py-4 text-muted">Sin datos.</div>
          <table v-else class="table table-sm mb-0">
            <thead class="table-light">
              <tr>
                <th>Proto</th><th>Estado</th><th>Local</th><th>Remoto</th><th>Proceso</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, i) in connections" :key="i">
                <td><code>{{ c.protocol }}</code></td>
                <td><span class="badge bg-light text-dark border">{{ c.state }}</span></td>
                <td class="font-monospace small">{{ c.local_addr }}:{{ c.local_port }}</td>
                <td class="font-monospace small">{{ c.remote_addr }}:{{ c.remote_port }}</td>
                <td>{{ c.process || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ Auditoría ═══════════════════════════ -->
    <div v-if="tab==='audit'">
      <div class="card shadow-sm">
        <div class="card-header d-flex justify-content-between align-items-center">
          <h5 class="mb-0">Auditoría de seguridad</h5>
          <div class="d-flex gap-2 align-items-center">
            <select v-model="auditCategory" @change="loadAudit" class="form-select form-select-sm" style="width: 180px;">
              <option value="">Todas las categorías</option>
              <option value="firewall">firewall</option>
              <option value="fail2ban">fail2ban</option>
              <option value="iplist">iplist</option>
              <option value="whitelist">whitelist</option>
            </select>
            <button class="btn btn-sm btn-outline-secondary" @click="loadAudit">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
        </div>
        <div class="card-body p-0">
          <div v-if="!audit.length" class="text-center py-4 text-muted">No hay eventos.</div>
          <table v-else class="table table-sm mb-0">
            <thead class="table-light">
              <tr>
                <th>Fecha</th><th>Usuario</th><th>Categoría</th><th>Acción</th>
                <th>Target</th><th>IP origen</th><th>OK</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id" :class="!a.success ? 'table-warning' : ''">
                <td class="small">{{ formatDate(a.created_at) }}</td>
                <td>{{ a.user_label || '—' }}</td>
                <td><code class="small">{{ a.category }}</code></td>
                <td><code class="small">{{ a.action }}</code></td>
                <td class="small text-muted">{{ a.target || '—' }}</td>
                <td class="font-monospace small">{{ a.ip_origin || '—' }}</td>
                <td>
                  <i v-if="a.success" class="bi bi-check-circle text-success"></i>
                  <i v-else class="bi bi-x-circle text-danger" :title="a.error"></i>
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

    <!-- ═══════════════════════════ Bad Bots ═══════════════════════════ -->
    <div v-if="tab === 'badbots'">
      <div class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span><i class="bi bi-robot me-2"></i>Bloqueo de User-Agents maliciosos</span>
          <button class="btn btn-primary btn-sm" @click="saveBadBots" :disabled="botsSaving">
            <span v-if="botsSaving" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-save me-1"></i>Guardar y recargar nginx
          </button>
        </div>
        <div class="card-body">
          <p class="text-muted small mb-3">
            Los user-agents activados serán bloqueados en nginx con HTTP 444 (cierra conexión sin respuesta).
            Los cambios se aplican inmediatamente recargando nginx.
          </p>

          <div v-if="botsLoading" class="text-center py-4">
            <div class="spinner-border spinner-border-sm"></div>
          </div>
          <div v-else>
            <!-- Catálogo de bots conocidos -->
            <h6 class="fw-semibold mb-2">Bots conocidos</h6>
            <div class="row g-2 mb-4">
              <div v-for="bot in knownBots" :key="bot.id" class="col-md-6 col-lg-4">
                <div class="border rounded p-2 d-flex align-items-start gap-2"
                     :class="bot.enabled ? 'border-danger bg-danger bg-opacity-10' : ''">
                  <div class="form-check mb-0 flex-shrink-0">
                    <input class="form-check-input" type="checkbox" :id="'bot-'+bot.id"
                           v-model="bot.enabled" />
                  </div>
                  <label :for="'bot-'+bot.id" class="form-check-label small cursor-pointer flex-fill">
                    <span class="fw-semibold">{{ bot.label }}</span>
                    <span class="text-muted d-block" style="font-size:0.78rem">{{ bot.description }}</span>
                    <code style="font-size:0.72rem">~*{{ bot.pattern }}</code>
                  </label>
                </div>
              </div>
            </div>

            <!-- Patrones custom -->
            <h6 class="fw-semibold mb-2">Patrones personalizados</h6>
            <div class="mb-2">
              <div v-for="(p, i) in customPatterns" :key="i" class="input-group input-group-sm mb-1" style="max-width:400px">
                <span class="input-group-text font-monospace">~*</span>
                <input v-model="customPatterns[i]" type="text" class="form-control font-monospace"
                       placeholder="patron-del-bot" />
                <button class="btn btn-outline-danger" type="button" @click="customPatterns.splice(i,1)">
                  <i class="bi bi-trash"></i>
                </button>
              </div>
              <button class="btn btn-outline-secondary btn-sm mt-1" @click="customPatterns.push('')">
                <i class="bi bi-plus me-1"></i>Añadir patrón
              </button>
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
.sv-counters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.sv-stat-num { font-size: 2rem; font-weight: 700; color: var(--text); }
@media (max-width: 768px) { .sv-counters { grid-template-columns: repeat(2, 1fr); } }
.nav-tabs .nav-link { cursor: pointer; }

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
