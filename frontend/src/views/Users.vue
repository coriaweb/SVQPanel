<template>
  <div class="sv-view">
    <!-- Cabecera page-head -->
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Usuarios</h1>
        <p class="page-head__sub">{{ users.length }} {{ users.length === 1 ? 'usuario' : 'usuarios' }} en el panel</p>
      </div>
      <BaseButton variant="primary" size="sm" @click="openCreateForm">
        <i class="bi bi-person-plus"></i> Crear usuario
      </BaseButton>
    </div>

    <BaseCard title="Usuarios del panel" icon="people" flush>
      <div v-if="loading" class="us-center"><div class="spinner-border spinner-border-sm"></div></div>

      <EmptyState v-else-if="users.length === 0" icon="people"
                  title="Sin usuarios"
                  description="No hay usuarios creados aún. Crea el primero con «Crear usuario»." />

      <div v-else class="us-table-wrap">
        <table class="us-table">
          <thead>
            <tr>
              <th>Usuario</th>
              <th>Plan</th>
              <th>Rol</th>
              <th>Dominios</th>
              <th style="min-width:160px">Disco</th>
              <th style="min-width:160px">Tráfico (mes)</th>
              <th>Estado</th>
              <th>Último acceso</th>
              <th class="us-right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id" :class="{ 'us-row--suspended': user.is_suspended }">
              <td>
                <div class="us-user">
                  <i class="bi bi-person-circle"></i>
                  <div>
                    <div class="us-name">{{ user.username }}</div>
                    <div class="us-muted">{{ user.email }}</div>
                    <div v-if="user.first_name || user.last_name" class="us-muted">
                      {{ [user.first_name, user.last_name].filter(Boolean).join(' ') }}
                    </div>
                  </div>
                </div>
              </td>
              <td>
                <span v-if="user.plan_name" class="us-tag us-tag--plan">{{ user.plan_name }}</span>
                <span v-else class="us-muted">—</span>
              </td>
              <td>
                <span class="us-tag" :class="roleTagClass(user.role)">{{ roleLabel(user.role) }}</span>
              </td>
              <td class="us-muted">
                <i class="bi bi-globe2"></i>
                {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}
              </td>
              <td>
                <UsageBar :used="user.disk_used_mb || 0" :quota="user.disk_quota_mb || 0" />
                <div v-if="(user.disk_used_mb || 0) > 0" class="us-breakdown" :title="diskBreakdownTitle(user)">
                  <span><i class="bi bi-globe2"></i> {{ fmtMB(user.disk_web_mb) }}</span>
                  <span><i class="bi bi-envelope"></i> {{ fmtMB(user.disk_mail_mb) }}</span>
                  <span><i class="bi bi-database"></i> {{ fmtMB(user.disk_db_mb) }}</span>
                </div>
              </td>
              <td><UsageBar :used="user.traffic_used_mb_month || 0" :quota="user.traffic_quota_mb_month || 0" /></td>
              <td>
                <span v-if="user.is_suspended" class="us-status us-status--suspended">
                  <i class="bi bi-pause-circle-fill"></i> Suspendido
                </span>
                <span v-else class="us-status" :class="user.is_active ? 'us-status--on' : 'us-status--off'">
                  {{ user.is_active ? 'Activo' : 'Inactivo' }}
                </span>
              </td>
              <td class="us-muted" style="font-size:.8rem;white-space:nowrap" :title="user.last_login ? 'Último login correcto al panel' : 'Nunca ha iniciado sesión (o antes de activarse el registro)'">
                {{ fmtLastLogin(user.last_login) }}
              </td>
              <td class="us-right">
                <div class="us-actions">
                  <BaseButton variant="secondary" size="sm" @click="goToAccount(user.id)" title="Gestionar cuenta">
                    <i class="bi bi-box-arrow-in-right"></i> Gestionar
                  </BaseButton>
                  <button v-if="!user.is_admin && !user.is_suspended" class="us-iconbtn us-iconbtn--warn"
                          title="Suspender (corta webs, correo, BD, accesos)" @click="suspendUser(user)">
                    <i class="bi bi-pause-circle"></i>
                  </button>
                  <button v-else-if="!user.is_admin" class="us-iconbtn us-iconbtn--ok"
                          title="Reactivar" @click="unsuspendUser(user)">
                    <i class="bi bi-play-circle"></i>
                  </button>
                  <button class="us-iconbtn" title="Editar" @click="openEditForm(user)"><i class="bi bi-pencil"></i></button>
                  <button class="us-iconbtn us-iconbtn--danger" title="Eliminar" @click="deleteUserConfirm(user)"><i class="bi bi-trash"></i></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <!-- User Form Modal -->
    <Modal :isOpen="showUserForm" :title="editingUser ? 'Editar Usuario' : 'Crear Usuario'" @close="closeUserForm">
      <UserForm
        :user="editingUser"
        @submit="handleUserSubmit"
        @cancel="closeUserForm"
      />
    </Modal>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'
