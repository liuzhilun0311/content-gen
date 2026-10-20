# 默认参数与完整选项

技能：`content-gen`

版本：1.2.0

默认值只在下面的 JSON 中维护；空字符串表示没有默认值，`null` 表示明确采用服务默认。名称和专业领域每个任务单独填写。服务和工具环境放在同目录 `.env`。

默认值仅由用户手动修改，不随任务选择自动更新。修改后只影响新生成的任务表，不改已保存任务。表格列出选项与说明，第三列留空，由程序生成任务表时填入当前默认快照；不要在本文件填写任务答案或修改选项编号。

```json
{
  "version": 3,
  "defaults": {
    "任务名称": "",
    "专业领域": "",
    "本次任务起点": 1,
    "use_image_gen": true,
    "preset": "tech-explainer",
    "type": "mixed",
    "style": "sketch-notes",
    "palette": "warm",
    "density": "rich",
    "language": "zh",
    "aspect_ratio": "4:3",
    "references": "none",
    "reference_usage": "",
    "watermark.enabled": false,
    "watermark.content": "",
    "watermark.position": "",
    "model": "gpt-image-2.5-sunburst",
    "resolution": "1k",
    "quality": "medium",
    "background": "design",
    "output_format": "png",
    "output_compression": "",
    "moderation": null,
    "variants_per_image": 1,
    "generation_batch_size": 1,
    "show_info": false,
    "limit": "teaching",
    "output_dir": "imgs",
    "article_action": "new-copy",
    "existing_images": "",
    "是否输出知乎": true,
    "是否输出微信公众号": true,
    "是否输出抖音": true,
    "是否输出小红书": true,
    "是否输出CSDN": true,
    "是否输出content": true,
    "是否需要配图方案审核": false,
    "是否需要图片审核": false
  }
}
```

字段名对应下表参数中的英文标识，无英文标识的字段使用中文名称。`use_image_gen` 对应“是否使用 image-gen”；布尔值 `true/false` 对应开关含义。起点可填写下表的完整说明或名称（如“原始内容”），也兼容数字1至5；生成的任务表仍使用编号选项。配置只包含 `version` 和 `defaults`。完整内部规则见 [parameter-rules.md](../references/parameter-rules.md)。

`image-gen` 专用输入参数仅在 `use_image_gen=true` 且本次需要生图时条件选填；留空沿用任务表中的默认值，无可用默认或有冲突时再补充。不使用 `image-gen`、仅处理正文或使用已有图片直接发布时，不要求填写或校验这些参数。输出压缩还需选择 JPEG 或 WebP 才适用。比例、参考图、变体数量等共用配图参数继续按各自条件处理。

