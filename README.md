# 精密件返修试验室

白班工艺员从逐次返修观察复核工位规则，冻结修订并发行站件。晚班质控员收录指定站件，冻结出口接线，在两站来源关闭后签发返修核账。次日可以更正工艺、发行新件，并按原号领取昨日结论。报告用于判断所选返修工艺的最终达标机会和达标件累计工时。

## 运行

使用 Python 3.11 标准库及随附的 SQLite。于项目根目录运行 `python3 -B check_project.py` 执行完整回归，或运行 `python3 -B demo.py` 查看两站返流、次日更正及重开领取。回归入口由运行环境提供。演示和测试创建独立临时库。可用 `python3 -B -m unittest discover -v` 直接运行同一套测试。

## 白班工艺与站件

- `rework.process.ports.ProcessPorts(workstations, entries, exits)` 使用元组声明工位、`(公开入口, 落地工位)` 对和公开出口。观察目标可为本地工位或公开出口，工位与出口名称须可区分。入口落在已声明工位，站内回到该工位仍是一次本地经过。
- `rework.process.observations.Observation(source, target, minutes)` 记录一次带非负整数分钟的经过。`ObservationBatch(station, ports, observations)` 使用元组保留原始出现顺序和次数。`build_frequencies(batch)` 返回按来源工位的精确复核视图。每个来源的分母为该工位的观察总次数，同去向的不同分钟数分别保留。
- `RevisionStore(connection).initialize()` 建立工艺表。`store.save_draft(batch)` 登记草稿，传同车间的 `draft_id=` 可替换可编辑草稿。`freeze_process(store, draft_id, reviewed_batch=...)` 冻结该草稿，可选参数提交一份经过复核的完整替换批次。每个工位须有出边。冻结后可按 `read_frozen_revision(store, revision_id)` 复核原观察及精确规则。`open_correction(store, old_revision_id, batch)` 创建独立更正草稿。
- `StationEvidenceStore(connection).initialize()` 建立发行表，可与工艺库共享同一个站端连接。`issue_evidence(store, evidence_store, revision_id)` 发行绑定修订的 V1 站件，`read_station_evidence(evidence_store, evidence_id)` 按号重领。调用者通过所持站库连接控制修订的可读范围。

`encode_evidence(piece)` 和 `decode_evidence(payload)` 交换 UTF-8 JSON 字节。V1 信封含 `version`、`identity`、`entries`、`exits` 和 `rows`。`identity` 包含 `evidence_id`、`station` 和 `revision_id`。证据行以公开入口和交接去向索引，后三列为这部分路径的概率、概率加权累计分钟数及概率加权累计分钟数平方。分数采用约分后的字符串，整数也作为字符串。一个入口可以没有交接证据，或只有不足 1 的交接质量。编码及固定站件重领保留公开证据，私有工位与原始观察保存在站端。

## 晚班接线与签发

- `RoutingCatalog(connection).initialize()` 建立中心收件和接线表。`receive_evidence(catalog, payload)` 校验并保留 V1 副本。同号等内容重收返回原固定身份，同号异内容拒绝。`get_received_evidence(catalog, evidence_id)` 重新校验指定存件。
- `PortRef(evidence_id, port)` 定位固定件上的端口。`RouteAssignment(exit, target)` 将出口接到另一个所选入口，或接到 `TerminalDisposition.PASS` / `TerminalDisposition.SCRAP`。`freeze_route(catalog, evidence_ids, assignments)` 固定选件及完整接线。每个所选出口须有唯一映射。成功返回 `FrozenRoute`，之后以 `read_frozen_route(catalog, route_id)` 按号读取。
- `ReportLedger(connection).initialize()` 建立中心报告与领取表，可与中心目录共享连接。`publish_assessment(catalog, ledger, route_id, start)` 按冻结路由和 `PortRef` 开工入口返回已提交的 `ReportSnapshot`。路径可返流多次，只有有限步内抵达达标终点才算达标。报废和无限返修保留其非达标质量。每段工时计一次，均值和方差只对达标路径计算。概率、分钟均值及平方分钟方差都是 `Fraction`。零达标时均值与方差为 `None`。

