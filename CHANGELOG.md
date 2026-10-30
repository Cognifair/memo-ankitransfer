# Changelog

## v1.1.8 — 2026-10-30

影响面：memo-ankitransfer(README.md, references/satellites.md)

### 变更

- Memo 系列清单加入「卡跳跳 Memo-CardLink」，同步 README 系列表与 satellites。

## v1.1.7 — 2026-10-30

影响面：memo-ankitransfer(README.md)

### 变更

- README 顶部增加「墨卡大师 · 专业制卡工作流」在线介绍页链接。

## v1.1.6 — 2026-10-28

影响面：memo-ankitransfer(SKILL.md)

### 变更

- 文档中的发布器名称由 `skill-publisher` 更新为 `maimemo-publisher`，与当前技能名保持一致。

## v1.1.5 — 2026-10-24

### 修复

- API 请求禁用重定向，避免跨域转发 Bearer；新增 302 重定向回归测试。

## v1.1.4 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.1.3 — 2026-10-23

- 修复：`agents/openai.yaml` 补充 `default_prompt`，`display_name` 带上版本号，与其他 Memo 技能保持一致。
- README 的「Memo 系列」表与 `references/satellites.md` 改由 `memo-series.json` 生成（`sync-series`）。

## v1.1.4 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.1.2 — 2026-10-23

- 变更：展示名正式采用「**迁墨**」（迁 Anki → 墨墨记忆卡）。`SKILL.md` 描述、标题与触发词、`agents/openai.yaml` 的 `display_name`、`README.md` 标题同步更新；仓库名与调用标识仍为 `memo-ankitransfer`。
- 关联：墨卡大师 `references/satellites.md` 中该支链的 `name` 同步改为「迁墨 Memo-Ankitransfer」。
- 说明：本次只改命名，转换与导入逻辑未变。

## v1.1.4 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.1.1 — 2026-10-23

- 新增：根目录 `version.json`（`id` / `version` / `updated_at`），作为墨卡大师 `references/satellites.md` 支链版本检查的版本源；此前无该文件，支链只能跳过版本核对。

## v1.1.4 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.1.0 — 2026-10-23

- 新增：同组多矩形不再整体拒收，按「先组序、再组内序」拆成连续 `index` 的独立遮罩；`manifest.json` 记录 `group_count`、`mask_count`、`flattened_groups`。
- 新增：`README.md`，并在 `SKILL.md` 顶部明确「不需要导出 Anki 文件」——直接连本机 AnkiConnect，Anki 未运行会自动启动一次（最多 45 秒）。
- 变更：`scan` 输出 `groups`、`masks`、`flattened_groups`、`flattened_notes`；`prepare` 输出遮罩总数与拆分统计。
- 变更：`source_data` 只校验组结构，不再因为组内多矩形报错；矩形合法性仍由 `convert` 逐块校验。
- 测试：新增多矩形拆分顺序、分组来源校验等用例，共 15 个离线用例。

## v1.1.4 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.0.0 — 2026-10-23

- 首个版本：`doctor` / `scan` / `prepare` / `targets` / `import` / `verify`，支持 `26讲义` 模板每组单矩形，本地预览 + 官方 OpenAPI 写入与回读校验。
