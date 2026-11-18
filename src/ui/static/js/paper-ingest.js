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
 *     docName, status: 'exists'|'started'|..., indexed, registryDocName,
 *     indexState: 'indexed'|'not_indexed'|'unknown'|null, note, error }
 * 页面各自决定怎么把状态画到按钮上，避免 chat.js / briefs.js 两份复制。
 * exists 时后端的 note（索引已在位 / 刚补排一次）直接拿来当按钮文案，
 * 轮询同时认 docName 与 registryDocName——registry 里历史名字可能带版本号。
 */
(function (global) {
    'use strict';

    const POLL_MS = 5000;
    const DEADLINE_MS = 30 * 60 * 1000;

    // 每个 URL 上一次的结果摘要——只为一个判断：上一轮是不是"文件已在库但
    // 没索引"。是的话这次重试就带 force 重下一遍（半截文件光等索引永远等
    // 不出来）；上一轮是正常在索引的，就别重下，免得同一篇论文被排第二遍
    // 索引、白烧 LLM。
    const lastOutcome = new Map();

    async function postFetchPdf(url, force) {
        if (!force) return API.briefs.fetchPdf(url);
        // force 这条走 api.fetch——api.briefs.fetchPdf 的 body 形状是固定的
        // {url}，多带一个键得先改 api.js，而 api.js 不归本任务管。
        const res = await API.fetch('/api/v1/briefs/fetch-pdf',
            { method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url, force: true }) });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
            throw new Error((data && data.detail) || 'HTTP ' + res.status);
        }
        return data || {};
    }

    async function start(url, onState) {
        const state = { phase: 'downloading', docName: null, status: null, indexed: false, error: null,
                        // fetch-pdf 的 exists 分支会带索引状态回来：registry 的
                        // 历史 doc_name 可能带版本号（手动上传那批），轮询要多认一个键
                        registryDocName: null, indexState: null, note: null };
        if (onState) onState(state);

        const prev = lastOutcome.get(url);
        const force = !!(prev && prev.status === 'exists' && !prev.indexed);
        let result;
        try {
            result = await postFetchPdf(url, force);
        } catch (err) {
            state.phase = 'failed';
            state.error = err.message || String(err);
            if (onState) onState(state);
            return state;
        }
        lastOutcome.set(url, { status: result.status, indexed: !!result.indexed });
        state.docName = String(result.doc_name || '').replace(/\.pdf$/i, '');
        state.registryDocName = String(result.registry_doc_name || '').replace(/\.pdf$/i, '');
        state.indexState = result.index_state || null;
        state.note = result.note || null;
        state.status = result.status;
        state.phase = 'indexing';
        if (result.status === 'exists' && result.indexed) {
            // 后端已经确认索引在位，不必再空等一轮轮询
            state.indexed = true;
            state.phase = 'indexed';
            if (onState) onState(state);
            return state;
        }
        if (result.status === 'exists' && result.reindex_started) {
            // 文件早在库里但索引没成——后端已补排，这里继续等即可，
            // note 里有话可展示（不重下、不重复下载）。
            state.phase = 'indexing';
            if (onState) onState(state);
        }

        // exists / started 之后都是同一段等待：等这个 doc 出现在已索引列表。
        await new Promise((resolve) => {
            const deadline = Date.now() + DEADLINE_MS;
            const names = [state.docName, state.registryDocName].filter(Boolean);
            const timer = setInterval(async () => {
                try {
                    const docs = await API.documents.list({ checkOk: false });
                    const hit = (docs || []).find(
                        (d) => names.includes(String(d.doc_name || '').replace(/\.pdf$/i, '')));
                    if (hit) {
                        state.indexed = true;
                        clearInterval(timer);
                        state.phase = 'indexed';
                        if (!state.docName) state.docName = String(hit.doc_name || '').replace(/\.pdf$/i, '');
                        lastOutcome.delete(url);  // 成了，下次点不触发强制重下
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
