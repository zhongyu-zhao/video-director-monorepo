# 视听语言词表（草案 v0）

状态：草案，M2 逐镜标注启用。M0 代码不读取本文件；在 M2 把词表写进 schema 校验之前，先按本文件评审。

## 原则

- 能汇总的维度用枚举；自由文本只用于画面描述和解释。
- 不确定时输出 `unknown`，不猜一个确定值。
- 每个标签必须能指向证据：关键帧、时间码或实测值。
- 景别按“主体在画框里占多大”判，不按焦段判；没有人物时按同等距离的物体换算。
- 运镜先问“整幅画面动了吗”；主体在画面里动但机位不动，是 `static`。
- 变焦和推拉要分开：变焦透视不变，推拉背景会“涌过来”。
- 浅景深不等于特写；景深和景别是两个维度。

## 枚举

### 景别 `scale`

`extreme-long` / `long` / `full` / `medium` / `medium-close` / `close` / `extreme-close` / `foreground` / `insert` / `unknown`

参考 CineScale 的九类；`foreground` 指前景遮挡/前景人物镜头，`insert` 指插入镜头（手、道具、字卡等）。

### 角度 `angle`

`eye-level` / `high-angle` / `low-angle` / `birds-eye` / `dutch` / `over-the-shoulder` / `point-of-view` / `unknown`

### 运镜 `camera`

`static` / `pan` / `tilt` / `push-in` / `pull-out` / `track` / `crane-up` / `crane-down` / `handheld` / `orbit` / `zoom-in` / `zoom-out` / `rack-focus` / `drone` / `unknown`

### 构图 `composition`

`rule-of-thirds` / `centered` / `symmetrical` / `frame-within-frame` / `foreground-occlusion` / `negative-space` / `lead-room` / `unknown`

### 光线 `lighting`

`high-key` / `low-key` / `hard` / `soft` / `backlight` / `side-light` / `top-light` / `under-light` / `practical` / `natural` / `unknown`

### 色彩 `color`

`warm` / `cool` / `saturated` / `desaturated` / `monochrome` / `complementary` / `unknown`

### 景深 `dof`

`shallow` / `deep` / `unknown`

焦距（广角/标准/长焦）从单帧不可靠，M2 先不单独出标签；需要时用透视和主体比例的代理指标，并标 `unknown`。

### 转场 `transition_in`

`start` / `cut` / `dissolve` / `fade` / `wipe` / `whip` / `morph` / `unknown`

`start` 只用于首镜。匹配剪辑、跳切、正反打属于镜头关系（L4），不是单镜转场，M3 再建模。

### 声音 `audio`

多值：`dialogue` / `voice-over` / `music` / `effects` / `ambience` / `silence`。

声音事件不是转场；由 ASR、说话人分离和音频事件模型给出，VLM 只做归纳。

## 证据要求

| 维度 | 最低证据 |
|---|---|
| `scale` | 人脸/主体框占画高比例，或关键帧 |
| `angle` | 地平线/人物透视 + 关键帧 |
| `camera` | 全局运动/光流测量 + 关键帧；静态需要运动低于阈值 |
| `composition` | 主体/人脸位置 + 边缘密度/对称性 |
| `lighting` | 亮度分布、对比度、方向性 + 关键帧 |
| `color` | 主色板、HSV 统计 + 关键帧 |
| `dof` | 背景虚化/人脸比例 + 关键帧 |
| `function` | 前后镜头、场景上下文 + 镜头卡 |

## 待定

- 词表是否要中英双语；报告展示中文，存储用英文 slug。
- `angle` 是否把过肩/主观拆成独立镜头关系维度。
- 景别和构图的边界案例（无人物空镜、动画、游戏画面）需要金标集校准。
- 词表版本如何与 `schema_version` 绑定；候选做法是 `taxonomy_version` 单独递增。
