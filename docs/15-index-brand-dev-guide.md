# 顾客首页品牌 UI 升级 · 开发指导（交付团队执行版）

> 版本：v1.0（2026-09-04）
> 上游方案：`docs/14-index-brand-ui.md`（视觉稿 + 设计规范）
> 设计系统：`docs/11-ui-design-spec.md`（token / 组件 / 无障碍）
> 交付对象：前端开发团队

---

## 0. 交付范围与前置

**改动文件（仅 3 个，不动后端）：**

| 文件 | 改动 |
|---|---|
| `app/templates/index.html` | 首页结构重写（Hero + 吉祥物 + 毛玻璃卡片） |
| `app/static/css/custom.css` | 追加「首页品牌化」样式块（第 16 节，不破坏既有 15 节） |
| `app/static/js/main.js` | 追加吉祥物表情彩蛋逻辑（约 10 行，不影响现有脚本） |

**不改动**：表单 `action`（`main.enter`）、字段名（`phone` / `code`）、CSRF token、后端路由与校验。

---

## 1. 开发思路（总体三步）

按 P0 → P1 → P2 推进，每步独立可上线、可回退：

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0 视觉骨架** | Hero 渐变 + 吉祥物静态 + 毛玻璃卡片 + 移动适配 | 手机端首屏完整、可下单 |
| **P1 动画 + 彩蛋** | 呼吸/漂浮/眨眼 + 输入框 focus 切「专注」表情 | 动画流畅、无卡顿 |
| **P2 打磨** | 副标徽章微调、桌面端视觉复核、降级兜底 | 全端一致 |

**核心原则：复用已有 token。** 品牌色、圆角、按钮、焦点环在 `custom.css` 第 1~6 节已定义，直接使用 `var(--kiwi)`、`var(--kiwi-dark)`、`var(--kiwi-50)`、`var(--kiwi-tint)`、`var(--kiwi-accent)`，**不要新造同名色值**。吉祥物插画专用色可硬编码（见 §2.2）。

---

## 2. 模块实现指导

### 2.1 品牌 Hero 区

```css
.home-hero {
  position: relative;
  background: linear-gradient(180deg, #2E6B47 0%, #3D8B5F 46%, #5C9B70 100%);
  padding: 34px 20px 74px;   /* 底部多留 74px，供毛玻璃卡片上浮重叠 */
  text-align: center;
  overflow: hidden;
}
```

- **柔光斑**：2 个绝对定位圆，`radial-gradient` 白 / 暖橙 `rgba(250,200,120,.3)`，边缘自然过渡（无需 blur）。
- **顶部导航处理（关键决策）**：首页顾客未登录，`base.html` 的 navbar 仅显示品牌名，与 Hero 内品牌名重复。建议二选一：
  - **方案 A（推荐，侵入最小）**：首页 `body` 加 `class="home-page"`，CSS 隐藏 navbar/footer（`.home-page .navbar, .home-page footer { display: none; }`），让 Hero 顶到状态栏。
  - 方案 B：navbar 透明化、文字变白、绝对定位叠在 Hero 上（需处理滚动与对比度）。
  - 无论哪种，「管理员入口」入口保留（已在毛玻璃卡片底部灰字）。

### 2.2 吉祥物 SVG（含表情态切换）

**形态**：切开猕猴桃（外皮棕环 → 绿果肉 → 奶油白果芯），果芯作脸盘子，顶部两片叶，果肉环带 8 颗黑籽。

**插画专用色（硬编码）**：外皮 `#8B5E3C`、果肉 `#97C459`、果芯 `#F6EFD8`、籽/五官 `#3A3A3A`/`#2C2C2A`、腮红 `#F0997B`、叶子 `#639922`/`#97C459`。

**SVG 内联**（无图片请求），`viewBox="0 0 120 130"`。

**四表情态切换（推荐实现）**：把「眼睛 + 嘴 + 腮红」拆成四组 `<g class="face face-normal|blink|happy|focus">`，身体（外皮/果肉/果芯/籽/叶）共用一份。CSS 控制显隐，JS 切 `data-state`：

```css
.mascot .face { display: none; }
.mascot[data-state="normal"] .face-normal { display: block; }
.mascot[data-state="blink"]  .face-blink  { display: block; }
.mascot[data-state="happy"]  .face-happy  { display: block; }
.mascot[data-state="focus"]  .face-focus  { display: block; }
```

| 态 | 触发 |
|---|---|
| normal | 默认 |
| blink | 定时循环（4s 周期，占 8% 时长） |
| happy | 下单成功等后续扩展 |
| focus | 手机号输入框 `focus` |

### 2.3 毛玻璃卡片

