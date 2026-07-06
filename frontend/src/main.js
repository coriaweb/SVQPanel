import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/tokens.css'
// bootstrap-compat.css existe para una futura retirada total de Bootstrap (Fase 7),
// pero por ahora Bootstrap se carga por CDN y aporta el grid/utilidades.
import './assets/bootstrap-bridge.css'
import App from './App.vue'
import router from './router'
import { useMainStore } from './stores/useMainStore'

// Aplicar el tema guardado antes de montar para evitar el flash de color
const savedTheme = localStorage.getItem('theme') || 'light'
document.documentElement.dataset.theme = savedTheme

const app = createApp(App)

app.use(createPinia())
app.use(router)

// Cargar la marca blanca (endpoint público) antes de montar para evitar el
// flash de la marca por defecto. Si la API tarda >1s, montamos igualmente
// y la marca se aplica cuando llegue.
const store = useMainStore()
Promise.race([
  store.loadBranding(),
  new Promise(resolve => setTimeout(resolve, 1000)),
]).finally(() => app.mount('#app'))
