/**
 * API 封装 —— 全站唯一的 fetch 出口。
 *
 * 波次9 收敛：原先各页面 js（manage / config / briefs / dashboard / memory /
 * structure_editor / chat）里各写各的 `fetch(...)`，同样的"拼 header、判状态码、
 * 取 detail、解析 body"抄了十几遍。现在统一收在本文件：
 *
 *   - API.fetch(url, options)     通用底座：只负责拼 method / headers / body，
 *                                 原样返回 Response。需要自己判状态码、自己决定
 *                                 怎么解析 body 的调用点用它（语义与裸 fetch 一致）。
 *   - API.request(url, options)   JSON 调用：默认非 2xx 抛 Error，然后解析 body。
 *   - API.<域>.<方法>(参数...)     各 REST 端点的语义化封装，路径集中在这一处，
 *                                 调用点只传业务参数。
 *
 * options 支持：
 *   method          HTTP 方法，默认 GET
 *   json            请求体对象，自动 JSON.stringify 并补 Content-Type: application/json
 *   formData        FormData 请求体（不补 Content-Type，交给浏览器生成 boundary）
 *   body            已序列化的请求体（原样透传）
 *   headers         追加/覆盖的请求头
 *   raw             true → 直接把 Response 返回给调用方（不判状态码、不解析 body）
 *   parse           'json'（默认）| 'blob' | 'text' | 'none'
 *   checkOk         默认 true；false → 不判状态码，直接解析 body（等价于 res.json()）
 *   useDetailError  true → 失败时优先用响应体的 detail 作为 Error.message
 *   errorText       失败兜底文案：字符串，或 (res) => string（默认 `HTTP <status>`）
 */

