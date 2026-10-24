# 餐品图片来源与范围

真实模式读取 `query-meals.data.meals[商品编码].image`，只接受无凭据、无查询参数的 HTTPS 官方菜单 CDN 地址：`menu-img.mcd.cn` 或 `img.mcd.cn`。其他地址或缺失图片使用占位，不按相似名称猜测真实商品图。

网页模拟数据的11个图片链接来自2026-10-24深圳福田门店菜单回执，逐张记录在 `examples/demo.json` 的 `image_url`、`image_caption` 和 `image_source`。模拟餐品为测试构造，图片仅作明确标注的同类餐品示意；价格、热量、门店和优惠仍为虚构。卷与无糖可乐没有取得对应图，继续使用占位。

图片按来源 URL 加载，失败时保留占位。本仓库不下载、打包或分发原图文件，不将官方图片纳入 MIT 代码许可。图片注明来源，实际规格以文字为准。加载会向官方 CDN 发起请求，使用 `no-referrer`，不发送本项目 Token。

效果图和录屏中出现的官方餐品图也不属于项目MIT许可。官方返回图片 URL 不代表获得任意转载、改作或商业再利用授权。使用仍须遵守适用的 MCP 服务协议、参赛规则和图片权利人要求。相关资料：

- [麦当劳官方使用条款](https://www.mcdonalds.com.cn/page/McDonalds-Internet-Site-Terms-and-Conditions/)
- [麦当劳官方 MCP 接入指南](https://github.com/M-China/mcd-mcp-server)
- [官方参赛声明](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/CONTEST_DECLARATION.md)