| 参数名称 | 必选/可选 | 当前默认值 | 用户选择 | 参数意义及可选项 |
|---|---|---|---|---|
| 任务名称 | 用户回答后回填 | | | 标识本次内容任务，用于任务目录、成果文件名和正文标题。名称为自定义文本。 |
| 专业领域 | 用户回答后回填 | | | 决定内容采用的专业知识、术语、证据要求及插图审校标准。<br>1. `field_battery`（动力电池）：电池原理、系统设计、管理与测试。<br>2. `field_ai`（人工智能）：模型、算法、技术应用与实验验证。<br>3. `field_psychology`（心理学）：心理理论、研究证据与适用人群。<br>4. `field_enterprise-ai-fde`（企业 AI 落地与 FDE）：企业需求、现场交付、应用采纳与价值验证。 |
| 本次任务起点 | 用户选填 | | | 决定本次从哪个内容生产阶段开始。<br>1. 原始内容：从整理或转换原始材料开始。<br>2. 已转换或无需转换的内容：正文已准备好，从配图分析开始。<br>3. 配图方案：已有方案，从检查或完善方案开始。<br>4. 生图：方案已确定，从生成图片开始。<br>5. 正文插图+发布内容生成：已有正文和图片，从插图及生成成品开始。 |
| 是否使用 image-gen | 用户选填 | | | 决定是否调用 image-gen 生图；不影响配图规划、提示词、专业自检及审核。<br>1. 使用：调用 image-gen，使用该技能提供的渠道。<br>0. 不使用：自行选择生图方式，不要求配置 image-gen。 |
| 预设 `preset` | 用户选填 | | | 提供类型、风格和配色的组合起点；后续明确选择可覆盖预设。<br>1. `tech-explainer`（技术解释）<br>2. `system-design`（系统设计）<br>3. `architecture`（架构关系）<br>4. `science-paper`（科研说明）<br>5. `knowledge-base`（知识解释）<br>6. `saas-guide`（软件产品指南）<br>7. `tutorial`（教程流程）<br>8. `process-flow`（过程流程）<br>9. `warm-knowledge`（暖色知识图）<br>10. `edu-visual`（教育信息图）<br>11. `hand-drawn-edu`（手绘教育信息图）<br>12. `hand-drawn-edu-flow`（手绘教育流程图）<br>13. `hand-drawn-edu-compare`（手绘教育对比图）<br>14. `ink-notes-compare`（墨迹对比图）<br>15. `ink-notes-framework`（墨迹框架图）<br>16. `ink-notes-flow`（墨迹流程图）<br>17. `data-report`（数据报告）<br>18. `versus`（技术比较）<br>19. `business-compare`（商业对比）<br>20. `storytelling`（故事场景）<br>21. `lifestyle`（生活方式）<br>22. `history`（历史时间线）<br>23. `evolution`（发展演变时间线）<br>24. `opinion-piece`（观点场景）<br>25. `editorial-poster`（观点对比海报）<br>26. `cinematic`（电影感叙事）<br>27. 手动组合，不使用预设 |
| 图片类型 `type` | 用户选填 | | | 决定知识的视觉结构。<br>1. `mixed`（根据内容混合选择）<br>2. `infographic`（信息图）<br>3. `flowchart`（流程图）<br>4. `comparison`（对比图）<br>5. `framework`（框架图）<br>6. `timeline`（时间线）<br>7. `scene`（场景图）<br>8. 沿用预设中的类型 |
| 图片风格 `style` | 用户选填 | | | 决定线条、字体、纹理和视觉表达。<br>1. `sketch-notes`（温暖教学手绘）<br>2. `ink-notes`（白底黑墨笔记）<br>3. `vector-illustration`（矢量插画）<br>4. `blueprint`（工程蓝图）<br>5. `scientific`（科学图示）<br>6. `notion`（极简手绘线稿）<br>7. `editorial`（杂志信息图）<br>8. `elegant`（精致商务）<br>9. `warm`（温暖生活化）<br>10. `watercolor`（水彩）<br>11. `minimal`（极简）<br>12. `chalkboard`（黑板教学）<br>13. `fantasy-animation`（幻想动画绘本）<br>14. `flat`（现代几何扁平）<br>15. `flat-doodle`（扁平涂鸦）<br>16. `intuition-machine`（复古技术简报）<br>17. `nature`（自然有机）<br>18. `pixel-art`（像素）<br>19. `playful`（活泼涂鸦）<br>20. `retro`（复古霓虹）<br>21. `sketch`（铅笔草图）<br>22. `screen-print`（丝网印刷海报）<br>23. `vintage`（复古纸张）<br>24. 沿用预设中的风格 |
| 配色 `palette` | 用户选填 | | | 决定背景、主色及强调色。<br>1. `macaron`（暖奶油底、柔和蓝绿紫桃色）<br>2. `mono-ink`（白底黑墨、少量语义强调色）<br>3. `warm`（暖色系）<br>4. `neon`（深色底霓虹配色）<br>5. 沿用所选风格自带配色<br>6. 沿用预设中的配色<br>7. 自定义配色，选择后补充规范 |
| 图片密度 `density` | 用户选填 | | | 决定正文知识的配图覆盖程度，图片数量随内容需要安排。<br>1. `rich`（丰富覆盖）：为主要概念、机制、流程和比较关系充分配图。<br>2. `balanced`（重点均衡）：优先为核心知识及较难理解的内容配图。<br>3. `minimal`（仅核心概念）：只为最关键、最需要视觉解释的内容配图。<br>4. `per-section`（按章节覆盖）：按章节组织配图，覆盖各章主要知识。 |
| 图中文字语言 `language` | 用户选填 | | | 只控制图片文字，不自动翻译整份讲义。<br>1. 中文<br>2. 英文<br>3. 中英对照<br>4. 使用正文语言 |
| 图片比例 `aspect_ratio` | 用户选填 | | | 确定画布比例；逐图安排时在审核稿落实每张图的比例。<br>1. 按各图内容安排<br>2. `1:1`（方图）<br>3. `3:2`（横版）<br>4. `2:3`（竖版）<br>5. `4:3`（横版）<br>6. `3:4`（竖版）<br>7. `5:4`（横版）<br>8. `4:5`（竖版）<br>9. `16:9`（横版）<br>10. `9:16`（竖版）<br>11. `2:1`（宽横版）<br>12. `1:2`（长竖版）<br>13. `21:9`（超宽横版）<br>14. `9:21`（超长竖版） |
| 参考图 `references` | 用户选填 | | | 决定生成图片时是否使用参考图片。<br>1. `none`（不使用）：依据正文和配图方案生成。<br>2. `attachments`（使用已有附件）：使用本任务已提供的参考图片。<br>3. `provide`（补充参考文件）：使用另行提供的参考图片。 |
| 参考图用途 `reference_usage` | 条件选填 | | | 决定借鉴参考图片的哪些特征，仅使用参考图时适用。<br>1. `direct`（参考内容与布局）：参考图中的对象、关系和画面组织。<br>2. `style`（只参考风格）：参考线条、质感和视觉表达。<br>3. `palette`（只参考配色）：参考背景、主色和强调色。 |
| 水印开关 `watermark.enabled` | 用户选填 | | | 决定是否加水印。<br>1. `true`（添加）<br>2. `false`（不添加） |
| 水印文字 `watermark.content` | 条件选填 | | | 决定图片中显示的水印内容，仅开启水印时适用。<br>1. 使用本任务中已提供的名称：以已明确的作者或品牌名称作为水印。<br>2. 自定义文字：以指定文本作为水印。 |
| 水印位置 `watermark.position` | 条件选填 | | | 决定水印在图片中的位置，仅开启水印时适用。<br>1. 右下角<br>2. 左下角<br>3. 底部居中<br>4. 右上角 |
| 模型 `model` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定生成图片使用的模型。<br>1. `gpt-image-2.5-flare`（更快）<br>2. `gpt-image-2.5-sunburst`（更精细）<br>3. `gpt-image-2` |
| 清晰度 `resolution` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定请求尺寸等级，实际宽高随比例变化。<br>1. `1k`（1K）<br>2. `2k`（2K）<br>3. `4k`（4K） |
| 质量 `quality` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定图片生成的质量等级；`gpt-image-2`不支持第5、6项。<br>1. `auto`（自动）：由服务决定质量等级。<br>2. `low`（低）<br>3. `medium`（中）<br>4. `high`（高）<br>5. `xhigh`（更高）<br>6. `max`（最高） |
| 背景 `background` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定背景处理；透明需模型和格式兼容。<br>1. `design`（按设计配色）<br>2. `auto`（服务自动决定）<br>3. `opaque`（不透明）<br>4. `transparent`（透明） |
| 输出格式 `output_format` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定文件格式；透明背景不能选 JPEG。<br>1. 服务默认<br>2. `png`（PNG 图片）<br>3. `jpeg`（JPEG 图片）<br>4. `webp`（WebP 图片） |
| 输出压缩 `output_compression` | 条件选填 | | | 仅 use_image_gen=true 且输出JPEG或WebP时适用，不影响PNG；具体效果取决于生成服务。<br>1. 服务默认：使用服务的默认压缩设置。<br>2. 压缩参数70：采用数值70。<br>3. 压缩参数90：采用数值90。<br>4. 自定义0～100：采用指定数值。 |
| 内容审核模式 `moderation` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。决定请求采用的服务内容审核设置，实际支持范围由服务决定。<br>1. 服务默认：使用服务默认审核设置。<br>2. `auto`（标准自动审核）<br>3. `low`（服务支持的较宽松设置） |
| 每图变体数 `variants_per_image` | 用户选填 | | | 每个插图方案生成几个候选；image-gen使用参考文件时只能选第1项，其他方式按其实际能力核对。<br>1. 一张<br>2. 两张候选<br>3. 自定义数量，选择后补充整数 |
| 批量大小 `generation_batch_size` | 用户选填 | | | 决定每批调度多少个独立生图任务，影响执行节奏，受实际环境能力限制。<br>1. 顺序生成：每批一个任务。<br>2. 两张一批：每批两个任务。<br>3. 四张一批：每批四个任务。<br>4. 自定义1～8：每批采用指定任务数。 |
| 图片信息展示 `show_info` | 条件选填 | | | 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。展示模型、实际分辨率、请求比例、已保存张数、质量、输出格式、背景设置、总耗时及输入/输出 token；多图显示请求合计，未返回的数值标注“未提供”。<br>1. `true`（显示图片信息）<br>2. `false`（不显示图片信息） |
| 数量或预算约束 `limit` | 用户选填 | | | 确定数量或预算策略，具体上限在选择后补充。<br>1. `teaching`（按教学需求提出方案）<br>2. `image-count`（设置图片数量上限）<br>3. `budget`（设置费用上限） |
| 图片保存方式 `output_dir` | 用户选填 | | | 决定图片存放位置，文档链接随之调整。<br>1. `imgs`（任务目录下的图片目录）<br>2. `same-directory`（与配图文档同级）<br>3. `illustrations`（独立插图目录）<br>4. `custom`（自定义目录，选择后补充路径） |
| 讲义处理 `article_action` | 用户选填 | | | 确定配图内容的保存位置，不覆盖输入；文件名固定为任务名称_内容_配图.md。<br>1. `new-copy`（在本任务目录另存配图版）<br>2. `custom-copy`（指定输出父目录，选择后补充；任务目录和文件名不变） |
| 已有图片 `existing_images` | 条件选填 | | | 决定如何处理目标目录中的已有图片，仅存在已有图片时适用。<br>1. `reuse`（复用合格图并补充）：保留可用图片，按需要补充。<br>2. `new-version`（新版本重新生成）：生成新的一组图片。<br>3. `skip`（暂不处理）：跳过已有图片处理。 |
| 是否输出知乎 | 用户选填 | | | 决定是否生成一篇知乎深度科普文章，交付内嵌图片的DOCX及引用原图。<br>1. 输出<br>0. 不输出 |
| 是否输出微信公众号 | 用户选填 | | | 决定是否生成一篇适合移动阅读的微信公众号知识文章，交付HTML及引用原图，支持分别复制标题、简介、标签和正文。<br>1. 输出<br>0. 不输出 |
| 是否输出抖音 | 用户选填 | | | 决定是否生成抖音图文发布内容，交付包含标题、文案、标签的Markdown，以及总封面和精选内容图；与小红书共用精选图组及顺序，文案分别编写。<br>1. 输出<br>0. 不输出 |
| 是否输出小红书 | 用户选填 | | | 决定是否生成小红书图文发布内容，交付包含标题、文案、标签的Markdown，以及总封面和精选内容图；与抖音共用精选图组及顺序，文案分别编写。<br>1. 输出<br>0. 不输出 |
| 是否输出CSDN | 用户选填 | | | 决定是否生成一篇CSDN专业文章，交付HTML及引用原图，支持分别复制标题、正文和摘要。<br>1. 输出<br>0. 不输出 |
| 是否输出content | 用户选填 | | | 决定是否将完整配图正文导出为带目录和内嵌图片的HTML、EPUB、PDF阅读版，保存到publish/content/任务名称/。<br>1. 输出：生成三种阅读格式。<br>0. 不输出：不生成阅读版。 |
| 是否需要配图方案审核 | 用户选填 | | | 决定生图前是否等待用户确认配图方案，不影响技能自检；仅本次需要生图时适用。<br>1. 需要：用户确认方案后开始生图。<br>0. 不需要：技能检查方案后直接生图。 |
| 是否需要图片审核 | 用户选填 | | | 决定图片自检通过后是否等待用户确认图组，再进行正文插图和发布内容生成；仅本次使用图片时适用。<br>1. 需要：用户确认图组后继续。<br>0. 不需要：技能自检通过后直接继续。 |
