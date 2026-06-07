<template>
  <div class="sv-view">

    <!-- Cabecera -->
    <div class="ua-head">
      <div style="display:flex;align-items:center;gap:1rem">
        <button class="ua-back-btn" @click="$router.back()">
          <i class="bi bi-arrow-left"></i> Volver
        </button>
        <div v-if="user">
          <h2 class="ua-title">
            <i class="bi bi-person-circle"></i> {{ user.username }}
            <span class="ua-badge" :class="roleBadgeClass(user.role)" style="font-size:.85rem;margin-left:.5rem">{{ roleLabel(user.role) }}</span>
          </h2>
          <p class="ua-subtitle">{{ user.email }}</p>
        </div>
        <div v-else-if="loadingUser" class="spinner-border spinner-border-sm"></div>
      </div>
      <button v-if="user" class="ua-btn ua-btn--ghost ua-btn--sm" @click="showEditUser = true">
        <i class="bi bi-pencil"></i> Editar usuario
      </button>
    </div>

    <div v-if="user" class="ua-layout">

      <!-- Sidebar info -->
      <aside class="ua-sidebar">
        <div class="ua-card">
          <div class="ua-card-title"><i class="bi bi-info-circle"></i> Información</div>
          <div class="ua-info-list">
            <div class="ua-info-row">
              <span>Rol</span>
              <span class="ua-badge" :class="roleBadgeClass(user.role)">{{ roleLabel(user.role) }}</span>
            </div>
            <div class="ua-info-row">
              <span>Estado</span>
              <span class="ua-badge" :class="user.is_active ? 'ua-badge--on' : 'ua-badge--danger'">
                {{ user.is_active ? 'Activo' : 'Inactivo' }}
              </span>
            </div>
            <div v-if="user.role === 'reseller'" class="ua-info-row">
              <span>Clientes</span>
              <strong>{{ clients.length }}</strong>
            </div>
            <div v-else class="ua-info-row">
              <span>Dominios</span>
              <strong>{{ domains.length }} / {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}</strong>
            </div>
            <div class="ua-info-row">
              <span>Creado</span>
              <span style="font-size:.8rem;color:var(--text-muted)">{{ formatDate(user.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- Uso de disco (cuota) -->
        <div v-if="user.role !== 'reseller'" class="ua-card">
          <div class="ua-card-title"><i class="bi bi-hdd"></i> Disco</div>
          <div style="padding:1rem">
            <div v-if="diskUsage === null" style="font-size:.85rem;color:var(--text-muted)">
              <span class="spinner-border spinner-border-sm"></span> Calculando…
            </div>
            <template v-else>
              <div style="display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:.4rem">
                <strong>{{ fmtMB(diskUsage.used_mb) }}</strong>
                <span style="color:var(--text-muted)">
                  de {{ diskUsage.limit_mb ? fmtMB(diskUsage.limit_mb) : '∞' }}
                </span>
              </div>
              <div class="ua-bar">
                <div class="ua-bar__fill"
                     :class="diskBarClass"
                     :style="{ width: Math.min(100, diskUsage.percent || 0) + '%' }"></div>
              </div>
              <div style="display:flex;justify-content:space-between;margin-top:.4rem;font-size:.75rem;color:var(--text-muted)">
                <span v-if="diskUsage.limit_mb">{{ diskUsage.percent }}% usado</span>
                <span v-else>Sin límite</span>
                <span v-if="diskUsage.over_quota" style="color:var(--danger);font-weight:600">
                  <i class="bi bi-exclamation-triangle"></i> Cuota llena
                </span>
              </div>
              <p v-if="diskUsage.active === false" style="font-size:.72rem;color:var(--warning,#d97706);margin:.5rem 0 0">
                <i class="bi bi-info-circle"></i> Las cuotas del sistema no están activas:
                el límite es informativo (no se aplica en el SO).
              </p>
            </template>
          </div>
        </div>
      </aside>

      <!-- Panel principal -->
      <main class="ua-main">

        <!-- RESELLER: clientes -->
        <template v-if="user.role === 'reseller'">
          <div class="ua-card">
            <div class="ua-card-head">
              <span class="ua-card-title"><i class="bi bi-people"></i> Clientes de {{ user.username }}</span>
              <button class="ua-btn ua-btn--primary ua-btn--sm" @click="showAddClient = true">
                <i class="bi bi-person-plus"></i> Añadir cliente
              </button>
            </div>
            <div v-if="loadingClients" class="ua-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <div v-else-if="clients.length === 0" class="ua-empty">
              <i class="bi bi-people"></i><span>Este reseller no tiene clientes aún</span>
            </div>
            <div v-else class="ua-table-wrap">
              <table class="ua-table">
                <thead><tr><th>Usuario</th><th>Email</th><th>Dominios</th><th>Estado</th><th style="text-align:right">Acciones</th></tr></thead>
                <tbody>
                  <tr v-for="client in clients" :key="client.id">
                    <td><strong>{{ client.username }}</strong></td>
                    <td style="color:var(--text-muted)">{{ client.email }}</td>
                    <td>{{ client.domains_limit === 0 ? '∞' : client.domains_limit }}</td>
                    <td><span class="ua-badge" :class="client.is_active ? 'ua-badge--on' : 'ua-badge--danger'">{{ client.is_active ? 'Activo' : 'Inactivo' }}</span></td>
                    <td style="text-align:right">
                      <div style="display:flex;gap:4px;justify-content:flex-end">
                        <button class="ua-btn ua-btn--ghost ua-btn--sm" @click="$router.push(`/users/${client.id}/account`)">
                          <i class="bi bi-box-arrow-in-right"></i> Gestionar
                        </button>
                        <button class="ua-icon-btn ua-icon-btn--danger" @click="deleteClientConfirm(client)"><i class="bi bi-trash"></i></button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- USER: SFTP + 2FA + Dominios -->
        <template v-else>

          <div class="ua-card">
            <div class="ua-card-head">
              <span class="ua-card-title"><i class="bi bi-folder-symlink"></i> Acceso SFTP</span>
            </div>
            <div style="padding:1rem">
              <SftpManager :user-id="user.id" />
            </div>
          </div>

          <div v-if="isOwnAccount" class="ua-card">
            <div class="ua-card-head">
              <span class="ua-card-title"><i class="bi bi-shield-lock"></i> Autenticación de doble factor (2FA)</span>
            </div>
            <div style="padding:1rem">
              <TwoFactorManager />
            </div>
          </div>

          <div class="ua-card">
            <div class="ua-card-head">
              <span class="ua-card-title"><i class="bi bi-globe2"></i> Dominios de {{ user.username }}</span>
              <button class="ua-btn ua-btn--primary ua-btn--sm" @click="showAddDomain = true">
                <i class="bi bi-plus-lg"></i> Añadir dominio
              </button>
            </div>
            <div v-if="loadingDomains" class="ua-loading"><div class="spinner-border spinner-border-sm"></div></div>
            <div v-else-if="domains.length === 0" class="ua-empty">
              <i class="bi bi-globe2"></i><span>Este usuario no tiene dominios</span>
            </div>
            <div v-else class="ua-table-wrap">
              <table class="ua-table">
                <thead><tr><th>Dominio</th><th>PHP</th><th>SSL</th><th>IPv6</th><th>Estado</th><th style="text-align:right">Acciones</th></tr></thead>
                <tbody>
                  <tr v-for="domain in domains" :key="domain.id">
                    <td>
                      <a :href="'http://' + domain.domain_name" target="_blank" style="font-weight:600;color:var(--ac);text-decoration:none">
                        {{ domain.domain_name }}
                      </a>
                    </td>
                    <td><span class="ua-badge ua-badge--blue">PHP {{ domain.php_version || '8.2' }}</span></td>
                    <td>
                      <span class="ua-badge" :class="domain.ssl_enabled ? 'ua-badge--on' : 'ua-badge--off'">
                        <i :class="domain.ssl_enabled ? 'bi bi-lock-fill' : 'bi bi-unlock'"></i>
                        {{ domain.ssl_enabled ? 'SSL' : 'No' }}
                      </span>
                    </td>
                    <td>
                      <span v-if="domain.ipv6" class="ua-badge ua-badge--blue" :title="domain.ipv6">IPv6</span>
                      <span v-else class="ua-badge ua-badge--off">—</span>
                    </td>
                    <td>
                      <span class="ua-badge" :class="domain.is_active ? 'ua-badge--on' : 'ua-badge--danger'">
                        {{ domain.is_active ? 'Activo' : 'Inactivo' }}
                      </span>
                    </td>
                    <td style="text-align:right">
                      <button class="ua-btn ua-btn--ghost ua-btn--sm" @click="openDomainManager(domain)">
                        <i class="bi bi-sliders"></i> Gestionar
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </main>
    </div>

    <!-- Modal: Gestionar Dominio -->
    <div v-if="showDomainManager && selectedDomain" class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.55)" @click.self="closeDomainManager">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-globe me-2"></i>{{ selectedDomain.domain_name }}</h5>
            <button type="button" class="btn-close" @click="closeDomainManager"></button>
          </div>
          <div class="modal-body p-0">

            <div class="ua-modal-section">
              <div class="ua-modal-section-title"><i class="bi bi-info-circle"></i> Información</div>
              <div class="ua-meta-grid">
                <span>Ruta web</span><code style="font-size:.8rem">/home/{{ user.username }}/web/{{ selectedDomain.domain_name }}/public_html</code>
                <span>Creado</span><span>{{ formatDate(selectedDomain.created_at) }}</span>
                <template v-if="selectedDomain.ipv6">
                  <span>IPv6</span><code style="font-size:.8rem;color:var(--ac)">{{ selectedDomain.ipv6 }}</code>
                </template>
              </div>
            </div>

            <div class="ua-modal-section">
              <div class="ua-modal-section-title"><i class="bi bi-filetype-php"></i> Versión PHP</div>
              <form @submit.prevent="handleChangePHP" style="display:flex;gap:.5rem;align-items:flex-end">
                <select v-model="phpVersion" class="form-select form-select-sm" style="max-width:240px">
                  <option v-for="v in phpAvailableVersions" :key="v" :value="v">PHP {{ v }}</option>
                </select>
                <button type="submit" class="btn btn-sm btn-primary" :disabled="changingPHP">
                  <span v-if="changingPHP" class="spinner-border spinner-border-sm"></span>
                  <i v-else class="bi bi-check-lg"></i> Aplicar
                </button>
              </form>
              <small style="color:var(--text-muted);font-size:.78rem;margin-top:.25rem;display:block">Actual: PHP {{ selectedDomain.php_version || '8.2' }}</small>
            </div>

            <div class="ua-modal-section">
              <div class="ua-modal-section-title"><i class="bi bi-lock"></i> Certificado SSL</div>
              <div v-if="selectedDomain.ssl_enabled" style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap">
                <span class="ua-badge ua-badge--on" style="font-size:.85rem"><i class="bi bi-lock-fill"></i> SSL activo</span>
                <span v-if="selectedDomain.ssl_expires" style="font-size:.82rem;color:var(--text-muted)">Expira: {{ formatDate(selectedDomain.ssl_expires) }}</span>
                <button class="btn btn-sm btn-outline-danger" style="margin-left:auto" @click="handleDeleteSSL" :disabled="sslLoading">
                  <span v-if="sslLoading" class="spinner-border spinner-border-sm"></span>
                  <i v-else class="bi bi-x-circle"></i> Revocar
                </button>
              </div>
              <div v-else>
                <span class="ua-badge ua-badge--off" style="margin-bottom:.75rem;display:inline-flex"><i class="bi bi-unlock"></i> Sin SSL</span>
                <br>
                <button class="btn btn-sm btn-success" @click="handleCreateSSL" :disabled="sslLoading">
                  <span v-if="sslLoading" class="spinner-border spinner-border-sm"></span>
                  <i v-else class="bi bi-shield-check"></i> Instalar Let's Encrypt
                </button>
                <small style="display:block;margin-top:.35rem;color:var(--text-muted)">El dominio debe resolver a este servidor.</small>
              </div>
            </div>

            <div class="ua-modal-section">
              <div class="ua-modal-section-title"><i class="bi bi-diagram-3"></i> IPv6 dedicada</div>
              <IPv6Manager :domain="selectedDomain" @reload="onDomainReload" />
            </div>

            <div class="ua-modal-section ua-modal-section--danger">
              <div class="ua-modal-section-title" style="color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> Zona de peligro</div>
              <div v-if="!confirmDeleteDomain">
                <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteDomain = true">
                  <i class="bi bi-trash"></i> Eliminar dominio
                </button>
                <small style="display:block;margin-top:.35rem;color:var(--danger)">Eliminará el dominio, archivos y configuración nginx.</small>
              </div>
              <div v-else class="alert alert-danger mb-0">
                <p class="mb-2 fw-bold">¿Confirmar eliminación de <em>{{ selectedDomain.domain_name }}</em>?</p>
                <p class="small mb-3">Se eliminarán todos los archivos en <code>/home/{{ user.username }}/web/{{ selectedDomain.domain_name }}/</code></p>
                <div style="display:flex;gap:.5rem">
                  <button class="btn btn-danger btn-sm" @click="handleDeleteDomain" :disabled="deletingDomain">
                    <span v-if="deletingDomain" class="spinner-border spinner-border-sm"></span>
                    Sí, eliminar
                  </button>
                  <button class="btn btn-secondary btn-sm" @click="confirmDeleteDomain = false">Cancelar</button>
                </div>
              </div>
            </div>

          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeDomainManager">Cerrar</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: editar usuario -->
    <Modal :isOpen="showEditUser" title="Editar Usuario" @close="showEditUser = false">
      <UserForm :user="user" @submit="onUserUpdated" @cancel="showEditUser = false" />
    </Modal>

    <!-- Modal: añadir cliente -->
    <Modal :isOpen="showAddClient" title="Añadir Cliente" @close="showAddClient = false">
      <UserForm :parentId="user?.id" @submit="onClientAdded" @cancel="showAddClient = false" />
    </Modal>

    <!-- Modal: añadir dominio -->
    <Modal :isOpen="showAddDomain" title="Añadir Dominio" @close="showAddDomain = false">
      <form @submit.prevent="handleAddDomain">
        <div class="mb-3">
          <label class="form-label">Nombre de dominio</label>
          <input v-model="newDomain.domain_name" type="text" class="form-control" placeholder="ejemplo.com" required />
        </div>
        <div class="mb-3">
          <label class="form-label">Versión PHP</label>
          <select v-model="newDomain.php_version" class="form-select">
            <option v-for="v in phpAvailableVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </div>
        <div style="display:flex;gap:.5rem">
          <button type="submit" class="btn btn-primary" :disabled="addingDomain">
            <span v-if="addingDomain" class="spinner-border spinner-border-sm me-1"></span>
            Crear dominio
          </button>
          <button type="button" class="btn btn-secondary" @click="showAddDomain = false">Cancelar</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'
import IPv6Manager from '../components/IPv6Manager.vue'
import SftpManager from '../components/SftpManager.vue'
import TwoFactorManager from '../components/TwoFactorManager.vue'

export default {
  name: 'UserAccount',
  components: { Modal, UserForm, IPv6Manager, SftpManager, TwoFactorManager },
  setup() {
    const route = useRoute()
    const store = useMainStore()
    const userId = parseInt(route.params.id)

    // ¿El usuario viendo esta página es el propio dueño de la cuenta?
    const currentUser = store.currentUser || JSON.parse(localStorage.getItem('user') || '{}')
    const isOwnAccount = computed(() => currentUser?.id === userId)

    const user           = ref(null)
    const clients        = ref([])
    const domains        = ref([])
    const diskUsage      = ref(null)
    const loadingUser    = ref(true)
    const loadingClients = ref(false)
    const loadingDomains = ref(false)

    const showEditUser       = ref(false)
    const showAddClient      = ref(false)
    const showAddDomain      = ref(false)
    const addingDomain       = ref(false)
    const newDomain          = ref({ domain_name: '', php_version: '8.2' })

    // Domain manager modal
    const showDomainManager  = ref(false)
    const selectedDomain     = ref(null)

    // PHP
    const phpVersion           = ref('8.2')
    const changingPHP          = ref(false)
    const phpAvailableVersions = ref(['7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'])

    // SSL
    const sslLoading = ref(false)

    // Delete domain
    const confirmDeleteDomain = ref(false)
    const deletingDomain      = ref(false)

    // ─── Helpers ────────────────────────────────────────────────────────────
    const roleLabel     = (role) => ({ admin: '🔑 Admin', reseller: '🏪 Reseller', user: '👤 Usuario' }[role] ?? role)
    const roleBadgeClass= (role) => ({ admin: 'bg-danger', reseller: 'bg-warning text-dark', user: 'bg-secondary' }[role] ?? 'bg-secondary')
    const formatDate    = (d) => d ? new Date(d).toLocaleDateString('es-ES', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

    // ─── Load data ──────────────────────────────────────────────────────────
    const loadUser = async () => {
      loadingUser.value = true
      try { user.value = await api.getUser(userId) }
      catch (e) { store.showNotification('Error al cargar usuario', 'danger') }
      finally { loadingUser.value = false }
    }

    const loadClients = async () => {
      loadingClients.value = true
      try {
        const data = await api.getUsers(0, 100, null, userId)
        clients.value = Array.isArray(data) ? data : []
      } catch (e) { store.showNotification('Error al cargar clientes', 'danger') }
      finally { loadingClients.value = false }
    }

    const loadDomains = async () => {
      loadingDomains.value = true
      try {
        const data = await api.getDomains(userId, 0, 100)
        domains.value = Array.isArray(data) ? data : []
      } catch (e) { store.showNotification('Error al cargar dominios', 'danger') }
      finally { loadingDomains.value = false }
    }

    const loadPHPVersions = async () => {
      try {
        const data = await api.getPHPVersions()
        if (data?.versions?.length) phpAvailableVersions.value = data.versions
      } catch { /* usa la lista por defecto */ }
    }

    // ─── Uso de disco (cuota) ──────────────────────────────────────────────
    const loadDiskUsage = async () => {
      try {
        diskUsage.value = await api.get(`/api/users/${userId}/disk-usage`)
      } catch {
        diskUsage.value = { active: false, used_mb: 0, limit_mb: user.value?.disk_quota_mb || 0, percent: 0, over_quota: false }
      }
    }
    const fmtMB = (mb) => {
      if (mb == null) return '—'
      return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : Math.round(mb) + ' MB'
    }
    const diskBarClass = computed(() => {
      const p = diskUsage.value?.percent || 0
      if (p >= 95) return 'ua-bar__fill--danger'
      if (p >= 80) return 'ua-bar__fill--warn'
      return 'ua-bar__fill--ok'
    })

    // ─── Domain manager ─────────────────────────────────────────────────────
    const openDomainManager = (domain) => {
      selectedDomain.value = { ...domain }
      phpVersion.value = domain.php_version || '8.2'
      confirmDeleteDomain.value = false
      showDomainManager.value = true
    }

    const closeDomainManager = () => {
      showDomainManager.value = false
      selectedDomain.value = null
    }

    // Cuando IPv6Manager emite reload, refrescamos dominio y lista
    const onDomainReload = async () => {
      await loadDomains()
      // Actualizar selectedDomain con los datos frescos
      if (selectedDomain.value) {
        const fresh = domains.value.find(d => d.id === selectedDomain.value.id)
        if (fresh) selectedDomain.value = { ...fresh }
      }
    }

    // ─── PHP ────────────────────────────────────────────────────────────────
    const handleChangePHP = async () => {
      changingPHP.value = true
      try {
        await api.changePHPVersion(selectedDomain.value.id, phpVersion.value)
        selectedDomain.value.php_version = phpVersion.value
        store.showNotification(`PHP cambiado a ${phpVersion.value}`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al cambiar PHP: ' + e.message, 'danger')
      } finally {
        changingPHP.value = false
      }
    }

    // ─── SSL ────────────────────────────────────────────────────────────────
    const handleCreateSSL = async () => {
      sslLoading.value = true
      try {
        await api.createSSL(selectedDomain.value.id, {})
        store.showNotification('SSL instalado correctamente', 'success')
        await onDomainReload()
      } catch (e) {
        store.showNotification('Error al instalar SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    const handleDeleteSSL = async () => {
      sslLoading.value = true
      try {
        await api.deleteSSL(selectedDomain.value.id)
        store.showNotification('SSL revocado', 'success')
        await onDomainReload()
      } catch (e) {
        store.showNotification('Error al revocar SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    // ─── Delete domain ───────────────────────────────────────────────────────
    const handleDeleteDomain = async () => {
      deletingDomain.value = true
      try {
        await api.deleteDomain(selectedDomain.value.id)
        store.showNotification('Dominio eliminado', 'success')
        closeDomainManager()
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al eliminar: ' + e.message, 'danger')
      } finally {
        deletingDomain.value = false
      }
    }

    // ─── Add domain ──────────────────────────────────────────────────────────
    const handleAddDomain = async () => {
      addingDomain.value = true
      try {
        await api.createDomain({
          user_id: userId,
          domain_name: newDomain.value.domain_name,
          php_version: newDomain.value.php_version
        })
        store.showNotification('Dominio creado', 'success')
        showAddDomain.value = false
        newDomain.value = { domain_name: '', php_version: '8.2' }
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        addingDomain.value = false
      }
    }

    // ─── User actions ────────────────────────────────────────────────────────
    const onUserUpdated = async () => { showEditUser.value = false; await loadUser() }
    const onClientAdded = async () => { showAddClient.value = false; await loadClients() }

    const deleteClientConfirm = (client) => {
      if (confirm(`¿Eliminar cliente "${client.username}"?\nEsto eliminará también sus dominios y archivos.`)) {
        api.deleteUser(client.id)
          .then(() => { store.showNotification('Cliente eliminado', 'success'); loadClients() })
          .catch(e => store.showNotification('Error: ' + e.message, 'danger'))
      }
    }

    // ─── Init ────────────────────────────────────────────────────────────────
    onMounted(async () => {
      await loadUser()
      await loadPHPVersions()
      if (user.value?.role === 'reseller') {
        await loadClients()
      } else {
        await loadDomains()
        loadDiskUsage()
      }
    })

    return {
      user, clients, domains, diskUsage, fmtMB, diskBarClass,
      loadingUser, loadingClients, loadingDomains,
      showEditUser, showAddClient, showAddDomain, addingDomain, newDomain,
      showDomainManager, selectedDomain,
      phpVersion, changingPHP, phpAvailableVersions,
      sslLoading,
      confirmDeleteDomain, deletingDomain,
      roleLabel, roleBadgeClass, formatDate,
      openDomainManager, closeDomainManager, onDomainReload,
      handleChangePHP, handleCreateSSL, handleDeleteSSL,
      handleDeleteDomain, handleAddDomain,
      onUserUpdated, onClientAdded, deleteClientConfirm,
      isOwnAccount,
    }
  }
}
</script>

<style scoped>
.sv-view { display:flex; flex-direction:column; gap:20px; }

/* Layout */
.ua-head { display:flex; justify-content:space-between; align-items:center; gap:1rem; flex-wrap:wrap; }
.ua-title { font-size:1.4rem; font-weight:700; margin:0 0 .15rem; display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }
.ua-subtitle { font-size:.875rem; color:var(--text-muted); margin:0; }
.ua-layout { display:grid; grid-template-columns:240px 1fr; gap:20px; align-items:start; }
.ua-sidebar { display:flex; flex-direction:column; gap:16px; }
.ua-main { display:flex; flex-direction:column; gap:16px; }

/* Back button */
.ua-back-btn { background:none; border:1px solid var(--border); border-radius:var(--r-sm,6px); padding:.3rem .75rem; font-size:.82rem; cursor:pointer; color:var(--text-secondary); transition:all .15s; white-space:nowrap; }
.ua-back-btn:hover { background:var(--surface-2); color:var(--text); }

/* Buttons */
.ua-btn { display:inline-flex; align-items:center; gap:6px; padding:.4rem .9rem; border-radius:var(--r-sm,6px); font-size:.875rem; font-weight:500; cursor:pointer; border:1px solid transparent; transition:all .15s; }
.ua-btn--primary { background:var(--ac); color:#fff; border-color:var(--ac); }
.ua-btn--primary:hover { opacity:.9; }
.ua-btn--ghost { background:var(--surface); color:var(--text-secondary); border-color:var(--border); }
.ua-btn--ghost:hover { background:var(--surface-2); color:var(--text); }
.ua-btn--sm { padding:.3rem .65rem; font-size:.82rem; }
.ua-icon-btn { width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:var(--r-sm,6px); background:var(--surface); color:var(--text-secondary); cursor:pointer; transition:all .15s; }
.ua-icon-btn--danger:hover { background:var(--danger); color:#fff; border-color:var(--danger); }

/* Cards */
.ua-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md,10px); overflow:hidden; }
.ua-card-head { display:flex; align-items:center; justify-content:space-between; padding:.875rem 1.25rem; border-bottom:1px solid var(--border); }
.ua-card-title { font-weight:600; font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
/* Cuando el título va suelto (tarjeta de disco), darle el padding del head */
.ua-card > .ua-card-title { padding:.875rem 1.25rem; border-bottom:1px solid var(--border); }

/* Barra de uso de disco */
.ua-bar { height:8px; background:var(--surface-2); border-radius:999px; overflow:hidden; }
.ua-bar__fill { height:100%; border-radius:999px; transition:width .3s ease; }
.ua-bar__fill--ok    { background:var(--success); }
.ua-bar__fill--warn  { background:var(--warning,#f59e0b); }
.ua-bar__fill--danger{ background:var(--danger); }

/* Sidebar info */
.ua-info-list { display:flex; flex-direction:column; }
.ua-info-row { display:flex; justify-content:space-between; align-items:center; padding:.6rem 1.25rem; border-bottom:1px solid var(--border); font-size:.875rem; }
.ua-info-row:last-child { border-bottom:none; }
.ua-info-row span:first-child { color:var(--text-muted); }

/* Badges */
.ua-badge { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }
.ua-badge--on { background:color-mix(in srgb,var(--success) 15%,transparent); color:var(--success); }
.ua-badge--off { background:var(--surface-2); color:var(--text-muted); border:1px solid var(--border); }
.ua-badge--danger { background:color-mix(in srgb,var(--danger) 15%,transparent); color:var(--danger); }
.ua-badge--blue { background:color-mix(in srgb,var(--ac) 15%,transparent); color:var(--ac); }

/* Table */
.ua-table-wrap { overflow-x:auto; }
.ua-table { width:100%; border-collapse:collapse; font-size:.875rem; }
.ua-table th { padding:.6rem 1rem; text-align:left; font-size:.75rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid var(--border); background:var(--surface-2); }
.ua-table td { padding:.65rem 1rem; border-bottom:1px solid var(--border); }
.ua-table tr:last-child td { border-bottom:none; }
.ua-table tbody tr:hover { background:var(--surface-2); }

/* Modal sections */
.ua-modal-section { padding:1rem 1.25rem; border-bottom:1px solid var(--border); }
.ua-modal-section:last-child { border-bottom:none; }
.ua-modal-section--danger { background:color-mix(in srgb,var(--danger) 4%,transparent); }
.ua-modal-section-title { font-size:.75rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--text-muted); margin-bottom:.75rem; display:flex; align-items:center; gap:.4rem; }
.ua-meta-grid { display:grid; grid-template-columns:120px 1fr; gap:.35rem .75rem; font-size:.85rem; }
.ua-meta-grid span:nth-child(odd) { color:var(--text-muted); }

/* Empty / loading */
.ua-empty { display:flex; align-items:center; gap:.75rem; padding:1.5rem; color:var(--text-muted); font-size:.875rem; }
.ua-empty i { font-size:1.5rem; }
.ua-loading { display:flex; justify-content:center; padding:1.5rem; }

@media (max-width:768px) {
  .ua-layout { grid-template-columns:1fr; }
}
</style>