```css
.glass-card {
  margin: -46px 14px 14px;              /* 上浮重叠 Hero 底部 */
  background: rgba(255, 255, 255, .78);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);  /* Safari 必加前缀 */
  border: .5px solid rgba(255,255,255,.6);
  border-radius: 20px;
  padding: 18px 16px;
}
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .glass-card { background: #fff; }      /* 兜底：退实心白底 */
}
```

### 2.4 动画（仅 transform / opacity）

```css
@keyframes kiwi-breathe { 0%,100%{transform:scale(1)} 50%{transform:scale(1.05)} }
@keyframes kiwi-float   { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
@keyframes kiwi-blink   { 0%,92%,100%{transform:scaleY(1)} 96%{transform:scaleY(.08)} }
@media (prefers-reduced-motion: reduce) { .mascot * { animation: none !important; } }
```

### 2.5 移动端适配

- Hero `padding-top: max(34px, env(safe-area-inset-top))` 处理刘海屏。
- 表单输入触控高度沿用全局 48px（`custom.css` 已设）。
- 桌面端：整页 `main.container` 下用 `.home-page .home-wrap { max-width: 420px; margin: 0 auto; }` 居中，避免拉宽。

---

## 3. 注意事项（重点）

### 3.1 兼容性（P0 级）
1. **`backdrop-filter` 必须加 `-webkit-` 前缀**（iOS Safari 12+、部分老 Safari 只认前缀）。
2. 部分安卓 WebView / 低端机不支持 blur → 已用 `@supports` 兜底实心白底，**必须保留这条兜底**，否则卡片可能全透明、文字看不清。
3. 渐变 + 柔光斑 + blur 叠加在低端机可能掉帧，见 §3.2。

### 3.2 性能
- 动画只允许 `transform` / `opacity`，**禁止动画 `top/left/width/height/background`**（触发重排）。
- 柔光斑用 `radial-gradient` 静止圆，**不要**再给它加 blur/动画。
- 吉祥物 SVG 元素控制在 30 个以内，避免低端机解析慢。

### 3.3 无障碍（WCAG AA）
- 吉祥物是纯装饰 → 加 `aria-hidden="true"`，避免读屏播报「切开猕猴桃」等无意义内容。
- 品牌名保留为 `<h1>`（语义层级），现有 `<h1 class="h4">` 可改为更明确的 hero 标题。
- 表单 `label[for]` 与 input 关联**保持不动**（现有 `phone-input` / `code-input`）。
- 焦点环沿用全局 `:focus-visible` 样式；毛玻璃卡片内的输入框焦点环在浅底上要仍清晰可见。
- 表情切换是纯视觉，不改变任何可访问语义。

### 3.4 品牌一致性
- 按钮、圆角、间距、字体一律复用 token，**不要**在首页重新定义一套按钮样式。
- 吉祥物插画色是唯一允许硬编码的部分（它是插画，非 UI 色）。
- 若决定替换全局 🥝 emoji（navbar/footer/底栏），需全站统一，避免「首页 SVG + 内页 emoji」混搭。

### 3.5 与现有代码衔接
- `custom.css` 已有 15 节，新样式追加为「16. 首页品牌化」区块，**不要**改动既有选择器，防止内页回归。
- `main.js` 是全局脚本（含下单页防重复提交、多地址逻辑），首页彩蛋逻辑要**独立 IIFE 包裹**，并用 `if (document.getElementById(...))` 守卫，避免在内页报错。
- 首页表单字段名与后端强绑定（`phone`/`code`/`_csrf_token`），改结构时**保持 name 不变**。

### 3.6 微信 / 真机场景（本项目顾客多从微信点链接）
- 重点真机验证：**iOS Safari、安卓微信内置浏览器、iOS 微信 WKWebView**——微信对 `backdrop-filter` 与 `env(safe-area-inset-top)` 支持不一，务必实测。
- 微信内 `100vh` 有地址栏遮挡问题，若 Hero 用视口高度，建议用 `min-height` 而非 `100vh`。

### 3.7 测试清单
- [ ] 手机端首屏：Hero 完整、毛玻璃卡片不透明不清、可输入可提交下单。
- [ ] 兜底：不支持 blur 的浏览器，卡片退实心白底、文字清晰。
- [ ] 动画：呼吸/漂浮流畅，`prefers-reduced-motion` 下静止。
- [ ] 表情彩蛋：focus 手机号 → 专注态；blur → 恢复正常；无 JS 报错。
- [ ] 内页回归：下单页、订单管理、登录页视觉与功能不受影响。
- [ ] 桌面端：≤420px 居中，不拉伸不变形。

---

**文档版本**：v1.0
**执行状态**：待开发团队按 P0 → P1 → P2 落地
