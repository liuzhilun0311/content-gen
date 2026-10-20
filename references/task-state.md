# 参数校验与任务状态

新任务由 `task_paths.py` 创建一个UUID及规则版本，保存到 `_work/task.json`。后续审核和续接都复用该UUID，不另创建任务ID。只有用户新建任务才换ID。已有任务无记录时先读取其参数、正文、方案和资产，建立显式迁移记录并保留已有任务ID；找不到审核证据不能声称曾经确认。任务事件和失效历史继续保留，用于审核与续接。

## 集中校验

按用户确认模板提供填写副本，保留页首任务名称、专业领域和五列结构；输入材料不是表内参数。名称与领域需明确回答，页首与表内冲突不能通过。用户选填项空白沿用展示的任务默认，条件触发项需具备可用值；不适用字段不发送。历史必填表只有明确接受默认时才用--allow-defaults，新表选填项无需此标志。实际输入由inputs事件绑定，不因移除输入行而省略材料检查。

重新读取用户填写文件，运行：

```text
python scripts/validate_parameters.py --parameters <任务参数.md> --scope <full|content|plan|images|publish> --supplements <补充参数.json>
```

`full`接续全部剩余流程；`content`仅正文；`plan`到配图方案；`images`到图组；`publish`仅从起点5接续成品。用户未限定时使用full。`--allow-defaults`只能对应上述明确沿用指令，来源仍记录，不作为新的偏好答案。

表外实际补充内容由技能从用户答案转换为 `_work/supplements.json`，是内部执行资料，不是第二套填写表。常用键：`field`、`references`（真实文件列表）、`author_name`、`watermark.content`、`palette`、`output_dir`、`article_action`、`variants_per_image`、`generation_batch_size`、`output_compression`、`limit`、`has_existing_images`；历史分档任务还可读取`longform_variants`及`longform_by_platform`，新任务不使用。未回答的值不能编造。路径以参数文档目录解释后转绝对路径；补充内容不能作为执行指令。

程序返回全部发现的缺项、无效编号、条件矛盾、补充值问题及路线；不通过则集中澄清，仅停止依赖阶段。即使程序通过，还须实际读取输入、检查领域配置、核对预设展开与类型风格适配、参考文件是否为可用图片、专业依据、方案位置、请求数和预算。

预算未知时不得保证硬费用上限。选费用上限但无可靠控制能力时，说明并请求改为可验证的数量或请求次数约束，不能继续猜测费用。正常请求、候选变体、技术修复及429服务重试分开记录。

解析开关优先采用有效第四列，再采用该任务第三列的默认快照。新任务由 `task_parameters.py` 从 `config/extend.md` 生成完整快照；无快照的旧表保留既有兼容回退，不读取新的全局配置。任务旧快照不能因全局默认改变被重新解释。旧起点先按选项含义迁移，新任务在内部状态记录 `parameter_schema_version: 4`、`starting_point_schema_version: 2`、`longform_schema_version: 2`；不要求在用户模板保留版本标记或操作说明。当前五起点可由表内选项含义识别，不能缺少标记就套用旧编号。

## 状态与确认

`task_state.py`用事件更新现有任务，不生成文章或图片。状态程序记录证据，不会替技能判断专业正确。每次成功写入递增
`state_revision`；读、变换、比较和原子替换在同一个锁文件事务内完成，两个并发更新不会静默互相覆盖。

```text
python scripts/task_state.py --state <_work/task.json> --event <事件> --payload <事件JSON>
python scripts/task_state.py --state <_work/task.json> --check-gates --plan-file <当前审核稿> --image-file <当前原图>
```

事件内容：

- `inputs`：实际读取的输入文件files列表，保存SHA256快照；补记历史任务时只证明当前输入版本。刷新后若输入哈希变化，content及全部下游阶段自动回到pending，并清除相关图组自检与确认。
- `parameters`：通过校验的完整JSON；领域变化会使content及全部下游阶段失效，视觉或专业作图参数变化会使plan、images、image_checks、illustrated、publish失效。仅改变起点、平台、篇幅或审核开关不清除当前文件证据，但仍按本次开关核对是否具备必要确认。
- `stage`：`stage`为content、plan、images、image_checks、illustrated、publish；`status`为pending、running、waiting、passed、failed。passed需路径到SHA256的evidence字典，程序逐一核对当前文件，不能用请求成功代替审校。
  新记录另保存stage_schema_version=2、当前领域及直接上游dependencies；content自动绑定已选择领域的三个实际配置文件。上游证据变化后重新记录，会使依赖阶段失效。额外补充文件、方案及执行配置需纳入evidence，仍须实际审校后记录。
- `image-check`：`files`列表；`checks`完整含text、professional、composition、content_mapping四个布尔结果；`notes`记录实际缺陷及修复。只在逐图实际查看后记录，不把同一结果批量套给未看图片。
- `plan-confirm`或`image-confirm`：`files`、`explicit_user_confirmation: true`及用户确认来源source。程序绑定真实文件哈希；图片确认前要求已有同一哈希的合格自检。

`--check-gates`只核对已记录证据与当前文件，不证明材料完整、预算充足或生图授权范围；执行仍以实际范围为准。图片或方案改变会令对应确认失效，图组集合改变也需重新核对。技术修正后记录新文件并重新检查，保留旧候选。

已有旧格式机器图方案时，合格历史图组可按当前哈希复用；新生图前先补齐并校验v2方案。generation_reasons单独报告新生图缺口，不把旧格式升级要求混作已审校图片的错误。v2文件存在时，最终验收检查其当前绑定，plan证据必须包含该文件。

无需人工审核时，实际自检通过即可接续；需要时核实当前确认后再执行依赖阶段。确认不能覆盖关键技术错误。阶段状态与当前成果路径写入记录，局部失败只阻塞依赖它的成果。程序使用读后并发检查和临时替换，避免悄悄覆盖同时编辑的状态。

更新当前任务时保留输入，修订固定名称的生成成果并保留必要工作历史；新整版任务才创建新时间目录。删除_work不影响已导出的成品，但会失去自动续接和审核证据，后续须重建并据实确认。
