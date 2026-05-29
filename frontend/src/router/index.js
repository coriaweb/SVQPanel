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
const DNS            = () => import('../views/DNS.vue')
const Mail           = () => import('../views/Mail.vue')
const Settings       = () => import('../views/Settings.vue')
const SystemServices = () => import('../views/SystemServices.vue')
const Security       = () => import('../views/Security.vue')
const FileManager    = () => import('../views/FileManager.vue')
const Plans          = () => import('../views/Plans.vue')
const MySftp         = () => import('../views/MySftp.vue')
const Crons          = () => import('../views/Crons.vue')
const Backups        = () => import('../views/Backups.vue')
const ServerIPs      = () => import('../views/ServerIPs.vue')
const SystemUpdates  = () => import('../views/SystemUpdates.vue')

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
    path: '/security',
    name: 'Security',
    component: Security,
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
  routes
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