const API = (function () {
    const JSON_CONTENT_TYPE = 'application/json';
    const LLM_MEMORY_BASE = '/api/v1/llmmemory';

    function buildInit(options) {
        const init = { method: options.method || 'GET' };
        const headers = Object.assign({}, options.headers);

        if (options.json !== undefined) {
            if (headers['Content-Type'] === undefined) {
                headers['Content-Type'] = JSON_CONTENT_TYPE;
            }
            init.body = JSON.stringify(options.json);
        } else if (options.formData !== undefined) {
            init.body = options.formData;
        } else if (options.body !== undefined) {
            init.body = options.body;
        }

        if (Object.keys(headers).length > 0) {
            init.headers = headers;
        }
        return init;
    }

    function fallbackErrorText(res, options) {
        if (typeof options.errorText === 'function') return options.errorText(res);
        if (options.errorText) return options.errorText;
        return 'HTTP ' + res.status;
    }

    /** 通用底座：唯一的 fetch 调用点。 */
    async function fetchResponse(url, options = {}) {
        return fetch(url, buildInit(options));
    }

    /** JSON 调用：默认判状态码 + 解析 body。raw=true 时退化为 fetchResponse。 */
    async function request(url, options = {}) {
        const res = await fetchResponse(url, options);
        if (options.raw) return res;

        if (options.checkOk !== false && !res.ok) {
            let message = null;
            if (options.useDetailError) {
                try {
                    const body = await res.json();
                    if (body && body.detail) {
                        message = typeof body.detail === 'string'
                            ? body.detail
                            : JSON.stringify(body.detail);
                    }
                } catch (e) {
                    // 错误体不是 JSON：退回兜底文案
                }
            }
            throw new Error(message || fallbackErrorText(res, options));
        }

        switch (options.parse) {
            case 'none':
                return undefined;
            case 'blob':
                return res.blob();
            case 'text':
                return res.text();
            default:
                return res.json();
        }
    }

    function withDefaults(defaults, options) {
        return Object.assign({}, defaults, options || {});
    }

    const api = {
        fetch: fetchResponse,
        request: request,

        // 文档管理
        documents: {
            // options 里传 raw:true 可拿回 Response 自己判状态码（/memory 页那种
            // "先解析 body 再按 detail 报错"的写法）；不传时保持原有行为：
            // 非 2xx 抛 Error('获取文档列表失败')。
            async list(options = {}) {
                return request('/api/v1/documents/list',
                    withDefaults({ errorText: '获取文档列表失败' }, options));
            },

            async availablePdfs(options = {}) {
                return request('/api/v1/documents/available-pdfs', withDefaults({ raw: true }, options));
            },

            async index(docName, options = {}) {
                return request('/api/v1/documents/index',
                    withDefaults({ method: 'POST', json: { doc_name: docName }, raw: true }, options));
            }
        },

        // PDF 页面图（pdf.js 直接拿这个 URL 去取文档，不是 fetch，所以只集中路径）
        pdf: {
            viewUrl(docName) {
                return '/api/v1/pdf/view/' + docName;
            }
        },

        // LLM-Memory 桥（/api/v1/llmmemory/*，转发给外部 LLM-Memory webui）
        // 同 documents 的三个 raw 封装：/memory 页自己判状态码并解析 detail。
        llmmemory: {
            async dates(options = {}) {
                return request(LLM_MEMORY_BASE + '/dates', withDefaults({ raw: true }, options));
            },

            async enqueueLoadJobs(dates, options = {}) {
                return request(LLM_MEMORY_BASE + '/load-jobs',
                    withDefaults({ method: 'POST', json: { dates }, raw: true }, options));
            },

            async loadJobs(options = {}) {
                return request(LLM_MEMORY_BASE + '/load-jobs', withDefaults({ raw: true }, options));
            },

            async download(url, options = {}) {
                return request(LLM_MEMORY_BASE + '/download',
                    withDefaults({ method: 'POST', json: { url }, raw: true }, options));
            },

            async chat(message, history, options = {}) {
                return request(LLM_MEMORY_BASE + '/chat',
                    withDefaults({ method: 'POST', json: { message, history }, raw: true }, options));
            },

            async chatProgress(jobId, options = {}) {
                return request(LLM_MEMORY_BASE + '/chat/progress/' + jobId,
                    withDefaults({ raw: true }, options));
            }
        },

        // 聊天
        chat: {
            async initialize(enabledTools = null, selectedDocs = null, sessionId = null) {
                return request('/api/v1/chat/initialize', {
                    method: 'POST',
                    json: {
                        enabled_tools: enabledTools,
                        selected_docs: selectedDocs,
                        session_id: sessionId
                    },
                    useDetailError: true,
                    errorText: '初始化失败'
                });
            },

            /**
             * 清空会话历史。
             * @param {string} [sessionId] 传了才带 body（不传保持旧行为：服务端按
             *        "最近活跃会话"清空），chat 页显式传当前会话 id 避免清错文件。
             */
            async clear(sessionId = undefined) {
                const options = {
                    method: 'POST',
                    useDetailError: true,
                    errorText: '清空失败'
                };
                if (sessionId !== undefined) {
                    options.json = { session_id: sessionId || null };
                }
                return request('/api/v1/chat/clear', options);
            },

            async loadMoreMessages(offset, limit = 20, sessionId = null) {
                const url = '/api/v1/chat/load-more-messages?offset=' + offset +
                    '&limit=' + limit +
                    (sessionId ? '&session_id=' + encodeURIComponent(sessionId) : '');
                return request(url, { errorText: '加载失败' });
            }
        },

        // 语音
        speech: {
            async transcribe(audioBlob) {
                const formData = new FormData();
                formData.append('file', audioBlob, 'recording.webm');

                return request('/api/v1/speech/transcribe', {
                    method: 'POST',
                    formData: formData,
                    useDetailError: true,
                    errorText: '语音转文字失败'
                });
            },

            async synthesize(text) {
                return request('/api/v1/speech/synthesize', {
                    method: 'POST',
                    json: { text },
                    parse: 'blob',
                    useDetailError: true,
                    errorText: '语音合成失败'
                });
            }
        },

        // 会话管理（/api/v1/sessions）
        sessions: {
            async list(options = {}) {
                return request('/api/v1/sessions/list', withDefaults({ errorText: '获取会话列表失败' }, options));
            },

            async get(sessionId, options = {}) {
                return request('/api/v1/sessions/' + sessionId,
                    withDefaults({ errorText: 'Failed to fetch session detail' }, options));
            },

            async remove(sessionId, options = {}) {
                return request('/api/v1/sessions/' + sessionId,
                    withDefaults({ method: 'DELETE', errorText: '删除会话失败' }, options));
            },

            async rename(sessionId, newTitle, options = {}) {
                return request('/api/v1/sessions/' + sessionId + '/rename',
                    withDefaults({ method: 'PATCH', json: { new_title: newTitle }, errorText: 'Failed to rename session' }, options));
            }
        },

        // 数据管理（/api/v1/data）
        data: {
            async overview(options = {}) {
                return request('/api/v1/data/overview', withDefaults({ errorText: 'Failed to fetch overview' }, options));
            },

            async documents(options = {}) {
                return request('/api/v1/data/documents', withDefaults({ errorText: 'Failed to fetch documents' }, options));
            },

            async documentSummary(docName, options = {}) {
                return request('/api/v1/data/documents/' + encodeURIComponent(docName) + '/summary',
                    withDefaults({ errorText: 'Failed to fetch document summary' }, options));
            },

            async pendingPdfs(options = {}) {
                return request('/api/v1/data/documents/pending',
                    withDefaults({ errorText: 'Failed to fetch pending PDFs' }, options));
            },

            async sessionStats(options = {}) {
                return request('/api/v1/data/sessions/stats',
                    withDefaults({ errorText: 'Failed to fetch session stats' }, options));
            },

            async deleteDocumentParts(docName, parts, options = {}) {
                return request('/api/v1/data/documents/' + docName + '/parts',
                    withDefaults({ method: 'DELETE', json: { parts }, useDetailError: true, errorText: 'Failed to delete document' }, options));
            },

            async deleteDocuments(docNames, deleteSource = false, options = {}) {
                return request('/api/v1/data/documents',
                    withDefaults({
                        method: 'DELETE',
                        json: { doc_names: docNames, delete_source: deleteSource },
                        errorText: 'Failed to batch delete documents'
                    }, options));
            },

            async smartCleanup(days, options = {}) {
                return request('/api/v1/data/cleanup/smart?days=' + days,
                    withDefaults({ method: 'POST', errorText: 'Failed to cleanup' }, options));
            },

            async indexDocument(filename, errorText = 'Index failed', options = {}) {
                return request('/api/v1/data/documents/' + encodeURIComponent(filename) + '/index',
                    withDefaults({ method: 'POST', useDetailError: true, errorText }, options));
            },

            async task(taskId, options = {}) {
                return request('/api/v1/data/tasks/' + taskId,
                    withDefaults({ errorText: 'Failed to fetch task' }, options));
            },

            // 原调用点是"先 json().catch(()=>({}))，再按 result.detail 报错"，
            // 所以默认 raw 把 Response 交回调用方，自己复用解析出来的 body。
            async deletePdfSources(filenames, options = {}) {
                return request('/api/v1/data/pdfs',
                    withDefaults({ method: 'DELETE', json: { filenames }, raw: true }, options));
            }
        },

        // 配置（/api/v1/config）
        config: {
            async get(options = {}) {
                return request('/api/v1/config', withDefaults({ checkOk: false }, options));
            },

            async saveProvider(providerConfig, options = {}) {
                return request('/api/v1/config/provider',
                    withDefaults({ method: 'POST', json: providerConfig, errorText: '保存提供商配置失败' }, options));
            },

            async saveSystem(systemConfig, options = {}) {
                return request('/api/v1/config/system',
                    withDefaults({ method: 'POST', json: systemConfig, errorText: '保存系统配置失败' }, options));
            },

            async reset(options = {}) {
                return request('/api/v1/config/reset',
                    withDefaults({ method: 'POST', errorText: '重置配置失败' }, options));
            }
        },

        // 每日简报（/api/v1/briefs）
        briefs: {
            async dates(options = {}) {
                return request('/api/v1/briefs/dates', withDefaults({ errorText: '加载简报日期失败' }, options));
            },

            async cards(coverageDate, options = {}) {
                return request('/api/v1/briefs/cards?coverage_date=' + encodeURIComponent(coverageDate),
                    withDefaults({ errorText: '加载简报内容失败' }, options));
            },

            async load(coverageDate, itemIds, options = {}) {
                return request('/api/v1/briefs/load',
                    withDefaults({ method: 'POST', json: { coverage_date: coverageDate, item_ids: itemIds }, errorText: '加载简报失败' }, options));
            },

            async syncMemory(options = {}) {
                return request('/api/v1/briefs/sync-memory',
                    withDefaults({ method: 'POST', parse: 'none', errorText: '补灌记忆失败' }, options));
            }
        },

        // 后台任务（/api/v1/jobs）
        jobs: {
            async list(options = {}) {
                return request('/api/v1/jobs', withDefaults({ errorText: '加载任务失败' }, options));
            },

            async cancel(jobId, options = {}) {
                return request('/api/v1/jobs/' + encodeURIComponent(jobId) + '/cancel',
                    withDefaults({ method: 'POST', useDetailError: true }, options));
            },

            async action(jobId, act, options = {}) {
                return request('/api/v1/jobs/' + encodeURIComponent(jobId) + '/' + act,
                    withDefaults({ method: 'POST', useDetailError: true }, options));
            }
        },

        // 长期记忆浏览（/api/v1/memory）
        memory: {
            async overview(options = {}) {
                return request('/api/v1/memory/overview',
                    withDefaults({ errorText: 'Failed to fetch memory overview' }, options));
            },

            async namespace(namespace, options = {}) {
                return request('/api/v1/memory/namespace/' + encodeURIComponent(namespace),
                    withDefaults({ errorText: 'Failed to fetch memory namespace' }, options));
            },

            async search(query, namespace = null, options = {}) {
                return request('/api/v1/memory/search',
                    withDefaults({ method: 'POST', json: { query, namespace }, errorText: '记忆检索失败' }, options));
            },

            async deleteItem(memoryId, options = {}) {
                return request('/api/v1/memory/item/' + encodeURIComponent(memoryId),
                    withDefaults({ method: 'DELETE', errorText: '删除记忆失败' }, options));
            },

            async deleteSource(namespace, sourceId, options = {}) {
                return request('/api/v1/memory/namespace/' + encodeURIComponent(namespace) +
                    '/source/' + encodeURIComponent(sourceId),
                    withDefaults({ method: 'DELETE', errorText: '删除记忆来源失败' }, options));
            },

            async deleteNamespace(namespace, options = {}) {
                return request('/api/v1/memory/namespace/' + encodeURIComponent(namespace),
                    withDefaults({ method: 'DELETE', errorText: '清空记忆 namespace 失败' }, options));
            }
        },

        // 结构编辑器（/api/v1/structure）
        structure: {
            async get(docName, options = {}) {
                return request('/api/v1/structure/' + docName, withDefaults({ checkOk: false }, options));
            },

            async save(docName, agendaDict, hasToc = false, options = {}) {
                return request('/api/v1/structure/' + docName,
                    withDefaults({ method: 'PUT', json: { agenda_dict: agendaDict, has_toc: hasToc }, checkOk: false }, options));
            },

            async rebuild(docName, options = {}) {
                return request('/api/v1/structure/' + docName + '/rebuild',
                    withDefaults({ method: 'POST', checkOk: false }, options));
            }
        }
    };

    return api;
})();
