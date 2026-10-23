# 迁墨 Memo-Ankitransfer

「**迁墨**」= 把 Anki 的图片挖空卡迁到墨墨。仓库名与调用标识仍是 `memo-ankitransfer`。

把 Anki 的图片挖空卡（原图 + 比例矩形遮罩）转成墨墨记忆卡原生图片遮罩（`.msk1`），生成位置预览，并可选择通过官方 OpenAPI 导入指定牌组。

**不需要导出 Anki 文件。** 不需要 `.apkg` / `.colpkg` / CSV，也不需要自己找 media 文件夹：脚本直接连接本机 Anki（AnkiConnect），Anki 没打开会自动启动一次。

## 特点

- **一键直连 Anki**：Anki 已运行就直接连；没运行就自动启动并等待最多 45 秒。
- **只读来源**：只查询笔记、取回原图，不移动、不删除、不改卡，不导出学习进度。
- **原图零改动**：不裁剪、不旋转、不重新压缩，遮罩坐标按原图尺寸换算到 0～10000。
- **同组多矩形自动拆分**：墨墨没有「同组同时揭示」，转换时按「组序 → 组内序」拆成连续 index，`manifest.json` 记录拆了多少组。
- **可视化预览**：每张卡生成 `preview.png`，先看位置再写入。
- **可续跑**：`receipt.json` + 包内锁 + 逐卡回读校验，断点不重复上传、不重复建卡。

## 环境要求

- Windows / macOS / Linux，Python 3.10+
- Anki 已安装，并启用 **AnkiConnect** 插件（插件代码 `2055492159`）
- 预览需要 Pillow：`pip install -r requirements.txt`
- 只有真正写入墨墨时才需要官方 API 凭证 `MAIMEMO_TOKEN`（只做本地转换不需要）

## 安装

把本目录（或克隆后的仓库目录）放进技能目录，例如：

```text
~/.agents/skills/memo-ankitransfer/
```

仓库根目录的 `version.json`（`id` / `version` / `updated_at`）是版本源：墨卡大师的支链检查会读 `https://raw.githubusercontent.com/Cognifair/memo-ankitransfer/main/version.json`，升版时与 `SKILL.md` 的 `metadata.version` 保持一致。

## 快速开始

```bash
cd memo-ankitransfer

# 1. 连接检查（没开 Anki 会自动打开）
python -X utf8 scripts/transfer.py doctor

# 2. 找到候选挖空卡：输出笔记 ID、标题、组数、遮罩数、是否兼容
python -X utf8 scripts/transfer.py scan --query 'note:"26讲义"'

# 3. 本地转换一张，生成原图 / .msk1 / preview.png
python -X utf8 scripts/transfer.py prepare --note-id <笔记ID> --out ./out/demo

# 4. 看位置对不对（打开 preview.png），再决定是否写入墨墨
```

写入墨墨（需要目标牌组、章节和 `MAIMEMO_TOKEN`）：

```bash
python -X utf8 scripts/transfer.py targets --deck "目标牌组"
python -X utf8 scripts/transfer.py import --package ./out/demo --deck "目标牌组" --chapter "目标章节" --write
python -X utf8 scripts/transfer.py verify --package ./out/demo
```

## 支持范围

| 项目 | 状态 |
| --- | --- |
| `26讲义` 模板（`Image` / `Masks` / `Mode=free_guess`） | 已验证 |
| 每组一个矩形 | 已验证（样卡 13 个遮罩 API 回读 + 客户端确认） |
| 同组多矩形 | 拆分为独立遮罩，逐块揭示；拆分行为已在本地与单测覆盖，客户端逐块效果请实测 |
| 非矩形 / 其他坐标结构 | 不支持 |
| Anki 内置 Image Occlusion、其他插件 | 不支持 |
| 图片 HTML 变换、EXIF 旋转、动画图 | 不支持 |

## 输出结构

```text
out/demo/
├── manifest.json          # 格式版本、笔记 ID、标题、尺寸、组数/遮罩数、SHA-256、坐标误差
└── <note_id>/
    ├── original.png       # Anki 原图字节，未改动
    ├── mask.msk1          # 墨墨遮罩（UTF-8 JSON，index 从 1 连续编号）
    └── preview.png        # 遮罩位置预览
```

导入后同一目录会出现 `receipt.json`（无凭证，可续跑）与 `import.lock`（同一 package 的并发保护，运行结束自动删除）。

## 测试

```bash
python -X utf8 -m unittest discover -s tests -v
```

全部离线：不连接真实账户，不写入任何卡片。

## 数据与隐私

- 不收集、不上传任何本地数据；只在用户显式执行 `import --write` 时调用官方 API。
- API 凭证只从环境变量读取，不落盘、不打印。
- 不在日志或提交里保存签名媒体 URL、Bearer、Cookie。

## License

MIT
