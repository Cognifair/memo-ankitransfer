# Changelog

## v1.1.1 — 2026-10-23

- 新增：根目录 `version.json`（`id` / `version` / `updated_at`），作为墨卡大师 `references/satellites.md` 支链版本检查的版本源；此前无该文件，支链只能跳过版本核对。

## v1.1.0 — 2026-10-23

- 新增：同组多矩形不再整体拒收，按「先组序、再组内序」拆成连续 `index` 的独立遮罩；`manifest.json` 记录 `group_count`、`mask_count`、`flattened_groups`。
- 新增：`README.md`，并在 `SKILL.md` 顶部明确「不需要导出 Anki 文件」——直接连本机 AnkiConnect，Anki 未运行会自动启动一次（最多 45 秒）。
- 变更：`scan` 输出 `groups`、`masks`、`flattened_groups`、`flattened_notes`；`prepare` 输出遮罩总数与拆分统计。
- 变更：`source_data` 只校验组结构，不再因为组内多矩形报错；矩形合法性仍由 `convert` 逐块校验。
- 测试：新增多矩形拆分顺序、分组来源校验等用例，共 15 个离线用例。

## v1.0.0 — 2026-10-23

- 首个版本：`doctor` / `scan` / `prepare` / `targets` / `import` / `verify`，支持 `26讲义` 模板每组单矩形，本地预览 + 官方 OpenAPI 写入与回读校验。
