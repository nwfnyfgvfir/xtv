<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'
import { getErrorMessage } from '@/utils/errors'

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
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '密码错误或登录失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="card">
      <div class="brand">
        <span class="brand-mark">TV</span>
        <span class="brand-divider" aria-hidden="true" />
        <span class="brand-sub">影院</span>
      </div>
      <h1 class="login-title">登录</h1>
      <p class="muted login-hint">
        {{ authEnabled ? '输入管理员密码以继续' : '当前未配置 ADMIN_PASSWORD，开发模式可直接进入' }}
      </p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            show-password
            size="large"
            placeholder="管理员密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="submit" @click="onSubmit">
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
  min-height: 100vh;
  padding: var(--space-6) var(--gutter);
}
.card {
  width: min(400px, 100%);
  padding: var(--space-10) var(--space-8) var(--space-8);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-8);
}
.brand-mark {
  font-family: var(--font-serif);
  font-size: 30px;
  font-weight: 500;
  line-height: 1;
  letter-spacing: var(--tracking-tight);
  color: var(--accent);
}
.brand-divider {
  width: 1px;
  height: 20px;
  background: var(--accent-line);
}
.brand-sub {
  font-size: var(--text-sm);
  font-weight: 500;
  letter-spacing: var(--tracking-widest);
  color: var(--muted);
}
.login-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 500;
  letter-spacing: var(--tracking-tight);
  color: var(--text);
}
.login-hint {
  margin: var(--space-2) 0 var(--space-6);
  font-size: var(--text-sm);
}
.submit {
  width: 100%;
}
</style>
