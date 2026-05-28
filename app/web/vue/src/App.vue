<template>
  <div class="min-h-screen bg-slate-50 dark:bg-[#0f172a] transition-colors duration-300">
    <!-- 顶部导航 -->
    <header class="bg-white/80 dark:bg-[#1e293b]/80 backdrop-blur-md shadow-sm sticky top-0 z-50 border-b border-slate-100 dark:border-slate-700/50">
      <div class="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <div class="flex items-center gap-4">
          <router-link to="/" class="flex flex-col items-center gap-0.5">
            <img src="/afd-logo-flat.png" class="w-8 h-8 rounded-lg" alt="AFD">
            <span class="text-\[10px\] text-gray-400">v0.2.1</span>
          </router-link>
          
          <nav class="flex gap-1">
            <router-link v-for="item in navItems" :key="item.path" :to="item.path"
              class="px-3 py-1.5 rounded-lg text-sm font-medium transition-all"
              :class="$route.path === item.path 
                ? 'bg-primary-50 text-primary-600 dark:bg-primary-500/15 dark:text-primary-400' 
                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'">
              {{ item.icon }} {{ item.name }}
            </router-link>
          </nav>
        </div>
      </div>
    </header>
    
    <!-- 主内容 -->
    <main class="max-w-7xl mx-auto px-4 py-6">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'

const navItems = [
  { name: '文件', icon: '📂', path: '/' },
  { name: '下载', icon: '📥', path: '/downloads' },
  { name: '节点', icon: '🖥️', path: '/nodes' },
  { name: '设置', icon: '⚙️', path: '/settings' },
  { name: '日志', icon: '📋', path: '/logs' },
]

onMounted(() => {
  const theme = localStorage.getItem('afd-theme') || 'light'
  document.documentElement.classList.toggle('dark', theme === 'dark')
})
</script>
