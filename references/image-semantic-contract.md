# 图片语义契约

图片提示词中的关系、箭头和拓扑属于专业内容，不能交给模型自由补全。凡是流程图、系统图、曲线因果图、电路图、控制框图或包含箭头的技术信息图，必须在 `outline.md` 和提示词中建立一份可审校的关系契约。

每张复杂图至少记录以下字段：

```text
SEMANTIC_CONTRACT
nodes: [节点或对象的唯一名称]
edges:
  - from: 来源节点
    to: 目标节点
    relation: 传递/控制/测量/因果/供电/散热/比较
    direction: source_to_target
    condition: 适用条件；没有则写 unconditional
forbidden_edges: [明确不能出现的连接]
forbidden_symbols: [不能自行添加的元件、字母、公式、坐标或单位]
allowed_labels: [画面中唯一允许出现的文字、符号和单位]
```

校验要求：

- 每条箭头都必须能在 `edges` 中找到，不能只因“看起来合理”而增加连接。
- `forbidden_edges` 重点写容易倒置的因果、反馈方向、正负极、串并联关系、散热路径和参考地。
- 技术拓扑没有明确依据时，改用分区并列示意或省略连接，不能编造闭合回路、短接、接地、反馈或电流路径。
- 画面只绘制 `allowed_labels` 中的文字和符号；仪表、芯片、端子、屏幕、元件内部不得出现未列出的字母、数字、公式、坐标轴或装饰性伪文字。
- `condition`、方向和证据性质必须与正文一致。概念示意不能加未经提供的精确刻度、测量值或拐点。
- 生图后逐张复核节点、边、方向、拓扑和禁用元素；任一关键关系错误都判为不合格，进入一次技术修正版流程。

提示词固定加入 `RELATION_GRAPH` 和 `FORBIDDEN_RELATIONS` 两个区块。简单主体图也要写 `forbidden_symbols` 和 `allowed_labels`；没有专业关系时明确写 `edges: []`，避免模型自行添加箭头或公式。

`relation`、`condition`、证据和字段名属于内部理解信息，不是默认可见文字。提示词将其与`LABELS`明确隔开；需要在箭头旁显示关系或条件时，先将完整短句加入白名单并指定位置。短流程优先采用单一阅读方向，逐条要求全部必要连接出现；不要用换行后的网格代替连续路径。仪表、屏幕和睡眠等图标也不得擅自增加V、A、Z、数字或循环箭头。自检既要查多出的关系，也要查遗漏的必要关系。

## 机器交接文件

新方案使用 `_work/image-plan.json`，格式如下。路径相对任务根目录；sha256填当前实际文件哈希，不能使用占位值执行。

```json
{
  "schema_version": 2,
  "binding": {
    "content": {"path": "任务名称_内容.md", "sha256": "当前内容SHA256"},
    "review": {"path": "任务名称_内容_配图审核稿.md", "sha256": "当前审核稿SHA256"},
    "parameters": {"path": "任务名称_参数.md", "sha256": "当前参数SHA256"}
  },
  "short_image_ids": ["00", "01"],
  "images": [
    {
      "image_id": "00",
      "prompt_path": "imgs/prompts/00-cover.md",
      "prompt_sha256": "当前提示词SHA256",
      "allowed_labels": ["电流", "SOC"],
      "semantic_contract": {
        "nodes": ["电流", "SOC"],
        "edges": [
          {"from": "电流", "to": "SOC", "relation": "积分输入", "condition": "时间单位一致"}
        ],
        "forbidden_edges": [
          {"from": "SOC", "to": "电流", "relation": "反向推导", "condition": ""}
        ],
        "forbidden_symbols": ["接地"]
      }
    },
    {
      "image_id": "01",
      "prompt_path": "imgs/prompts/01-soc.md",
      "prompt_sha256": "当前提示词SHA256",
      "allowed_labels": ["电流", "SOC"],
      "semantic_contract": {
        "nodes": ["电流", "SOC"],
        "edges": [
          {"from": "电流", "to": "SOC", "relation": "积分输入", "condition": "时间单位一致"}
        ],
        "forbidden_edges": [],
        "forbidden_symbols": ["接地"]
      }
    }
  ]
}
```

示例只示字段和方向表达，不是可以直接生图的专业方案。`from→to`唯一表示方向；condition空字符串表示无附加条件。总封面00或00-cover排第一，ID唯一，短平台选图是同一有序子集。节点端点必须存在，允许与禁止边不得重合。校验器会核对来源和提示词哈希及安全路径；legacy方案只给兼容结果及警告，正式新生图先补为v2。提示词与机器图的语义一致性仍需逐条实际阅读核对。
