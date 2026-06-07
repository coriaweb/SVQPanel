<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="pl-head">
      <div>
        <h2 class="pl-title"><i class="bi bi-stack"></i> Planes</h2>
        <p class="pl-subtitle">
          Plantillas de límites que asignas a los usuarios. Al asignar, los valores
          se <strong>copian</strong> al usuario (snapshot).
        </p>
      </div>
      <button class="pl-btn pl-btn--success" @click="openForm()">
        <i class="bi bi-plus-lg"></i> Nuevo plan
      </button>
    </div>

    <div v-if="loading" class="pl-loading"><div class="spinner-border spinner-border-sm"></div></div>
    <div v-else-if="!plans.length" class="pl-empty">
      <i class="bi bi-stack"></i>
      <p>No hay planes todavía. Crea uno con el botón de arriba.</p>
    </div>

    <!-- Tabla en desktop -->
    <div v-else class="pl-card pl-table-wrap">
      <table class="pl-table">
        <thead>
          <tr>
            <th>Nombre</th><th>Propietario</th><th>Disco</th><th>Tráfico/mes</th>
            <th>Dominios</th><th>BDs</th><th>Buzones</th><th>DNS</th>
            <th style="text-align:center">Usuarios</th><th style="text-align:right">Acciones</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in plans" :key="p.id">
            <td>
              <strong>{{ p.name }}</strong>
              <span v-if="p.is_default" class="pl-badge pl-badge--blue">default</span>
              <div v-if="p.description" style="font-size:.78rem;color:var(--text-muted);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ p.description }}</div>
            </td>
            <td>
              <span v-if="p.owner_id === null" class="pl-badge pl-badge--off">global</span>
              <span v-else style="font-size:.82rem"><i class="bi bi-person-badge"></i> {{ p.owner_username || p.owner_id }}</span>
            </td>
            <td>{{ formatMB(p.disk_quota_mb) }}</td>
            <td>{{ formatMB(p.traffic_quota_mb_month) }}</td>
            <td>{{ unlim(p.domains_limit) }}</td>
            <td>{{ unlim(p.databases_limit) }}</td>
            <td>{{ unlim(p.mailboxes_limit) }}</td>
            <td>{{ unlim(p.dns_zones_limit) }}</td>
            <td style="text-align:center"><span class="pl-badge pl-badge--off">{{ p.users_count }}</span></td>
            <td style="text-align:right">
              <div style="display:flex;gap:4px;justify-content:flex-end">
                <button class="pl-icon-btn" @click="openForm(p)" title="Editar" :disabled="!canEdit(p)"><i class="bi bi-pencil"></i></button>
                <button class="pl-icon-btn pl-icon-btn--danger" @click="deletePlan(p)" title="Eliminar" :disabled="!canEdit(p)"><i class="bi bi-trash"></i></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Tarjetas en móvil -->
    <div v-if="!loading && plans.length" class="pl-cards">
      <div v-for="p in plans" :key="'c'+p.id" class="pl-card-item">
        <div class="pl-card-top">
          <div>
            <strong>{{ p.name }}</strong>
            <span v-if="p.is_default" class="pl-badge pl-badge--blue">default</span>
          </div>
          <div style="display:flex;gap:4px">
            <button class="pl-icon-btn" @click="openForm(p)" :disabled="!canEdit(p)"><i class="bi bi-pencil"></i></button>
            <button class="pl-icon-btn pl-icon-btn--danger" @click="deletePlan(p)" :disabled="!canEdit(p)"><i class="bi bi-trash"></i></button>
          </div>
        </div>
        <div v-if="p.description" class="pl-card-desc">{{ p.description }}</div>
        <div class="pl-card-grid">
          <div><span>Propietario</span><b>{{ p.owner_id === null ? 'global' : (p.owner_username || p.owner_id) }}</b></div>
          <div><span>Usuarios</span><b>{{ p.users_count }}</b></div>
          <div><span>Disco</span><b>{{ formatMB(p.disk_quota_mb) }}</b></div>
          <div><span>Tráfico/mes</span><b>{{ formatMB(p.traffic_quota_mb_month) }}</b></div>
          <div><span>Dominios</span><b>{{ unlim(p.domains_limit) }}</b></div>
          <div><span>BDs</span><b>{{ unlim(p.databases_limit) }}</b></div>
          <div><span>Buzones</span><b>{{ unlim(p.mailboxes_limit) }}</b></div>
          <div><span>DNS</span><b>{{ unlim(p.dns_zones_limit) }}</b></div>
        </div>
      </div>
    </div>

    <!-- Modal formulario -->
    <Modal :isOpen="showForm" @close="showForm=false"
           :title="form.id ? `Editar plan «${form.name}»` : 'Nuevo plan'">
      <form @submit.prevent="savePlan">
        <div class="row g-3">
          <div class="col-md-7">
            <label class="form-label small">Nombre</label>
            <input class="form-control form-control-sm" v-model="form.name" required maxlength="64">
          </div>
          <div class="col-md-5" v-if="isAdmin && !form.id">
            <label class="form-label small">Propietario</label>
            <select class="form-select form-select-sm" v-model="form.owner_id">
              <option :value="null">Global (todos los resellers/admin)</option>
              <option v-for="r in resellers" :key="r.id" :value="r.id">
                {{ r.username }} ({{ r.role }})
              </option>
            </select>
          </div>
          <div class="col-12">
            <label class="form-label small">Descripción</label>
            <input class="form-control form-control-sm" v-model="form.description" maxlength="255">
          </div>

          <hr class="my-1">
          <div class="col-12 small text-muted"><i class="bi bi-info-circle me-1"></i>
            0 = sin límite. Las cuotas se cuentan en MB.
          </div>

          <div class="col-md-6">
            <label class="form-label small">Cuota disco (MB)</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.disk_quota_mb" min="0">
          </div>
          <div class="col-md-6">
            <label class="form-label small">Cuota tráfico mensual (MB)</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.traffic_quota_mb_month" min="0">
          </div>

          <div class="col-md-3">
            <label class="form-label small">Dominios</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.domains_limit" min="0">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Bases de datos</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.databases_limit" min="0">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Buzones de correo</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.mailboxes_limit" min="0">
          </div>
          <div class="col-md-3">
            <label class="form-label small">Zonas DNS</label>
            <input type="number" class="form-control form-control-sm" v-model.number="form.dns_zones_limit" min="0">
          </div>

          <div class="col-12">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" v-model="form.is_default" id="pl-def">
              <label class="form-check-label small" for="pl-def">
                Marcar como plan por defecto para este propietario
              </label>
            </div>
          </div>
        </div>

        <div class="text-end mt-3">
          <button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="showForm=false">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
            Guardar
          </button>
        </div>
      </form>
    </Modal>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'
