# 文档翻译 API（临时说明）

上传指定格式文件并发起翻译，后端根据文件类型自动走「文本翻译」（md/doc/docx/txt）或「OCR 翻译」（pdf/图片）。前端通过轮询翻译任务状态获取译文附件。

---

## 支持格式与输出

| 类型     | 支持格式 | 译文输出 |
|----------|----------|----------|
| **文本型** | `.md`、`.doc`、`.docx`、`.txt` | 同时产出 **.md** 与 **.docx**：`translated_attachment_id` 为译文 docx 的附件 ID，`context.translated_md_attachment_id` 为译文 md 的附件 ID。 |
| **PDF**   | `.pdf` | 单文件 PDF（`xxx_translated.pdf`）；`translated_attachment_id` 为该 PDF 的附件 ID。**支持逐页渲染**：翻译过程中每译完一页会生成该页预览图 URL，通过任务接口的 `pages` 数组返回，前端可逐页展示。 |
| **图片**  | `.jpg`、`.jpeg`、`.png`、`.webp`、`.bmp`、`.gif` | 单张译文图（如 `xxx_translated.jpg`）；`translated_attachment_id` 为该图片的附件 ID。 |

**上传接口支持但本翻译不支持**：上传接口 `/api/upload/` 允许的格式中，以下类型**仅能上传，不能用于翻译**（若带 `action_type=translate` 会失败或按未支持处理）：`.xls`、`.xlsx`、`.ppt`、`.pptx`、`.csv`、`.json`、`.svg`。请仅对上述「文本型 / PDF / 图片」格式发起翻译。

---

## 1. 上传文件并发起翻译

上传文件到文件系统；当 `action_type=translate` 时同时创建翻译任务，可将文件上传到指定文件夹。

**POST** `<host>/api/upload/`

**Headers**

```
Authorization: Token <your_token>
Content-Type: multipart/form-data
```

**Body**（form-data）

| 字段              | 类型   | 必填 | 说明 |
|-------------------|--------|------|------|
| `files`           | file   | 是   | 文件（可上传多个；翻译场景通常单文件） |
| `action_type`     | string | 否   | 传 **`translate`** 时发起翻译，否则为普通上传 |
| `target_language` | string | 翻译必填 | 目标语言，如 `Chinese`、`cn`、`English`、`en` |
| `input_language`  | string | 否   | 源语言，可选 |
| `parent_id`       | string | 否   | 父文件夹 ID，不提供则上传到根目录 |
| `parse`           | string | 否   | 是否解析文件内容，默认 `true` |

**Response**（200）

```json
{
    "status": "success",
    "uploaded_files": [
        {
            "id": "46ae311b-66fc-48ba-9241-a16fd4cd7c60",
            "name": "细胞重编程巨大潜力.docx",
            "url": "https://noahdata.blob.core.windows.net/nudata/attachments/...",
            "size": 14830,
            "type": "document",
            "extension": "docx",
            "tokens": 0,
            "parsed": false,
            "full_path": "/细胞重编程巨大潜力.docx",
            "translation_task_id": 7
        }
    ],
    "failed_files": [],
    "total_tokens": 0
}
```

- 当 `action_type=translate` 且上传成功时，`uploaded_files` 中每一项会多出 **`translation_task_id`**，用于查询翻译任务状态与获取译文。

---

## 2. 查询翻译任务状态

根据任务 ID 查询翻译任务状态及译文附件 ID；仅可查询当前用户自己的任务。  
- **PDF**：可使用 **`context.current_page`** / **`context.total_pages`** 作为进度；**`pages`** 数组为已译页的预览图 URL（每译完一页追加一条），前端可按 `page_index` 顺序逐页渲染，无需等整份译完。
- **Word/文本型**：整文件翻译，页数固定为 1，无 `pages`。

**GET** `<host>/api/workflow/translation-task/<task_id>/`

**Headers**

```
Authorization: Token <your_token>
```

**Response**（200）

**PDF 示例**（含进度与逐页预览）

