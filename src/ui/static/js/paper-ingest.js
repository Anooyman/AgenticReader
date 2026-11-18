/**
 * 共享原语：论文"按需下载入库"（点击是唯一触发点——不自动下载，
 * 用户从对话回复/简报卡片里自己挑哪篇值得入库）。
 *
 * 流程与 /briefs 卡片的"⬇下载入库"完全同源：
 *   POST /api/v1/briefs/fetch-pdf（下载到 data/pdf + 后台 IndexingAgent）
 *   → 轮询 GET /api/documents/list 直到该 doc_name 出现在已索引列表。
 *
 * 本模块刻意不碰 DOM：状态只通过 onState(state) 回调外抛——
 *   { phase: 'downloading' | 'indexing' | 'indexed' | 'timeout' | 'failed',
 *     docName, status: 'exists'|'started'|..., error }
 * 页面各自决定怎么把状态画到按钮上，避免 chat.js / briefs.js 两份复制。
 */
(function (global) {
    'use strict';

    const POLL_MS = 5000;
    const DEADLINE_MS = 30 * 60 * 1000;

    async function start(url, onState) {
        const state = { phase: 'downloading', docName: null, status: null, indexed: false, error: null };
        if (onState) onState(state);

        let result;
        try {
            result = await API.briefs.fetchPdf(url);
        } catch (err) {
            state.phase = 'failed';
            state.error = err.message || String(err);
            if (onState) onState(state);
            return state;
        }
        state.docName = String(result.doc_name || '').replace(/\.pdf$/i, '');
        state.status = result.status;
        state.phase = 'indexing';
        if (onState) onState(state);

        // exists / started 之后都是同一段等待：等这个 doc 出现在已索引列表。
        await new Promise((resolve) => {
            const deadline = Date.now() + DEADLINE_MS;
            const timer = setInterval(async () => {
                try {
                    const docs = await API.documents.list({ checkOk: false });
                    const hit = (docs || []).find(
                        (d) => String(d.doc_name || '').replace(/\.pdf$/i, '') === state.docName);
                    if (hit) {
                        state.indexed = true;
                        clearInterval(timer);
                        state.phase = 'indexed';
                        resolve();
                        if (onState) onState(state);
                        return;
                    }
                } catch (err) {
                    // 轮询失败不终止——deadline 兜底，列表瞬时故障继续等
                }
                if (Date.now() > deadline) {
                    clearInterval(timer);
                    state.phase = 'timeout';
                    resolve();
                }
                if (onState) onState(state);
            }, POLL_MS);
        });
        return state;
    }

    global.PaperIngest = { start };
})(window);
