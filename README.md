# Kaoyan Print Kit

面向考研复习的 Codex Skill，用于把知识点、错题和理解检测内容整理为适合 A4 双面打印的 PDF，并同步生成可编辑的 DOCX。

## 能做什么

- 背诵资料：按科目、章节和内容类型整理公式、定义、定理、时间线、词汇或混合知识点。
- 错题与题目摘取：从 PDF、Word 或图片中选取指定页码、题号或关键词内容，生成练习版和解析版。
- 理解与检测：解释知识点，并生成覆盖回忆、辨析、解释、应用、迁移和纠错的检测题。
- 打印质检：检查来源对应、公式与图形、答案隔离、中文字体、分页、裁切和黑白打印效果。
- 背诵材料构建：在保持原章节与知识点顺序的前提下，区分来源原文、AI 内容和用户补充，使用独立的 A/B/C 重要度与 R 薄弱点标签，生成彩色学习版和黑白兼容版。

## 仓库结构

```text
skills/kaoyan-print-kit/       Skill 主体
skills/kaoyan-strategy-advisor/ 阶段策略分析与授权历史
skills/kaoyan-memorization-builder/ 知识点选择、分级、证据链和双版本生成
agents/study-pdf-reviewer.toml 可选的只读质检 Agent
```

## 安装

将 `skills/kaoyan-print-kit` 放入个人 Codex Skills 目录：

- Windows：`%USERPROFILE%\.codex\skills\kaoyan-print-kit`
- macOS / Linux：`~/.codex/skills/kaoyan-print-kit`

如需独立质检 Agent，再将 `agents/study-pdf-reviewer.toml` 放入个人 Codex Agents 目录：

- Windows：`%USERPROFILE%\.codex\agents\study-pdf-reviewer.toml`
- macOS / Linux：`~/.codex/agents/study-pdf-reviewer.toml`

## 阶段策略分析

安装 `skills/kaoyan-strategy-advisor` 后，可用 `$kaoyan-strategy-advisor` 分析当前问题、历程状态和已明确保留的学习记录。输出只覆盖阶段方向、各科或学习活动投入比例、进度风险、阶段切换条件、观察周期和备选方案，不自动制定每日任务。

该 Skill 默认只读。用户明确选择后，才会追加 `data/kaoyan-journey.md`、`data/study-records.jsonl` 或 `data/strategy-history.jsonl`。策略建议与 `accepted`、`rejected`、`undecided` 状态均采用 JSONL 追加事件，历史不会被无痕覆盖。

在仓库根目录运行数据校验：

    python skills/kaoyan-strategy-advisor/scripts/strategy_store.py validate --data-dir data

重启 Codex 后，可直接用自然语言调用，无需记住 Agent 名称。例如：

```text
把这份 PDF 第 12 页的第 3、5、8 题整理成练习版和解析版，并检查排版。
```

也可以显式调用：

```text
$kaoyan-print-kit 把这些定义整理成适合黑白打印的背诵 PDF 和 DOCX。
```

## 输出流程

Skill 会先确认黑白或彩色打印、科目章节、内容范围和不确定的 OCR 片段。在用户确认结构后生成草稿、渲染预览、完成逐页质检，再交付最终 PDF 与 DOCX。

生成器使用 Python，并依赖 `Pillow`、`python-docx`、`pypdf` 和 `reportlab`。PDF 需要可嵌入的简体中文 TrueType 字体；生成器会自动查找 Windows 等线字体或 Noto Sans CJK。也可通过 `KAOYAN_FONT_REGULAR`、`KAOYAN_FONT_BOLD` 和 `KAOYAN_DOCX_FONT` 指定字体。

## Kaoyan Memorization Builder

将 `skills/kaoyan-memorization-builder` 与 `skills/kaoyan-print-kit` 一起安装。新 Skill 复用 print-kit 的 PDF/DOCX 排版内核，不复制公式、字体和渲染代码。

先从 PDF、DOCX、图片或 UTF-8 文本建立待确认项目：

```powershell
python skills/kaoyan-memorization-builder/scripts/extract_sources.py --title "标题" --subject "科目" --output project.json source.pdf
```

也可用可重复的 `--text "用户原始文本"` 直接加入本次输入；脚本会原样保存，不把它改写成 AI 概括。

逐条核对来源、原文、公式、顺序、A/B/C、R 和 AI 标记后，由用户明确确认项目，再生成彩色与黑白版本：

```powershell
python skills/kaoyan-memorization-builder/scripts/build_memorization.py project.json --output-dir outputs/memorization
```

正式构建会分别检查 A/B/C 与 R 的确认状态，拒绝待校对片段、越权重排、缺失或哈希已变化的来源，以及缺少来源引用的原文。彩色和黑白的四个文件会先在临时区全部验证，再发布到输出目录。`schemas/memorization-project.schema.json` 是项目数据契约；真实来源、项目、输出和临时文件默认被 Git 忽略。

生成后可执行 PDF/DOCX 结构质检；含图片时默认要求至少 150 有效 DPI：

```powershell
python skills/kaoyan-memorization-builder/scripts/qa_material.py outputs/memorization/bw-study.pdf --min-image-dpi 150
python skills/kaoyan-memorization-builder/scripts/qa_docx.py outputs/memorization/color-study.docx outputs/memorization/bw-study.docx --min-image-dpi 150
```
