<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <h1>SVQPanel</h1>
        <p class="version">v0.1.0</p>
      </div>

      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="username">Usuario</label>
          <input
            id="username"
            v-model="credentials.username"
            type="text"
            class="form-control"
            placeholder="Ingresa tu usuario"
            required
          />
        </div>

        <div class="form-group">
          <label for="password">Contraseña</label>
          <input
            id="password"
            v-model="credentials.password"
            type="password"
            class="form-control"
            placeholder="Ingresa tu contraseña"
            required
          />
        </div>

        <div v-if="error" class="alert alert-danger">
          <i class="bi bi-exclamation-circle"></i> {{ error }}
        </div>

        <button
          type="submit"
          class="btn btn-primary btn-login"
          :disabled="loading"
        >
          <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
          {{ loading ? 'Autenticando...' : 'Iniciar Sesión' }}
        </button>
      </form>

      <div class="login-footer">
        <p class="text-muted">SVQPanel © 2026 - Panel de Control de Servidores</p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'Login',
  setup() {
    const router = useRouter()
    const store = useMainStore()
    const credentials = ref({
      username: '',
      password: ''
    })
    const loading = ref(false)
    const error = ref(null)

    const handleLogin = async () => {
      error.value = null
      loading.value = true

      try {
        const response = await api.login(credentials.value)

        // Guardar token en localStorage
        localStorage.setItem('token', response.access_token)
        localStorage.setItem('user', JSON.stringify({
          id: response.user_id,
          username: response.username,
          email: response.email,
          role: response.role,
          is_admin: response.is_admin
        }))

        // Actualizar store
        store.setCurrentUser({
          id: response.user_id,
          username: response.username,
          email: response.email,
          role: response.role,
          is_admin: response.is_admin
        })
        store.setToken(response.access_token)

        // Redirect a dashboard
        await router.push('/dashboard')
        store.showNotification(`¡Bienvenido ${response.username}!`, 'success')
      } catch (err) {
        error.value = err.message || 'Error al iniciar sesión'
        store.showNotification(error.value, 'danger')
      } finally {
        loading.value = false
      }
    }

    return {
      credentials,
      loading,
      error,
      handleLogin
    }
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
}

.login-card {
  background: white;
  border-radius: 10px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 100%;
  max-width: 400px;
  padding: 40px;
}

.login-header {
  text-align: center;
  margin-bottom: 30px;
}

.login-header h1 {
  margin: 0;
  font-size: 2em;
  font-weight: 700;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.login-header .version {
  margin: 5px 0 0 0;
  color: #999;
  font-size: 0.9em;
}

.login-form {
  margin-bottom: 20px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 5px;
  font-weight: 500;
  color: #333;
}

.form-control {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 5px;
  font-size: 1em;
  transition: border-color 0.3s;
}

.form-control:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.btn-login {
  width: 100%;
  padding: 12px;
  font-size: 1em;
  font-weight: 600;
  border: none;
  border-radius: 5px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.btn-login:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
}

.btn-login:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.alert {
  margin-bottom: 15px;
  padding: 12px;
  border-radius: 5px;
}

.alert-danger {
  background-color: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.login-footer {
  text-align: center;
  border-top: 1px solid #eee;
  padding-top: 20px;
  margin-top: 20px;
}

.login-footer .text-muted {
  margin: 0;
  font-size: 0.85em;
  color: #999;
}
</style>
