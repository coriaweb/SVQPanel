import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useMainStore = defineStore('main', () => {
  const notification = ref(null)
  const loading = ref(false)
  const users = ref([])
  const domains = ref([])
  const currentUser = ref(null)

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
  }

  return {
    notification,
    loading,
    users,
    domains,
    currentUser,
    showNotification,
    setLoading,
    updateUsers,
    updateDomains,
    setCurrentUser
  }
})