```json
{
    "id": 6,
    "name": "001生物BP20241224.pdf",
    "status": "complete",
    "original_attachment_id": "b997a59d-0023-4c10-9b81-6b879ad664dd",
    "translated_attachment_id": "cc304c17-2ec7-4e1d-b9e3-5c11c6b4c951",
    "target_language": "en",
    "input_language": "zh",
    "time_created": "2026-02-05T05:06:05.852682+00:00",
    "time_updated": "2026-02-05T05:09:03.481918+00:00",
    "time_finished": null,
    "context": {
        "file_name": "001生物BP20241224.pdf",
        "total_pages": 21,
        "current_page": 21
    },
    "pages": [
        { "page_index": 1, "url": "https://noahdata.blob.core.windows.net/nudata/attachments/translation/6/page_1.jpg?..." },
        { "page_index": 2, "url": "https://noahdata.blob.core.windows.net/nudata/attachments/translation/6/page_2.jpg?..." }
    ]
}
```

- **`pages`**：仅 **PDF 翻译**存在；按 `page_index` 从 1 递增，每项为该页「原页 + 白底译文」的预览图 URL。翻译进行中会逐步追加，前端轮询时可依此逐页展示；非 PDF 或旧任务无此字段或为空数组 `[]`。

**Word/文本型示例**（整文件翻译，无逐页进度）

```json
{
    "id": 7,
    "name": "细胞重编程巨大潜力.docx",
    "status": "complete",
    "original_attachment_id": "46ae311b-66fc-48ba-9241-a16fd4cd7c60",
    "translated_attachment_id": "1ff956a2-45de-4b82-bfd5-708895c2b8b6",
    "target_language": "en",
    "input_language": "zh",
    "time_created": "2026-02-05T07:21:54.888866+00:00",
    "time_updated": "2026-02-05T07:22:15.038887+00:00",
    "time_finished": null,
    "context": {
        "file_name": "细胞重编程巨大潜力.docx",
        "total_pages": 1,
        "current_page": 1,
        "translated_md_attachment_id": "ded9b890-cdf1-496f-9f9b-61f24c868f58"
    },
    "pages": []
}
```

| 字段 | 说明 |
|------|------|
| `status` | `submitted` / `running` / `complete` / `failed`；完成前可轮询本接口。**完成态为 `complete`**（非 completed） |
| `translated_attachment_id` | 译文主附件 ID：文本型为 **docx**，PDF/图片为 **译文 PDF 或图片**；用于下载/预览 |
| `context.translated_md_attachment_id` | 仅文本型翻译存在，为译文 **.md** 的 attachment_id |
| `context.current_page` / `context.total_pages` | 仅 PDF/图片翻译存在；表示当前已翻译页数与总页数，可用于进度条 |
| `pages` | 仅 **PDF 翻译**存在；`[{ "page_index": 1, "url": "..." }, ...]`，按页序的预览图 URL，可逐页渲染；非 PDF 或旧任务为 `[]` |

---

## 3. 查询文件 URL（获取附件详情）

根据附件 ID 查询附件名称与可读 URL（用于下载或预览）；可一次查询多个。仅可查询当前用户自己的附件。

**GET** `<host>/api/upload/list/?ids=<attachment_id1>,<attachment_id2>,...`

**Headers**

```
Authorization: Token <your_token>
```

**Query**

| 参数  | 类型  | 必填 | 说明 |
|-------|-------|------|------|
| `ids` | string | 是   | 附件 ID，多个用英文逗号分隔，如 `a1b2c3d4-...,f9e8d7c6-...` |

**Response**（200）

返回附件列表（数组），每项包含：

```json
[
    {
        "id": "ded9b890-cdf1-496f-9f9b-61f24c868f58",
        "name": "tmpkulx1nn9_translated.md",
        "url": "https://noahdata.blob.core.windows.net/nudata/attachments/translation/7/tmpkulx1nn9_translated.md?st=..."
    }
]
```

- `url` 为带签名的可读地址，可直接用于浏览器下载或预览；过期时间由服务端配置决定。

---

## 4. 简要流程

