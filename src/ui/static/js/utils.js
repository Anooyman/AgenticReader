/**
 * 工具函数
 */

const Utils = {
    /**
     * 显示通知。
     * 浮层的 DOM/动画已收敛到 ui-feedback.js（波次9），这里保留 `Utils.notify`
     * 这层壳，chat / config 页的调用点不用改；样式沿用原来的 preset 'default'。
     */
    notify(message, type = 'info', duration = 3000) {
        return UIFeedback.toast(message, { type, duration, preset: 'default' });
    }
};
