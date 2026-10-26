/**
 * PDF 预览共享层（pdf.js 渲染原语）。
 *
 * 波次9 收敛：chat.js 的 PDFReader 段和 structure_editor.js 的 PDF 预览段原本是
 * 两份复制粘贴的 pdf.js 渲染代码——同样的"取第 1 页算占位尺寸、建占位 div、
 * 按 devicePixelRatio × 1.5 的画质因子渲到 canvas、按滚动容器可视区挑要渲染的页、
 * scrollIntoView 跳页"。这里把与页面 DOM 无关的原语合成一份，两个页面各自保留
 * 自己的容器选择、页码显示、初始渲染页数与懒加载缓冲。
 *
 * 依赖：pdf.js（页面模板里的 <script src=.../pdf.min.js>）；本文件不引入任何新依赖。
 */

const PdfViewer = (function () {
    // 渲染画质因子：canvas 实际分辨率 = scale × devicePixelRatio × 该系数
    const QUALITY_FACTOR = 1.5;

    /**
     * 用第 1 页的视口算出单页的显示尺寸（占位框用它撑高度，避免布局跳动）。
     * @returns {Promise<{width: number, height: number}>}
     */
    async function measurePageSize(pdfDoc, scale) {
        const firstPage = await pdfDoc.getPage(1);
        const baseViewport = firstPage.getViewport({ scale });
        return {
            width: Math.floor(baseViewport.width),
            height: Math.floor(baseViewport.height)
        };
    }

    /**
     * 建一个页占位块（`.pdf-page` + 内嵌 `.pdf-placeholder`）。
     * @param {number} pageNum 页码（写进 id="pdf-page-N" 与 data-page）
     * @param {{width:number, height:number}} size 由 measurePageSize 得到
     * @param {object} [options]
     *        placeholderText   占位文案，默认 `第 N 页`
     *        decoratePage      (pageDiv) => void，页面级额外样式（chat 页用它加间距）
     *        decoratePlaceholder (placeholderDiv) => void，占位级额外样式
     */
    function createPageElement(pageNum, size, options = {}) {
        const pageDiv = document.createElement('div');
        pageDiv.className = 'pdf-page';
        pageDiv.id = 'pdf-page-' + pageNum;
        pageDiv.setAttribute('data-page', pageNum);
        pageDiv.setAttribute('data-rendered', 'false');
        if (options.decoratePage) options.decoratePage(pageDiv);

        const placeholder = document.createElement('div');
        placeholder.className = 'pdf-placeholder';
        placeholder.style.width = size.width + 'px';
        placeholder.style.height = size.height + 'px';
        placeholder.textContent = options.placeholderText
            ? options.placeholderText(pageNum)
            : '第 ' + pageNum + ' 页';
        if (options.decoratePlaceholder) options.decoratePlaceholder(placeholder);

        pageDiv.appendChild(placeholder);
        return pageDiv;
    }

    /**
     * 渲染单页到 canvas 并替换掉占位块。
     * 已渲染过 / 没有文档 / 找不到占位块都直接返回；渲染失败会撤销"已渲染"标记，
     * 让懒加载下次滚动能重试。
     */
    async function renderPage(context) {
        const {
            pdfDoc, pageNum, pageDiv, scale, devicePixelRatio,
            renderedPages, decorateCanvas
        } = context;

        if (!pdfDoc) return;
        if (renderedPages && renderedPages.has(pageNum)) return;
        if (!pageDiv) return;

        try {
            if (renderedPages) renderedPages.add(pageNum);
            pageDiv.setAttribute('data-rendered', 'true');

            const page = await pdfDoc.getPage(pageNum);

            const qualityScale = (devicePixelRatio || 2) * QUALITY_FACTOR;
            const baseViewport = page.getViewport({ scale });
            const renderViewport = page.getViewport({ scale: scale * qualityScale });

            const canvas = document.createElement('canvas');
            canvas.width = renderViewport.width;
            canvas.height = renderViewport.height;
            canvas.style.width = Math.floor(baseViewport.width) + 'px';
            canvas.style.height = Math.floor(baseViewport.height) + 'px';
            if (decorateCanvas) decorateCanvas(canvas);

            const ctx = canvas.getContext('2d');
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';

            await page.render({
                canvasContext: ctx,
                viewport: renderViewport,
                intent: 'display'
            }).promise;

            pageDiv.innerHTML = '';
            pageDiv.appendChild(canvas);
        } catch (error) {
            console.error(`渲染第 ${pageNum} 页失败:`, error);
            if (renderedPages) renderedPages.delete(pageNum);  // 允许下次重试
        }
    }

    /**
     * 找出滚动容器可视区（含上下缓冲）内的页码。
     * @param {Element} scrollEl 滚动容器
     * @param {Element[]} pageElements 页占位块列表（读 data-page）
     * @param {number} buffer 上下缓冲像素
     * @returns {number[]}
     */
    function collectVisiblePageNumbers(scrollEl, pageElements, buffer = 1000) {
        const visiblePages = [];
        if (!scrollEl) return visiblePages;

        const viewerRect = scrollEl.getBoundingClientRect();
        pageElements.forEach((page) => {
            const rect = page.getBoundingClientRect();
            const isVisible = rect.bottom >= viewerRect.top - buffer &&
                              rect.top <= viewerRect.bottom + buffer;
            if (isVisible) {
                visiblePages.push(parseInt(page.getAttribute('data-page'), 10));
            }
        });

        return visiblePages;
    }

    /** 跳到某一页（占位块已由 createPageElement 建好）。 */
    function scrollToPage(pageNum) {
        const pageElement = document.getElementById('pdf-page-' + pageNum);
        if (pageElement) {
            pageElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    /** 把 1..totalPages 的占位块元素取出来（给 collectVisiblePageNumbers 用）。 */
    function collectPageElements(totalPages) {
        const elements = [];
        for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
            const pageDiv = document.getElementById('pdf-page-' + pageNum);
            if (pageDiv) elements.push(pageDiv);
        }
        return elements;
    }

    return {
        QUALITY_FACTOR,
        measurePageSize,
        createPageElement,
        renderPage,
        collectVisiblePageNumbers,
        collectPageElements,
        scrollToPage
    };
})();
