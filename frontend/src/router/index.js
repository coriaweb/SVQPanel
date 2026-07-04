import { createRouter, createWebHistory } from 'vue-router'
// Dashboard y Login van en el bundle inicial (primera pantalla tras login/auth).
// El resto se cargan bajo demanda (code-splitting) para acelerar el arranque.
import Dashboard from '../views/Dashboard.vue'
import Login from '../views/Login.vue'

const Users          = () => import('../views/Users.vue')
const UserAccount    = () => import('../views/UserAccount.vue')
const Domains        = () => import('../views/Domains.vue')
const DomainDetail   = () => import('../views/DomainDetail.vue')
const Databases      = () => import('../views/Databases.vue')
const DbTuner        = () => import('../views/DbTuner.vue')
const MailQueue      = () => import('../views/MailQueue.vue')
const OutboundMail   = () => import('../views/OutboundMail.vue')
const Antispam       = () => import('../views/Antispam.vue')
const Processes      = () => import('../views/Processes.vue')
const Migrations     = () => import('../views/Migrations.vue')
const DNS            = () => import('../views/DNS.vue')
const Mail           = () => import('../views/Mail.vue')
const Settings       = () => import('../views/Settings.vue')
const License        = () => import('../views/License.vue')
const SystemServices = () => import('../views/SystemServices.vue')
const Logs           = () => import('../views/Logs.vue')
const Security       = () => import('../views/Security.vue')
const Monitoring     = () => import('../views/Monitoring.vue')
const FileManager    = () => import('../views/FileManager.vue')
const Plans          = () => import('../views/Plans.vue')
const MySftp         = () => import('../views/MySftp.vue')
const Crons          = () => import('../views/Crons.vue')
const Backups        = () => import('../views/Backups.vue')
const Terminal       = () => import('../views/Terminal.vue')
const ServerIPs      = () => import('../views/ServerIPs.vue')
const SystemUpdates  = () => import('../views/SystemUpdates.vue')
const ApiTokens      = () => import('../views/ApiTokens.vue')

const isAuthenticated = () => {
  return !!localStorage.getItem('token')
}

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    redirect: () => {
      return isAuthenticated() ? '/dashboard' : '/login'
    }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: Dashboard,
    meta: { requiresAuth: true }
  },
  {
    path: '/users',
    name: 'Users',
    component: Users,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/users/:id/account',
    name: 'UserAccount',
    component: UserAccount,
    meta: { requiresAuth: true, requiresAdminOrOwn: true }
  },
  {
    path: '/domains',
    name: 'Domains',
    component: Domains,
    meta: { requiresAuth: true }
  },
  {
    path: '/domains/:id',
    name: 'DomainDetail',
    component: DomainDetail,
    meta: { requiresAuth: true }
  },
  {
    path: '/files',
    name: 'FileManager',
    component: FileManager,
    meta: { requiresAuth: true }
  },
  {
    path: '/sftp',
    name: 'MySftp',
    component: MySftp,
    meta: { requiresAuth: true }
  },
  {
    path: '/databases',
    name: 'Databases',
    component: Databases,
    meta: { requiresAuth: true }
  },
  {
    path: '/db-tuner',
    name: 'DbTuner',
    component: DbTuner,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/mail-monitor',
    name: 'MailMonitor',
    component: () => import('../views/MailMonitor.vue'),
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/mail-queue',
    name: 'MailQueue',
    component: MailQueue,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/outbound-mail',
    name: 'OutboundMail',
    component: OutboundMail,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/antispam',
    name: 'Antispam',
    component: Antispam,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/processes',
    name: 'Processes',
    component: Processes,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/api-tokens',
    name: 'ApiTokens',
    component: ApiTokens,
    meta: { requiresAuth: true }
  },
  {
    path: '/migrations',
    name: 'Migrations',
    component: Migrations,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/dns',
    name: 'DNS',
    component: DNS,
    meta: { requiresAuth: true }
  },
  {
    path: '/mail',
    name: 'Mail',
    component: Mail,
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/system',
    name: 'SystemServices',
    component: SystemServices,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/logs',
    name: 'Logs',
    component: Logs,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/security',
    name: 'Security',
    component: Security,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/license',
    name: 'License',
    component: License,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/monitoring',
    name: 'Monitoring',
    component: Monitoring,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/plans',
    name: 'Plans',
    component: Plans,
    meta: { requiresAuth: true, requiresAdminOrReseller: true }
  },
  {
    path: '/crons',
    name: 'Crons',
    component: Crons,
    meta: { requiresAuth: true }
  },
  {
    path: '/backups',
    name: 'Backups',
    component: Backups,
    meta: { requiresAuth: true }
  },
  {
    path: '/terminal',
    name: 'Terminal',
    component: Terminal,
    meta: { requiresAuth: true }
  },
  {
    path: '/server-ips',
    name: 'ServerIPs',
    component: ServerIPs,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/system/updates',
    name: 'SystemUpdates',
    component: SystemUpdates,
    meta: { requiresAuth: true, requiresAdmin: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  linkActiveClass: 'is-active-exact',
  linkExactActiveClass: 'is-active-exact'
})

// Chunk viejo tras una actualización del panel: el build borra los JS antiguos
// (nombres con hash), así que una pestaña abierta de ANTES del deploy falla al
// cargar la vista (import dinámico → 404) y el click en el menú "no hace nada"
// hasta recargar. Al detectarlo, navegamos con recarga completa a la ruta
// destino: baja el index.html nuevo con los chunks nuevos y el click funciona.
router.onError((error, to) => {
  const msg = String(error && error.message || '')
  const chunkFailed =
    msg.includes('Failed to fetch dynamically imported module') ||   // Chrome
    msg.includes('error loading dynamically imported module') ||     // Firefox
    msg.includes('Importing a module script failed')                 // Safari
  if (!chunkFailed) return
  // Cortafuegos anti-bucle: si acabamos de recargar por esto mismo (<10s),
  // no reintentar (el fallo sería real, no un chunk desfasado).
  const last = Number(sessionStorage.getItem('svq_chunk_reload') || 0)
  if (Date.now() - last < 10000) return
  sessionStorage.setItem('svq_chunk_reload', String(Date.now()))
  window.location.assign((to && to.fullPath) || window.location.href)
})

router.beforeEach((to, from, next) => {
  const authenticated = isAuthenticated()
  const user = JSON.parse(localStorage.getItem('user') || '{}')

  // Si la ruta requiere autenticación
  if (to.meta.requiresAuth && !authenticated) {
    next('/login')
    return
  }

  // Si la ruta requiere admin
  if (to.meta.requiresAdmin && !user.is_admin) {
    next('/dashboard')
    return
  }

  // Si la ruta requiere ser admin O ser el propio usuario (/users/:id/account)
  if (to.meta.requiresAdminOrOwn) {
    const ownId = parseInt(to.params.id)
    if (!user.is_admin && user.id !== ownId) {
      next('/dashboard')
      return
    }
  }

  // Si la ruta requiere admin o reseller
  if (to.meta.requiresAdminOrReseller && !['admin', 'reseller'].includes(user.role)) {
    next('/dashboard')
    return
  }

  // Si está logueado e intenta acceder a login
  if (to.path === '/login' && authenticated) {
    next('/dashboard')
    return
  }

  next()
})

export default router
