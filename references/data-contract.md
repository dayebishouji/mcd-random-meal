# 数据与调用契约

先发现当前 `tools/list` 的实际 schema。只读桥 `scripts/mcp_readonly.py` 固定连接 `https://mcp.mcd.cn`，拒绝跳转和写工具；支持 JSON 与 SSE、会话头及分页。Token 仅从 `MCD_MCP_TOKEN` 读取。

## 可执行入口

```text
python scripts/main.py tools --output local/tools.json
python scripts/main.py call query-nearby-stores --arguments local/search.json --output local/stores.json
python scripts/main.py draw --input local/snapshot.json --output local/draw.json
python scripts/main.py plan --draw local/draw.json --catalog local/catalog.json --output local/plans.json
python scripts/main.py quote --draw local/draw.json --plans local/plans.json --requests local/requests.json --output local/quotes.json
python scripts/main.py compare --draw local/draw.json --plans local/plans.json --quotes local/quotes.json --output local/result.json --html local/result.html
```

`local/` 为本机私有数据目录，不提交 GitHub。以上路径应由宿主转成绝对路径。`call` 参数必须保留实际数据类型，尤其 `items` 是数组，不能传数组的字符串。

## snapshot.json

```json
{
  "mode": "live",
  "observed_at": "由本次工具回执提供",
  "source": "麦当劳 MCP query-meals + query-meal-detail + list-nutrition-foods",
  "store": {"id": "实际门店编码", "name": "实际门店名称", "address": "实际地址"},
  "context": {"orderType": 1, "beType": 1},
  "items": [{
    "id": "实际餐品编码或已解析规格的唯一标识",
    "name": "实际默认规格名称",
    "kind": "main",
    "selectable": true,
    "menu_fen": null,
    "kcal": null,
    "evidence": "本次在售、分类、规格和每份营养的依据"
  }]
}
```

`kind` 支持 main / side / drink / dessert / unknown。未知分类不抽取，未知热量仍可抽取。`kcal` 是一份所选规格的能量，不是每100克；`menu_fen` 只能由明确单位的菜单价转换。真实适配器另附 `components` 与 `request_item`，分别保存实际组成编码和 schema 派生的核价商品参数。

`draw --count` 支持1–6样；程序在主食最多1份（默认1份，不要主食为0份）、饮品最多1份、甜品最多1份、其余为小食且至少一份食物的组合中等概率抽取，不通过重抽实现约束。可选 `image_url` 保存本次菜单返回的官方图片地址，`image_source` 保存来源；只显示受支持的官方HTTPS图片，不提供图片时使用占位。图片不能作为价格、热量或实际规格的证据。

## catalog.json

从 `draw.json` 原样复制 `draw_id`、`mode`、`store`、`context`。每个购买选项保存如下字段：

- `id`、`label`：唯一编码与用户可读买法。
- `covers`：实际覆盖的抽中餐品标识到份数的映射。套餐必须按实际子项核实与目标餐品、规格、份数一致；不能只凭名称相似判断。
- `request_item`：当前 `calculate-price.items` 的一个真实参数对象。保留所选 `roundList` 和 `modification`，不能照抄示例编码。
- `evidence`：实际工具及组成依据。
- `conditions`：使用条件。
- `exclusive_groups`：可选字符串数组，例如同一张一次性券使用相同分组，防止重复用券。分组不代表服务端已确认券间可叠加；最终仍需整单核价。
- `scope` 位于 catalog 根：列出本轮收集的优惠范围和未覆盖部分。

`plan` 只枚举 `covers` 恰好等于目标餐单的组合，过滤加购及数量变化。最多120个选项，最多64份购买方案，搜索最多20000节点；截断会明确标出。

## 真实核价与 quotes.json

`requests.json` 格式为 `{"draw_id":"本次标识","requests":{"方案id":{完整calculate-price参数}}}`。每个请求的 `items` 必须逐项等于该计划的 `request_item`，实际子项编码、份数和特调必须与原餐单 `request_item` 一致，门店和场景必须一致。默认金额路径 `/data/price`、单位 `fen`；变更只能依据当前官方 schema，命令参数为 `--amount-pointer` 和 `--unit`。

宿主通过原生 MCP 核价时，把每次回执规范化成数组：

```json
[{
  "draw_id": "本次标识",
  "mode": "live",
  "plan_id": "已生成的方案id",
  "status": "success",
  "payable_fen": 1234,
  "quoted_at": "实际核价时间",
  "source": "本次 calculate-price 的实际金额路径与单位"
}]
```

失败报价用 `status: failed` 和 `reason`，不填虚构金额。不要将菜品列表价、优惠券名义折扣或业务失败响应作为成功核价。

当前接口业务结果可以在 `structuredContent` 中，也可能包在文本的 JSON 内。必须确认业务 `success:true`，再读取金额。HTTP401/403/429及业务/参数错误不自动重试；超时、连接失败和HTTP500/502/503/504对同一只读请求最多重试2次。一个方案的业务拒绝会标记失败并继续其他固定方案，网络/协议故障停止后续核价。保留已有有效报价，说明未核价范围，不轮换参数探测。

## 官方来源

- MCP 官方指南：https://github.com/M-China/mcd-mcp-server
- 接入文档：https://open.mcd.cn/mcp/doc
- 参数依据：2026-10-24 真实 `tools/list` 及工具回执。当前适配器只实现 `beType=1 / orderType=1` 到店取餐，不实现外送、预订或特调修改。
