import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Users from '../views/Users.vue'
import UserAccount from '../views/UserAccount.vue'
import Domains from '../views/Domains.vue'
import Databases from '../views/Databases.vue'
import DNS from '../views/DNS.vue'
import Mail from '../views/Mail.vue'
import Settings from '../views/Settings.vue'
import SystemServices from '../views/SystemServices.vue'
import Security from '../views/Security.vue'
import FileManager from '../views/FileManager.vue'
import Plans from '../views/Plans.vue'
import MySftp from '../views/MySftp.vue'
import Crons from '../views/Crons.vue'
import Backups from '../views/Backups.vue'
import ServerIPs from '../views/ServerIPs.vue'
import Login from '../views/Login.vue'

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
