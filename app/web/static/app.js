// AFD 下载管理 v2 — Full Feature
(() => {
    'use strict';

    let refreshCount = 0;

    document.addEventListener('DOMContentLoaded', () => {
        loadTasks();
        startSmartRefresh();

        // Download form
        const form = document.getElementById('downloadForm');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                const url = document.getElementById('downloadUrl').value.trim();
                const filename = document.getElementById('filename').value.trim();
                const statusEl = document.getElementById('submitStatus');
                if (!url) return;

                // Detect magnet/torrent
                const isMagnet = url.startsWith('magnet:');
                const isTorrent = url.endsWith('.torrent');

                statusEl.className = 'status-msg';
                statusEl.textContent = '⏳ 提交中...';
                statusEl.style.display = 'block';

                try {
                    const res = await fetch('/api/task/create', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url, filename: filename || null, priority: parseInt(document.getElementById('priority').value) || 5 })
                    });
                    const data = await res.json();
                    if (data.task_id) {
                        const label = isMagnet ? '磁力链接' : isTorrent ? '种子' : '下载';
                        statusEl.className = 'status-msg success';
                        statusEl.textContent = `✅ ${label}任务已创建 (${data.task_id.slice(0,8)}...)`;
                        document.getElementById('downloadUrl').value = '';
                        document.getElementById('filename').value = '';
                        loadTasks();
                    } else {
                        statusEl.className = 'status-msg error';
                        statusEl.textContent = `❌ ${data.error || '创建失败'}`;
                    }
                } catch (err) {
                    statusEl.className = 'status-msg error';
                    statusEl.textContent = `❌ 请求失败: ${err.message}`;
                }
            });
        }
    });

    // ============ Tasks ============
    window.loadTasks = async function() {
        try {
            const res = await fetch('/api/task/list');
            const data = await res.json();
            renderTasks(data.tasks || []);
        } catch (err) {
            console.error('loadTasks:', err);
        }
    };

    function renderTasks(tasks) {
        const container = document.getElementById('taskList');
        const countEl = document.getElementById('taskCount');
        if (countEl) countEl.textContent = tasks.length;

        if (tasks.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding:40px 20px"><span style="font-size:2rem;display:block;margin-bottom:8px">📥</span><p style="color:#555;font-size:0.85rem">暂无下载任务，粘贴链接开始吧</p></div>';
            return;
        }

        // 批量操作栏
        let batchBar = '';
        const hasSelectable = tasks.some(t => !['completed','all_completed','seeding'].includes(t.status));
        if (hasSelectable) {
            batchBar = `
                <div class="batch-bar" style="display:flex;gap:8px;align-items:center;padding:8px 12px;margin-bottom:12px;background:var(--bg-surface);border:1px solid var(--border-color);border-radius:var(--radius-sm)">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.85rem">
                        <input type="checkbox" id="batchSelectAll" onchange="toggleSelectAll()">
                        <span>全选</span>
                    </label>
                    <span id="batchCount" style="font-size:0.8rem;color:var(--text-tertiary);margin-left:auto">已选 0 项</span>
                    <button class="btn btn-sm" onclick="batchPause()" title="暂停选中">⏸️</button>
                    <button class="btn btn-sm" onclick="batchResume()" title="继续选中">▶️</button>
                    <button class="btn btn-sm btn-danger" onclick="batchDelete()" title="删除选中">🗑️</button>
                </div>
            `;
        }

        const tasksHtml = tasks.map(task => {
            const statusMap = {downloading:'下载中',paused:'已暂停',completed:'已完成',failed:'失败',pending:'等待中',seeding:'做种',cancelled:'已取消',all_completed:'全部完成'};
            const st = statusMap[task.status] || task.status;
            const badgeClass = ['all_completed','completed'].includes(task.status) ? 'badge-completed'
                : task.status === 'failed' ? 'badge-failed'
                : task.status === 'cancelled' ? 'badge-failed'
                : task.status === 'pending' ? 'badge-pending'
                : task.status === 'paused' ? 'badge-warning'
                : task.status === 'seeding' ? 'badge-seeding' : 'badge-downloading';

            const nodesHtml = (task.nodes || []).map(n => {
                const pct = Math.round((n.progress || 0) * 100);
                const barClass = ['completed','seeding'].includes(n.status) ? 'progress-bar-green'
                    : n.status === 'failed' || n.status === 'cancelled' ? 'progress-bar-red'
                    : n.status === 'paused' ? 'progress-bar-yellow'
                    : n.status === 'offline' ? 'progress-bar-red'
                    : 'progress-bar-accent';
                const speedHtml = n.status === 'active' && n.download_speed > 0
                    ? `<span class="meta-chip" style="margin-left:auto">⬇ ${fmtSize(n.download_speed)}/s</span>`
                    : '';
                return `
                    <div class="node-progress" data-node="${esc(n.node_id)}">
                        <span class="node-label ${n.status === 'offline' ? 'offline' : ''}">${esc(n.node_name || n.node_id)}</span>
                        <div class="progress-bar-wrap">
                            <div class="progress-bar ${barClass}" style="width:${pct}%"></div>
                        </div>
                        <span class="pct">${pct}%</span>
                        ${speedHtml}
                    </div>
                `;
            }).join('');

            const filename = task.filename || task.url.split('/').pop() || task.url;
            const isDownloading = task.status === 'downloading';
            const isPaused = task.status === 'paused';
            const isFailed = task.status === 'failed';
            const isCancelled = task.status === 'cancelled';
            const isFinished = ['completed','all_completed','seeding'].includes(task.status);
            const canSelect = !isFinished;

            const priorityHtml = task.priority ? `<span class="meta-chip" title="优先级 ${task.priority}">⚡ ${task.priority}</span>` : '';

            let actionBtns = '';
            if (isPaused) {
                actionBtns += `<button class="task-action-btn resume" onclick="event.stopPropagation();resumeTask('${attr(task.id)}')" title="继续下载">▶️</button>`;
            }
            if (isDownloading) {
                actionBtns += `<button class="task-action-btn pause" onclick="event.stopPropagation();pauseTask('${attr(task.id)}')" title="暂停">⏸️</button>`;
                actionBtns += `<button class="task-action-btn cancel" onclick="event.stopPropagation();cancelTask('${attr(task.id)}')" title="取消">⏹</button>`;
            }
            if (isFailed || isCancelled) {
                actionBtns += `<button class="task-action-btn retry" onclick="event.stopPropagation();retryTask('${attr(task.id)}')" title="重新下载">🔄</button>`;
            }
            if (!isDownloading) {
                actionBtns += `<button class="task-action-btn delete" onclick="event.stopPropagation();deleteTask('${attr(task.id)}')" title="删除">🗑️</button>`;
            }

            const selectCheckbox = canSelect ? `<input type="checkbox" class="batch-check" data-task-id="${attr(task.id)}" onchange="updateBatchCount()" style="margin-right:8px">` : '<span style="width:20px;display:inline-block"></span>';

            return `
                <div class="task-item" id="task-${attr(task.id)}" onclick="showTaskDetail('${attr(task.id)}')" style="cursor:pointer">
                    <div class="task-header">
                        ${selectCheckbox}
                        <div class="task-info" style="flex:1">
                            <div class="name">${esc(filename)} <span style="font-size:0.7rem;color:var(--text-tertiary)">${task.id.slice(0,8)}</span></div>
                            <div class="url">${esc(task.url)}</div>
                            <div class="task-meta-bar">
                                ${priorityHtml}
                                ${task.total_size ? `<span class="meta-chip">📦 ${fmtSize(task.total_size)}</span>` : ''}
                                ${isDownloading || isPaused ? `<span class="meta-chip detail-btn" onclick="event.stopPropagation();showTaskDetail('${attr(task.id)}')">📋 详情</span>` : ''}
                            </div>
                        </div>
                        <div class="task-status-col">
                            <span class="badge ${badgeClass}">${st}</span>
                            <div class="task-actions">${actionBtns}</div>
                        </div>
                    </div>
                    <div class="nodes-section" id="nodes-${attr(task.id)}">
                        ${nodesHtml}
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = batchBar + tasksHtml;

        // Fetch remote node info for each task
        tasks.forEach(t => {
            if (t.id) fetchNodeOverview(t.id);
        });
    }

    async function fetchNodeOverview(taskId) {
        try {
            const res = await fetch('/api/task/' + encodeURIComponent(taskId) + '/overview');
            if (!res.ok) return;
            const data = await res.json();
            const nodesSection = document.getElementById('nodes-' + attr(taskId));
            if (!nodesSection || !data.nodes) return;

            // Update existing node entries and add missing ones
            for (const n of data.nodes) {
                const pct = Math.round((n.progress || 0) * 100);
                const barClass = ['completed','seeding'].includes(n.status) ? 'progress-bar-green'
                    : n.status === 'failed' || n.status === 'cancelled' ? 'progress-bar-red'
                    : n.status === 'paused' ? 'progress-bar-yellow'
                    : n.status === 'offline' ? 'progress-bar-red'
                    : 'progress-bar-accent';
                const speedHtml = (n.status === 'active' || n.status === 'downloading') && n.download_speed > 0
                    ? `<span class="meta-chip" style="margin-left:auto">⬇ ${fmtSize(n.download_speed)}/s</span>`
                    : '';

                let existing = nodesSection.querySelector('[data-node="' + esc(n.node_id) + '"]');
                if (existing) {
                    existing.querySelector('.pct').textContent = pct + '%';
                    const bar = existing.querySelector('.progress-bar');
                    bar.style.width = pct + '%';
                    bar.className = 'progress-bar ' + barClass;
                    // Update speed display
                    const existingSpeed = existing.querySelector('.meta-chip');
                    if (existingSpeed) {
                        if (speedHtml) existingSpeed.outerHTML = speedHtml;
                        else existingSpeed.remove();
                    } else if (speedHtml) {
                        existing.appendChild(document.createRange().createContextualFragment(speedHtml));
                    }
                    const label = existing.querySelector('.node-label');
                    label.classList.toggle('offline', n.status === 'offline');
                } else {
                    // Add new node row from remote
                    const row = document.createElement('div');
                    row.className = 'node-progress';
                    row.setAttribute('data-node', n.node_id);
                    row.innerHTML = '<span class="node-label' + (n.status === 'offline' ? ' offline' : '') + '">' + esc(n.node_name || n.node_id) + '</span>'
                        + '<div class="progress-bar-wrap"><div class="progress-bar ' + barClass + '" style="width:' + pct + '%"></div></div>'
                        + '<span class="pct">' + pct + '%</span>'
                        + speedHtml;
                    nodesSection.appendChild(row);
                }
            }
        } catch(e) {
            // Ignore overview fetch errors
        }
    }

    window.cancelTask = async function(taskId) {
        if (!confirm('确定取消这个下载任务？')) return;
        try {
            const res = await fetch('/api/task/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (res.ok) loadTasks();
        } catch (err) {
            alert('取消失败: ' + err.message);
        }
    };

    window.pauseTask = async function(taskId) {
        try {
            const res = await fetch('/api/task/pause', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (res.ok) loadTasks();
        } catch (err) {
            alert('暂停失败: ' + err.message);
        }
    };

    window.resumeTask = async function(taskId) {
        try {
            const res = await fetch('/api/task/resume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (res.ok) loadTasks();
        } catch (err) {
            alert('继续失败: ' + err.message);
        }
    };

    window.retryTask = async function(taskId) {
        if (!confirm('确定重新下载这个任务？')) return;
        try {
            const res = await fetch('/api/task/retry', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (res.ok) loadTasks();
        } catch (err) {
            alert('重试失败: ' + err.message);
        }
    };

    window.deleteTask = async function(taskId) {
        if (!confirm('确定删除这个任务？文件和记录将被彻底清除。')) return;
        try {
            const res = await fetch('/api/task/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (res.ok) loadTasks();
        } catch (err) {
            alert('删除失败: ' + err.message);
        }
    };

    // ============ Batch Operations ============
    window.toggleSelectAll = function() {
        const allCheckbox = document.getElementById('batchSelectAll');
        const checkboxes = document.querySelectorAll('.batch-check');
        checkboxes.forEach(cb => cb.checked = allCheckbox.checked);
        updateBatchCount();
    };

    window.updateBatchCount = function() {
        const checked = document.querySelectorAll('.batch-check:checked');
        const countEl = document.getElementById('batchCount');
        if (countEl) countEl.textContent = `已选 ${checked.length} 项`;
    };

    function getSelectedTaskIds() {
        return Array.from(document.querySelectorAll('.batch-check:checked'))
            .map(cb => cb.dataset.taskId);
    }

    window.batchPause = async function() {
        const ids = getSelectedTaskIds();
        if (!ids.length) { alert('请先选择任务'); return; }
        if (!confirm(`确定暂停选中的 ${ids.length} 个任务？`)) return;
        await batchAction(ids, 'pause');
    };

    window.batchResume = async function() {
        const ids = getSelectedTaskIds();
        if (!ids.length) { alert('请先选择任务'); return; }
        if (!confirm(`确定继续选中的 ${ids.length} 个任务？`)) return;
        await batchAction(ids, 'resume');
    };

    window.batchDelete = async function() {
        const ids = getSelectedTaskIds();
        if (!ids.length) { alert('请先选择任务'); return; }
        if (!confirm(`确定删除选中的 ${ids.length} 个任务？文件和记录将被彻底清除。`)) return;
        await batchAction(ids, 'delete');
    };

    async function batchAction(taskIds, action) {
        const endpoint = `/api/task/batch/${action}`;
        try {
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_ids: taskIds })
            });
            const data = await res.json();
            if (data.success) {
                loadTasks();
            } else {
                alert(`批量操作失败: ${data.error || '未知错误'}`);
            }
        } catch (err) {
            alert('批量操作失败: ' + err.message);
        }
    }

    window.clearCompleted = async function() {
        if (!confirm('确定清除所有已完成/失败/已取消的任务？')) return;
        try {
            const res = await fetch('/api/task/clear-completed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (data.status === 'cleared') loadTasks();
        } catch (err) {
            alert('清除失败: ' + err.message);
        }
    };

    // ============ Task Detail ============
    window.showTaskDetail = async function(taskId) {
        try {
            const res = await fetch(`/api/task/${taskId}`);
            const task = await res.json();
            if (!task || task.error) return;

            const statusMap = {downloading:'下载中',paused:'已暂停',completed:'已完成',failed:'失败',pending:'等待中',seeding:'做种',cancelled:'已取消',all_completed:'全部完成'};
            const st = statusMap[task.status] || task.status;

            let subFilesHtml = '';
            if (task.nodes && task.nodes.length) {
                subFilesHtml = task.nodes.map(n => {
                    const pct = Math.round((n.progress || 0) * 100);
                    return `<tr><td style="color:var(--text-primary)">${esc(n.node_name)}</td><td>${pct}%</td><td>${n.status}</td><td style="font-size:0.7rem">${n.gid ? n.gid.slice(0,8) : '-'}</td></tr>`;
                }).join('');
            }

            // Copy URL helper
            const detailHtml = `
                <div class="detail-modal-overlay" onclick="closeTaskDetail(event)">
                    <div class="detail-modal" onclick="event.stopPropagation()">
                        <div class="detail-head">
                            <h3>${esc(task.filename || task.url.split('/').pop() || task.id)}</h3>
                            <button class="detail-close" onclick="closeTaskDetail()">✕</button>
                        </div>
                        <div class="detail-body">
                            <div class="detail-grid">
                                <span class="detail-label">任务 ID</span><span class="detail-value mono">${task.id}</span>
                                <span class="detail-label">状态</span><span class="detail-value badge ${['completed','all_completed'].includes(task.status)?'badge-completed':task.status==='failed'?'badge-failed':task.status==='paused'?'badge-warning':task.status==='seeding'?'badge-seeding':'badge-downloading'}">${st}</span>
                                <span class="detail-label">链接</span><span class="detail-value" style="word-break:break-all;font-size:0.78rem"><a href="${esc(task.url)}" target="_blank" style="color:var(--accent)">${esc(task.url)}</a></span>
                                <span class="detail-label">大小</span><span class="detail-value">${fmtSize(task.total_size) || '未知'}</span>
                                ${task.downloaded_size ? `<span class="detail-label">已下载</span><span class="detail-value">${fmtSize(task.downloaded_size)}</span>` : ''}
                                <span class="detail-label">创建时间</span><span class="detail-value" style="font-size:0.78rem" data-time-iso="${task.created_at || ''}">${task.created_at ? timeAgo(task.created_at) : '-'}</span>
                                <span class="detail-label">更新时间</span><span class="detail-value" style="font-size:0.78rem" data-time-iso="${task.updated_at || ''}">${task.updated_at ? timeAgo(task.updated_at) : '-'}</span>
                            </div>
                            ${subFilesHtml ? `
                                <h4 style="margin:14px 0 8px;font-size:0.82rem;color:var(--text-secondary)">节点状态</h4>
                                <table style="width:100%;border-collapse:collapse;font-size:0.8rem">
                                    <thead><tr style="color:var(--text-tertiary)"><th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border-color)">节点</th><th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border-color)">进度</th><th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border-color)">状态</th><th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border-color)">GID</th></tr></thead>
                                    <tbody>${subFilesHtml}</tbody>
                                </table>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;

            // Remove existing modal if any
            const old = document.querySelector('.detail-modal-overlay');
            if (old) old.remove();
            document.body.insertAdjacentHTML('beforeend', detailHtml);
        } catch (err) {
            console.error('showTaskDetail:', err);
        }
    };

    window.closeTaskDetail = function(e) {
        if (e && e.target !== e.currentTarget) return;
        const el = document.querySelector('.detail-modal-overlay');
        if (el) el.remove();
    };

    // ============ Utils ============
    function fmtSize(bytes) {
        if (!bytes || bytes === 0) return '';
        const u = ['B','KB','MB','GB','TB']; let i = 0, s = bytes;
        while (s >= 1024 && i < u.length-1) { s /= 1024; i++; }
        return s.toFixed(1) + ' ' + u[i];
    }

    function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    function attr(s) { return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;'); }

    // ============ Time utils ============
    function timeAgo(isoStr) {
        if (!isoStr) return '';
        const now = Date.now();
        const then = new Date(isoStr).getTime();
        if (isNaN(then)) return isoStr;
        const diff = now - then;
        const sec = Math.floor(diff / 1000);
        if (sec < 5) return '刚刚';
        if (sec < 60) return sec + '秒前';
        const min = Math.floor(sec / 60);
        if (min < 60) return min + '分钟前';
        const hours = Math.floor(min / 60);
        if (hours < 24) return hours + '小时前';
        const days = Math.floor(hours / 24);
        if (days < 7) return days + '天前';
        // Fall back to date
        const d = new Date(then);
        const pad = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
    }

    // Apply time-ago via mutation observer (auto-convert [data-time-iso] elements)
    let timeObserver = null;
    function initTimeObserver() {
        if (timeObserver) return;
        timeObserver = new MutationObserver(() => {
            document.querySelectorAll('[data-time-iso]').forEach(el => {
                if (el.dataset.timeAgoProcessed) return;
                el.dataset.timeAgoProcessed = '1';
                const iso = el.getAttribute('data-time-iso');
                el.textContent = timeAgo(iso);
                el.title = iso || '';
            });
        });
        timeObserver.observe(document.body, { childList: true, subtree: true });
    }
    initTimeObserver();

    // ============ Smart Refresh ============
    let _refreshTimer = null;
    let _hasActiveTasks = false;

    function startSmartRefresh() {
        // Initial: fast refresh
        scheduleRefresh(3000);
    }

    function scheduleRefresh(intervalMs) {
        if (_refreshTimer) clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(async () => {
            try {
                const res = await fetch('/api/task/list');
                const data = await res.json();
                const tasks = data.tasks || [];
                _hasActiveTasks = tasks.some(t => ['downloading', 'pending', 'paused'].includes(t.status));
                renderTasks(tasks);
            } catch (err) {
                console.error('Refresh:', err);
            }
            // Adjust interval based on activity
            const nextInterval = _hasActiveTasks ? 3000 : 12000;
            scheduleRefresh(nextInterval);
        }, intervalMs);
    }

})();
