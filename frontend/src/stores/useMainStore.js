import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useMainStore = defineStore('main', () => {
  const notification = ref(null)
  const loading = ref(false)
  const users = ref([])
  const domains = ref([])
  const currentUser = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const token = ref(localStorage.getItem('token') || null)
  const isAuthenticated = ref(!!token.value)

  const showNotification = (message, type = 'success', duration = 3000) => {
    notification.value = { message, type }
    setTimeout(() => {
      notification.value = null
    }, duration)
  }

  const setLoading = (state) => {
    loading.value = state
  }

  const updateUsers = (data) => {
    users.value = data
  }

  const updateDomains = (data) => {
    domains.value = data
  }

  const setCurrentUser = (user) => {
    currentUser.value = user
    if (user) {
      localStorage.setItem('user', JSON.stringify(user))
    }
  }

  const setToken = (newToken) => {
    token.value = newToken
    isAuthenticated.value = !!newToken
    if (newToken) {
      localStorage.setItem('token', newToken)
    } else {
      localStorage.removeItem('token')
    }
  }

  const logout = () => {
    token.value = null
    isAuthenticated.value = false
    currentUser.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return {
    notification,
    loading,
    users,
    domains,
    currentUser,
    token,
    isAuthenticated,
    showNotification,
    setLoading,
    updateUsers,
    updateDomains,
    setCurrentUser,
    setToken,
    logout
  }
})
