import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from '@/views/LibraryView.vue'
import DetailView from '@/views/DetailView.vue'
import SettingsView from '@/views/SettingsView.vue'
import SearchView from '@/views/SearchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: LibraryView },
    { path: '/search', name: 'search', component: SearchView },
    { path: '/media/:id', name: 'detail', component: DetailView, props: true },
    { path: '/settings', name: 'settings', component: SettingsView },
  ],
})

export default router
