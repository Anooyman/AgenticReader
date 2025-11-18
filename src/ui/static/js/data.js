/**
 * LLMReader 数据管理页面 JavaScript
 * 管理文档数据、清理缓存文件、监控存储使用情况
 */

class LLMReaderDataApp {
    constructor() {
        this.stats = {
            totalDocuments: 0,
            totalSize: '0 MB',
            chatSessions: 0,
            lastCleanup: '从未'
        };

        this.confirmationCallback = null;

        // API基础URL配置 - 自动检测当前协议和主机
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        this.init();
    }

    // 获取完整的API URL
    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        console.log('🚀 数据管理页面初始化开始');

        // 初始化UI组件
        this.initTabs();
        this.initEventListeners();
        this.initConfirmationDialog();

        // 加载数据
        await this.loadStorageStats();
        await this.loadDocumentList();

        console.log('✅ 数据管理页面初始化完成');
    }

    /* === 初始化方法 === */

    initTabs() {
        const tabBtns = document.querySelectorAll('.management-tabs .tab-btn');
        const tabContents = document.querySelectorAll('.management-tab-content');

        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.getAttribute('data-tab');

                // 更新按钮状态
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // 更新内容显示
                tabContents.forEach(content => {
                    content.classList.remove('active');
                    if (content.id === `${tabId}-tab`) {
                        content.classList.add('active');
                    }
                });

                // 根据标签页加载相应数据
                switch (tabId) {
                    case 'documents':
                        this.loadDocumentList();
                        break;
                    case 'cache':
                        this.loadCacheStats();
                        break;
                    case 'chat':
                        this.loadChatStats();
                        break;
                }
            });
        });
    }

    initEventListeners() {
        // 刷新按钮
        document.getElementById('refresh-documents-btn').addEventListener('click', () => {
            this.loadDocumentList();
        });

        document.getElementById('refresh-cache-btn').addEventListener('click', () => {
            this.loadCacheStats();
        });

        document.getElementById('refresh-chat-btn').addEventListener('click', () => {
            this.loadChatStats();
        });

        // 清理按钮
        document.getElementById('cleanup-old-documents-btn').addEventListener('click', () => {
            this.confirmAction('清理旧文档', '确定要清理超过30天的旧文档数据吗？此操作不可撤销。', () => {
                this.cleanupOldDocuments();
            });
        });

        document.getElementById('clear-all-cache-btn').addEventListener('click', () => {
            this.confirmAction('清空所有缓存', '确定要清空所有缓存文件吗？这将删除PDF图片、向量数据库和JSON数据。', () => {
                this.clearAllCache();
            });
        });

        // 单独缓存清理
        document.getElementById('clear-pdf-cache-btn').addEventListener('click', () => {
            this.confirmAction('清理PDF缓存', '确定要清理PDF图片缓存吗？', () => {
                this.clearCache('pdf');
            });
        });

        document.getElementById('clear-vector-cache-btn').addEventListener('click', () => {
            this.confirmAction('清理向量数据库', '确定要清理向量数据库缓存吗？', () => {
                this.clearCache('vector');
            });
        });

        document.getElementById('clear-json-cache-btn').addEventListener('click', () => {
            this.confirmAction('清理JSON缓存', '确定要清理JSON数据缓存吗？', () => {
                this.clearCache('json');
            });
        });

        // 聊天数据清理
        document.getElementById('clear-local-sessions-btn').addEventListener('click', () => {
            this.confirmAction('清理本地会话', '确定要清理所有本地聊天会话吗？', () => {
                this.clearLocalSessions();
            });
        });

        document.getElementById('clear-server-history-btn').addEventListener('click', () => {
            this.confirmAction('清空服务器历史', '确定要清空所有服务器聊天历史吗？此操作不可撤销。', () => {
                this.clearServerHistory();
            });
        });

        document.getElementById('export-chat-history-btn').addEventListener('click', () => {
            this.exportChatHistory();
        });

        // 批量操作
        document.getElementById('smart-cleanup-btn').addEventListener('click', () => {
            this.smartCleanup();
        });

        document.getElementById('backup-data-btn').addEventListener('click', () => {
            this.backupData();
        });

        document.getElementById('rebuild-index-btn').addEventListener('click', () => {
            this.confirmAction('重建索引', '确定要重建向量数据库索引吗？这可能需要较长时间。', () => {
                this.rebuildIndex();
            });
        });

        document.getElementById('full-reset-btn').addEventListener('click', () => {
            this.confirmAction('完全重置', '⚠️ 警告：此操作将删除所有数据，包括文档、聊天历史、缓存等。确定要继续吗？', () => {
                this.fullReset();
            });
        });
    }

    initConfirmationDialog() {
        const dialog = document.getElementById('confirmation-dialog');
        const confirmBtn = document.getElementById('dialog-confirm');
        const cancelBtn = document.getElementById('dialog-cancel');
        const overlay = dialog.querySelector('.dialog-overlay');

        const closeDialog = () => {
            dialog.style.display = 'none';
            this.confirmationCallback = null;
        };

        confirmBtn.addEventListener('click', () => {
            if (this.confirmationCallback) {
                this.confirmationCallback();
            }
            closeDialog();
        });

        cancelBtn.addEventListener('click', closeDialog);
        overlay.addEventListener('click', closeDialog);
    }

    /* === API调用方法 === */

    async loadStorageStats() {
        try {
            const response = await fetch(this.getApiUrl('/api/data/stats'));
            const stats = await response.json();

            if (stats.status === 'success') {
                this.stats = stats.data;
                this.updateStorageDisplay();
                this.loadChatSessionCount();
            }
        } catch (error) {
            console.error('加载存储统计失败:', error);
            this.showStatus('error', '加载存储统计失败');
        }
    }

    async loadDocumentList() {
        try {
            const listContainer = document.getElementById('document-list');
            listContainer.innerHTML = '<div class="loading-message">正在加载文档列表...</div>';

            const response = await fetch(this.getApiUrl('/api/data/documents'));
            const result = await response.json();

            if (result.status === 'success') {
                this.displayDocumentList(result.documents);
            } else {
                listContainer.innerHTML = '<div class="error-message">加载文档列表失败</div>';
            }
        } catch (error) {
            console.error('加载文档列表失败:', error);
            document.getElementById('document-list').innerHTML = '<div class="error-message">加载文档列表失败</div>';
        }
    }

    async loadCacheStats() {
        try {
            const response = await fetch(this.getApiUrl('/api/data/cache-stats'));
            const result = await response.json();

            if (result.status === 'success') {
                const stats = result.data;

                // 更新缓存统计
                document.getElementById('pdf-cache-count').textContent = `${stats.pdf.count} 个文件`;
                document.getElementById('pdf-cache-size').textContent = `${stats.pdf.size} MB`;

                document.getElementById('vector-cache-count').textContent = `${stats.vector.count} 个文件`;
                document.getElementById('vector-cache-size').textContent = `${stats.vector.size} MB`;

                document.getElementById('json-cache-count').textContent = `${stats.json.count} 个文件`;
                document.getElementById('json-cache-size').textContent = `${stats.json.size} MB`;
            }
        } catch (error) {
            console.error('加载缓存统计失败:', error);
            this.showStatus('error', '加载缓存统计失败');
        }
    }

    async loadChatStats() {
        try {
            // 加载本地会话数量
            this.loadChatSessionCount();

            // 加载服务器聊天历史统计
            const response = await fetch(this.getApiUrl('/api/data/chat-stats'));
            const result = await response.json();

            if (result.status === 'success') {
                const stats = result.data;

                document.getElementById('server-history-count').textContent = stats.message_count || 0;
                document.getElementById('last-chat-activity').textContent = stats.last_activity || '无记录';
            }
        } catch (error) {
            console.error('加载聊天统计失败:', error);
            this.showStatus('error', '加载聊天统计失败');
        }
    }

    loadChatSessionCount() {
        try {
            const sessionsData = localStorage.getItem('llmreader_chat_sessions');
            let sessionCount = 0;

            if (sessionsData) {
                const sessions = JSON.parse(sessionsData);
                sessionCount = Object.keys(sessions).length;
            }

            document.getElementById('local-sessions-count').textContent = sessionCount;
            document.getElementById('chat-sessions').textContent = sessionCount;
        } catch (error) {
            console.error('加载本地会话统计失败:', error);
            document.getElementById('local-sessions-count').textContent = '错误';
            document.getElementById('chat-sessions').textContent = '错误';
        }
    }

    /* === 清理操作 === */

    async cleanupOldDocuments() {
        try {
            this.showStatus('info', '正在清理旧文档数据...');

            const response = await fetch(this.getApiUrl('/api/data/cleanup-old'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', `清理完成：删除了 ${result.deleted_count} 个旧文档`);
                this.loadStorageStats();
                this.loadDocumentList();
            } else {
                this.showStatus('error', '清理失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('清理旧文档失败:', error);
            this.showStatus('error', '清理旧文档失败');
        }
    }

    async clearAllCache() {
        try {
            this.showStatus('info', '正在清空所有缓存...');

            const response = await fetch(this.getApiUrl('/api/data/clear-cache'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ cache_type: 'all' })
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', '所有缓存已清空');
                this.loadStorageStats();
                this.loadCacheStats();
            } else {
                this.showStatus('error', '清空缓存失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('清空缓存失败:', error);
            this.showStatus('error', '清空缓存失败');
        }
    }

    async clearCache(cacheType) {
        try {
            this.showStatus('info', `正在清理${cacheType}缓存...`);

            const response = await fetch(this.getApiUrl('/api/data/clear-cache'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ cache_type: cacheType })
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', `${cacheType}缓存已清理`);
                this.loadStorageStats();
                this.loadCacheStats();
            } else {
                this.showStatus('error', '清理缓存失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('清理缓存失败:', error);
            this.showStatus('error', '清理缓存失败');
        }
    }

    clearLocalSessions() {
        try {
            localStorage.removeItem('llmreader_chat_sessions');
            localStorage.removeItem('llmreader_document_state');

            this.showStatus('success', '本地聊天会话已清理');
            this.loadChatStats();
        } catch (error) {
            console.error('清理本地会话失败:', error);
            this.showStatus('error', '清理本地会话失败');
        }
    }

    async clearServerHistory() {
        try {
            this.showStatus('info', '正在清空服务器聊天历史...');

            const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', '服务器聊天历史已清空');
                this.loadChatStats();
            } else {
                this.showStatus('error', '清空聊天历史失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('清空聊天历史失败:', error);
            this.showStatus('error', '清空聊天历史失败');
        }
    }

    /* === 批量操作 === */

    async smartCleanup() {
        try {
            this.showStatus('info', '正在执行智能清理...');

            const response = await fetch(this.getApiUrl('/api/data/smart-cleanup'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                const summary = result.summary;
                this.showStatus('success', `智能清理完成：清理了 ${summary.files_deleted} 个文件，释放了 ${summary.space_freed} 空间`);
                this.loadStorageStats();
            } else {
                this.showStatus('error', '智能清理失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('智能清理失败:', error);
            this.showStatus('error', '智能清理失败');
        }
    }

    async backupData() {
        try {
            this.showStatus('info', '正在创建数据备份...');

            const response = await fetch(this.getApiUrl('/api/data/backup'), {
                method: 'POST'
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);

                const a = document.createElement('a');
                a.href = url;
                a.download = `llmreader_backup_${new Date().toISOString().split('T')[0]}.zip`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this.showStatus('success', '数据备份已创建并下载');
            } else {
                this.showStatus('error', '创建备份失败');
            }
        } catch (error) {
            console.error('创建备份失败:', error);
            this.showStatus('error', '创建备份失败');
        }
    }

    async rebuildIndex() {
        try {
            this.showStatus('info', '正在重建索引，请稍等...');

            const response = await fetch(this.getApiUrl('/api/data/rebuild-index'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', '索引重建完成');
                this.loadStorageStats();
            } else {
                this.showStatus('error', '重建索引失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('重建索引失败:', error);
            this.showStatus('error', '重建索引失败');
        }
    }

    async fullReset() {
        try {
            this.showStatus('info', '正在执行完全重置...');

            const response = await fetch(this.getApiUrl('/api/data/full-reset'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                // 同时清理本地存储
                localStorage.clear();

                this.showStatus('success', '完全重置完成，系统已恢复到初始状态');

                // 重新加载页面数据
                setTimeout(() => {
                    this.loadStorageStats();
                    this.loadDocumentList();
                    this.loadCacheStats();
                    this.loadChatStats();
                }, 2000);
            } else {
                this.showStatus('error', '完全重置失败：' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('完全重置失败:', error);
            this.showStatus('error', '完全重置失败');
        }
    }

    async exportChatHistory() {
        try {
            this.showStatus('info', '正在导出聊天历史...');

            const response = await fetch(this.getApiUrl('/api/data/export-chat'));

            if (response.ok) {
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);

                const a = document.createElement('a');
                a.href = url;
                a.download = `chat_history_${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this.showStatus('success', '聊天历史已导出');
            } else {
                this.showStatus('error', '导出聊天历史失败');
            }
        } catch (error) {
            console.error('导出聊天历史失败:', error);
            this.showStatus('error', '导出聊天历史失败');
        }
    }

    /* === UI辅助方法 === */

    updateStorageDisplay() {
        document.getElementById('total-documents').textContent = this.stats.totalDocuments;
        document.getElementById('total-size').textContent = this.stats.totalSize;
        document.getElementById('last-cleanup').textContent = this.stats.lastCleanup;
    }

    displayDocumentList(documents) {
        const listContainer = document.getElementById('document-list');

        if (!documents || documents.length === 0) {
            listContainer.innerHTML = '<div class="empty-message">暂无处理过的文档</div>';
            return;
        }

        const documentHTML = documents.map(doc => `
            <div class="document-item">
                <div class="doc-info">
                    <div class="doc-name">${doc.name}</div>
                    <div class="doc-meta">
                        <span class="doc-type">${doc.type}</span>
                        <span class="doc-size">${doc.size}</span>
                        <span class="doc-date">${doc.date}</span>
                    </div>
                </div>
                <div class="doc-actions">
                    <button class="btn btn-sm btn-warning" onclick="window.llmReaderDataApp.deleteDocument('${doc.id}')">
                        🗑️ 删除
                    </button>
                </div>
            </div>
        `).join('');

        listContainer.innerHTML = documentHTML;
    }

    async deleteDocument(docId) {
        this.confirmAction('删除文档', '确定要删除这个文档及其相关数据吗？', async () => {
            try {
                this.showStatus('info', '正在删除文档...');

                const response = await fetch(this.getApiUrl(`/api/data/documents/${docId}`), {
                    method: 'DELETE'
                });

                const result = await response.json();

                if (result.status === 'success') {
                    this.showStatus('success', '文档已删除');
                    this.loadDocumentList();
                    this.loadStorageStats();
                } else {
                    this.showStatus('error', '删除文档失败：' + (result.detail || '未知错误'));
                }
            } catch (error) {
                console.error('删除文档失败:', error);
                this.showStatus('error', '删除文档失败');
            }
        });
    }

    confirmAction(title, message, callback) {
        const dialog = document.getElementById('confirmation-dialog');
        const titleElement = document.getElementById('dialog-title');
        const messageElement = document.getElementById('dialog-message');

        titleElement.textContent = title;
        messageElement.textContent = message;
        this.confirmationCallback = callback;

        dialog.style.display = 'block';
    }

    showStatus(type, message) {
        const statusElement = document.getElementById('data-status');

        statusElement.className = `status-message ${type}`;
        statusElement.textContent = message;
        statusElement.style.display = 'block';

        // 自动隐藏成功和信息消息
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                statusElement.style.display = 'none';
            }, 5000);
        }
    }
}

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 数据管理页面DOM内容已加载');
    setTimeout(() => {
        console.log('🚀 开始初始化数据管理页面应用');
        window.llmReaderDataApp = new LLMReaderDataApp();
    }, 200);
});