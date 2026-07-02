<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="dns-head">
      <div>
        <h2 class="dns-title"><i class="bi bi-diagram-3"></i> DNS</h2>
        <p class="dns-subtitle">{{ zones.length }} {{ zones.length === 1 ? 'zona' : 'zonas' }} · BIND9</p>
      </div>
      <button class="dns-btn dns-btn--primary" @click="openCreateZone">
        <i class="bi bi-plus-lg"></i> Nueva Zona
      </button>
    </div>

    <!-- Nameservers (solo admin) -->
    <div v-if="isAdmin" class="dns-card">
      <div class="dns-card-head">
        <span class="dns-card-title"><i class="bi bi-pin-map"></i> Nameservers del panel</span>
      </div>
      <div class="dns-card-body">
        <p class="dns-hint">
          Los nameservers publicados en el <strong>SOA</strong> y registros <strong>NS</strong> de tus zonas.
          <span v-if="ns.is_placeholder" class="dns-warn-text">
            <i class="bi bi-exclamation-triangle"></i> Usando valor por defecto (<code>{{ ns.ns1 }}</code>); configúralos.
          </span>
        </p>
        <div class="dns-ns-form">
          <div class="dns-field">
            <label>ns1 (primario)</label>
            <input v-model="nsForm.ns1" class="form-control form-control-sm font-monospace" :placeholder="ns.ns1 || 'ns1.tudominio.com'">
          </div>
          <div class="dns-field">
            <label>ns2 (secundario)</label>
            <input v-model="nsForm.ns2" class="form-control form-control-sm font-monospace" :placeholder="ns.ns2 || 'ns2.tudominio.com'">
          </div>
          <div class="dns-field dns-field--actions">
            <button class="dns-btn dns-btn--primary dns-btn--sm" @click="saveNameservers" :disabled="nsSaving">
              <i class="bi bi-save"></i> {{ nsSaving ? 'Guardando…' : 'Guardar' }}
            </button>
            <button class="dns-btn dns-btn--ghost dns-btn--sm" @click="regenerateAll" :disabled="regenAll">
              <i class="bi bi-arrow-repeat"></i> {{ regenAll ? 'Regenerando…' : 'Aplicar a todas' }}
            </button>
          </div>
        </div>
        <div class="dns-info-box" style="margin-top:.75rem">
          <strong style="font-size:.82rem"><i class="bi bi-link-45deg"></i> Glue records</strong>
          — regístralos en el registrador del dominio de tus nameservers:
          <table class="dns-glue-table">
            <tr><td>{{ ns.ns1 }}</td><td>A</td><td>{{ ns.ns1_ip || '— (IP de ns1)' }}</td></tr>
            <tr v-if="ns.ns2"><td>{{ ns.ns2 }}</td><td>A</td><td>{{ ns.ns2_ip || '— (IP de ns2)' }}</td></tr>
          </table>
        </div>
      </div>
    </div>

    <!-- Cluster DNS (solo admin) -->
    <div v-if="isAdmin" class="dns-card">
      <div class="dns-card-head">
        <span class="dns-card-title"><i class="bi bi-hdd-network"></i> Cluster DNS</span>
        <span class="dns-badge" :class="cluster.enabled ? 'dns-badge--on' : 'dns-badge--off'">
          {{ cluster.enabled ? 'Activo' : 'Sin cluster · el panel sirve DNS' }}
        </span>
      </div>
      <div class="dns-card-body">
        <p class="dns-hint">
          Sin cluster, este servidor sirve el DNS. Con cluster, las zonas se empujan a
          <strong>ns1 (master)</strong> y este replica a <strong>ns2 (slave)</strong> vía AXFR + TSIG.
        </p>

        <!-- Tabla nodos -->
        <div class="dns-table-wrap" style="margin-bottom:1rem">
          <table class="dns-table">
            <thead>
              <tr><th>Rol</th><th>Hostname</th><th>IP</th><th>SSH</th><th>Estado</th><th style="text-align:right">Acciones</th></tr>
            </thead>
            <tbody>
              <tr v-for="n in clusterNodes" :key="n.id">
                <td><span class="dns-badge" :class="n.role === 'master' ? 'dns-badge--blue' : 'dns-badge--teal'">{{ n.role === 'master' ? 'ns1 master' : 'ns2 slave' }}</span></td>
                <td style="font-family:var(--font-mono);font-size:.82rem">{{ n.hostname }}</td>
                <td style="font-family:var(--font-mono);font-size:.82rem">{{ n.ip }}</td>
                <td style="font-size:.8rem;color:var(--text-muted)">{{ n.ssh_user }}:{{ n.ssh_port }}</td>
                <td>
                  <span class="dns-badge" :class="n.status === 'ok' ? 'dns-badge--on' : n.status === 'error' ? 'dns-badge--danger' : 'dns-badge--off'">
                    {{ n.status === 'ok' ? 'OK' : n.status === 'error' ? 'Error' : 'Pendiente' }}
                  </span>
                </td>
                <td style="text-align:right">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="dns-icon-btn" @click="testNode(n)" :disabled="testingNodeId === n.id" title="Probar SSH">
                      <i class="bi bi-plug"></i>
                    </button>
                    <button class="dns-icon-btn dns-icon-btn--danger" @click="deleteNode(n)" title="Quitar"><i class="bi bi-trash"></i></button>
                  </div>
                </td>
              </tr>
              <tr v-if="!clusterNodes.length">
                <td colspan="6" style="text-align:center;padding:1.5rem;color:var(--text-muted);font-size:.875rem">Sin nodos. Añade ns1 (master) y ns2 (slave).</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Alta nodo -->
        <div class="dns-node-form">
          <div class="dns-field">
            <label>Rol</label>
            <select v-model="nodeForm.role" class="form-select form-select-sm">
              <option value="master">ns1 (master)</option>
              <option value="slave">ns2 (slave)</option>
            </select>
          </div>
          <div class="dns-field" style="flex:2">
            <label>Hostname</label>
            <input v-model="nodeForm.hostname" class="form-control form-control-sm font-monospace" placeholder="ns1.tudominio.com" />
          </div>
          <div class="dns-field">
            <label>IP</label>
            <input v-model="nodeForm.ip" class="form-control form-control-sm font-monospace" placeholder="185.x.x.x" />
          </div>
          <div class="dns-field">
            <label>Usuario SSH</label>
            <input v-model="nodeForm.ssh_user" class="form-control form-control-sm" placeholder="root" />
          </div>
          <div class="dns-field">
            <label>Contraseña SSH</label>
            <input v-model="nodeForm.ssh_password" type="password" class="form-control form-control-sm" placeholder="(o usa clave)" />
          </div>
          <div class="dns-field dns-field--actions" style="padding-top:1.4rem">
            <button class="dns-btn dns-btn--success dns-btn--sm" @click="addNode" :disabled="savingNode">
              <i class="bi bi-plus-lg"></i>
            </button>
          </div>
        </div>

        <!-- Acciones cluster -->
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:.75rem">
          <button class="dns-btn dns-btn--primary dns-btn--sm" @click="provisionCluster" :disabled="provisioning || !clusterNodes.some(n => n.role === 'master')">
            <i class="bi bi-gear-wide-connected"></i> {{ provisioning ? 'Configurando…' : 'Configurar cluster' }}
          </button>
          <button v-if="cluster.enabled" class="dns-btn dns-btn--ghost dns-btn--sm" @click="resyncCluster" :disabled="provisioning">
            <i class="bi bi-arrow-repeat"></i> Resincronizar
          </button>
          <button class="dns-icon-btn" @click="loadCluster" :disabled="loadingCluster">
            <i class="bi bi-arrow-clockwise"></i>
          </button>
          <span v-if="cluster.replication" style="font-size:.82rem;margin-left:.5rem" :style="cluster.replication.ok ? 'color:var(--success)' : 'color:var(--warning)'">
            <i class="bi" :class="cluster.replication.ok ? 'bi-check-circle' : 'bi-exclamation-triangle'"></i>
            Replicación {{ cluster.replication.ok ? 'OK' : 'pendiente' }} ({{ cluster.replication.sample_domain }})
          </span>
        </div>

        <!-- Salud de sincronización -->
        <div v-if="cluster.enabled" style="margin-top:1.25rem">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem">
            <span style="font-weight:600;font-size:.875rem">
              <i class="bi bi-clipboard-pulse"></i> Sincronización por zona
              <span v-if="health.summary" class="dns-badge ms-2" :class="health.allOk ? 'dns-badge--on' : 'dns-badge--warn'">
                {{ health.summary.ok }}/{{ health.summary.total }} OK
              </span>
            </span>
            <div style="display:flex;align-items:center;gap:8px">
              <span v-if="health.checkedAt" style="font-size:.78rem;color:var(--text-muted)">
                comprobado {{ formatHealthTime(health.checkedAt) }}
              </span>
              <button class="dns-btn dns-btn--ghost dns-btn--sm" @click="loadHealth(true)" :disabled="loadingHealth">
                <i class="bi" :class="loadingHealth ? 'bi-hourglass-split' : 'bi-arrow-clockwise'"></i>
                {{ loadingHealth ? 'Comprobando…' : 'Comprobar ahora' }}
              </button>
            </div>
          </div>
          <div class="dns-table-wrap">
            <table v-if="health.rows.length" class="dns-table" style="font-size:.82rem">
              <thead>
                <tr>
                  <th>Dominio</th>
                  <th style="text-align:right">Panel (BD)</th>
                  <th style="text-align:right">ns1 master</th>
                  <th style="text-align:right">ns2 slave</th>
                  <th style="text-align:center">Estado</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in health.rows" :key="r.domain">
                  <td style="font-family:var(--font-mono)">{{ r.domain }}</td>
                  <td style="text-align:right;font-family:var(--font-mono);color:var(--text-muted)">{{ r.db_serial }}</td>
                  <td style="text-align:right;font-family:var(--font-mono)" :class="serialClass(r, r.master_serial)">{{ r.master_serial ?? '—' }}</td>
                  <td style="text-align:right;font-family:var(--font-mono)" :class="serialClass(r, r.slave_serial)">{{ r.slave_serial ?? '—' }}</td>
                  <td style="text-align:center">
                    <span class="dns-badge" :class="r.status==='ok'?'dns-badge--on':r.status==='desync'?'dns-badge--warn':'dns-badge--danger'">
                      {{ r.status==='ok'?'Sincronizado':r.status==='desync'?'Desfasado':r.status==='master_down'?'ns1 caído':'ns2 caído' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else style="font-size:.82rem;color:var(--text-muted);padding:.75rem 0;margin:0">Aún no hay datos. Pulsa «Comprobar ahora».</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Lista de zonas -->
    <div class="dns-card">
      <div class="dns-card-head">
        <span class="dns-card-title"><i class="bi bi-diagram-3"></i> Zonas DNS</span>
        <span class="dns-count">{{ zones.length }}</span>
      </div>
      <div v-if="loadingZones" class="dns-loading"><div class="spinner-border spinner-border-sm"></div></div>
      <div v-else-if="!zones.length" class="dns-empty">
        <i class="bi bi-diagram-3"></i>
        <p>No hay zonas DNS configuradas.</p>
        <button class="dns-btn dns-btn--ghost dns-btn--sm" @click="openCreateZone">Crear primera zona</button>
      </div>
      <div v-else class="dns-table-wrap">
        <table class="dns-table">
          <thead>
            <tr>
              <th>Dominio</th>
              <th>IP</th>
              <th>SOA NS</th>
              <th>Plantilla</th>
              <th>DNSSEC</th>
              <th style="text-align:center">Registros</th>
              <th>Serial</th>
              <th style="text-align:right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="zone in zones" :key="zone.id" :class="{ 'dns-row--active': selectedZone?.id === zone.id }">
              <td style="font-weight:600">{{ zone.domain_name }}</td>
              <td style="font-family:var(--font-mono);font-size:.82rem">{{ zone.ip_address || '—' }}</td>
              <td style="font-size:.8rem;color:var(--text-muted)">{{ zone.soa_ns || '—' }}</td>
              <td><span class="dns-badge dns-badge--off">{{ zone.template || 'default' }}</span></td>
              <td>
                <button v-if="zone.can_edit" style="background:none;border:none;cursor:pointer;padding:0"
                        @click="openDnssec(zone)">
                  <span class="dns-badge" :class="zone.dnssec_enabled ? 'dns-badge--on' : 'dns-badge--off'">
                    <i :class="zone.dnssec_enabled ? 'bi bi-shield-lock' : 'bi bi-shield'"></i>
                    {{ zone.dnssec_enabled ? 'Activo' : 'No' }}
                  </span>
                </button>
                <span v-else class="dns-badge" :class="zone.dnssec_enabled ? 'dns-badge--on' : 'dns-badge--off'">
                  {{ zone.dnssec_enabled ? 'Activo' : 'No' }}
                </span>
              </td>
              <td style="text-align:center"><span class="dns-badge dns-badge--blue">{{ zone.record_count }}</span></td>
              <td><code style="font-size:.75rem;color:var(--text-muted)">{{ zone.serial }}</code></td>
              <td style="text-align:right">
                <div style="display:flex;gap:4px;justify-content:flex-end">
                  <button v-if="zone.can_edit" class="dns-icon-btn" @click="openEditZone(zone)" title="Editar zona"><i class="bi bi-pencil"></i></button>
                  <button class="dns-icon-btn" @click="openZoneRecords(zone)" title="Ver registros"><i class="bi bi-list-ul"></i></button>
                  <button v-if="zone.can_edit" class="dns-icon-btn dns-icon-btn--danger" @click="confirmDeleteZone(zone)" title="Eliminar"><i class="bi bi-trash"></i></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Registros de la zona seleccionada -->
    <div v-if="selectedZone" class="dns-card">
      <div class="dns-card-head">
        <span class="dns-card-title">
          <i class="bi bi-list-ul"></i>
          Registros de <strong>{{ selectedZone.domain_name }}</strong>
          <code style="font-size:.75rem;color:var(--text-muted);margin-left:.5rem">serial {{ selectedZone.serial }}</code>
        </span>
        <div style="display:flex;gap:6px;align-items:center">
          <button v-if="selectedZone.can_edit" class="dns-btn dns-btn--success dns-btn--sm" @click="openAddRecord">
            <i class="bi bi-plus-lg"></i> Añadir
          </button>
          <div v-if="selectedZone.can_edit" class="dropdown">
            <button class="dns-btn dns-btn--ghost dns-btn--sm" @click="showTemplates = !showTemplates">
              <i class="bi bi-magic"></i> Plantillas
            </button>
            <div v-if="showTemplates" class="dns-templates" v-click-away="() => showTemplates = false">
              <p class="dns-templates__title">Registros de correo</p>
              <button @click="applyMailTemplate('spf')"><i class="bi bi-shield-check"></i> SPF (~all)</button>
              <button @click="applyMailTemplate('dmarc')"><i class="bi bi-shield-check"></i> DMARC (p=none)</button>
              <button @click="applyMailTemplate('mx')"><i class="bi bi-envelope"></i> MX (este servidor)</button>
              <div class="dns-templates__sep"></div>
              <button @click="applyMailTemplate('all')"><i class="bi bi-stars"></i> Pack email seguro</button>
            </div>
          </div>
          <button v-if="selectedZone.can_edit" class="dns-btn dns-btn--ghost dns-btn--sm" @click="confirmRegenerate">
            <i class="bi bi-arrow-repeat"></i> Regenerar
          </button>
          <button class="dns-icon-btn" @click="selectedZone = null" title="Cerrar"><i class="bi bi-x-lg"></i></button>
        </div>
      </div>
      <div v-if="loadingRecords" class="dns-loading"><div class="spinner-border spinner-border-sm"></div></div>
      <div v-else class="dns-table-wrap">
        <table class="dns-table dns-table--mono">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Tipo</th>
              <th>Contenido</th>
              <th>TTL</th>
              <th>Prio</th>
              <th v-if="selectedZone.can_edit" style="text-align:right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rec in records" :key="rec.id" :class="{ 'dns-row--editing': inlineEditId === rec.id }">
              <td>{{ rec.name }}</td>
              <td><span :class="typeClass(rec.record_type)">{{ rec.record_type }}</span></td>
              <template v-if="inlineEditId !== rec.id">
                <td style="max-width:280px;word-break:break-all">{{ rec.content }}</td>
                <td style="color:var(--text-muted)">{{ rec.ttl }}</td>
                <td style="color:var(--text-muted)">{{ rec.priority || '—' }}</td>
                <td v-if="selectedZone.can_edit" style="text-align:right">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="dns-icon-btn" @click="startInlineEdit(rec)" title="Editar"><i class="bi bi-pencil"></i></button>
                    <button class="dns-icon-btn dns-icon-btn--danger" @click="confirmDeleteRecord(rec)" title="Eliminar"><i class="bi bi-trash"></i></button>
                  </div>
                </td>
              </template>
              <template v-else>
                <td><input v-model="inlineForm.content" class="form-control form-control-sm font-monospace" @keydown.enter="saveInlineEdit" @keydown.esc="cancelInlineEdit" /></td>
                <td>
                  <select v-model.number="inlineForm.ttl" class="form-select form-select-sm" style="min-width:80px">
                    <option :value="300">300</option><option :value="3600">3600</option>
                    <option :value="14400">14400</option><option :value="86400">86400</option>
                  </select>
                </td>
                <td>
                  <input v-if="['MX','SRV'].includes(rec.record_type)" v-model.number="inlineForm.priority" type="number" class="form-control form-control-sm" min="0" style="width:70px" />
                  <span v-else style="color:var(--text-muted)">—</span>
                </td>
                <td style="text-align:right;white-space:nowrap">
                  <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="dns-btn dns-btn--success dns-btn--sm" @click="saveInlineEdit" :disabled="savingRecord">
                      <span v-if="savingRecord" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-check-lg"></i>
                    </button>
                    <button class="dns-icon-btn" @click="cancelInlineEdit"><i class="bi bi-x-lg"></i></button>
                  </div>
                </td>
              </template>
            </tr>
            <tr v-if="!records.length">
              <td :colspan="selectedZone.can_edit ? 6 : 5" style="text-align:center;padding:1.5rem;color:var(--text-muted)">Sin registros</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>


    <!-- ═══════════════ Modal: Crear / Editar Zona ═══════════════ -->
    <div v-if="showZoneModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-diagram-3 me-2"></i>
              {{ editingZone ? 'Editar Dominio DNS' : 'Nueva Zona DNS' }}
            </h5>
            <button class="btn-close" @click="showZoneModal = false"></button>
          </div>
          <div class="modal-body">
            <div class="row g-3">

              <!-- Dominio -->
              <div class="col-12">
                <label class="form-label fw-semibold">Dominio</label>
                <input
                  v-model="zoneForm.domain_name"
                  type="text"
                  class="form-control"
                  placeholder="ejemplo.com"
                  list="dns-domain-options"
                  :disabled="!!editingZone"
                />
                <datalist id="dns-domain-options">
                  <option v-for="d in domainsWithoutZone" :key="d.id" :value="d.domain_name" />
                </datalist>
                <div v-if="!editingZone" class="form-text">
                  Debe ser un dominio existente de un cliente. Si no aparece, créalo primero
                  en <strong>Dominios</strong> asignándolo a su cliente.
                </div>
              </div>

              <!-- IP -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Dirección IP</label>
                <input
                  v-model="zoneForm.ip_address"
                  type="text"
                  class="form-control font-monospace"
                  placeholder="185.104.188.53"
                />
                <div class="form-text">IP del servidor para los registros A de la zona.</div>
              </div>

              <!-- Plantilla -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Plantilla</label>
                <select v-model="zoneForm.template" class="form-select">
                  <option value="default">Completa (web + correo)</option>
                  <option value="web">Solo web (A + www)</option>
                  <option value="mail">Solo correo (MX + SPF + DMARC)</option>
                  <option value="dns">Solo DNS (NS + A)</option>
                </select>
              </div>

              <!-- SOA NS -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">SOA — Nameserver primario</label>
                <input
                  v-model="zoneForm.soa_ns"
                  type="text"
                  class="form-control font-monospace"
                  placeholder="ns1.svqpanel.local"
                />
                <div class="form-text">Se actualiza también el registro NS primario.</div>
              </div>

              <!-- TTL -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">TTL <small class="text-muted">(segundos)</small></label>
                <select v-model.number="zoneForm.ttl" class="form-select">
                  <option :value="300">300 (5 min — propagación rápida)</option>
                  <option :value="3600">3600 (1 hora)</option>
                  <option :value="14400">14400 (4 horas — recomendado)</option>
                  <option :value="86400">86400 (24 horas)</option>
                </select>
              </div>

              <!-- DNSSEC -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">DNSSEC</label>
                <div class="form-check form-switch mt-1">
                  <input
                    id="dnssecSwitch"
                    v-model="zoneForm.dnssec_enabled"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                  />
                  <label for="dnssecSwitch" class="form-check-label">
                    {{ zoneForm.dnssec_enabled ? 'Habilitado' : 'Deshabilitado' }}
                  </label>
                </div>
                <div class="form-text text-warning small" v-if="zoneForm.dnssec_enabled">
                  <i class="bi bi-exclamation-triangle me-1"></i>
                  Requiere configuración adicional en BIND9.
                </div>
              </div>

              <!-- Fecha expiración -->
              <div class="col-md-6">
                <label class="form-label fw-semibold">Fecha de Expiración <small class="text-muted">(DD-MM-AAAA)</small></label>
                <input
                  v-model="zoneForm.expires_at"
                  type="date"
                  class="form-control"
                />
                <div class="form-text">Fecha de renovación del dominio (solo referencia).</div>
              </div>

            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showZoneModal = false">Cancelar</button>
            <button
              class="btn btn-primary"
              :disabled="savingZone || !zoneForm.domain_name"
              @click="saveZone"
            >
              <span v-if="savingZone" class="spinner-border spinner-border-sm me-2"></span>
              {{ editingZone ? 'Guardar cambios' : 'Crear Zona' }}
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════ Modal: Añadir / Editar Registro ═══════════════ -->
    <div v-if="showRecordModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">{{ editingRecord ? 'Editar Registro DNS' : 'Añadir Registro DNS' }}</h5>
            <button class="btn-close" @click="showRecordModal = false"></button>
          </div>
          <div class="modal-body">
            <template v-if="!editingRecord">
              <div class="mb-3">
                <label class="form-label">Tipo</label>
                <select v-model="recordForm.record_type" class="form-select">
                  <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Nombre <small class="text-muted">(@ para raíz, o subdominio)</small></label>
                <input v-model="recordForm.name" type="text" class="form-control font-monospace" placeholder="@" />
              </div>
            </template>
            <template v-else>
              <div class="mb-3">
                <label class="form-label">Tipo / Nombre <small class="text-muted">(no editable)</small></label>
                <input :value="editingRecord.record_type + ' — ' + editingRecord.name" type="text" class="form-control font-monospace" disabled />
              </div>
            </template>
            <div class="mb-3">
              <label class="form-label">Contenido</label>
              <input v-model="recordForm.content" type="text" class="form-control font-monospace" placeholder="IP, hostname, texto..." />
              <div class="form-text" v-if="recordForm.record_type === 'NS'">
                Recuerda añadir el punto final: <code>ns1.tuservidor.com<strong>.</strong></code>
              </div>
              <div class="form-text" v-if="recordForm.record_type === 'MX'">
                Recuerda añadir el punto final: <code>mail.tudominio.com<strong>.</strong></code>
              </div>
            </div>
            <div class="row g-2">
              <div class="col-6">
                <label class="form-label">TTL</label>
                <select v-model.number="recordForm.ttl" class="form-select">
                  <option :value="300">300</option>
                  <option :value="3600">3600</option>
                  <option :value="14400">14400</option>
                  <option :value="86400">86400</option>
                </select>
              </div>
              <div v-if="['MX','SRV'].includes(recordForm.record_type)" class="col-6">
                <label class="form-label">Prioridad</label>
                <input v-model.number="recordForm.priority" type="number" class="form-control" min="0" />
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showRecordModal = false">Cancelar</button>
            <button class="btn btn-primary" :disabled="savingRecord" @click="saveRecord">
              <span v-if="savingRecord" class="spinner-border spinner-border-sm me-2"></span>
              {{ editingRecord ? 'Guardar' : 'Añadir' }}
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════ Modal: DNSSEC ═══════════════ -->
    <div v-if="showDnssecModal" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-shield-lock me-2"></i>DNSSEC — {{ dnssecZone?.domain_name }}</h5>
            <button class="btn-close" @click="showDnssecModal = false"></button>
          </div>
          <div class="modal-body">
            <div v-if="!dnssecData.cluster" class="alert alert-warning">
              <i class="bi bi-exclamation-triangle me-1"></i>
              DNSSEC requiere un <strong>cluster DNS</strong> configurado (el master firma las zonas).
              Configúralo arriba en «Cluster DNS».
            </div>
            <template v-else>
              <div class="d-flex justify-content-between align-items-center mb-3">
                <div>
                  <strong>Firmar esta zona con DNSSEC</strong>
                  <p class="text-muted small mb-0">El master (ns1) firma la zona; ns2 recibe la copia firmada.</p>
                </div>
                <div class="form-check form-switch">
                  <input class="form-check-input" type="checkbox" role="switch"
                         :checked="dnssecData.enabled" :disabled="dnssecSaving"
                         @change="toggleDnssec($event.target.checked)" style="width:3em;height:1.5em">
                </div>
              </div>

              <div v-if="dnssecData.enabled">
                <div v-if="!dnssecData.signed" class="alert alert-info">
                  <span class="spinner-border spinner-border-sm me-2"></span>
                  Firmando la zona… puede tardar unos segundos. Pulsa «Actualizar» para ver el DS.
                </div>
                <template v-else>
                  <label class="form-label fw-semibold">
                    <i class="bi bi-key me-1"></i>Registro DS — pégalo en tu registrador de dominios
                  </label>
                  <p class="text-muted small">
                    Copia esto en el panel de tu <strong>registrador</strong> (donde compraste el dominio),
                    en la sección DNSSEC/DS. Sin este paso, DNSSEC no se valida de cara a Internet.
                  </p>
                  <div v-for="(ds, i) in dnssecData.ds_records" :key="i" class="input-group mb-2">
                    <input class="form-control font-monospace small" :value="ds" readonly>
                    <button class="btn btn-outline-secondary" @click="copyDs(ds)" title="Copiar"><i class="bi bi-clipboard"></i></button>
                  </div>
                  <p class="small text-success mb-0"><i class="bi bi-check-circle me-1"></i>Zona firmada ({{ dnssecData.dnskeys }} clave(s) DNSKEY activa(s)).</p>
                </template>
              </div>
            </template>
          </div>
          <div class="modal-footer">
            <button v-if="dnssecData.cluster && dnssecData.enabled" class="btn btn-outline-primary" @click="refreshDnssec" :disabled="dnssecLoading">
              <i class="bi" :class="dnssecLoading ? 'bi-hourglass-split' : 'bi-arrow-clockwise'"></i> Actualizar
            </button>
            <button class="btn btn-secondary" @click="showDnssecModal = false">Cerrar</button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════ Modal: Confirmar regenerar plantilla ═══════════════ -->
    <div v-if="showRegenerateConfirm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-warning">
            <h5 class="modal-title"><i class="bi bi-arrow-repeat me-2"></i>Regenerar plantilla DNS</h5>
            <button class="btn-close" @click="showRegenerateConfirm = false"></button>
          </div>
          <div class="modal-body">
            <p>¿Regenerar los registros de <strong>{{ selectedZone?.domain_name }}</strong> con la plantilla <strong>{{ templateLabel(selectedZone?.template) }}</strong>?</p>
            <p class="text-muted small">{{ templateHint(selectedZone?.template) }}</p>
            <p class="text-warning small"><i class="bi bi-exclamation-triangle me-1"></i>Se borrarán todos los registros actuales y se crearán de nuevo con esa plantilla.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showRegenerateConfirm = false">Cancelar</button>
            <button class="btn btn-warning" :disabled="regenerating" @click="regenerateZone">
              <span v-if="regenerating" class="spinner-border spinner-border-sm me-2"></span>
              Regenerar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════ Modal: Confirmar borrado zona ═══════════════ -->
    <div v-if="zoneToDelete" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-danger text-white">
            <h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2"></i>Eliminar Zona DNS</h5>
            <button class="btn-close btn-close-white" @click="zoneToDelete = null"></button>
          </div>
          <div class="modal-body">
            <p>¿Seguro que quieres eliminar la zona <strong>{{ zoneToDelete.domain_name }}</strong>?</p>
            <p class="text-danger small">Se eliminarán todos los registros DNS y el fichero de zona de BIND9.</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="zoneToDelete = null">Cancelar</button>
            <button class="btn btn-danger" :disabled="deletingZone" @click="deleteZone">
              <span v-if="deletingZone" class="spinner-border spinner-border-sm me-2"></span>
              Eliminar Zona
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════ Modal: Confirmar borrado registro ═══════════════ -->
    <div v-if="recordToDelete" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Eliminar Registro DNS</h5>
            <button class="btn-close" @click="recordToDelete = null"></button>
          </div>
          <div class="modal-body">
            ¿Eliminar el registro
            <strong>{{ recordToDelete.record_type }} {{ recordToDelete.name }}</strong>
            → <code>{{ recordToDelete.content }}</code>?
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="recordToDelete = null">Cancelar</button>
            <button class="btn btn-danger" :disabled="deletingRecord" @click="deleteRecord">
              <span v-if="deletingRecord" class="spinner-border spinner-border-sm me-2"></span>
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
import { formatDateTime } from '../utils/datetime'

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA']

const TYPE_CLASSES = {
  A:     'dns-type dns-type--a',
  AAAA:  'dns-type dns-type--aaaa',
  CNAME: 'dns-type dns-type--cname',
  MX:    'dns-type dns-type--mx',
  TXT:   'dns-type dns-type--txt',
  NS:    'dns-type dns-type--ns',
  SRV:   'dns-type dns-type--srv',
  CAA:   'dns-type dns-type--caa',
}

const emptyZoneForm = () => ({
  domain_name:    '',
  ip_address:     '',
  soa_ns:         '',            // vacío = usar el ns1 del panel (backend lo rellena)
  ttl:            14400,
  template:       'default',
  dnssec_enabled: false,
  expires_at:     '',
})

const clickAway = {
  mounted(el, binding) {
    el._away = (e) => { if (!el.contains(e.target)) binding.value(e) }
    setTimeout(() => document.addEventListener('click', el._away), 0)
  },
  unmounted(el) { document.removeEventListener('click', el._away) },
}

export default {
  name: 'DNS',
  directives: { clickAway },
  setup() {
    const store   = useMainStore()
    // Doble check: por role (nuevo) o por is_admin (por si el localStorage es antiguo)
    const isAdmin = computed(() =>
      store.currentUser?.role === 'admin' || store.currentUser?.is_admin === true
    )

    // Zones
    const zones        = ref([])
    const loadingZones = ref(false)

    // Dominios existentes (la zona DNS se ata a un dominio de cliente, no al admin)
    const domains = ref([])
    const loadDomains = async () => {
      try {
        const data = await api.getDomains(null, 0, 1000)
        domains.value = Array.isArray(data) ? data : (data?.domains || data?.items || [])
      } catch (e) { /* no bloqueante */ }
    }
    // Dominios candidatos para una zona: los que NO tienen ya zona creada.
    const domainsWithoutZone = computed(() => {
      const withZone = new Set(zones.value.map(z => z.domain_name))
      return domains.value.filter(d => !withZone.has(d.domain_name))
    })

    // Selected zone + records
    const selectedZone   = ref(null)
    const records        = ref([])
    const loadingRecords = ref(false)

    // Zone modal (create + edit)
    const showZoneModal = ref(false)
    const editingZone   = ref(null)   // null = crear, object = editar
    const zoneForm      = ref(emptyZoneForm())
    const savingZone    = ref(false)

    // Record modal
    const showRecordModal = ref(false)
    const editingRecord   = ref(null)
    const savingRecord    = ref(false)
    const recordForm      = ref({ record_type: 'A', name: '@', content: '', ttl: 14400, priority: 0 })

    // Edición inline de registros
    const inlineEditId = ref(null)
    const inlineForm   = ref({ content: '', ttl: 14400, priority: 0 })

    // Plantillas de correo
    const showTemplates = ref(false)

    // Regenerate zone
    const showRegenerateConfirm = ref(false)
    const regenerating          = ref(false)

    // Delete zone
    const zoneToDelete  = ref(null)
    const deletingZone  = ref(false)

    // Delete record
    const recordToDelete  = ref(null)
    const deletingRecord  = ref(false)

    const recordTypes = RECORD_TYPES

    // ─── helpers ──────────────────────────────────────────────────────────────

    const typeClass = (t) => TYPE_CLASSES[t] || 'bg-secondary'

    // ─── Load ─────────────────────────────────────────────────────────────────

    const loadZones = async () => {
      loadingZones.value = true
      try {
        zones.value = await api.getDnsZones()
      } catch (e) {
        store.showNotification('Error al cargar zonas DNS: ' + e.message, 'danger')
      } finally {
        loadingZones.value = false
      }
    }

    const loadRecords = async (zoneId) => {
      loadingRecords.value = true
      records.value = []
      try {
        records.value = await api.getDnsRecords(zoneId)
      } catch (e) {
        store.showNotification('Error al cargar registros: ' + e.message, 'danger')
      } finally {
        loadingRecords.value = false
      }
    }

    // ─── Zone records panel ───────────────────────────────────────────────────

    const openZoneRecords = async (zone) => {
      selectedZone.value = zone
      await loadRecords(zone.id)
    }

    // ─── Create zone ──────────────────────────────────────────────────────────

    const openCreateZone = () => {
      editingZone.value = null
      zoneForm.value = emptyZoneForm()
      // Prefill el SOA con el ns1 efectivo del panel (no el placeholder)
      if (ns.value.ns1 && !ns.value.is_placeholder) zoneForm.value.soa_ns = ns.value.ns1
      showZoneModal.value = true
    }

    // ─── Edit zone ────────────────────────────────────────────────────────────

    const openEditZone = (zone) => {
      editingZone.value = zone
      zoneForm.value = {
        domain_name:    zone.domain_name,
        ip_address:     zone.ip_address   || '',
        soa_ns:         zone.soa_ns       || ns.value.ns1 || '',
        ttl:            zone.ttl          || 14400,
        template:       zone.template     || 'default',
        dnssec_enabled: zone.dnssec_enabled || false,
        expires_at:     zone.expires_at   || '',
      }
      showZoneModal.value = true
    }

    const saveZone = async () => {
      savingZone.value = true
      try {
        const payload = {
          ip_address:     zoneForm.value.ip_address     || null,
          soa_ns:         zoneForm.value.soa_ns         || null,
          ttl:            zoneForm.value.ttl,
          template:       zoneForm.value.template,
          dnssec_enabled: zoneForm.value.dnssec_enabled,
          expires_at:     zoneForm.value.expires_at     || null,
        }

        if (editingZone.value) {
          // PUT /dns/{id}
          const updated = await api.updateDnsZone(editingZone.value.id, payload)
          store.showNotification(`Zona ${updated.domain_name} actualizada`, 'success')
          // Refrescar zona seleccionada si está abierta
          if (selectedZone.value?.id === editingZone.value.id) {
            selectedZone.value = { ...selectedZone.value, ...updated }
          }
        } else {
          // POST /dns
          const zone = await api.createDnsZone({ domain_name: zoneForm.value.domain_name, ...payload })
          store.showNotification(`Zona ${zone.domain_name} creada`, 'success')
          await openZoneRecords(zone)
        }

        showZoneModal.value = false
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingZone.value = false
      }
    }

    // ─── Delete zone ──────────────────────────────────────────────────────────

    const confirmDeleteZone = (zone) => { zoneToDelete.value = zone }

    const deleteZone = async () => {
      if (!zoneToDelete.value) return
      deletingZone.value = true
      try {
        await api.deleteDnsZone(zoneToDelete.value.id)
        store.showNotification(`Zona ${zoneToDelete.value.domain_name} eliminada`, 'success')
        if (selectedZone.value?.id === zoneToDelete.value.id) selectedZone.value = null
        zoneToDelete.value = null
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        deletingZone.value = false
      }
    }

    // ─── Records ──────────────────────────────────────────────────────────────

    const openAddRecord = () => {
      editingRecord.value = null
      recordForm.value = { record_type: 'A', name: '@', content: '', ttl: 14400, priority: 0 }
      showRecordModal.value = true
    }

    const openEditRecord = (rec) => {
      editingRecord.value = rec
      recordForm.value = {
        record_type: rec.record_type,
        name:        rec.name,
        content:     rec.content,
        ttl:         rec.ttl,
        priority:    rec.priority,
      }
      showRecordModal.value = true
    }

    const saveRecord = async () => {
      if (!selectedZone.value) return
      savingRecord.value = true
      try {
        if (editingRecord.value) {
          await api.updateDnsRecord(selectedZone.value.id, editingRecord.value.id, {
            content:  recordForm.value.content,
            ttl:      recordForm.value.ttl,
            priority: recordForm.value.priority,
          })
          store.showNotification('Registro actualizado', 'success')
        } else {
          await api.addDnsRecord(selectedZone.value.id, recordForm.value)
          store.showNotification('Registro añadido', 'success')
        }
        showRecordModal.value = false
        const updatedZone = await api.getDnsZone(selectedZone.value.id)
        selectedZone.value = { ...selectedZone.value, serial: updatedZone.serial }
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingRecord.value = false
      }
    }

    // ─── Edición inline ─────────────────────────────────────────────────────
    const startInlineEdit = (rec) => {
      inlineEditId.value = rec.id
      inlineForm.value = { content: rec.content, ttl: rec.ttl, priority: rec.priority || 0 }
    }
    const cancelInlineEdit = () => { inlineEditId.value = null }
    const saveInlineEdit = async () => {
      if (!selectedZone.value || inlineEditId.value == null) return
      savingRecord.value = true
      try {
        await api.updateDnsRecord(selectedZone.value.id, inlineEditId.value, {
          content:  inlineForm.value.content,
          ttl:      inlineForm.value.ttl,
          priority: inlineForm.value.priority,
        })
        store.showNotification('Registro actualizado', 'success')
        inlineEditId.value = null
        const updatedZone = await api.getDnsZone(selectedZone.value.id)
        selectedZone.value = { ...selectedZone.value, serial: updatedZone.serial }
        await loadRecords(selectedZone.value.id)
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        savingRecord.value = false
      }
    }

    // ─── Plantillas de correo ───────────────────────────────────────────────
    const applyMailTemplate = async (kind) => {
      if (!selectedZone.value) return
      showTemplates.value = false
      const domain = selectedZone.value.domain_name
      const ns = (selectedZone.value.soa_ns || `mail.${domain}`).replace(/\.$/, '')
      const recs = []
      if (kind === 'mx' || kind === 'all') {
        recs.push({ record_type: 'MX', name: '@', content: `${ns}.`, ttl: 14400, priority: 10 })
      }
      if (kind === 'spf' || kind === 'all') {
        recs.push({ record_type: 'TXT', name: '@', content: 'v=spf1 mx ~all', ttl: 14400, priority: 0 })
      }
      if (kind === 'dmarc' || kind === 'all') {
        recs.push({ record_type: 'TXT', name: '_dmarc', content: `v=DMARC1; p=none; rua=mailto:postmaster@${domain}`, ttl: 14400, priority: 0 })
      }
      try {
        for (const r of recs) await api.addDnsRecord(selectedZone.value.id, r)
        store.showNotification(`${recs.length} registro(s) de correo añadidos`, 'success')
        const updatedZone = await api.getDnsZone(selectedZone.value.id)
        selectedZone.value = { ...selectedZone.value, serial: updatedZone.serial }
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error añadiendo plantilla: ' + e.message, 'danger')
      }
    }

    const confirmDeleteRecord = (rec) => { recordToDelete.value = rec }

    const deleteRecord = async () => {
      if (!recordToDelete.value || !selectedZone.value) return
      deletingRecord.value = true
      try {
        await api.deleteDnsRecord(selectedZone.value.id, recordToDelete.value.id)
        store.showNotification('Registro eliminado', 'success')
        recordToDelete.value = null
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        deletingRecord.value = false
      }
    }

    // ─── Regenerate zone ──────────────────────────────────────────────────────

    const confirmRegenerate = () => { showRegenerateConfirm.value = true }

    // Compat: zonas viejas pueden tener 'minimal' (→ dns).
    const _tplKey = (t) => ({ minimal: 'dns' })[t] || t || 'default'
    const templateLabel = (t) => ({
      dns: 'Solo DNS (NS + A)',
      web: 'Solo web (A + www)',
      mail: 'Solo correo (MX + SPF + DMARC)',
      default: 'Completa (web + correo)',
    })[_tplKey(t)] || 'Completa (web + correo)'

    const templateHint = (t) => ({
      dns: 'Zona mínima: los NS del servidor y el A/AAAA del dominio. Nada más.',
      web: 'Web sin correo: NS, A/AAAA del dominio y CNAME www.',
      mail: 'Solo correo: NS, A/AAAA de mail, MX, SPF, DMARC y webmail. Sin web.',
      default: 'Todo: NS, A/AAAA, CNAME (www/ftp/webmail), MX, SPF, DMARC, SRV y CAA.',
    })[_tplKey(t)] || ''

    const regenerateZone = async () => {
      if (!selectedZone.value) return
      regenerating.value = true
      try {
        const updated = await api.regenerateDnsZone(selectedZone.value.id)
        store.showNotification(`Registros de ${selectedZone.value.domain_name} regenerados`, 'success')
        showRegenerateConfirm.value = false
        selectedZone.value = { ...selectedZone.value, serial: updated.serial }
        await loadRecords(selectedZone.value.id)
        await loadZones()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        regenerating.value = false
      }
    }

    // ── Nameservers del panel (Fase A) ──
    const ns       = ref({ ns1: '', ns2: '', ns1_ip: null, ns2_ip: null, is_placeholder: true })
    const nsForm   = ref({ ns1: '', ns2: '' })
    const nsSaving = ref(false)
    const regenAll = ref(false)

    const loadNameservers = async () => {
      if (!isAdmin.value) return
      try {
        ns.value = await api.getDnsNameservers()
        // Prefill el formulario con los valores configurados (no el placeholder)
        if (!ns.value.is_placeholder) {
          nsForm.value = { ns1: ns.value.ns1, ns2: ns.value.ns2 }
        }
      } catch (e) { /* silencioso */ }
    }

    const saveNameservers = async () => {
      nsSaving.value = true
      try {
        await api.updateSettings({ dns_ns1: nsForm.value.ns1 || null, dns_ns2: nsForm.value.ns2 || null })
        store.showNotification('Nameservers guardados', 'success')
        await loadNameservers()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        nsSaving.value = false
      }
    }

    const regenerateAll = async () => {
      if (!confirm('Reescribirá el SOA y los registros NS de TODAS las zonas con estos nameservers. ¿Continuar?')) return
      regenAll.value = true
      try {
        const r = await api.regenerateAllZones()
        store.showNotification(`${r.updated} zona(s) regenerada(s)` + (r.failed?.length ? `, ${r.failed.length} con error` : ''), r.failed?.length ? 'warning' : 'success')
        await loadZones()
        await loadHealth(true)
      } catch (e) {
        store.showNotification('Error regenerando: ' + e.message, 'danger')
      } finally {
        regenAll.value = false
      }
    }

    // ── Cluster DNS ──
    const cluster        = ref({ enabled: false, replication: null })
    const clusterNodes   = ref([])
    const loadingCluster = ref(false)
    const savingNode     = ref(false)
    const provisioning   = ref(false)
    const testingNodeId  = ref(null)
    const nodeForm       = ref({ role: 'master', hostname: '', ip: '', ssh_user: 'root', ssh_password: '' })

    const loadCluster = async () => {
      if (!isAdmin.value) return
      loadingCluster.value = true
      try {
        const [status, nodes] = await Promise.all([
          api.getDnsClusterStatus(),
          api.getDnsClusterNodes(),
        ])
        cluster.value = status
        clusterNodes.value = nodes
      } catch (e) {
        // silencioso: el cluster es opcional
      } finally {
        loadingCluster.value = false
      }
    }

    // ── Salud de sincronización ──
    const health        = ref({ rows: [], summary: null, allOk: false, checkedAt: null })
    const loadingHealth = ref(false)

    const loadHealth = async (live = false) => {
      if (!isAdmin.value) return
      loadingHealth.value = true
      try {
        const r = await api.getDnsClusterHealth(live)
        health.value = {
          rows: r.rows || [],
          summary: r.summary || null,
          allOk: r.all_ok || false,
          checkedAt: r.checked_at || null,
        }
      } catch (e) {
        // silencioso
      } finally {
        loadingHealth.value = false
      }
    }

    const serialClass = (row, serial) => {
      if (serial == null) return 'text-danger'
      if (serial !== row.db_serial) return 'text-warning fw-semibold'
      return 'text-success'
    }

    const formatHealthTime = (iso) => iso ? formatDateTime(iso) : ''

    // ── DNSSEC ──
    const showDnssecModal = ref(false)
    const dnssecZone      = ref(null)
    const dnssecData      = ref({ cluster: false, enabled: false, signed: false, dnskeys: 0, ds_records: [] })
    const dnssecLoading   = ref(false)
    const dnssecSaving    = ref(false)

    const refreshDnssec = async () => {
      if (!dnssecZone.value) return
      dnssecLoading.value = true
      try {
        dnssecData.value = await api.getDnssec(dnssecZone.value.id)
      } catch (e) {
        store.showNotification('Error leyendo DNSSEC: ' + e.message, 'danger')
      } finally {
        dnssecLoading.value = false
      }
    }

    const openDnssec = async (zone) => {
      dnssecZone.value = zone
      dnssecData.value = { cluster: cluster.value.enabled, enabled: zone.dnssec_enabled, signed: false, dnskeys: 0, ds_records: [] }
      showDnssecModal.value = true
      await refreshDnssec()
    }

    const toggleDnssec = async (enabled) => {
      dnssecSaving.value = true
      try {
        const r = await api.setDnssec(dnssecZone.value.id, enabled)
        store.showNotification(r.message || 'DNSSEC actualizado', 'success')
        // reflejar en la tabla
        const z = zones.value.find(z => z.id === dnssecZone.value.id)
        if (z) z.dnssec_enabled = enabled
        dnssecZone.value.dnssec_enabled = enabled
        // dar unos segundos a que firme y releer
        await new Promise(res => setTimeout(res, enabled ? 4000 : 500))
        await refreshDnssec()
        await loadHealth(true)
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
        await refreshDnssec()
      } finally {
        dnssecSaving.value = false
      }
    }

    const copyDs = (text) => {
      navigator.clipboard?.writeText(text)
      store.showNotification('DS copiado al portapapeles', 'success')
    }

    const addNode = async () => {
      if (!nodeForm.value.hostname || !nodeForm.value.ip) {
        store.showNotification('Indica hostname e IP del nodo', 'danger'); return
      }
      savingNode.value = true
      try {
        await api.addDnsClusterNode({ ...nodeForm.value })
        store.showNotification('Nodo añadido', 'success')
        nodeForm.value = { role: nodeForm.value.role === 'master' ? 'slave' : 'master', hostname: '', ip: '', ssh_user: 'root', ssh_password: '' }
        await loadCluster()
      } catch (e) {
        store.showNotification('Error añadiendo nodo: ' + e.message, 'danger')
      } finally {
        savingNode.value = false
      }
    }

    const testNode = async (n) => {
      testingNodeId.value = n.id
      try {
        const r = await api.testDnsClusterNode(n.id)
        if (r.ok) store.showNotification('Conexión SSH OK con ' + n.hostname, 'success')
        else store.showNotification('Falló: ' + (r.error || 'sin detalle'), 'danger')
        await loadCluster()
      } catch (e) {
        store.showNotification('Error probando nodo: ' + e.message, 'danger')
      } finally {
        testingNodeId.value = null
      }
    }

    const deleteNode = async (n) => {
      if (!confirm(`¿Quitar el nodo ${n.role} ${n.hostname}?`)) return
      try {
        await api.deleteDnsClusterNode(n.id)
        store.showNotification('Nodo eliminado', 'success')
        await loadCluster()
      } catch (e) {
        store.showNotification('Error eliminando nodo: ' + e.message, 'danger')
      }
    }

    const provisionCluster = async () => {
      if (!confirm('Esto instalará y configurará BIND en los nodos y subirá las zonas. ¿Continuar?')) return
      provisioning.value = true
      try {
        const r = await api.provisionDnsCluster()
        store.showNotification(r.message || 'Cluster configurado', 'success')
        await loadCluster()
        await loadHealth(true)
      } catch (e) {
        store.showNotification('Error configurando cluster: ' + e.message, 'danger')
      } finally {
        provisioning.value = false
      }
    }

    const resyncCluster = async () => {
      provisioning.value = true
      try {
        const r = await api.resyncDnsCluster()
        store.showNotification(r.message || 'Zonas resincronizadas', 'success')
        await loadCluster()
      } catch (e) {
        store.showNotification('Error resincronizando: ' + e.message, 'danger')
      } finally {
        provisioning.value = false
      }
    }

    onMounted(() => {
      // En paralelo (no encadenado) para que la página no espere a que termine
      // una llamada antes de empezar la siguiente.
      // loadHealth(false): usa el ÚLTIMO health-check cacheado (rápido, sin SSH).
      // El recálculo EN VIVO (SSH a los nodos) solo lo hace el botón "Comprobar".
      loadZones()
      loadDomains()
      loadNameservers()
      loadCluster()
      loadHealth(false)
    })

    return {
      domainsWithoutZone,
      isAdmin,
      ns, nsForm, nsSaving, regenAll, loadNameservers, saveNameservers, regenerateAll,
      cluster, clusterNodes, loadingCluster, savingNode, provisioning, testingNodeId, nodeForm,
      loadCluster, addNode, testNode, deleteNode, provisionCluster, resyncCluster,
      health, loadingHealth, loadHealth, serialClass, formatHealthTime,
      showDnssecModal, dnssecZone, dnssecData, dnssecLoading, dnssecSaving,
      openDnssec, toggleDnssec, refreshDnssec, copyDs,
      zones, loadingZones,
      selectedZone, records, loadingRecords,
      showZoneModal, editingZone, zoneForm, savingZone,
      showRecordModal, editingRecord, savingRecord, recordForm, recordTypes,
      showRegenerateConfirm, regenerating,
      zoneToDelete, deletingZone,
      recordToDelete, deletingRecord,
      typeClass,
      openZoneRecords, openCreateZone, openEditZone, saveZone, confirmDeleteZone, deleteZone,
      openAddRecord, openEditRecord, saveRecord, confirmDeleteRecord, deleteRecord,
      confirmRegenerate, regenerateZone, templateLabel, templateHint,
      inlineEditId, inlineForm, startInlineEdit, saveInlineEdit, cancelInlineEdit,
      showTemplates, applyMailTemplate,
    }
  }
}
</script>

<style scoped>
.sv-view { display: flex; flex-direction: column; gap: 20px; }

/* ── Layout ── */
.dns-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; }
.dns-title { font-size:1.5rem; font-weight:700; margin:0 0 .25rem; display:flex; align-items:center; gap:.5rem; }
.dns-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }
.dns-hint { font-size:.85rem; color:var(--text-muted); margin:0 0 .75rem; }
.dns-warn-text { color:var(--warning,#d97706); font-size:.82rem; }

/* ── Card ── */
.dns-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); overflow:hidden; }
.dns-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); }
.dns-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }
.dns-card-body { padding:1.25rem; }
.dns-count { background:var(--surface-2); border:1px solid var(--border); border-radius:999px; padding:.1rem .5rem; font-size:.75rem; font-weight:600; }

