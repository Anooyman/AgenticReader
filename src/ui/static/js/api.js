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
        }
    },

    // 语音
    speech: {
        async transcribe(audioBlob) {
            const formData = new FormData();
            formData.append('file', audioBlob, 'recording.webm');

            const res = await fetch('/api/v1/speech/transcribe', {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '语音转文字失败');
            }

            return await res.json();
        },

        async synthesize(text) {
            const res = await fetch('/api/v1/speech/synthesize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || '语音合成失败');
            }

            return await res.blob();
        }
    }
};
