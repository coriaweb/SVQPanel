<template>
  <div class="container-fluid py-4">

    <!-- Cabecera -->
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h2 class="mb-1"><i class="bi bi-shield-lock me-2"></i>Seguridad</h2>
        <p class="text-muted mb-0">Firewall (nftables), fail2ban, listas IP, conexiones y auditoría</p>
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

    <!-- Resumen -->
    <div class="row g-3 mb-4" v-if="fwStatus">
      <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
        <div class="text-muted small">Reglas activas</div>
        <div class="display-6">{{ fwStatus.rule_count }}</div>
      </div></div></div>
      <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
        <div class="text-muted small">Whitelist</div>
        <div class="display-6">{{ fwStatus.whitelist_count }}</div>
      </div></div></div>
      <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
        <div class="text-muted small">IPs baneadas</div>
        <div class="display-6">{{ fwStatus.banned_count }}</div>
      </div></div></div>
      <div class="col-md-3"><div class="card text-center shadow-sm"><div class="card-body">
        <div class="text-muted small">Jails fail2ban</div>
        <div class="display-6">{{ f2bStatus?.jails?.length || 0 }}</div>
      </div></div></div>
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
        <a class="nav-link" :class="{active: tab==='connections'}" href="#" @click.prevent="changeTab('connections')">
          <i class="bi bi-broadcast me-1"></i> Conexiones
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" :class="{active: tab==='audit'}" href="#" @click.prevent="changeTab('audit')">
          <i class="bi bi-journal-text me-1"></i> Auditoría
        </a>
      </li>
    </ul>

    <!-- ═══════════════════════════ Firewall ═══════════════════════════ -->
    <div v-if="tab==='firewall'">
      <div class="card shadow-sm mb-3">
        <div class="card-header d-flex justify-content-between">
          <h5 class="mb-0">Reglas firewall</h5>
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
    <Modal v-if="showRuleForm" @close="showRuleForm=false" :title="ruleForm.id ? 'Editar regla' : 'Nueva regla'">
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
    <Modal v-if="showIpListForm" @close="showIpListForm=false" :title="ipListForm.id ? 'Editar lista' : 'Nueva lista IP'">
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
    <Modal v-if="showManualBan" @close="showManualBan=false" title="Banear IP manualmente">
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

    <Modal v-if="showAddIgnore" @close="showAddIgnore=false" title="Añadir IP a whitelist permanente">
      <form @submit.prevent="submitAddIgnore">
        <label class="form-label small">IP o CIDR</label>
        <input class="form-control form-control-sm" v-model="ignoreForm.ip" required placeholder="1.2.3.4 o 10.0.0.0/8">
        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showAddIgnore=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="saving">Añadir</button>
        </div>
      </form>
    </Modal>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import Modal from '../components/Modal.vue'

// ─── State ──────────────────────────────────────────────────────────────────
const tab = ref('firewall')

const fwStatus  = ref(null)
const f2bStatus = ref(null)

const rules     = ref([])
const loadingFw = ref(false)

const jails    = ref([])
const banned   = ref([])
const ignoreip = ref([])

const ipLists       = ref([])

const connections   = ref([])
const connListening = ref(true)

const audit         = ref([])
const auditCategory = ref('')

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
})
</script>

<style scoped>
.nav-tabs .nav-link { cursor: pointer; }
</style>
