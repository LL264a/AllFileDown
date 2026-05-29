<template>
  <div class="min-h-screen bg-slate-100 dark:bg-[#0a0a0a] flex">
    <!-- 左侧窄导航栏 - AriaNG 风格 -->
    <aside class="w-16 bg-gradient-to-b from-slate-800 to-slate-900 dark:from-[#1a1a1a] dark:to-[#0a0a0a] flex flex-col items-center py-4 shrink-0">
      <!-- Logo -->
      <router-link to="/" class="mb-6">
        <img src="/afd-logo-flat.png" class="w-10 h-10 rounded-lg" alt="AFD">
      </router-link>
      
      <!-- 导航图标 -->
      <nav class="flex flex-col gap-2 w-full px-2">
        <router-link v-for="item in navItems" :key="item.path" :to="item.path"
          class="flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-xs transition-all"
          :class="$route.path === item.path 
            ? 'bg-primary-500/20 text-primary-400' 
            : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'">
          <span class="text-lg">{{ item.icon }}</span>
          <span>{{ item.name }}</span>
        </router-link>
      </nav>
      
      <!-- 底部：设置 -->
      <div class="mt-auto pt-4">
        <button @click="toggleTheme" class="text-slate-400 hover:text-slate-200 text-lg">
          {{ isDark ? '☀️' : '🌙' }}
        </button>
      </div>
    </aside>
    
    <!-- 右侧主内容区 -->
    <main class="flex-1 overflow-auto">
      <!-- 顶部栏：节点状态 + 快速操作 -->
      <header class="h-14 bg-white dark:bg-[#1a1a1a] border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-4 shrink-0">
        <div class="flex items-center gap-4">
          <h1 class="text-lg font-semibold text-slate-800 dark:text-white">{{ pageTitle }}</h1>
          <span class="text-xs px-2 py-0.5 rounded-full" 
            :class="aria2Connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'">
            {{ aria2Connected ? 'Aria2 ' + aria2Version : '未连接' }}
          </span>
        </div>
        
        <div class="flex items-center gap-3">
          <!-- 全局速度显示 -->
          <div class="flex items-center gap-4 text-sm text-slate-500">
            <span>⬇️ {{ formatSpeed(downloadSpeed) }}</span>
            <span>⬆️ {{ formatSpeed(uploadSpeed) }}</span>
          </div>
          
          <!-- 新建下载按钮 -->
          <button @click="showNewDownload = true" 
            class="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-sm rounded-lg flex items-center gap-1">
            <span>+</span> 新建下载
          </button>
        </div>
      </header>
      
      <!-- 页面内容 -->
      <div class="p-4">
        <router-view />
      </div>
    </main>
    
    <!-- 新建下载弹窗 -->
    <dialog :open="showNewDownload" class="modal">
      <div class="bg-white dark:bg-[#1a1a1a] rounded-xl p-6 w-96 shadow-xl">
        <h3 class="text-lg font-semibold mb-4">新建下载</h3>
        <input v-model="newUrl" type="url" placeholder="输入下载链接..." 
          class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 mb-3">
        <input v-model="newFilename" type="text" placeholder="自定义文件名（可选）" 
          class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 mb-4">
        <div class="flex justify-end gap-2">
          <button @click="showNewDownload = false" class="px-4 py-2 text-slate-500">取消</button>
          <button @click="startDownload" class="px-4 py-2 bg-primary-600 text-white rounded-lg">下载</button>
        </div>
      </div>
    </dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { aria2Api } from './composables/useApi'

const route = useRoute()

// 导航项 - 更简洁
const navItems = [
  { name: '下载', icon: '⬇️', path: '/downloads' },
  { name: '文件', icon: '📁', path: '/' },
  { name: '节点', icon: '🖥️', path: '/nodes' },
  { name: '设置', icon: '⚙️', path: '/settings' },
]

// 状态
const isDark = ref(false)
const showNewDownload = ref(false)
const newUrl = ref('')
const newFilename = ref('')
const aria2Connected = ref(false)
const aria2Version = ref('')
const downloadSpeed = ref(0)
const uploadSpeed = ref(0)

// 页面标题
const pageTitle = computed(() => {
  const titles = {
    '/': '文件管理',
    '/downloads': '下载管理',
    '/nodes': '节点管理',
    '/settings': '系统设置',
    '/logs': '日志查看',
  }
  return titles[route.path] || 'AFD'
})

// 速度格式化
function formatSpeed(bytes) {
  if (!bytes) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0, s = bytes
  while (s >= 1024 && i < 3) { s /= 1024; i++ }
  return s.toFixed(1) + ' ' + units[i]
}

// 主题切换
function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('afd-theme', isDark.value ? 'dark' : 'light')
}

// 获取 Aria2 状态
async function fetchAria2Status() {
  try {
    const res = await aria2Api.status()
    aria2Connected.value = res.connected
    aria2Version.value = res.version
    downloadSpeed.value = res.download_speed
    uploadSpeed.value = res.upload_speed
  } catch (e) {
    aria2Connected.value = false
  }
}

// 开始下载
async function startDownload() {
  if (!newUrl.value) return
  try {
    await fetch('/api/task/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: newUrl.value, filename: newFilename.value || undefined })
    })
    showNewDownload.value = false
    newUrl.value = ''
    newFilename.value = ''
  } catch (e) {
    alert('创建任务失败')
  }
}

let statusTimer = null

onMounted(() => {
  // 初始化主题
  const theme = localStorage.getItem('afd-theme') || 'light'
  isDark.value = theme === 'dark'
  document.documentElement.classList.toggle('dark', isDark.value)
  
  // 获取 Aria2 状态
  fetchAria2Status()
  statusTimer = setInterval(fetchAria2Status, 3000)
})

onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
})
</script>

<style>
.modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
</style>