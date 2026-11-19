# 交班限时达标复核

`README.md` 说明现有工艺修订、V1 站件、冻结接线和报告的调用方式。限时复核继续使用这套接线。限时从请求中的开工入口起算，站内返修及跨站返流均计入累计时间。只有沿真实出口接线抵达 `TerminalDisposition.PASS` 才算达标。时限含端点，分钟为非负整数，布尔值拒绝。报废、超时和永久滞留均为未达标，原概率质量保持。允许零分钟接续，也允许全量重算。

## 发行与接纳

- `rework.station.issue.issue_deadline_evidence(revisions, issued, evidence_id, coverage) -> bytes` 从指定的已发行 V1 站件读取其绑定修订，按 `coverage` 覆盖 0 至该分钟数，固定发行一份伴随件并返回 UTF-8 JSON 字节。`revisions` 和 `issued` 沿用 `RevisionStore` 与 `StationEvidenceStore`。
- `rework.routing.intake.receive_deadline_evidence(catalog, payload) -> str` 在 `RoutingCatalog` 中接纳伴随件。先接收其 V1 父件。成功返回伴随件号。同号同内容重投返回原号并保留原接纳内容，同号异内容拒绝。

伴随件信封是 JSON 对象，包含 `kind`（固定为 `deadline-evidence`）、`version`（整数 `1`）、`companion_id`（非空字符串）、`parent`（含 `evidence_id`、`station`、`revision_id` 的 V1 身份对象）、`parent_sha256`（对 `encode_evidence(parent_piece)` 取 SHA256 后的小写十六进制字符串）、`entries` 和 `exits`（父件各自的完整公开端口名称数组）、`coverage`（非负整数）及 `data`（JSON 对象）。接纳时核对父件身份、指纹和公开端口。JSON 对象键的排列和空白不改变内容，重复字段为坏件。

正文 data 的表示由实现选择，发行和接纳使用同一解释。中心凭这些数据须能为每个公开入口恢复覆盖范围内按实际出口区分的累计分钟质量，并能在任意合法接线下使用。多个公开入口可以落在同一工位，某个入口也可能始终无法出站。站内再访只续本站，只有真实出站才执行中心接线。原工位标识、完整站内工序图和逐次观察只保存在站端。分钟和概率保持精确，正文中的有理质量采用 V1 的约分分数字符串。引用不存在的公开端口、超出覆盖的证据、无效质量或互斥去向质量合计超过 1 的记录均为坏件。合法的缺失概率质量保持缺失。

## 签发与领取

- `rework.analysis.assessment.publish_deadline_assessment(catalog, ledger, route_id, start, limit, companion_ids)` 按已冻结的路由签发。`start` 沿用 `PortRef`，必须是该路由所选 V1 件的公开入口。`limit` 为本次全程分钟上限。`companion_ids` 是伴随件号序列，按父件身份配对，须给路由每件恰好选一份且覆盖 `limit`，包括核账时未走到的站件。
- `rework.report.ledger.read_deadline_report(ledger, report_id)` 凭原号读取保存的限时报告。两入口返回相同形状的快照对象，属性为 `report_id`、`route_id`、`start`、`limit`、`pieces`、`companion_ids`、`probability`。`pieces` 与 `FrozenRoute.pieces` 一致，`companion_ids` 为与其一一对应的元组。`probability` 为 `Fraction`，可为零。领取使用存值，更正及重开后仍保持原出处和结论。

缺失编号报 `KeyError`。非法输入、身份不符、坏件、选件漏配或重复及覆盖不足报 `ValueError`。SQLite 提交错误由调用方接收。发行、接纳、签发各自原子提交，失败无新增且可重试。沿用原连接和初始化方式，保留原有接口、旧编码、旧件、旧报告及全部原回归。

## 样例与运行

`deadline_examples.py` 提供原始观察夹具，可运行 `python3 -B deadline_examples.py` 查看它们经 V1 发行和断源签发的结果。扩展后的调用顺序是在站库打开时先发行 V1 父件，再以其 `piece.identity.evidence_id` 调用 `issue_deadline_evidence`。关闭站库后，在中心用 `receive_evidence(catalog, encode_evidence(piece))` 接纳父件，用 `receive_deadline_evidence` 接纳伴随件，用原入口 `freeze_route` 冻结接线，最后传入接纳号调用 `publish_deadline_assessment`。重新打开中心库后，使用返回的 `report_id` 调用 `read_deadline_report`。

| 原始观察及接线 | 限时复核预期 |
| --- | --- |
| `same_moment_batches()` 的两批各自直连达标，工时分别为 `[1,3]` 和 `[0,2,2,2,2,2,2,4]` | 两份 V1 报告均为概率 1、均值 2、方差 1。期限 1 分钟分别为 `1/2` 与 `1/8`。 |
| `tests.support.alpha_batch()` 与 `beta_batch()` 使用原返流接线 | 首次达标路径累计 3 分钟，返甲后第二次达标路径累计 4 分钟。伴随件均覆盖 4 分钟时，期限 2、3、4 的概率依次为 `0`、`1/2`、`5/8`。 |
| `zero_return_batches()` 使用原返流接线 | 甲的 `start` 与 `alternate` 均落在同一工位，本站自返和送乙等概率且都耗时 0。乙每趟达标 `1/2`、返甲 `1/4`、陷入闭类 `1/4`。期限 0 时，甲两个入口各为 `2/3`，乙的 `trapped` 起点为 `0`，三者均可签发。 |

`.pointwise-runtime.json` 的 `verify` 和 `demo` 继续作为统一入口。核验保留原回归并覆盖限时证据从发行到签发的交接，失败以非零状态退出。演示展示断源限时签发和源更正后重开领取的实际结果。
