/**
 * API 封装
 */

const API = {
    // 文档管理
    documents: {
        async list() {
            const res = await fetch('/api/v1/documents/list');
            if (!res.ok) throw new Error('获取文档列表失败');
            return await res.json();
        },

        async getAvailablePdfs() {
            const res = await fetch('/api/v1/documents/available-pdfs');
            if (!res.ok) throw new Error('获取可用PDF失败');
            return await res.json();
        },

        async upload(file) {
            const formData = new FormData();
            formData.append('file', file);

            const res = await fetch('/api/v1/documents/upload', {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '上传失败');
            }

            return await res.json();
        },

        async index(docName, provider = 'openai', pdfPreset = 'high') {
            const res = await fetch('/api/v1/documents/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    doc_name: docName,
                    provider: provider,
                    pdf_preset: pdfPreset
                })
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '索引失败');
            }

            return await res.json();
        },

        async delete(docName) {
            const res = await fetch(`/api/v1/documents/${docName}`, {
                method: 'DELETE'
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '删除失败');
            }

            return await res.json();
        }
    },

    // 聊天
    chat: {
        async initialize(enabledTools = null, selectedDocs = null, sessionId = null) {
            const res = await fetch('/api/v1/chat/initialize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled_tools: enabledTools,
                    selected_docs: selectedDocs,
                    session_id: sessionId
                })
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '初始化失败');
            }

            return await res.json();
        },

        async clear() {
            const res = await fetch('/api/v1/chat/clear', {
                method: 'POST'
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '清空失败');
            }

            return await res.json();
        },

        async loadMoreMessages(offset = 0, limit = 20) {
            const res = await fetch(`/api/v1/chat/load-more-messages?offset=${offset}&limit=${limit}`);

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '加载历史消息失败');
            }

            return await res.json();
        }
    },

    // 会话管理
    sessions: {
        async list(limit = null) {
            let url = '/api/v1/sessions/list';
            if (limit) {
                url += `?limit=${limit}`;
            }

            const res = await fetch(url);
            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '获取会话列表失败');
            }

            return await res.json();
        },

        async get(sessionId) {
            const res = await fetch(`/api/v1/sessions/${sessionId}`);
            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '获取会话失败');
            }

            return await res.json();
        },

        async delete(sessionId) {
            const res = await fetch(`/api/v1/sessions/${sessionId}`, {
                method: 'DELETE'
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '删除会话失败');
            }

            return await res.json();
        },

        async getCurrent() {
            const res = await fetch('/api/v1/sessions/current/info');
            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '获取当前会话失败');
            }

            return await res.json();
        }
    },

    // 章节
    chapters: {
        async get(docName) {
            const res = await fetch(`/api/v1/chapters/documents/${docName}/chapters`);
            if (!res.ok) throw new Error('获取章节失败');
            return await res.json();
        }
    }
};
