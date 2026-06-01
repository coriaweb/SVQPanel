<template>
  <div class="container-fluid py-4">

    <!-- Cabecera -->
    <div class="page-head-row">
      <div>
        <h2 class="mb-1"><i class="bi bi-stack me-2"></i>Planes</h2>
        <p class="text-muted mb-0">
          Plantillas de límites que asignas a los usuarios. Al asignar, los valores
          se <strong>copian</strong> al usuario (snapshot — editar el plan después no
          afecta a usuarios ya asignados).
        </p>
      </div>
      <button class="btn btn-success" @click="openForm()">
        <i class="bi bi-plus-lg me-1"></i> Nuevo plan
      </button>
    </div>

    <!-- Tabla -->
    <div class="card shadow-sm">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-4">
          <div class="spinner-border text-primary"></div>
        </div>
        <div v-else-if="!plans.length" class="text-center py-5 text-muted">
          No hay planes todavía. Crea uno con el botón de arriba.
        </div>
        <table v-else class="table table-hover mb-0">
          <thead class="table-light">
            <tr>
              <th>Nombre</th>
              <th>Propietario</th>
              <th>Disco</th>
              <th>Tráfico/mes</th>
              <th>Dominios</th>
              <th>BDs</th>
              <th>Buzones</th>
              <th>DNS</th>
              <th class="text-center">Usuarios</th>
              <th></th>
              <th class="text-end">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in plans" :key="p.id">
              <td>
                <strong>{{ p.name }}</strong>
                <span v-if="p.is_default" class="badge bg-info ms-2">default</span>
                <div v-if="p.description" class="small text-muted text-truncate" style="max-width: 240px;">
                  {{ p.description }}
                </div>
              </td>
              <td>
                <span v-if="p.owner_id === null" class="badge bg-secondary">global</span>
                <span v-else class="small">
                  <i class="bi bi-person-badge me-1"></i>{{ p.owner_username || p.owner_id }}
                </span>
              </td>
              <td>{{ formatMB(p.disk_quota_mb) }}</td>
              <td>{{ formatMB(p.traffic_quota_mb_month) }}</td>
              <td>{{ unlim(p.domains_limit) }}</td>
              <td>{{ unlim(p.databases_limit) }}</td>
              <td>{{ unlim(p.mailboxes_limit) }}</td>
              <td>{{ unlim(p.dns_zones_limit) }}</td>
              <td class="text-center">
                <span class="badge bg-light text-dark border">{{ p.users_count }}</span>
              </td>
              <td></td>
              <td class="text-end">
                <button class="btn btn-sm btn-outline-secondary me-1" @click="openForm(p)" title="Editar"
                        :disabled="!canEdit(p)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="deletePlan(p)" title="Eliminar"
                        :disabled="!canEdit(p)">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
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
.table th { font-weight: 600; }
</style>
