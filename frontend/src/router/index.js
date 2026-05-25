import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Users from '../views/Users.vue'
import UserAccount from '../views/UserAccount.vue'
import Domains from '../views/Domains.vue'
import Settings from '../views/Settings.vue'
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
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/domains',
    name: 'Domains',
    component: Domains,
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
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

  // Si está logueado e intenta acceder a login
  if (to.path === '/login' && authenticated) {
    next('/dashboard')
    return
  }

  next()
})

export default router