import Modal from '../components/Modal.vue'

const plans     = ref([])
const resellers = ref([])
const loading   = ref(false)
const saving    = ref(false)
const showForm  = ref(false)

const currentUser = JSON.parse(localStorage.getItem('user') || '{}')
const isAdmin     = computed(() => currentUser.role === 'admin')
const isReseller  = computed(() => currentUser.role === 'reseller')

function emptyForm() {
  return {
    id: null,
    name: '',
    description: '',
    owner_id: isReseller.value ? currentUser.user_id : null,
    disk_quota_mb: 1024,
    traffic_quota_mb_month: 10240,
    domains_limit: 5,
    databases_limit: 5,
    mailboxes_limit: 10,
    dns_zones_limit: 10,
    is_default: false,
  }
}

const form = ref(emptyForm())

function formatMB(mb) {
  if (mb === 0) return '∞'
  if (mb >= 1024) return (mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1) + ' GB'
  return mb + ' MB'
}
function unlim(v) { return v === 0 ? '∞' : v }

function canEdit(plan) {
  if (isAdmin.value) return true
  if (isReseller.value) return plan.owner_id === currentUser.user_id
  return false
}

async function load() {
  loading.value = true
  try { plans.value = await api.getPlans() }
  catch (e) { alert('Error cargando planes: ' + e.message) }
  finally  { loading.value = false }

  if (isAdmin.value) {
    try {
      const all = await api.get('/api/users')
      resellers.value = (all || []).filter(u => u.role === 'reseller' || u.role === 'admin')
    } catch (e) { console.error(e) }
  }
}

