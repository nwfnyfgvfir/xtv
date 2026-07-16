import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/main.css'
// Imperative Element Plus APIs are not resolved via SFC components — load styles once.
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import { useTheme } from './composables/useTheme'

// apply theme before mount to avoid flash
useTheme()

createApp(App).use(router).mount('#app')
