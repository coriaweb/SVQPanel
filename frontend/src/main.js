import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/tokens.css'
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