/* ── Botones ── */
.dns-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--r-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.dns-btn--primary { background:var(--ac); color:#fff; border-color:var(--ac); }
.dns-btn--primary:hover { opacity:.9; }
.dns-btn--ghost { background:var(--surface); color:var(--text-secondary); border-color:var(--border); }
.dns-btn--ghost:hover { background:var(--surface-2); color:var(--text); }
.dns-btn--success { background:color-mix(in srgb,var(--success) 12%,transparent); color:var(--success); border-color:color-mix(in srgb,var(--success) 30%,transparent); }
.dns-btn--success:hover { background:var(--success); color:#fff; }
.dns-btn--sm { padding:.3rem .7rem; font-size:.82rem; }
.dns-btn:disabled { opacity:.5; cursor:not-allowed; }
.dns-icon-btn { width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:var(--r-sm,6px); background:var(--surface); color:var(--text-secondary); cursor:pointer; transition:all .15s; font-size:.875rem; }
.dns-icon-btn:hover { background:var(--surface-2); color:var(--text); }
.dns-icon-btn--danger:hover { background:var(--danger); color:#fff; border-color:var(--danger); }

/* ── Badges ── */
.dns-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; white-space:nowrap; }
.dns-badge--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.dns-badge--off { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); }
.dns-badge--blue { background:color-mix(in srgb,var(--ac) 15%,transparent); color:var(--ac); }
.dns-badge--teal { background:color-mix(in srgb,var(--info,#06b6d4) 15%,transparent); color:var(--info,#06b6d4); }
.dns-badge--warn { background:color-mix(in srgb,var(--warning,#f59e0b) 15%,transparent); color:var(--warning,#d97706); }
.dns-badge--danger { background:color-mix(in srgb,var(--danger) 15%,transparent); color:var(--danger); }

/* ── Tabla ── */
.dns-table-wrap { overflow-x:auto; }
.dns-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.dns-table th { padding:.6rem 1rem; text-align:left; font-size:.75rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); }
.dns-table td { padding:.65rem 1rem; border-bottom:1px solid var(--border); }
.dns-table tr:last-child td { border-bottom:none; }
.dns-table tbody tr:hover { background:var(--surface-2); }
.dns-table--mono td { font-family:var(--font-mono); font-size:.82rem; }
.dns-row--active td { background:color-mix(in srgb,var(--ac) 6%,var(--surface)); }
.dns-row--editing td { background:color-mix(in srgb,var(--ac) 4%,var(--surface)); }

/* ── Formularios inline ── */
.dns-ns-form { display:grid; grid-template-columns:1fr 1fr auto; gap:.75rem; align-items:end; }
.dns-node-form { display:flex; gap:.75rem; align-items:end; flex-wrap:wrap; }
.dns-field { display:flex; flex-direction:column; gap:.3rem; flex:1; min-width:120px; }
.dns-field label { font-size:.78rem; font-weight:600; color:var(--text-secondary); }
.dns-field--actions { flex:0; min-width:auto; }

/* ── Info / empty / loading ── */
.dns-info-box { background:var(--surface-2); border:1px solid var(--border); border-radius:var(--r-sm,6px); padding:.75rem 1rem; font-size:.85rem; }
.dns-glue-table { width:100%; font-family:var(--font-mono); font-size:.78rem; margin-top:.5rem; border-collapse:collapse; }
.dns-glue-table td { padding:.2rem .5rem; color:var(--text-secondary); }
.dns-empty { display:flex; flex-direction:column; align-items:center; gap:.5rem; padding:3rem 1rem; text-align:center; color:var(--text-muted); }
.dns-empty i { font-size:2.5rem; }
.dns-loading { display:flex; justify-content:center; padding:2rem; }

@media (max-width:700px) {
  .dns-ns-form { grid-template-columns:1fr; }
  .dns-node-form { flex-direction:column; }
}
/* Badges de tipo de registro DNS — colores semánticos legibles en light/dark */
.dns-type {
  display: inline-block;
  min-width: 52px; text-align: center;
  padding: 3px 8px;
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  font-family: var(--font-mono);
  letter-spacing: .02em;
  border: 1px solid transparent;
}
.dns-type--a     { background: var(--brand-50);    color: var(--brand-700);  border-color: var(--brand-200); }
.dns-type--aaaa  { background: var(--info-bg);     color: var(--info);       border-color: var(--info-border); }
.dns-type--cname { background: var(--surface-inset); color: var(--text-secondary); border-color: var(--border); }
.dns-type--mx    { background: var(--warning-bg);  color: var(--warning);    border-color: var(--warning-border); }
.dns-type--txt   { background: var(--surface-inset); color: var(--text-muted); border-color: var(--border); }
.dns-type--ns    { background: var(--success-bg);  color: var(--success);    border-color: var(--success-border); }
.dns-type--srv   { background: var(--info-bg);     color: var(--info);       border-color: var(--info-border); }
.dns-type--caa   { background: var(--danger-bg);   color: var(--danger);     border-color: var(--danger-border); }
[data-theme="dark"] .dns-type--a { background: var(--surface-2); color: var(--brand-400); border-color: var(--border-strong); }

/* Dropdown de plantillas de correo */
.dropdown { position: relative; }
.dns-templates {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 60;
  min-width: 240px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-md); box-shadow: var(--shadow-lg); padding: var(--sp-2);
}
.dns-templates__title {
  margin: var(--sp-1) var(--sp-2) var(--sp-2);
  font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .05em;
  color: var(--text-muted); font-weight: var(--fw-semibold);
}
.dns-templates button {
  display: flex; align-items: center; gap: var(--sp-2); width: 100%;
  padding: 8px var(--sp-2); border: none; background: transparent;
  color: var(--text-secondary); font-size: var(--fs-sm); border-radius: var(--r-sm);
  cursor: pointer; text-align: left;
}
.dns-templates button .bi { width: 16px; color: var(--color-primary); }
.dns-templates button:hover { background: var(--surface-inset); color: var(--text); }
.dns-templates__sep { height: 1px; background: var(--border); margin: var(--sp-2) 0; }
</style>