确定性接力耗时依次为 1 和 2 分钟，应报 1、3、0。两站返流样例中，甲耗时 1 分钟进入乙，乙四次观察分别为达标 2 分钟、达标 2 分钟、返甲 0 分钟、报废 0 分钟。报告应为 2/3、10/3、4/9。达标条件下先返甲的次数服从公比 1/4 的几何权重。将乙的达标工时更正为 5 分钟后，新报告应为 2/3、19/3、4/9。

## 重开和失败语义

`read_report(ledger, report_id)` 按原号取回原数值、单位、路由、开工入口和全部固定件出处，并记录本次成功领取。`export_report(snapshot)` 返回带换行的 UTF-8 JSON 字节。报告读取使用已存快照，同一报告的导出在后续更正与重开后保持一致。

## 交班限时复核（断源签发）

站库关闭后，质控员只凭公开端口数据核定在交班时限内沿真实出口抵达 `TerminalDisposition.PASS` 的精确概率。时限含端点，分钟为非负整数（布尔值拒绝）；站内返修与跨站返流共用同一份累计分钟预算，零分钟接续（含任意有限次零分钟循环）以精确线性求解处理。报废、超时和永久滞留保持未达标，原有缺失质量保持缺失。

- `rework.station.deadline_issue.issue_deadline_evidence(revisions, issued, evidence_id, coverage)` 在站库打开时从已发行的 V1 站件读取其绑定修订，按公开入口与实际出口计算 `0..coverage` 的逐分钟精确质量，发行一份伴随件并返回 UTF-8 JSON 字节。原工位、完整站内工序图和逐次观察仍只保存在站端，不进入伴随件。
- `rework.station.deadline_codec` 的 `encode_deadline_evidence` / `decode_deadline_evidence` 交换伴随件信封：`kind="deadline-evidence"`、`version=1`、`companion_id`、V1 `parent` 身份、对 `encode_evidence(parent_piece)` 取的 `parent_sha256`、父件完整公开 `entries`/`exits`、`coverage` 与稀疏逐分钟 `data`。有理质量采用约分分数字符串。
- `rework.routing.deadline_intake.receive_deadline_evidence(catalog, payload)` 在中心先接纳 V1 父件，再核对父件身份、指纹和公开端口后接纳伴随件，返回伴随件号。同号同内容重投返回原号，同号异内容拒绝。
- `rework.analysis.deadline_assessment.publish_deadline_assessment(catalog, ledger, route_id, start, limit, companion_ids)` 按已冻结路由、`PortRef` 开工入口、非负整数 `limit` 和与路由每件一一对应且覆盖 `limit` 的伴随件签发限时报告。
- `rework.report.ledger.read_deadline_report(ledger, report_id)` 凭原号读取快照，属性为 `report_id`、`route_id`、`start`、`limit`、`pieces`、`companion_ids`、`probability`（`Fraction`，可为零）。领取使用存值，更正及重开后保持原出处和结论。

未知编号报 `KeyError`；非法输入、身份不符、坏件、选件漏配或重复及覆盖不足报 `ValueError`。发行、接纳、签发各自原子提交，失败无新增且可重试。`python3 -B deadline_examples.py` 同时演示 V1 与限时结果；`python3 -B demo.py` 在 V1 场景后追加断源限时签发与源更正后重开领取。

未知记录抛出 `KeyError`。输入、冻结状态、身份冲突及损坏证据错误抛出 `ValueError`。SQLite 错误由调用方接收。各存储对象借用调用方提供的连接，写入操作管理自己的事务，须在该连接没有待提交事务时调用。非法批次、发行、接线、核账及失败的报告提交均无对应的新增成果。未知报告号不增加领取记录。可重复调用 `initialize()`，已有草稿及中心业务记录会保留。
