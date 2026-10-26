/**
 * 共享轻提示（toast）实现。
 *
 * 波次9 收敛：全站原本有三份复制粘贴的同款浮层——
 *   - utils.js 的 `Utils.notify`（chat / config 页）
 *   - manage.js 的 `DataManager.showSuccess` / `showError`（数据管理 / 首页）
 *   - structure_editor.js 的 `StructureEditor.showNotification`（结构编辑器）
 * 三者都是"createElement + 内联 cssText + appendChild + setTimeout 动画移除"，
 * 只在颜色、位置、z-index、停留时间上各自微调。这里合成一份，各调用方保留
 * 自己原来的外观（preset），所以视觉上看不出差别。
 *
 * 只管浮层 toast：原生 alert()/confirm() 不在这里包装（保持原生调用，避免时序
 * 变化）；确认框沿用 ui-components.js 里已有的 `UIComponents.confirm`，它本来就是
 * 全站共用的一份实现；#errBox / #config-status 这类"页面内固定位置的提示条"绑定
 * 各自模板里的元素和 CSS 类，也保持各自原样。
 */

const UIFeedback = (function () {
    const STYLE_ID = 'ui-feedback-styles';

    const TYPE_ICONS = { success: '✅', error: '❌' };

    const PRESETS = {
        // Utils.notify 原样式（chat / config 页）
        default: {
            top: '20px',
            right: '20px',
            padding: '1rem 1.5rem',
            borderRadius: '0.5rem',
            boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
            zIndex: '10000',
            maxWidth: null,
            fontSize: null,
            fontWeight: null,
            duration: 3000,
            colors: {
                success: '#10b981',
                error: '#ef4444',
                info: '#3b82f6',
                warning: '#3b82f6'
            }
        },
        // DataManager.showSuccess / showError 原样式（数据管理 / 首页）
        manage: {
            top: '2rem',
            right: '2rem',
            padding: '1rem 1.5rem',
            borderRadius: '0.5rem',
            boxShadow: 'var(--shadow-lg)',
            zIndex: '2000',
            maxWidth: null,
            fontSize: null,
            fontWeight: null,
            duration: 3000,
            colors: {
                success: '#28a745',
                error: '#dc3545',
                info: '#2563eb',
                warning: '#ffc107'
            }
        },
        // StructureEditor.showNotification 原样式（结构编辑器）
        editor: {
            top: '20px',
            right: '20px',
            padding: '15px 20px',
            borderRadius: '8px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            zIndex: '10001',
            maxWidth: '400px',
            fontSize: '14px',
            fontWeight: '500',
            duration: 3000,
            colors: {
                success: '#28a745',
                error: '#dc3545',
                info: '#2563eb',
                warning: '#ffc107'
            }
        }
    };

    function injectStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            @keyframes ui-feedback-in {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes ui-feedback-out {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }

    function buildCss(preset, background) {
        const lines = [
            'position: fixed;',
            'top: ' + preset.top + ';',
            'right: ' + preset.right + ';',
            'padding: ' + preset.padding + ';',
            'background: ' + background + ';',
            'color: white;',
            'border-radius: ' + preset.borderRadius + ';',
            'box-shadow: ' + preset.boxShadow + ';',
            'z-index: ' + preset.zIndex + ';',
            'animation: ui-feedback-in 0.3s ease-out;'
        ];
        if (preset.maxWidth) lines.push('max-width: ' + preset.maxWidth + ';');
        if (preset.fontSize) lines.push('font-size: ' + preset.fontSize + ';');
        if (preset.fontWeight) lines.push('font-weight: ' + preset.fontWeight + ';');
        return lines.join('\n');
    }

    /**
     * 弹一条浮层提示。
     * @param {string} message 文本（按 textContent 写入，不解析 HTML）
     * @param {object} [options]
     *        type     'success' | 'error' | 'info' | 'warning'，默认 'info'
     *        duration 停留毫秒数，默认取 preset 的默认值
     *        preset   'default' | 'manage' | 'editor'，对应各页原来的外观
     *        mark     true → success/error 文案缺少 ✅/❌ 前缀时自动补上
     * @returns {HTMLElement} 浮层元素
     */
    function toast(message, options = {}) {
        injectStyles();

        const preset = PRESETS[options.preset] || PRESETS.default;
        const type = preset.colors[options.type] ? options.type : 'info';
        const duration = options.duration !== undefined ? options.duration : preset.duration;

        let text = message == null ? '' : String(message);
        const icon = TYPE_ICONS[type];
        if (options.mark && icon && !text.startsWith(icon)) {
            text = icon + ' ' + text;
        }

        const notification = document.createElement('div');
        notification.style.cssText = buildCss(preset, preset.colors[type]);
        notification.textContent = text;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'ui-feedback-out 0.3s ease-out';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, duration);

        return notification;
    }

    return {
        toast,
        notify(message, type = 'info', duration = 3000) {
            return toast(message, { type, duration });
        },
        success(message, duration) {
            return toast(message, { type: 'success', duration });
        },
        error(message, duration) {
            return toast(message, { type: 'error', duration });
        },
        info(message, duration) {
            return toast(message, { type: 'info', duration });
        },
        warning(message, duration) {
            return toast(message, { type: 'warning', duration });
        }
    };
})();
