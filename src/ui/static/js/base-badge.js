/**
 * base-badge.js — 全站"待处理 PDF"徽章（波次10 从 base.html 内联块外链而来）
 *
 * 依赖 api.js 的 API.data.pendingPdfs()（base.html 已保证先于本文件加载）。
 * manage.js 在删除待处理 PDF 后会按全局名调用 updatePendingBadge()
 * （typeof 守卫），因此函数名必须保持全局，不能包进 IIFE。
 */
async function updatePendingBadge() {
    try {
        const pendingPdfs = await API.data.pendingPdfs();
        const count = pendingPdfs.length;
        const badge = document.getElementById('pending-badge');

        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    } catch (error) {
        console.error('Failed to load pending count:', error);
    }
}

// Update badge on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updatePendingBadge);
} else {
    updatePendingBadge();
}
