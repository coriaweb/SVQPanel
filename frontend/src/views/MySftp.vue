<template>
  <div class="sv-view">
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Acceso SFTP</h1>
        <p class="page-head__sub">
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