import UsageBar from '../components/UsageBar.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import EmptyState from '../components/ui/EmptyState.vue'

export default {
  name: 'Users',
  components: {
    Modal,
    UserForm,
    UsageBar,
    BaseCard,
    BaseButton,
    EmptyState
  },
  setup() {
    const store = useMainStore()
    const router = useRouter()
    const users = ref([])
    const loading = ref(false)
    const showUserForm = ref(false)
    const editingUser = ref(null)

    const roleLabel = (role) => {
      switch (role) {
        case 'admin': return 'Admin'
        case 'reseller': return 'Reseller'
        default: return 'Usuario'
      }
    }

    const fmtMB = (mb) => {
      mb = mb || 0
      return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
    }
    const diskBreakdownTitle = (u) =>
      `Web: ${fmtMB(u.disk_web_mb)} · Correo: ${fmtMB(u.disk_mail_mb)} · BD: ${fmtMB(u.disk_db_mb)}`

    const fmtLastLogin = (dt) => {
      if (!dt) return '—'
      // El backend guarda UTC naive (sin zona): añadir Z para que se muestre en hora local
      const iso = /Z$|[+-]\d{2}:\d{2}$/.test(dt) ? dt : dt + 'Z'
      return new Date(iso).toLocaleString('es-ES', {
        day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
      })
    }

    const roleTagClass = (role) => {
      switch (role) {
        case 'admin': return 'us-tag--admin'
        case 'reseller': return 'us-tag--reseller'
        default: return 'us-tag--user'
      }
    }

    const loadUsers = async () => {
      loading.value = true
      try {
        const data = await api.getUsers(0, 100)
        users.value = Array.isArray(data) ? data : []
      } catch (error) {
        store.showNotification('Error al cargar usuarios', 'danger')
      } finally {
        loading.value = false
      }
    }

    const goToAccount = (userId) => {
      router.push(`/users/${userId}/account`)
    }

    const openCreateForm = () => {
      editingUser.value = null
      showUserForm.value = true
    }

    const openEditForm = (user) => {
      editingUser.value = user
      showUserForm.value = true
    }

    const closeUserForm = () => {
      showUserForm.value = false
      editingUser.value = null
    }

    const handleUserSubmit = async () => {
      await loadUsers()
      closeUserForm()
    }

    const deleteUserConfirm = (user) => {
      if (confirm(`¿Eliminar usuario "${user.username}"?\n\nEsto eliminará también su cuenta del sistema y todos sus archivos.`)) {
        deleteUser(user.id)
      }
    }

    const deleteUser = async (userId) => {
      try {
        await api.deleteUser(userId)
        store.showNotification('Usuario eliminado', 'success')
        loadUsers()
      } catch (error) {
        store.showNotification('Error al eliminar usuario: ' + error.message, 'danger')
      }
    }

    const suspendUser = async (user) => {
      if (!confirm(`¿Suspender a "${user.username}"?\n\nSe cortarán sus webs (página de cortesía), su correo, sus bases de datos y sus accesos (panel, SSH/FTP). No se borra nada y es reversible.`)) return
      try {
        await api.post(`/api/users/${user.id}/suspend`, {})
        store.showNotification(`Usuario "${user.username}" suspendido`, 'success')
        loadUsers()
      } catch (e) {
        store.showNotification('Error al suspender: ' + (e.message || e), 'danger')
      }
    }
    const unsuspendUser = async (user) => {
      try {
        await api.post(`/api/users/${user.id}/unsuspend`, {})
        store.showNotification(`Usuario "${user.username}" reactivado`, 'success')
        loadUsers()
      } catch (e) {
        store.showNotification('Error al reactivar: ' + (e.message || e), 'danger')
      }
    }

    onMounted(loadUsers)

    return {
      users,
      loading,
      showUserForm,
      editingUser,
      roleLabel,
      roleTagClass,
      fmtMB,
      diskBreakdownTitle,
      fmtLastLogin,
      goToAccount,
      openCreateForm,
      openEditForm,
      closeUserForm,
      handleUserSubmit,
      deleteUserConfirm,
      suspendUser,
      unsuspendUser,
    }
  }
}
</script>

