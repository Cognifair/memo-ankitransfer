---
name: memo-ankitransfer
description: 迁墨 Memo-Ankitransfer，直接连接本机 Anki（无需导出 apkg/CSV），把图片挖空卡的原图与矩形遮罩转成墨墨记忆卡原生图片遮罩，生成位置预览，并通过官方 OpenAPI 导入指定牌组。同组多矩形按原顺序拆成独立遮罩。用于 Anki 转墨墨、Anki 迁墨、图片遮盖迁移、Memo-Ankitransfer；当前实测支持 Image/Masks/Mode 字段的 26讲义模板，不承诺支持所有 Image Occlusion 插件或迁移学习进度。
metadata:
  version: "1.1.7"
---

# 迁墨 Memo-Ankitransfer

展示名「**迁墨**」（英文标识与仓库名仍为 `memo-ankitransfer`）：把 Anki 里的图片挖空卡迁到墨墨记忆卡。

把「Anki 原图 + 比例矩形 → Markji 原图 + .msk1」流程变成可复用命令：直接读本机 Anki，不需要导出任何 Anki 文件，也不把模板 JavaScript 写进墨墨正文。

## 不需要导出 Anki 文件

- 通过本机 AnkiConnect 直接读取已经打开的 Anki 库，不需要导出 `.apkg` / `.colpkg` / CSV，也不需要自己找 media 图片。
- Anki 没在运行就自动启动一次（Windows），最多等 45 秒；已经在运行就直接连，不重启、不打断当前界面。
- 连接固定走 `127.0.0.1:8765` 并绕过系统代理；全程只读，不移动、不删除、不改卡，也不导出学习进度。
- 前置条件只有两个：本机装了 Anki，并且装了 AnkiConnect 插件（插件代码 `2055492159`）。缺插件时 `doctor` 会直接报连接失败。

## 使用范围

- 已验证：`26讲义` 模板，`Image` 是单个本地媒体图片，`Masks` 为 `[[[x,y,w,h]], ...]`，坐标为相对原图的 0～1 比例，`Mode=free_guess`。模板里实际坐标解释（`mask[i] * imgWidth/imgHeight`）会逐项核对。
- 同组多矩形：Anki 里点一下，整组矩形同时显形。墨墨没有「同组同时揭示」，所以转换时按原顺序拆成独立遮罩——组顺序不变，组内矩形保持相邻且 `index` 连续。这会把「一次点出多块」变成「逐块点出」，用户在 2026-10-23 明确接受该取舍；`manifest.json` 记录 `group_count` / `mask_count` / `flattened_groups`，可复核拆了多少组。
- 2026-10-23，「几组概念」样卡的 13 个遮罩已用官方 API 写入、回读一致，用户确认客户端验证成功。这只证明单矩形组的结构；多矩形拆分后的逐块揭示效果以客户端实测为准，不预先宣称已验证。
- 暂不转换：非矩形遮罩、其他坐标结构、Anki 内置 Image Occlusion 或其他插件、图片 HTML 变换、带 EXIF 旋转或动画的原图。扫描会说明原因，不猜坐标、不悄悄跳过。
- 只读 Anki；墨墨里是新增卡片，不能保留 Anki 的学习调度。

## 低门槛入口

在本技能目录运行 `python -X utf8 scripts/transfer.py ...`。不要使用创建此技能时的工作目录、样卡 ID、账户 ID 或文件路径。

Python 3.10+；预览需要 Pillow。优先用当前环境已经提供的 Python/Pillow；在 Codex 桌面可用 `load_workspace_dependencies` 找到自带运行时，不把作者机器路径写成依赖。AnkiConnect 应已安装。连接本地 Anki 时绕过代理；未运行则自动启动一次，等待最多 45 秒。这部分沿用 `anki-connect-operations` 的启动逻辑，已内置，不要求另装该技能。

其他环境缺少 Pillow 时，可安装本目录 `requirements.txt`；本技能不会自动安装软件。运行离线测试：`python -X utf8 -m unittest discover -s tests -v`，不连接账户、不新增卡片。

```powershell
# 本地连接检查：没开 Anki 会自动打开，不需要先导出库
python -X utf8 scripts/transfer.py doctor

# 找到候选笔记，输出笔记 ID、标题、组数、遮罩数量和兼容性
python -X utf8 scripts/transfer.py scan --query 'note:"26讲义"'

# 只做本地转换，原图字节不变；选择一个新的输出目录
python -X utf8 scripts/transfer.py prepare --note-id <笔记ID> --out <输出目录>

# 也支持明确选择的一批笔记；超过 --max-notes（默认 500）会停止，不截断
python -X utf8 scripts/transfer.py prepare --query 'note:"26讲义"' --out <输出目录>

# 用户选择 API 路线后，读取精确的牌组和章节
python -X utf8 scripts/transfer.py targets --deck "目标牌组"

# 已获用户导入授权后执行；一个章节时可以省略 --chapter
python -X utf8 scripts/transfer.py import --package <输出目录> --deck "目标牌组" --chapter "目标章节" --write

# 后续只读复核，不重新创建
python -X utf8 scripts/transfer.py verify --package <输出目录>
```

