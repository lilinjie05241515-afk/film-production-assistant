---
name: 影视创作工作台 2.0.0
description: 黑金夜间与磨砂白日间，围绕准确文稿和真实项目画面的紧凑工作台。
colors:
  dark-bg: "#111314"
  dark-surface: "#1b1e20"
  dark-subtle: "#171a1c"
  dark-side: "rgba(21,23,24,.94)"
  dark-hover: "#24282a"
  dark-ink: "#eeede8"
  dark-muted: "#a2a6a8"
  dark-line: "#303437"
  dark-accent: "#d0b47d"
  dark-soft: "#302b21"
  dark-accent-ink: "#171713"
  dark-good: "#a8c7b7"
  dark-good-bg: "#22362d"
  dark-danger: "#efb3a7"
  dark-danger-bg: "#3b2521"
  dark-warning: "#dbc38d"
  dark-warning-bg: "#332c1f"
  dark-overlay: "#0009"
  light-bg: "#f3f3ef"
  light-surface: "#fdfdfa"
  light-subtle: "#eeefea"
  light-side: "rgba(251,251,248,.88)"
  light-hover: "#eaece7"
  light-ink: "#262c2c"
  light-muted: "#626b6c"
  light-line: "#d9dcd5"
  light-accent: "#80602a"
  light-soft: "#ebe4d6"
  light-accent-ink: "#fff"
  light-good: "#38644f"
  light-good-bg: "#e6eee7"
  light-danger: "#963e2e"
  light-danger-bg: "#fae9e4"
  light-warning: "#77571e"
  light-warning-bg: "#f2e9d5"
  light-overlay: "#27302c66"
  video-stage: "#080b0e"
typography:
  headline:
    fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif'
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-.03em"
  title:
    fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif'
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.45
  body:
    fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif'
    fontSize: "14px"
    lineHeight: 1.65
  prose:
    fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif'
    fontSize: "15px"
    lineHeight: 1.95
  button:
    fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif'
    fontSize: "13px"
    lineHeight: 1.5
  label:
    fontSize: "11px"
  mono:
    fontFamily: "Consolas,monospace"
    fontSize: "12px"
    lineHeight: 1.65
rounded:
  badge: "5px"
  control: "7px"
  switch: "9px"
  cover: "10px"
  panel: "12px"
  dialog: "14px"
spacing:
  compact: "8px"
  control-gap: "12px"
  row: "16px"
  mobile-gutter: "18px"
  panel: "22px"
  section: "24px"
  overview-gap: "32px"
  desktop-gutter: "36px"
components:
  button-primary-dark:
    backgroundColor: "{colors.dark-accent}"
    textColor: "{colors.dark-accent-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-primary-light:
    backgroundColor: "{colors.light-accent}"
    textColor: "{colors.light-accent-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-secondary:
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-text:
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "5px"
  input:
    rounded: "{rounded.control}"
    padding: "8px 10px"
  navigation:
    rounded: "{rounded.control}"
    padding: "11px 12px"
  badge:
    typography: "{typography.label}"
    rounded: "{rounded.badge}"
    padding: "3px 8px"
  panel:
    rounded: "{rounded.panel}"
    padding: "22px"
  reader-drawer:
    width: "650px"
    height: "100dvh"
    rounded: "14px 0 0 14px"
---

# Design System: 影视创作工作台 2.0.0

## Overview

**Creative North Star: "安静的影视创作工作台"**

沿用用户已选的黑金夜间、磨砂白日间和画面优先审看方向。紧凑导航、薄边界与克制的圆角为文稿、项目画面和下一项明确决定让出空间；两种外观共享同一信息层级。

这是当前开发副本的实现记录，依据 `plugin/ui/board.html` 的最终级联以及 `scripts/board2000.css`、`scripts/board2000-runtime.js`。生成入口为 `scripts/build_creator_ui.py`。设计记录不表示正式安装、发布或作品审批完成。

**Key Characteristics:**
- 黑金与磨砂白共享布局和语义。
- 真实项目画面、准确文稿版本与明确确认入口。
- 短暂状态动效，键盘与减少动态效果优先。

## Colors

### Primary
夜间香槟金与日间深金分别使用 `dark-accent`、`light-accent`，标识当前位置、链接及主操作；`soft` 为选中底色，`accent-ink` 为实色主按钮文字。实际 CSS 通过同名语义变量切换主题；`--paper` 与 `--bg` 同值，`--green` 是 `--accent` 的兼容别名。

### Secondary
`good`、`warning`、`danger` 及对应底色分别用于成功、待核对和错误；状态同时保留文字说明，不从金色推断采用或审批状态。

### Neutral
`bg` 是页面底色；`surface` 是面板与弹窗；`subtle` 是预览空位、阅读辅助区与嵌套底层；`side` 是半透明导航和顶栏；`line` 是细分隔线。`ink` 与 `muted` 区分正文和辅助内容。视频舞台在两种外观下保持深色。Sidecar 的八阶 OKLCH 色带仅为面板展示合成，不是应用实际使用或新增批准的颜色 token。