<style scoped>
/* Cabecera */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: var(--sp-5); flex-wrap: wrap; }
.page-head__title { font-size: 1.5rem; font-weight: var(--fw-bold, 700); margin: 0; letter-spacing: -.01em; }
.page-head__sub { color: var(--text-muted); margin: .25rem 0 0; font-size: var(--fs-sm); }

.us-center { display: flex; justify-content: center; padding: var(--sp-6) 0; color: var(--text-muted); }
.us-muted { color: var(--text-muted); font-size: var(--fs-sm); }

/* Tabla */
.us-table-wrap { overflow-x: auto; }
.us-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.us-table thead th { text-align: left; padding: var(--sp-3) var(--sp-4); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: var(--fw-semibold); border-bottom: 1px solid var(--border); white-space: nowrap; }
.us-table tbody td { padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); vertical-align: middle; }
.us-table tbody tr:last-child td { border-bottom: none; }
.us-table tbody tr:hover { background: var(--surface-inset); }
.us-right { text-align: right; }

.us-user { display: flex; align-items: center; gap: var(--sp-3); }
.us-user > i { font-size: 1.6rem; color: var(--text-muted); flex-shrink: 0; }
.us-name { font-weight: var(--fw-semibold); color: var(--text); }

/* Tags de rol y plan */
.us-tag { display: inline-block; font-size: var(--fs-xs); font-weight: var(--fw-semibold); padding: 2px 9px; border-radius: var(--r-pill); }
.us-tag--admin    { background: var(--danger-bg); color: var(--danger); }
.us-tag--reseller { background: var(--warning-bg); color: var(--warning); }
.us-tag--user     { background: var(--surface-inset); color: var(--text-secondary); }
.us-tag--plan     { background: var(--brand-50); color: var(--color-primary); }

/* Estado */
.us-breakdown { display: flex; gap: .6rem; margin-top: 3px; font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.us-breakdown i { opacity: .7; margin-right: 1px; }
.us-status { display: inline-block; font-size: var(--fs-xs); font-weight: var(--fw-semibold); padding: 2px 9px; border-radius: var(--r-pill); }
.us-status--on  { background: var(--success-bg); color: var(--success); }
.us-status--off { background: var(--danger-bg); color: var(--danger); }
.us-status--suspended { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); display:inline-flex; align-items:center; gap:4px; }

/* Fila de usuario suspendido: tono ámbar tenue para distinguirla de un vistazo */
.us-row--suspended > td { background: color-mix(in srgb, var(--warning) 7%, transparent); }
.us-row--suspended .us-name { opacity: .7; }

/* Acciones */
.us-actions { display: inline-flex; align-items: center; gap: 4px; }
.us-iconbtn { width: 32px; height: 32px; display: inline-grid; place-items: center; border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary); border-radius: var(--r-sm); cursor: pointer; transition: all .12s; }
.us-iconbtn:hover { background: var(--surface-inset); color: var(--text); border-color: var(--border-strong); }
.us-iconbtn--danger:hover { color: var(--danger); border-color: var(--danger); }
.us-iconbtn--warn:hover { color: var(--warning); border-color: var(--warning); }
.us-iconbtn--ok { color: var(--success); }
.us-iconbtn--ok:hover { border-color: var(--success); }
</style>
