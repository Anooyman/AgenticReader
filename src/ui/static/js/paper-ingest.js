/**
 * 共享原语：论文"按需收入 PDF 文档库"（点击是唯一触发点——不自动下载，
 * 用户从对话回复/简报卡片里自己挑哪篇值得收入文档库精读）。
 *
 * 流程：
 *   POST /api/v1/briefs/fetch-pdf（下载到 data/pdf + 后台 IndexingAgent）
 *   → 轮询 GET /api/v1/documents/list 直到该 doc_name 或 registryDocName 出现在已索引列表。
 *
 * 本模块不碰 DOM：状态只通过 onState(state) 回调外抛——
 *   { phase: 'downloading' | 'indexing' | 'indexed' | 'timeout' | 'failed',
 *     docName, status: 'exists'|'started'|..., indexed, registryDocName,
 *     indexState: 'indexed'|'not_indexed'|'indexed_elsewhere'|'unknown'|null,
 *     note, error }
 * 第三个可选参数 opts = { signal?: AbortSignal } 允许调用方（如切日期）中止轮询；
 * 省略 opts 时与 chat.js 既有两参数调用完全向后兼容。
 */
(function (global) {
    'use strict';

    const POLL_MS = 5000;
    const DEADLINE_MS = 30 * 60 * 1000;

    // 每个 URL 上一次的结果摘要：上一轮是"文件已在库但没索引"时重试带 force 重下。
    const lastOutcome = new Map();

    async function postFetchPdf(url, force) {
        return API.briefs.fetchPdf(url, force ? { force: true } : {});
    }

    async function start(url, onState, opts = {}) {
        const signal = opts && opts.signal ? opts.signal : null;
        const state = {
            phase: 'downloading',
            docName: null,
            status: null,
            indexed: false,
            error: null,
            registryDocName: null,
            indexState: null,
            note: null,
        };
        if (onState) onState(state);

        const prev = lastOutcome.get(url);
        const force = !!(prev && prev.status === 'exists' && !prev.indexed && prev.indexState !== 'indexed_elsewhere');
        let result;
        try {
            result = await postFetchPdf(url, force);
        } catch (err) {
            state.phase = 'failed';
            state.error = err.message || String(err);
            if (onState) onState(state);
            return state;
        }
        lastOutcome.set(url, {
            status: result.status,
            indexed: !!result.indexed,
            indexState: result.index_state || null,
        });
        state.docName = String(result.doc_name || '').replace(/\.pdf$/i, '');
        state.registryDocName = String(result.registry_doc_name || '').replace(/\.pdf$/i, '');
        state.indexState = result.index_state || null;
        state.note = result.note || null;
        state.status = result.status;
        state.phase = 'indexing';

        // 后端已经确认精确同名或兄弟版本号已索引，无需空等轮询
        if (result.status === 'exists' && (result.indexed || result.index_state === 'indexed_elsewhere')) {
            state.indexed = true;
            state.phase = 'indexed';
            if (result.index_state === 'indexed_elsewhere' && state.registryDocName) {
                state.docName = state.registryDocName;
            }
            lastOutcome.delete(url);
            if (onState) onState(state);
            return state;
        }
        if (result.status === 'exists' && result.reindex_started) {
            state.phase = 'indexing';
            if (onState) onState(state);
        }

        if (signal && signal.aborted) {
            return state;
        }

        await new Promise((resolve) => {
            const deadline = Date.now() + DEADLINE_MS;
            const names = [state.docName, state.registryDocName].filter(Boolean);
            let done = false;

            const finish = () => {
                if (done) return;
                done = true;
                clearInterval(timer);
                if (signal) signal.removeEventListener('abort', onAbort);
                resolve();
            };

            const onAbort = () => finish();
            if (signal) signal.addEventListener('abort', onAbort, { once: true });

            const timer = setInterval(async () => {
                if (signal && signal.aborted) {
                    finish();
                    return;
                }
                try {
                    const docs = await API.documents.list({ checkOk: false });
                    const hit = (docs || []).find(
                        (d) => names.includes(String(d.doc_name || '').replace(/\.pdf$/i, '')));
                    if (hit) {
                        state.indexed = true;
                        state.phase = 'indexed';
                        state.docName = String(hit.doc_name || '').replace(/\.pdf$/i, '') || state.docName;
                        lastOutcome.delete(url);
                        finish();
                        if (onState) onState(state);
                        return;
                    }
                } catch (err) {
                    // 轮询瞬时失败不终止——由 deadline 兜底
                }
                if (Date.now() > deadline) {
                    state.phase = 'timeout';
                    finish();
                }
                if (onState) onState(state);
            }, POLL_MS);
        });
        return state;
    }

    global.PaperIngest = { start };
})(window);