所有命令均支持 `--help`。`doctor`、`scan`、`prepare` 可加 `--anki-exe <路径>`；已运行时不重启。`--deck-id` / `--chapter-id` 可代替名称；同名目标不猜选，多个章节不默认随便选一个。`prepare` 的返回值会同时给出 `masks`（实际遮罩块数）、`groups`（原组数）和 `flattened_groups`（被拆分的多矩形组数）。

## Agent 执行流程

1. 根据用户范围做只读 `scan`，不要擅自把单张扩展到整库。不要要求用户先导出 Anki 文件；直接连本机 Anki 即可。用户只问能否转换时，完成扫描、样例转换和预览即可，不访问墨墨账户。找不到卡时读取真实模型和字段，不因内置「图片遮盖」模型为空就断言没有挖空卡。
2. `prepare` 生成 `manifest.json`、逐卡原图、`.msk1`、`preview.png`。打开预览检查覆盖位置；报告总数、坐标量化误差、被拆分的多矩形组数，以及仍不支持的结构。转换前核对 `references/format-and-api.md`；位置一致依赖不裁剪、不旋转、不重新压缩原图。
3. 用户明确选择官方 API 且已指定源卡/目标时，直接执行，不重复询问已经回答过的路线或授权。只有还缺实际目标、范围或凭证时才补问。仅制作技能或预览不授权往账户写卡。
4. API 前实时读取 [官方文档](https://open.maimemo.com/#/) 实际引用的定义（当前为 `https://open.maimemo.com/api_bundle.yaml`）与 [tutuji 图片遮罩](https://tutuji333.github.io/markji-faq/questions/content/card-syntax-guide/#62)，核对生产地址、接口和 MIME；本地 reference 是已验证经验，不冒充实时文档。接口若变更，暂停相关写入，先更新实现。
5. 默认从非空 `MAIMEMO_TOKEN` 读取用户已配置的官方凭证，不打印、不落盘，不拿 Web token 替代。用户本次明确指定其他凭证时由安全会话环境注入该脚本，不静默改用旧账户，不持久化。只做本地转换时不读凭证。
6. `targets` 解析真实 OpenAPI ID。正式写入前核对 manifest 数量及目标。`import --write` 上传 `image/*` 原图与 `markji/mask` 遮罩，使用完整 ID、`grammar_version=3`、路径寻址和仅 `card` 的创建正文。默认追加现有章节，不创建牌组或章节。
7. 每卡 GET 回读逐字符核对正文、语法版本、原图尺寸、媒体 ID/MIME 和章节归属；章节 ID 列表校验只有本批新增，发现并发改动时如实标记，不回滚他人修改。保存无凭证 receipt，续跑按同一 package 复用已完成结果。
8. 报告新增/复用/失败数量与目标章节，区分「本地预览」「API 回读通过」「本批客户端已确认」。2026-10-23 的样卡成功不等于新批次已在客户端验证；多矩形拆分后的逐块揭示尤其需要看一眼客户端。

## 续跑与错误

- 幂等范围是同一个 package 的 `receipt.json`，保留它；另建 package 不保证去重。包内锁防止两个进程同时导入同一 package，不承诺跨机器或跨 package 的全局锁。
- 每个上传和建卡请求前写入 pending 状态；请求失败后不盲重发。建卡响应丢失时，续跑从目标章节查找「本次基线之外 + 全文一致」的唯一卡，再核验，无法唯一确认就停止。上传响应丢失且没有 file.id 时停止，由 Agent 核查，不自动重复上传。
- 401/403 报凭证/权限问题，不换账户；429 尊重错误提供的重试时间，不循环；批量在首个失败处停止，保留先前完成卡。
- 上次进程异常退出留下 `import.lock` 时，先确认没有同包进程运行、查看 receipt 再处理锁，不能为了重试直接清空 receipt。不得把签名媒体 URL、Bearer、Cookie 或用户材料收进技能本体或发布包。

本技能不依赖 Memo-Cardest 的启动同步或会员询问；只在实际 API 路线需要凭证。新 Memo 技能的 GitHub 发布收尾按本机 `maimemo-publisher` 的明确授权处理，不自动发布。
