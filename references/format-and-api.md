# 已验证的转换与接口契约

核对与实测日期：2026-10-23。实时官方文档优先；这里记录可复现路径，不含真实账户 ID 或媒体 ID。

## 坐标

Anki 模板以 `mask[0]*imgWidth`、`mask[1]*imgHeight`、`mask[2]*imgWidth`、`mask[3]*imgHeight` 绘制 left/top/width/height，源数据已经归一化。保持原图字节和像素尺寸不变时：

```text
left   = round(x * 10000)
top    = round(y * 10000)
width  = round(w * 10000)
height = round(h * 10000)
```

`.msk1` 是 UTF-8 JSON 数组，按原顺序从 1 编号：

```json
[{"width":2189,"height":146,"top":1880,"left":2312,"index":1,"type":"rect"}]
```

以 `Decimal(str(value))` 确定性换算，Python round 的 half-even 规则。四位小数的比例能精确映射。更高精度输入会量化，坐标/尺寸各自误差不超过对应图像维度的 0.00005；右/下边缘由位置与尺寸相加，误差可相加。manifest 记录实际最大几何参数误差和最大边缘误差（像素），不笼统承诺所有输入绝对无损。

越界、零尺寸、量化后消失的矩形拒绝，不自动裁剪或把它撑大。同组多矩形按「先组序、再组内序」拆成连续 index 的独立矩形：Anki 模板给每组一个 `cloze_id`，点组内任一块会同时切换该组全部矩形；墨墨 `.msk1` 没有这种同组揭示，因此拆分是明确取舍（用户 2026-10-23 同意），拆分后变成逐块揭示。拆分数量写入 manifest 的 `group_count` / `mask_count` / `flattened_groups`，便于复核。不要用重复 index 去模拟同组：该行为未在本流程验证。

来源不经过 apkg 导出：脚本直接用 AnkiConnect（`127.0.0.1:8765`，绕过代理）读已打开的 Anki 库，`findNotes` / `notesInfo` / `retrieveMediaFile` 全是只读调用；Anki 未运行时会按安装路径自动启动一次并最多等待 45 秒。

原图只从 AnkiConnect `retrieveMediaFile` 取回；HTML 必须只有一个本地 img，不接受外链、CSS 变换或多个图片。模板 JavaScript 仅作为文本核对，不执行来源中的代码。图片无 EXIF 方向变换且不是动画，确保浏览器显示方向和坐标一致。

## 官方 API

入口 `https://open.maimemo.com/` 当前引用 `/api_bundle.yaml`；生产服务器是 `https://open.maimemo.com/open`，路径前缀 `/api/v1/markji`。鉴权 `Authorization: Bearer <MAIMEMO_TOKEN>`。

| 用途 | 方法与路径（相对 markji 前缀） |
|---|---|
| 分页牌组 | `GET /decks?offset=0&limit=100` |
| 章节和卡片 | `GET /decks/{deck}/chapters?with_cards=true` |
| 媒体上传 | `POST /files`，multipart 字段 `file`、`deck_id` |
| 新增卡片 | `POST /decks/{deck}/chapters/{chapter}/cards` |
| 回读单卡 | `GET /decks/{deck}/cards/{card}` |

文件 MIME：按原图实际格式，例如 `image/png`；遮罩为 `markji/mask`，扩展名 `.msk1`。上传返回的完整 `file.id` 大小写不变。预览 PNG 不能充当遮罩。

创建正文使用已实测的路径寻址形式：

```json
{"card":{"content":"[P#H1#标题]\n[Pic#ID/<imageFileId>,MID/<maskFileId>#]\n","grammar_version":3}}
```

上面仅解释结构，尖括号内容不能直接写卡。官方定义把 deck/chapter 也列成正文 required，但实测使用 OpenAPI 长 ID 时在正文重复传入会报 ObjectId 参数错误；仅 `card` 的路径寻址已写入并回读成功。

发布时频控为 10 秒 20 次、60 秒 40 次，Markji 5 小时 8000 次；脚本每个官方 API 请求间隔至少 1.6 秒，长时间累计配额仍以服务端为准。不在写请求失败后自动重试；错误输出仅保留状态码、错误码和 Retry-After，不打印可能包含签名 URL 的完整响应。

## 本地包与可复核性

每包 `manifest.json` 固定格式版本、笔记 ID、模型/模板摘要、标题、图像尺寸、遮罩数量、媒体相对路径与 SHA-256、坐标误差。每次 import/verify 重新核对原图、遮罩和源数据摘要，防止转换后换图或篡改坐标。输出路径拒绝绝对路径或逃逸 package 的相对路径。

`receipt.json` 保存目标牌组/章节、逐卡正文、上传 ID、建卡前 ID 列表、阶段和验证结果，不保存 key、媒体签名 URL 或原始 API 完整响应。`import.lock` 用独占创建限制同包并行写入。重复 verify 只读；同包重复 import 回读既有卡，不创建第二张。
