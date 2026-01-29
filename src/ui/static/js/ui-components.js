/**
 * UI 组件
 */

const UIComponents = {
    /**
     * 显示加载遮罩
     */
    showLoading(message = '加载中...') {
        // 移除已存在的加载遮罩
        this.hideLoading();

        const overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div style="text-align: center;">
                <div class="loading-spinner"></div>
                <div class="loading-text">${message}</div>
            </div>
        `;

        document.body.appendChild(overlay);
    },

    /**
     * 隐藏加载遮罩
     */
    hideLoading() {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    },

    /**
     * 确认对话框
     */
    async confirm(message, title = '确认') {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <h3 style="margin-bottom: 1rem;">${title}</h3>
                    <p style="margin-bottom: 1.5rem;">${message}</p>
                    <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
                        <button class="btn btn-secondary" id="cancel-btn">取消</button>
                        <button class="btn btn-primary" id="confirm-btn">确认</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            modal.querySelector('#confirm-btn').addEventListener('click', () => {
                modal.remove();
                resolve(true);
            });

            modal.querySelector('#cancel-btn').addEventListener('click', () => {
                modal.remove();
                resolve(false);
            });

            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve(false);
                }
            });
        });
    }
};