1. **POST** `/api/upload/`，`action_type=translate`，带 `target_language` 和 `files`。
2. 从响应 `uploaded_files[].translation_task_id` 取得任务 ID。
3. 轮询 **GET** `/api/workflow/translation-task/<task_id>/`，直到 **`status === "complete"`**（或 `failed`）。  
   - PDF：用 `context.current_page` / `context.total_pages` 做进度条；用 **`pages`** 数组按 `page_index` 顺序渲染每页预览图（每译完一页会多一条，可逐页展示）。
4. 使用 `translated_attachment_id`（及可选 `context.translated_md_attachment_id`）调用 **GET** `/api/upload/list/?ids=<attachment_id>` 获取整份译文 `url`，用于下载或预览。

---

## 可选语言

- **`input_language`**（源语言，用于提升 OCR 识别准确率）：仅支持下表所列 OCR 模式；传入**短码**即可，下表即全部支持范围。
- **`target_language`**（目标语言）：支持**所有**语言，下表可作为目标语参考；传入规范名或短码（如 `Chinese`、`cn`、`English`、`en`）即可。

表头**说明**列为中文简要说明该模式适用的源语言（即该行短码可识别的文档语言）。

| 规范名 | 短码/别名 | 说明 |
|--------|-----------|------|
| 中文/繁体/英文 | ch | 简体中文、英文、繁体中文 |
| 中文轻量 | ch_lite | 简体中文、英文、繁体中文、日语 |
| 中文服务端 | ch_server | 简体中文、英文、繁体中文、日语 |
| 英文 | en | 英文 |
| 韩文 | korean | 韩语、英文 |
| 日文 | japan | 简体中文、英文、繁体中文、日语 |
| 繁体中文 | chinese_cht | 简体中文、英文、繁体中文、日语 |
| 泰米尔语 | ta | 泰米尔语、英文 |
| 泰卢固语 | te | 泰卢固语、英文 |
| 坎纳达语 | ka | 坎纳达语 |
| 泰语 | th | 泰语、英文 |
| 希腊语 | el | 希腊语、英文 |
| 拉丁语系 | latin | 法语、德语、南非荷兰语、意大利语、西班牙语、波斯尼亚语、葡萄牙语、捷克语、威尔士语、丹麦语、爱沙尼亚语、爱尔兰语、克罗地亚语、乌兹别克语、匈牙利语、塞尔维亚语(拉丁)、印尼语、奥克语、冰岛语、立陶宛语、毛利语、马来语、荷兰语、挪威语、波兰语、斯洛伐克语、斯洛文尼亚语、阿尔巴尼亚语、瑞典语、斯瓦希里语、他加禄语、土耳其语、拉丁语、阿塞拜疆语、库尔德语、拉脱维亚语、马耳他语、巴利语、罗马尼亚语、越南语、芬兰语、巴斯克语、加利西亚语、卢森堡语、罗曼什语、加泰罗尼亚语、克丘亚语 |
| 阿拉伯语系 | arabic | 阿拉伯语、波斯语、维吾尔语、乌尔都语、普什图语、库尔德语、信德语、俾路支语、英文 |
| 东斯拉夫语系 | east_slavic | 俄语、白俄罗斯语、乌克兰语、英文 |
| 西里尔语系 | cyrillic | 俄语、白俄罗斯语、乌克兰语、塞尔维亚语(西里尔)、保加利亚语、蒙古语、阿布哈兹语、阿迪格语、卡巴尔达语、阿瓦尔语、达尔金语、印古什语、车臣语、拉克语、列兹金语、塔巴萨兰语、哈萨克语、吉尔吉斯语、塔吉克语、马其顿语、鞑靼语、楚瓦什语、巴什基尔语、马里语、摩尔多瓦语、乌德穆尔特语、科米语、奥塞梯语、布里亚特语、卡尔梅克语、图瓦语、萨哈语、卡拉卡尔帕克语、英文 |
| 天城文语系 | devanagari | 印地语、马拉地语、尼泊尔语、比哈尔语、迈蒂利语、安吉卡语、博杰普尔语、马加希语、桑塔利语、纽瓦里语、孔卡尼语、梵语、哈里亚纳语、英文 |

---

*临时说明，与当前 NoahAgent + Backend 实现一致；接口变更以代码为准。*