**The Placeholder Rule.** 输入提示使用当前主题 `--muted`，且 `opacity:1`；不要叠加浏览器默认透明度。

## Typography

系统中文无衬线字体统一承担界面与长文；准确身份、摘要和代码使用 Consolas 后备等宽字体。标题层级遵循前置 token，移动端主标题在 620px 及以下降为 27px。任务标题为 14px，手机任务列表为 13px；辅助标签通常为 11–12px。阅读正文最大宽度为 72ch，段落行高宽松，长身份可断行。

## Layout

桌面采用 218px 左导航与自适应内容列，内容最大宽度 1500px，正文区内边距为 32px 36px 45px。总览为待办与项目视觉两列（1:1.1），下方接近期文稿。阅读抽屉靠右占满视口高度，标准宽度见 token。

最终 HTML 保留早期规则；以下是有实际影响的断点，而非仅新样式文件的断点：

| 条件 | 实际变化 |
| --- | --- |
| ≥1550px | 通用素材网格四列，独立阅读区左右留白 50px。 |
| ≤1250px | 任务看板与对象网格两列，通用双栏变单栏。 |
| ≤1100px | 导航 188px；内容左右 25px；总览等宽两列；列表隐藏阶段列；预演侧栏移至下一行。 |
| ≤1000px | 通用素材网格两列；独立阅读目录 177px、正文左右 22px。 |
| ≤950px | 双机位预演画面变单列。 |
| ≤850px | 侧导航改顶部 60px 导航条，主导航明确横向排列；顶栏露出主题切换和项目设置；对象网格两列；创作环节隐藏数量说明。 |
| ≤720px | 独立阅读目录 125px，阅读高度 65vh，版本盒单列；通用素材卡缩小。 |
| ≤650px | 任务看板与用途素材网格单列；资料设置缩略图 88px；需求信息单列。 |
| ≤620px | 顶部导航 58px、隐藏品牌文字；内容左右 18px；总览及对象网格单列；列表操作换行；阅读抽屉与预演窗口全屏；预演镜头横向滚动。 |

创作环节与分类标签允许横向滚动。通用素材网格仍保留两列手机规则，与对象素材网格的单列规则不同。

## Elevation & Depth

页面以相邻底色和细边界区分层次；普通任务行不浮起。导航和顶栏使用 20px 背景模糊；弹窗遮罩使用 4px 背景模糊。弹窗阴影随主题切换：夜间 `0 20px 70px #0005`，日间 `0 20px 70px #35403625`。这些扩展 token 保存在 sidecar。

## Shapes

控件、徽标、封面、面板和弹窗使用前置圆角 token。任务列表与任务卡以直线分隔；对象卡外壳无边框、无圆角，只有画面容器带圆角。手机阅读抽屉与预演窗口为直角全屏。图标为细描边内嵌 SVG，不依赖远程图标字体。

## Components

按钮以实色主操作、描边次操作、透明文字操作分级。主按钮悬停亮度为 1.08；普通按钮使用 `hover` 底色；按下缩放为 .985。禁用按钮透明度为 .5。键盘焦点为 2px 当前强调色轮廓、向外偏移 3px。输入框使用主题面板底色与细边框，提示文字遵守 Placeholder Rule。

导航用 `aria-current=page`，主题与布局切换用 `aria-pressed` 表达选择。徽标使用语义文字与对应色组；空态保留明确说明和虚线边框，不补入虚构项目内容。

阅读抽屉打开准确文稿版本；项目身份、版本和 SHA-256 不匹配会报错。进入确认再返回时保存原节点、阅读滚动位置与焦点，并核对当前项目。采用、素材选用仍经过明确确认，阅读本身不改变采用状态。

项目视觉优先匹配项目封面 ID 与摘要，其次匹配当前已选用图像；都没有则显示空态。总览画面为 16:10 且可裁切，普通对象缩略图默认 4:3 且完整显示，用途素材缩略图保留 1.65 比例；手机对象封面变为 16:10。预览、原图与视频使用真实项目读取结果，不打包参考照片冒充作品资产。

主题切换直接更新属性和控件状态，保留输入与视频 DOM；用户偏好保存至 `film-board-appearance-v2`，无有效偏好时默认夜间。颜色过渡 180ms ease，普通弹窗进入 180ms、抽屉进入 220ms，缓动均为 `cubic-bezier(.22,1,.36,1)`；关闭淡出 140ms ease-out，无闲置动画。键盘操作将 CSS 动效时长归零并跳过关闭动画；减少动态效果模式关闭 CSS 动效与关闭动画。静态按下缩放不属于时长控制，仍保留。

## Do's and Don'ts

- **Do** 使用当前主题语义变量，让两种外观保持同一信息层级。
- **Do** 显示真实项目素材或明确空态，并保留准确文稿身份。
- **Do** 保留焦点轮廓、状态文字、返回上下文和减少动态效果支持。
- **Don't** 将金色、阅读完成或候选展示解释为正式采用。
- **Don't** 用参考照片或虚构作品填充真实项目的空态。
- **Don't** 把开发副本、设计文档或本地验证表述为生产安装完成。
