/**
 * 轻量全局 i18n：中英文切换。
 *
 * 设计目标：
 * 1. 不依赖后端；语言偏好存在 localStorage；
 * 2. 页面加载完成后自动翻译 DOM 中的 UI 文案；
 * 3. 后续动态插入的节点也会被 MutationObserver 自动翻译；
 * 4. locale 文件可分别注册 exact 映射与 regex patterns，避免为了换语言去逐行改大量 DOM；
 * 5. 每个文本节点/属性会保留原始文案，因此切换回中文也能恢复原文；
 * 6. LLM 答案/文档正文/日志通常不在 locale 中注册，因此不会被强行翻译。
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'AgenticReader_lang';
    const SUPPORTED = { zh: '中文', en: 'English' };

    const exact = { zh: {}, en: {} };
    const reverse = { zh: {}, en: {} };
    const patterns = { zh: [], en: [] };
    const listeners = [];
    const textOriginal = typeof WeakMap === 'function' ? new WeakMap() : null;
    const attrOriginal = typeof WeakMap === 'function' ? new WeakMap() : null;

    function getInitialLang() {
        let saved = null;
        try {
            saved = global.localStorage ? global.localStorage.getItem(STORAGE_KEY) : null;
        } catch (_) {
            saved = null;
        }
        if (saved === 'en' || saved === 'zh') return saved;
        return 'zh';
    }

    let lang = getInitialLang();
    document.documentElement.setAttribute('data-lang', lang);
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';

    function shouldSkipNode(node) {
        if (!node) return true;
        if (node.nodeType === Node.COMMENT_NODE) return true;
        if (node.nodeType === Node.ELEMENT_NODE) {
            const tag = node.tagName && node.tagName.toLowerCase();
            if (!tag) return true;
            if (tag === 'script' || tag === 'style' || tag === 'code' || tag === 'pre' || tag === 'textarea') return true;
            if (node.hasAttribute && node.hasAttribute('data-i18n-skip')) return true;
            if (node.closest && node.closest('.i18n-skip')) return true;
            // 聊天正文/文档正文由调用方自行控制，不默认翻译长文本
            if (node.closest && node.closest('.chat-messages, .message-content, .bubble, .markdown-body, .pdf-page canvas')) return true;
        }
        return false;
    }

    function isTextCandidate(node) {
        return node.nodeType === Node.TEXT_NODE && node.nodeValue && node.nodeValue.trim().length > 0;
    }

    function applyExact(target, text) {
        const map = exact[target] || {};
        if (Object.prototype.hasOwnProperty.call(map, text)) return map[text];
        return text;
    }

    function applyPatterns(target, text) {
        let out = text;
        const list = patterns[target] || [];
        for (const entry of list) {
            if (!entry) continue;
            const re = entry.re instanceof RegExp ? entry.re : (entry.re && entry.re.re ? entry.re.re : null);
            const flags = re ? (re.flags || '') : (entry.flags || '');
            let targetRe = re;
            if (targetRe && flags.includes('g') && !targetRe.global) {
                targetRe = new RegExp(targetRe.source, flags);
            }
            if (!targetRe) {
                if (typeof entry.test === 'function' && entry.test(out) && entry.to) {
                    const before = out;
                    out = typeof entry.to === 'function' ? entry.to(out) : entry.to;
                    if (before !== out && entry.stopIfChanged) break;
                }
                continue;
            }
            if (!targetRe.test(out)) continue;
            const repl = typeof entry.repl === 'function' ? entry.repl : entry.repl ?? '$1';
            const before = out;
            out = out.replace(targetRe, repl);
            if (before === out && entry.stopIfUnchanged) break;
        }
        return out;
    }

    function transform(original, originalKnown) {
        if (lang === 'zh') {
            return original;
        }
        const exacted = applyExact('en', original);
        if (exacted !== original) return exacted;
        return applyPatterns('en', original);
    }

    function hasTextOriginal(node) {
        return Boolean(textOriginal) && textOriginal.has(node);
    }

    function getTextOriginal(node) {
        if (textOriginal && textOriginal.has(node)) return textOriginal.get(node);
        return node.nodeValue;
    }

    function setTextOriginal(node, original) {
        if (textOriginal) textOriginal.set(node, original);
    }

    function hasAttrOriginal(el, attr) {
        const store = attrOriginal ? attrOriginal.get(el) : null;
        return Boolean(store && Object.prototype.hasOwnProperty.call(store, attr));
    }

    function getAttrOriginal(el, attr) {
        const store = attrOriginal ? attrOriginal.get(el) : null;
        if (store && Object.prototype.hasOwnProperty.call(store, attr)) return store[attr];
        return el.getAttribute(attr);
    }

    function setAttrOriginal(el, attr, original) {
        let store = attrOriginal ? attrOriginal.get(el) : null;
        if (!store) {
            store = {};
            if (attrOriginal) attrOriginal.set(el, store);
        }
        store[attr] = original;
    }

    function applyAttributes(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) return;
        const attrs = ['placeholder', 'aria-label', 'title', 'alt', 'data-tooltip'];
        attrs.forEach((attr) => {
            if (!el.hasAttribute || !el.hasAttribute(attr)) return;
            const known = hasAttrOriginal(el, attr);
            const original = known ? getAttrOriginal(el, attr) : (el.getAttribute(attr) || '');
            if (!known) setAttrOriginal(el, attr, original);
            const translated = transform(original);
            const current = el.getAttribute(attr);
            if (translated !== current) el.setAttribute(attr, translated);
        });
    }

    function applyToTextNodes(root, seen) {
        if (!root || shouldSkipNode(root)) return;
        const set = seen || new WeakSet();
        if (root.nodeType === Node.TEXT_NODE) {
            const known = hasTextOriginal(root);
            const original = known ? getTextOriginal(root) : root.nodeValue;
            if (!known) setTextOriginal(root, original);
            const translated = transform(original);
            if (root.nodeValue !== translated) {
                root.nodeValue = translated;
            }
            return;
        }
        if (root.nodeType === Node.ELEMENT_NODE) {
            if (set.has(root)) return;
            set.add(root);
            applyAttributes(root);
            Array.from(root.childNodes || []).forEach((child) => applyToTextNodes(child, set));
            return;
        }
    }

    function applyTitle() {
        const hasOriginal = Object.prototype.hasOwnProperty.call(global, '__i18nOriginalTitle');
        const original = hasOriginal ? global.__i18nOriginalTitle : document.title;
        global.__i18nOriginalTitle = original;
        const translated = transform(original || '');
        if (document.title !== translated) document.title = translated;
    }

    function applyAll(root) {
        const scope = root || document.body;
        if (!scope) return;
        applyToTextNodes(scope.nodeType === Node.DOCUMENT ? document.body : scope);
        applyTitle();
    }

    let observer = null;
    function startObserver() {
        if (observer || typeof MutationObserver === 'undefined') return;
        observer = new MutationObserver((mutations) => {
            for (const m of mutations) {
                if (m.type === 'childList') {
                    Array.from(m.addedNodes).forEach((node) => applyToTextNodes(node));
                } else if (m.type === 'attributes') {
                    applyAttributes(m.target);
                }
            }
        });
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['placeholder', 'aria-label', 'title', 'alt', 'data-tooltip'],
        });
    }

    function emitChange() {
        try {
            const evt = new CustomEvent('i18n:change', { detail: { lang } });
            document.dispatchEvent(evt);
        } catch (_) {
            listeners.slice().forEach((fn) => {
                try { fn(lang); } catch (e) { console.error('[i18n] listener error', e); }
            });
        }
    }

    function rebuildReverseMaps() {
        reverse.zh = { reverse: {} };
        reverse.en = { reverse: {} };
        Object.keys(exact).forEach((target) => {
            const rev = reverse[target] ? reverse[target].reverse : {};
            reverse[target].reverse = rev;
        });
        Object.keys(exact.en || {}).forEach((source) => {
            const target = exact.en[source];
            if (typeof target === 'string' && !reverse.en.reverse[target]) {
                reverse.en.reverse[target] = source;
            }
            if (typeof target === 'string' && !reverse.zh.reverse[target]) {
                reverse.zh.reverse[target] = source;
            }
        });
    }

    function setLang(next) {
        next = (next || '').toLowerCase();
        if (next !== 'en' && next !== 'zh') next = 'zh';
        if (next === lang) return lang;
        lang = next;
        try {
            if (global.localStorage) global.localStorage.setItem(STORAGE_KEY, lang);
        } catch (_) {
            // 私密模式失败不影响切换
        }
        document.documentElement.setAttribute('data-lang', lang);
        document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
        applyAll(document.body);
        updateToggleUI();
        emitChange();
        return lang;
    }

    function toggle() {
        return setLang(lang === 'en' ? 'zh' : 'en');
    }

    function register(entries) {
        const source = entries || {};
        const target = source.lang || 'en';
        if (!exact[target]) exact[target] = {};
        if (!reverse[target]) reverse[target] = { reverse: {} };
        if (!patterns[target]) patterns[target] = [];
        if (source.exact) {
            Object.keys(source.exact).forEach((key) => {
                const value = source.exact[key];
                if (value !== undefined && value !== null) {
                    exact[target][key] = value;
                }
            });
        }
        if (Array.isArray(source.patterns)) {
            source.patterns.forEach((p) => {
                if (p && p.re) patterns[target].push(p);
            });
        }
        rebuildReverseMaps();
    }

    function t(text, original) {
        if (textOriginal && original !== undefined) {
            // 允许调用方显式告诉 i18n 原始文案，避免把已翻译结果误认成原文。
            return transform(String(original == null ? text : original));
        }
        return transform(String(text == null ? '' : text));
    }

    function onChange(fn) {
        if (typeof fn === 'function') {
            listeners.push(fn);
            document.addEventListener('i18n:change', (e) => {
                try { fn(e.detail.lang); } catch (err) { console.error(err); }
            });
        }
    }

    function updateToggleUI() {
        document.querySelectorAll('[data-i18n-lang-btn]').forEach((btn) => {
            const other = lang === 'en' ? '中文' : 'English';
            btn.textContent = other;
            btn.setAttribute('aria-pressed', lang === 'en' ? 'true' : 'false');
            btn.title = lang === 'en' ? '切换到中文' : 'Switch to English';
            btn.classList.toggle('is-en', lang === 'en');
        });
    }

    function bindToggleButtons() {
        const buttons = Array.from(document.querySelectorAll('[data-i18n-lang-btn]'));
        buttons.forEach((btn) => {
            if (btn.__i18nBound) return;
            btn.__i18nBound = true;
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                toggle();
            });
        });
        updateToggleUI();
    }

    function boot() {
        bindToggleButtons();
        startObserver();
        applyAll(document.body);
        updateToggleUI();
    }

    const DEFAULT_LABELS = {
        confirm: { zh: '确定', en: 'OK' },
        cancel: { zh: '取消', en: 'Cancel' },
        title: { zh: '确认操作', en: 'Confirm action' },
    };

    function ensureDialogDom() {
        let host = document.querySelector('.i18n-dialog-host');
        if (host) return host;
        host = document.createElement('div');
        host.className = 'i18n-dialog-host';
        host.innerHTML = `
            <div class="i18n-dialog-overlay" hidden>
                <div class="i18n-dialog-card" role="dialog" aria-modal="true" aria-labelledby="i18n-dialog-title">
                    <div class="i18n-dialog-head">
                        <h3 id="i18n-dialog-title"></h3>
                    </div>
                    <div class="i18n-dialog-body">
                        <div id="i18n-dialog-message"></div>
                        <input id="i18n-dialog-input" class="i18n-dialog-input" hidden />
                    </div>
                    <div class="i18n-dialog-actions">
                        <button type="button" class="btn btn-ghost btn-sm" id="i18n-dialog-cancel"></button>
                        <button type="button" class="btn btn-primary btn-sm" id="i18n-dialog-ok"></button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(host);
        return host;
    }

    function dialogLabel(key, fallback) {
        const map = DEFAULT_LABELS[key] || {};
        return map[lang] || (lang === 'en' ? (map.en || fallback) : (map.zh || fallback));
    }

    function closeDialog(result) {
        const host = ensureDialogDom();
        const overlay = host.querySelector('.i18n-dialog-overlay');
        const input = host.querySelector('#i18n-dialog-input');
        overlay.hidden = true;
        overlay.classList.remove('is-prompt');
        if (input) {
            input.hidden = true;
            input.value = '';
            input.onkeydown = null;
        }
        const ok = host.querySelector('#i18n-dialog-ok');
        const cancel = host.querySelector('#i18n-dialog-cancel');
        ok.onclick = null;
        cancel.onclick = null;
        overlay.onkeydown = null;
        if (host._i18nResolve) {
            const resolve = host._i18nResolve;
            host._i18nResolve = null;
            resolve(result);
        }
    }

    function openDialog(opts) {
        const host = ensureDialogDom();
        const overlay = host.querySelector('.i18n-dialog-overlay');
        const titleEl = host.querySelector('#i18n-dialog-title');
        const messageEl = host.querySelector('#i18n-dialog-message');
        const input = host.querySelector('#i18n-dialog-input');
        const ok = host.querySelector('#i18n-dialog-ok');
        const cancel = host.querySelector('#i18n-dialog-cancel');
        if (host._i18nResolve) {
            const resolve = host._i18nResolve;
            host._i18nResolve = null;
            resolve(null);
        }
        titleEl.textContent = t(opts.title || dialogLabel('title'));
        messageEl.textContent = t(opts.message || '');
        input.hidden = opts.type !== 'prompt';
        if (opts.type === 'prompt') {
            input.value = String(opts.value == null ? '' : opts.value);
            input.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    closeDialog(input.value);
                } else if (e.key === 'Escape') {
                    closeDialog(null);
                }
            };
        } else {
            input.onkeydown = null;
        }
        ok.textContent = t(opts.okText || dialogLabel('confirm'));
        cancel.textContent = t(opts.cancelText || dialogLabel('cancel'));
        cancel.hidden = opts.type === 'alert';
        if (opts.type === 'alert') ok.classList.add('is-single');
        else ok.classList.remove('is-single');
        ok.onclick = () => closeDialog(opts.type === 'prompt' ? input.value : (opts.type === 'alert' ? undefined : true));
        cancel.onclick = () => closeDialog(opts.type === 'alert' ? undefined : (opts.type === 'prompt' ? null : false));
        overlay.onkeydown = (e) => {
            if (e.key === 'Escape') closeDialog(opts.type === 'prompt' ? null : false);
        };
        overlay.hidden = false;
        overlay.classList.toggle('is-prompt', opts.type === 'prompt');
        if (opts.type === 'prompt') {
            window.setTimeout(() => input.focus(), 0);
        }
        return new Promise((resolve) => {
            host._i18nResolve = resolve;
        });
    }

    function confirmDialog(message, title = dialogLabel('title')) {
        return openDialog({ type: 'confirm', message, title });
    }

    function promptDialog(message, value = '', title = dialogLabel('title')) {
        return openDialog({ type: 'prompt', message, value, title });
    }

    function alertDialog(message, title = dialogLabel('title')) {
        return openDialog({ type: 'alert', message, title, okText: dialogLabel('confirm') });
    }

    const i18n = {
        get lang() { return lang; },
        get labels() { return SUPPORTED; },
        setLang,
        toggle,
        register,
        t,
        onChange,
        apply: applyAll,
        bindToggleButtons,
        boot,
        confirm: confirmDialog,
        prompt: promptDialog,
        alert: alertDialog,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
        boot();
    }

    global.I18N = i18n;
})(window);
