import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Users from '../views/Users.vue'
import Domains from '../views/Domains.vue'
import Settings from '../views/Settings.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/users',
    name: 'Users',
    component: Users
  },
  {
    path: '/domains',
    name: 'Domains',
    component: Domains
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
