<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listLibraries, reorderLibraries } from '@/api/media'
import type { Library } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'

const emit = defineEmits<{ saved: [libraries: Library[]] }>()
const libraries = ref<Library[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const list = ref<HTMLUListElement | null>(null)
const draggingId = ref<number | null>(null)
let drag: { pointer: number; original: Library[] } | null = null

async function load() {
  loading.value = true
  error.value = ''
  try {
    libraries.value = await listLibraries()
  } catch (cause) {
    error.value = getErrorMessage(cause, '无法读取媒体库')
  } finally {
    loading.value = false
  }
}

async function save(original: Library[]) {
  if (libraries.value.every((lib, index) => lib.id === original[index]?.id)) return
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    libraries.value = await reorderLibraries(libraries.value.map((lib) => lib.id))
    saved.value = true
    emit('saved', libraries.value)
  } catch (cause) {
    libraries.value = original
    error.value = getErrorMessage(cause, '排序保存失败，已恢复原顺序')
  } finally {
    saving.value = false
  }
}

function move(from: number, to: number) {
  if (from === to || from < 0 || to < 0 || to >= libraries.value.length) return
  const next = [...libraries.value]
  next.splice(to, 0, ...next.splice(from, 1))
  libraries.value = next
}

function startDrag(event: PointerEvent, id: number) {
  if (event.button !== 0 || !event.isPrimary || loading.value || saving.value || drag || libraries.value.length < 2) return
  drag = { pointer: event.pointerId, original: [...libraries.value] }
  draggingId.value = id
  saved.value = false
  list.value?.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function moveDrag(event: PointerEvent) {
  if (!drag || drag.pointer !== event.pointerId || !list.value) return
  const rows = [...list.value.querySelectorAll<HTMLLIElement>('li')]
  const target = rows.findIndex((row) => {
    const box = row.getBoundingClientRect()
    return event.clientY >= box.top && event.clientY <= box.bottom
  })
  move(libraries.value.findIndex((lib) => lib.id === draggingId.value), target)
}

function endDrag(event: PointerEvent) {
  if (!drag || drag.pointer !== event.pointerId) return
  const original = drag.original
  drag = null
  draggingId.value = null
  if (event.type === 'pointercancel' || event.type === 'lostpointercapture') {
    libraries.value = original
  } else {
    void save(original)
  }
}

function step(index: number, direction: number) {
  if (loading.value || saving.value || drag) return
  const original = [...libraries.value]
  move(index, index + direction)
  void save(original)
}

onMounted(load)
</script>

<template>
  <div class="library-order" :aria-busy="loading || saving">
    <p class="order-help">拖动手柄调整媒体库顺序，松开后自动保存。也可使用上下按钮或方向键。</p>
    <p v-if="loading" role="status">正在读取媒体库…</p>
    <p v-else-if="!libraries.length && !error" class="order-help">添加媒体库后即可排序。</p>
    <ul ref="list" class="order-list" aria-label="媒体库排序"
      @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag">
      <li v-for="(lib, index) in libraries" :key="lib.id" :data-library-id="lib.id"
        :class="{ dragging: lib.id === draggingId }">
        <button type="button" class="order-handle" :aria-label="`拖动排序 ${lib.name}`"
          :aria-pressed="draggingId === lib.id" :disabled="loading || saving || libraries.length < 2"
          @pointerdown="startDrag($event, lib.id)" @keydown.up.prevent="step(index, -1)" @keydown.down.prevent="step(index, 1)">
          <span aria-hidden="true">⠿</span>
        </button>
        <span class="order-position">{{ index + 1 }}</span>
        <div class="order-name"><strong>{{ lib.name }}</strong><span :title="lib.path">{{ lib.path }}</span></div>
        <button type="button" class="order-step" :aria-label="`上移媒体库 ${lib.name}`"
          :disabled="loading || saving || index === 0" @click="step(index, -1)">↑</button>
        <button type="button" class="order-step" :aria-label="`下移媒体库 ${lib.name}`"
          :disabled="loading || saving || index === libraries.length - 1" @click="step(index, 1)">↓</button>
      </li>
    </ul>
    <p v-if="error" class="order-error" role="alert">{{ error }}<button type="button" :disabled="loading || saving" @click="load">刷新列表</button></p>
    <p v-else class="order-status" role="status">{{ saving ? '正在保存顺序…' : saved ? '顺序已保存' : '' }}</p>
  </div>
</template>

<style scoped>
.order-help { color: var(--muted); font-size: 12px; line-height: 1.7; margin: 0 0 14px; }
.order-list { list-style: none; padding: 0; margin: 0; }
.order-list li { display: flex; align-items: center; gap: 6px; min-height: 68px; padding: 6px; border-bottom: 1px solid var(--border-subtle); }
.order-list li.dragging { background: var(--bg-elevated); outline: 1px solid var(--accent); border-radius: 6px; }
.order-handle, .order-step { flex-shrink: 0; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; }
.order-handle { touch-action: none; cursor: grab; font-size: 23px; }
.order-handle:active { cursor: grabbing; }
.order-step { font-size: 18px; }
.order-handle:hover, .order-step:hover { background: var(--bg-elevated); color: var(--text); }
button:disabled { opacity: .35; cursor: default; }
.order-position { width: 18px; flex-shrink: 0; font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
.order-name { flex: 1; min-width: 0; display: grid; gap: 4px; }
.order-name strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 550; }
.order-name > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--faint); font-size: 11px; }
.order-status, .order-error { min-height: 20px; margin: 10px 0 0; font-size: 12px; color: var(--muted); }
.order-error { color: var(--text); }
.order-error > button { min-height: 44px; margin-left: 8px; color: var(--accent); border: 0; background: none; cursor: pointer; }
</style>
