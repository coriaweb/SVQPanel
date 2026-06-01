import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/tokens.css'
// bootstrap-compat.css existe para una futura retirada total de Bootstrap (Fase 7),
// pero por ahora Bootstrap se carga por CDN y aporta el grid/utilidades.
import './assets/bootstrap-bridge.css'
import App from './App.vue'
import router from './router'

// Aplicar el tema guardado antes de montar para evitar el flash de color
const savedTheme = localStorage.getItem('theme') || 'light'
document.documentElement.dataset.theme = savedTheme

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