function openForm(p = null) {
  form.value = p ? { ...p } : emptyForm()
  showForm.value = true
}

async function savePlan() {
  saving.value = true
  try {
    if (form.value.id) {
      const { id, owner_id, owner_username, users_count, created_at, updated_at, ...update } = form.value
      await api.updatePlan(id, update)
    } else {
      await api.createPlan(form.value)
    }
    showForm.value = false
    await load()
  } catch (e) {
    alert('Error: ' + e.message)
  } finally {
    saving.value = false
  }
}

async function deletePlan(p) {
  if (p.users_count > 0 && !confirm(
    `El plan "${p.name}" está asignado a ${p.users_count} usuario(s). ` +
    `Los usuarios se quedarán SIN plan pero conservarán sus límites actuales. ¿Continuar?`
  )) return
  if (!confirm(`¿Eliminar plan "${p.name}"?`)) return
  try {
    await api.deletePlan(p.id)
    await load()
  } catch (e) {
    alert('Error: ' + e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.sv-view { display:flex; flex-direction:column; gap:20px; }

.pl-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap; }
.pl-title { font-size:1.5rem; font-weight:700; margin:0 0 .25rem; display:flex; align-items:center; gap:.5rem; }
.pl-title > .bi:first-child { color:var(--svq-orange); }
.pl-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; max-width:640px; }

.pl-btn { display:inline-flex; align-items:center; gap:6px; padding:.5rem 1rem; border-radius:var(--r-sm,6px); font-size:.9rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.pl-btn--success { background:var(--success); color:#fff; border-color:var(--success); }
.pl-btn--success:hover { opacity:.9; }
.pl-icon-btn { width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:var(--r-sm,6px); background:var(--surface); color:var(--text-secondary); cursor:pointer; transition:all .15s; }
.pl-icon-btn:hover:not(:disabled) { background:var(--surface-2); color:var(--text); }
.pl-icon-btn--danger:hover:not(:disabled) { background:var(--danger); color:#fff; border-color:var(--danger); }
.pl-icon-btn:disabled { opacity:.4; cursor:not-allowed; }

.pl-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); overflow:hidden; }
.pl-table-wrap { overflow-x:auto; }
.pl-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.pl-table th { padding:.65rem 1rem; text-align:left; font-size:.72rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); white-space:nowrap; }
.pl-table td { padding:.7rem 1rem; border-bottom:1px solid var(--border); white-space:nowrap; }
.pl-table tr:last-child td { border-bottom:none; }
.pl-table tbody tr:hover { background:var(--surface-2); }

.pl-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.15rem .5rem; border-radius:999px; font-size:.7rem; font-weight:600; margin-left:6px; }
.pl-badge--blue { background:color-mix(in srgb,var(--ac) 15%,transparent); color:var(--ac); }
.pl-badge--off { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); margin-left:0; }

.pl-loading { display:flex; justify-content:center; padding:2rem; }
.pl-empty { display:flex; flex-direction:column; align-items:center; gap:.5rem; padding:3rem; color:var(--text-muted); text-align:center; }
.pl-empty i { font-size:2.5rem; }

/* Tarjetas móvil */
.pl-cards { display:none; flex-direction:column; gap:12px; }
.pl-card-item { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); padding:1rem; }
.pl-card-top { display:flex; justify-content:space-between; align-items:center; gap:.5rem; margin-bottom:.5rem; }
.pl-card-desc { font-size:.8rem; color:var(--text-muted); margin-bottom:.75rem; }
.pl-card-grid { display:grid; grid-template-columns:1fr 1fr; gap:.6rem 1rem; }
.pl-card-grid > div { display:flex; flex-direction:column; gap:1px; }
.pl-card-grid span { font-size:.72rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:.03em; }
.pl-card-grid b { font-size:.9rem; }

@media (max-width: 860px) {
  .pl-table-wrap { display:none; }
  .pl-cards { display:flex; }
}
</style>
