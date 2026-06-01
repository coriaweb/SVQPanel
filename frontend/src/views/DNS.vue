<template>
  <div class="container-fluid py-4">

    <!-- Cabecera -->
    <div class="page-head-row">
      <div>
        <h2 class="mb-1"><i class="bi bi-diagram-3 me-2"></i>DNS</h2>
        <p class="text-muted mb-0">
          {{ zones.length }} {{ zones.length === 1 ? 'zona' : 'zonas' }} · BIND9
        </p>
      </div>
      <button class="btn btn-primary" @click="openCreateZone">
        <i class="bi bi-plus-lg me-1"></i> Nueva Zona
      </button>
    </div>

    <!-- Cluster DNS (solo admin) -->
    <div v-if="isAdmin" class="card shadow-sm mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0"><i class="bi bi-hdd-network me-2"></i>Cluster DNS</h5>
        <span v-if="cluster.enabled" class="badge bg-success">Activo</span>
        <span v-else class="badge bg-light text-muted border">Sin cluster · el panel sirve DNS</span>
      </div>
      <div class="card-body">
        <p class="text-muted small mb-3">
          Sin cluster, este servidor sirve el DNS. Con cluster, las zonas se empujan a
          <strong>ns1 (master)</strong> y este replica a <strong>ns2 (slave)</strong> vía AXFR + TSIG.
          Da de alta los dos nodos (Debian 12, acceso SSH) y pulsa <em>Configurar cluster</em>.
        </p>

        <!-- Tabla de nodos -->
        <table class="table table-sm mb-3">
          <thead class="table-light">
            <tr><th>Rol</th><th>Hostname</th><th>IP</th><th>SSH</th><th>Estado</th><th class="text-end">Acciones</th></tr>
          </thead>
          <tbody>
            <tr v-for="n in clusterNodes" :key="n.id">
              <td><span class="badge" :class="n.role === 'master' ? 'bg-primary' : 'bg-info'">{{ n.role === 'master' ? 'ns1 master' : 'ns2 slave' }}</span></td>
              <td class="font-monospace small">{{ n.hostname }}</td>
              <td class="font-monospace small">{{ n.ip }}</td>
              <td class="small text-muted">{{ n.ssh_user }}:{{ n.ssh_port }}</td>
              <td>
                <span v-if="n.status === 'ok'" class="badge bg-success">OK</span>
                <span v-else-if="n.status === 'error'" class="badge bg-danger" :title="n.last_error">Error</span>
                <span v-else class="badge bg-secondary">Pendiente</span>
              </td>
              <td class="text-end">
                <button class="btn btn-sm btn-outline-secondary me-1" @click="testNode(n)" :disabled="testingNodeId === n.id" title="Probar conexión SSH">
                  <i class="bi bi-plug"></i> {{ testingNodeId === n.id ? '...' : 'Probar' }}
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="deleteNode(n)" title="Quitar nodo"><i class="bi bi-trash"></i></button>
              </td>
            </tr>
            <tr v-if="!clusterNodes.length"><td colspan="6" class="text-center text-muted py-3">Sin nodos. Añade ns1 (master) y ns2 (slave).</td></tr>
          </tbody>
        </table>

        <!-- Alta de nodo -->
        <div class="row g-2 align-items-end mb-3">
          <div class="col-md-2">
            <label class="form-label small mb-1">Rol</label>
            <select v-model="nodeForm.role" class="form-select form-select-sm">
              <option value="master">ns1 (master)</option>
              <option value="slave">ns2 (slave)</option>
            </select>
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-1">Hostname</label>
            <input v-model="nodeForm.hostname" class="form-control form-control-sm font-monospace" placeholder="ns1.tudominio.com" />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1">IP</label>
            <input v-model="nodeForm.ip" class="form-control form-control-sm font-monospace" placeholder="185.x.x.x" />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1">Usuario SSH</label>
            <input v-model="nodeForm.ssh_user" class="form-control form-control-sm" placeholder="root" />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1">Contraseña SSH</label>
            <input v-model="nodeForm.ssh_password" type="password" class="form-control form-control-sm" placeholder="(o usa clave)" />
          </div>
          <div class="col-md-1">
            <button class="btn btn-sm btn-success w-100" @click="addNode" :disabled="savingNode"><i class="bi bi-plus-lg"></i></button>
          </div>
        </div>

        <div class="d-flex gap-2 align-items-center">
          <button class="btn btn-primary btn-sm" @click="provisionCluster" :disabled="provisioning || !clusterNodes.some(n => n.role === 'master')">
            <i class="bi bi-gear-wide-connected me-1"></i> {{ provisioning ? 'Configurando…' : 'Configurar cluster' }}
          </button>
          <button v-if="cluster.enabled" class="btn btn-outline-primary btn-sm" @click="resyncCluster" :disabled="provisioning">
            <i class="bi bi-arrow-repeat me-1"></i> Resincronizar zonas
          </button>
          <button class="btn btn-outline-secondary btn-sm" @click="loadCluster" :disabled="loadingCluster">
            <i class="bi bi-arrow-clockwise"></i>
          </button>
          <span v-if="cluster.replication" class="small ms-2" :class="cluster.replication.ok ? 'text-success' : 'text-warning'">
            <i class="bi" :class="cluster.replication.ok ? 'bi-check-circle' : 'bi-exclamation-triangle'"></i>
            Replicación {{ cluster.replication.ok ? 'OK' : 'pendiente' }} ({{ cluster.replication.sample_domain }})
          </span>
        </div>
      </div>
    </div>

    <!-- Lista de zonas -->
    <div class="card shadow-sm mb-4">
      <div class="card-header"><h5 class="mb-0">Zonas DNS</h5></div>
      <div class="card-body p-0">
        <div v-if="loadingZones" class="text-center py-5">
          <div class="spinner-border text-primary"></div>
        </div>
        <div v-else-if="!zones.length" class="text-center py-5 text-muted">
          <i class="bi bi-diagram-3 display-4"></i>
          <p class="mt-2">No hay zonas DNS configuradas.</p>
          <button class="btn btn-outline-primary btn-sm" @click="openCreateZone">
            Crear primera zona
          </button>
        </div>
        <table v-else class="table table-hover mb-0">
          <thead class="table-light">
            <tr>
              <th>Dominio</th>
              <th>IP</th>
              <th>SOA NS</th>
              <th>Plantilla</th>
              <th>DNSSEC</th>
              <th>Registros</th>
              <th>Serial</th>
              <th class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="zone in zones" :key="zone.id" :class="selectedZone?.id === zone.id ? 'table-primary' : ''">
              <td class="fw-semibold">{{ zone.domain_name }}</td>
              <td class="font-monospace small">{{ zone.ip_address || '—' }}</td>
              <td class="small text-muted">{{ zone.soa_ns || '—' }}</td>
              <td><span class="badge bg-secondary">{{ zone.template || 'default' }}</span></td>
              <td>
                <span v-if="zone.dnssec_enabled" class="badge bg-success"><i class="bi bi-shield-lock me-1"></i>Activo</span>
                <span v-else class="badge bg-light text-muted border">No</span>
              </td>
              <td><span class="badge bg-secondary">{{ zone.record_count }}</span></td>
              <td><code class="text-muted small">{{ zone.serial }}</code></td>
              <td class="text-end">
                <button v-if="zone.can_edit" class="btn btn-sm btn-outline-secondary me-1" @click="openEditZone(zone)" title="Editar zona">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-primary me-1" @click="openZoneRecords(zone)" title="Ver registros">
                  <i class="bi bi-list-ul"></i>
                </button>
                <button v-if="zone.can_edit" class="btn btn-sm btn-outline-danger" @click="confirmDeleteZone(zone)" title="Eliminar zona">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Panel de registros de la zona seleccionada -->
    <div v-if="selectedZone" class="card shadow-sm">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">
          <i class="bi bi-list-ul me-2"></i>
          Registros de <strong>{{ selectedZone.domain_name }}</strong>
          <code class="ms-2 small text-muted">serial {{ selectedZone.serial }}</code>
        </h5>
        <div class="d-flex gap-2">
          <button v-if="selectedZone.can_edit" class="btn btn-sm btn-success" @click="openAddRecord">
            <i class="bi bi-plus-lg me-1"></i> Añadir Registro
          </button>
          <div v-if="selectedZone.can_edit" class="dropdown">
            <button class="btn btn-sm btn-outline-primary dropdown-toggle" @click="showTemplates = !showTemplates">
              <i class="bi bi-magic me-1"></i> Plantillas
            </button>
            <div v-if="showTemplates" class="dns-templates" v-click-away="() => showTemplates = false">
              <p class="dns-templates__title">Añadir registros de correo</p>
              <button @click="applyMailTemplate('spf')"><i class="bi bi-shield-check"></i> SPF (~all)</button>
              <button @click="applyMailTemplate('dmarc')"><i class="bi bi-shield-check"></i> DMARC (p=none)</button>
              <button @click="applyMailTemplate('mx')"><i class="bi bi-envelope"></i> MX (este servidor)</button>
              <div class="dns-templates__sep"></div>
              <button @click="applyMailTemplate('all')"><i class="bi bi-stars"></i> Pack email seguro (MX+SPF+DMARC)</button>
            </div>
          </div>
          <button v-if="selectedZone.can_edit" class="btn btn-sm btn-outline-warning" @click="confirmRegenerate" :title="'Regenerar registros con plantilla ' + (selectedZone.template || 'default')">
            <i class="bi bi-arrow-repeat me-1"></i> Regenerar plantilla
          </button>
          <button class="btn btn-sm btn-outline-secondary" @click="selectedZone = null">
            <i class="bi bi-x"></i> Cerrar
          </button>
        </div>
      </div>
      <div class="card-body p-0">
        <div v-if="loadingRecords" class="text-center py-4">
          <div class="spinner-border spinner-border-sm text-primary"></div>
        </div>
        <table v-else class="table table-sm table-hover mb-0 font-monospace">
          <thead class="table-light">
            <tr>
              <th>Nombre</th>
              <th>Tipo</th>
              <th>Contenido</th>
              <th>TTL</th>
              <th>Prio</th>
              <th v-if="selectedZone.can_edit" class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rec in records" :key="rec.id" :class="{ 'table-active': inlineEditId === rec.id }">
              <td>{{ rec.name }}</td>
              <td><span :class="typeClass(rec.record_type)" class="badge">{{ rec.record_type }}</span></td>

              <!-- Modo lectura -->
              <template v-if="inlineEditId !== rec.id">
                <td class="text-break" style="max-width:280px;">{{ rec.content }}</td>
                <td class="text-muted">{{ rec.ttl }}</td>
                <td class="text-muted">{{ rec.priority || '—' }}</td>
                <td v-if="selectedZone.can_edit" class="text-end">
                  <button class="btn btn-sm btn-outline-secondary me-1" @click="startInlineEdit(rec)" title="Editar aquí">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteRecord(rec)" title="Eliminar">
                    <i class="bi bi-trash"></i>
                  </button>
                </td>
              </template>

              <!-- Modo edición inline -->
              <template v-else>
                <td><input v-model="inlineForm.content" class="form-control form-control-sm font-monospace" @keydown.enter="saveInlineEdit" @keydown.esc="cancelInlineEdit" /></td>
                <td>
                  <select v-model.number="inlineForm.ttl" class="form-select form-select-sm" style="min-width:90px">
                    <option :value="300">300</option><option :value="3600">3600</option>
                    <option :value="14400">14400</option><option :value="86400">86400</option>
                  </select>
                </td>
                <td>
                  <input v-if="['MX','SRV'].includes(rec.record_type)" v-model.number="inlineForm.priority" type="number" class="form-control form-control-sm" min="0" style="width:70px" />
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="text-end" style="white-space:nowrap">
                  <button class="btn btn-sm btn-success me-1" @click="saveInlineEdit" :disabled="savingRecord" title="Guardar">
                    <span v-if="savingRecord" class="spinner-border spinner-border-sm"></span>
                    <i v-else class="bi bi-check-lg"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-secondary" @click="cancelInlineEdit" title="Cancelar">
                    <i class="bi bi-x-lg"></i>
                  </button>
                </td>
              </template>
            </tr>
            <tr v-if="!records.length">
              <td :colspan="selectedZone.can_edit ? 6 : 5" class="text-center text-muted py-3">Sin registros</td>
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
                  :disabled="!!editingZone"
                />
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
                  <option value="default">BIND9 (default)</option>
                  <option value="minimal">Mínima (solo NS + A)</option>
                  <option value="mail">Con correo (NS + A + MX + SPF)</option>
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


    <!-- ═══════════════ Modal: Confirmar regenerar plantilla ═══════════════ -->
    <div v-if="showRegenerateConfirm" class="modal d-block" tabindex="-1" style="background:rgba(0,0,0,.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-warning">
            <h5 class="modal-title"><i class="bi bi-arrow-repeat me-2"></i>Regenerar plantilla DNS</h5>
            <button class="btn-close" @click="showRegenerateConfirm = false"></button>
          </div>
          <div class="modal-body">
            <p>¿Regenerar los registros de <strong>{{ selectedZone?.domain_name }}</strong> con la plantilla <strong>{{ selectedZone?.template || 'default' }}</strong>?</p>
            <p class="text-warning small"><i class="bi bi-exclamation-triangle me-1"></i>Se borrarán todos los registros actuales y se crearán de nuevo con la plantilla Hestia.</p>
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
  soa_ns:         'ns1.svqpanel.local',
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
      showZoneModal.value = true
    }

    // ─── Edit zone ────────────────────────────────────────────────────────────

    const openEditZone = (zone) => {
      editingZone.value = zone
      zoneForm.value = {
        domain_name:    zone.domain_name,
        ip_address:     zone.ip_address   || '',
        soa_ns:         zone.soa_ns       || 'ns1.svqpanel.local',
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

    onMounted(async () => { await loadZones(); await loadCluster() })

    return {
      isAdmin,
      cluster, clusterNodes, loadingCluster, savingNode, provisioning, testingNodeId, nodeForm,
      loadCluster, addNode, testNode, deleteNode, provisionCluster, resyncCluster,
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
      confirmRegenerate, regenerateZone,
      inlineEditId, inlineForm, startInlineEdit, saveInlineEdit, cancelInlineEdit,
      showTemplates, applyMailTemplate,
    }
  }
}
</script>

<style scoped>
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
