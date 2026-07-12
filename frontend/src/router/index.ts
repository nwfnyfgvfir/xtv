import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from '@/views/LibraryView.vue'
import DetailView from '@/views/DetailView.vue'
import SettingsView from '@/views/SettingsView.vue'
import SearchView from '@/views/SearchView.vue'
import LoginView from '@/views/LoginView.vue'
import ActorsView from '@/views/ActorsView.vue'
import ActorDetailView from '@/views/ActorDetailView.vue'
import FavoritesView from '@/views/FavoritesView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: LibraryView },
    { path: '/search', name: 'search', component: SearchView },
    { path: '/media/:id', name: 'detail', component: DetailView, props: true },
    { path: '/actors', name: 'actors', component: ActorsView },
    { path: '/actors/:id', name: 'actor-detail', component: ActorDetailView, props: true },
    { path: '/favorites', name: 'favorites', component: FavoritesView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/login', name: 'login', component: LoginView },
  ],
})

export default router
