<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'

const password = ref('')
const loading = ref(false)
const { login, authEnabled } = useAuth()
const router = useRouter()
const route = useRoute()

async function onSubmit() {
  loading.value = true
  try {
    await login(password.value)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    await router.replace(redirect)
  } catch {
    ElMessage.error('密码错误或登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page login-page">
    <div class="card">
      <h1 class="page-title">登录</h1>
      <p class="muted">
        {{ authEnabled ? '输入管理员密码以继续' : '当前未配置 ADMIN_PASSWORD，开发模式可直接进入' }}
      </p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            show-password
            placeholder="管理员密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="onSubmit">
          进入
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 80px);
}
.card {
  width: min(400px, 100%);
  padding: 28px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
}
.muted {
  margin: 0 0 18px;
}
</style>
