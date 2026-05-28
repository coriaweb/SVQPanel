<template>
  <div class="container-fluid py-4">
    <div class="d-flex align-items-center mb-3">
      <div>
        <h2 class="mb-1"><i class="bi bi-folder-symlink me-2"></i>Acceso SFTP</h2>
        <p class="text-muted mb-0">
          Gestiona tu acceso SFTP y crea cuentas adicionales para dar acceso a
          carpetas concretas (por ejemplo, a un desarrollador).
        </p>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-body">
        <SftpManager v-if="userId" :user-id="userId" />
        <div v-else class="alert alert-warning mb-0">
          No se pudo determinar tu usuario. Vuelve a iniciar sesión.
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import SftpManager from '../components/SftpManager.vue'

const store = useMainStore()
const userId = computed(() => store.currentUser?.id || null)
</script>
