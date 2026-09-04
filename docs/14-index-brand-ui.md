# 顾客首页 · 品牌化 UI 方案（移动端）

> 版本：v1.0（2026-09-04）
> 适用：顾客端首页 `app/templates/index.html`
> 目标：从「朴素表单卡片」升级为「有品牌记忆点的移动端门面」，含猕猴桃拟人化吉祥物 + 毛玻璃质感

---

## 1. 设计目标

| 目标 | 手段 |
|---|---|
| 3 秒建立「自然新鲜」第一印象 | 顶部猕猴桃绿渐变 Hero + 柔光斑 |
| 品牌人格化 | 切开猕猴桃吉祥物（多表情态 + 呼吸/漂浮动画） |
| 现代质感与聚焦输入 | 毛玻璃表单卡片上浮于 Hero |
| 移动端沉浸 | 全屏 Hero、安全区适配、≥48px 触控 |

---

## 2. 三模块设计

### 2.1 品牌 Hero 区

- **背景渐变**（上→下）：`#2E6B47 → #3D8B5F → #5C9B70`
- **柔光斑**：2 个 `radial-gradient` 半透明圆（白色 + 暖橙 `rgba(250,200,120,.3)`），模拟果肉透亮感
- **品牌语**：主标题「猕猴桃订购」（21px/500/白，字距 1px）+ 副标毛玻璃徽章「太白山 · 产地直发」
- 副标徽章：`rgba(255,255,255,.18)` + `backdrop-filter: blur(8px)` + 白色半透明描边

### 2.2 猕猴桃吉祥物（Mascot）

**形态**：切开猕猴桃（外皮棕环 → 绿果肉 → 奶油白果芯），果芯作「脸盘子」，顶部两片小叶，果肉环带散落 8 颗黑籽。

**配色**（贴合品牌绿）：

| 部位 | 色值 |
|---|---|
| 外皮 | `#8B5E3C` |
| 果肉 | `#97C459` |
| 果芯 | `#F6EFD8` |
| 籽 / 五官 | `#3A3A3A` / `#2C2C2A` |
| 腮红 | `#F0997B` |
| 叶子 | `#639922` / `#97C459` |

**四种表情态**（可做交互彩蛋）：

| 态 | 触发 | 五官 |
|---|---|---|
| 正常 | 默认 | 圆眼 + 微笑 |
| 眨眼 | 定时/循环 | 一眼前闭合弧 |
| 开心 | 下单成功等 | 双眼上弯 + 张嘴 |
| 专注输入 | 手机号输入框 `focus` | 瞳孔下移 + 抿嘴 |

**动画**（全部 `@media (prefers-reduced-motion: reduce)` 降级为静止）：

| 动画 | 关键帧 |
|---|---|
| 呼吸 | `scale(1) ↔ scale(1.05)`，2.6s |
| 漂浮 | `translateY(0) ↔ -6px`，3.4s |
| 眨眼（可选） | 眼睛组 `scaleY(1) → scaleY(.08)`，4s 周期 |

### 2.3 毛玻璃表单卡片

- 位置：`margin-top: -46px` 上浮，与 Hero 底部重叠
- 样式：`background: rgba(255,255,255,.78)` + `backdrop-filter: blur(16px)` + 圆角 20px + 半透明白描边
- 内容：手机号输入 / 查询码（选填）/「进入下单」主按钮 / 管理员入口
- **降级**：`@supports not (backdrop-filter: blur(1px))` 时退回实心白底 `#fff`（保证老浏览器可用）

---

## 3. 移动端适配

- Hero 全屏沉浸，顶部不叠加独立导航（或导航透明融入 Hero）。
- 刘海屏安全区：`padding-top: env(safe-area-inset-top)`。
- 表单卡片左右留白 14px，触控区 ≥48px。
- 桌面端：居中窄容器（`max-width: 420px`），保留同一视觉，避免拉伸。

---

## 4. 落地实现要点

### 4.1 结构（`index.html` 改造）

```html
<section class="home-hero">
  <div class="hero-glow hero-glow--a"></div>
  <div class="hero-glow hero-glow--b"></div>
  <div class="mascot mascot--float">
    <svg class="mascot-svg mascot--breathe" viewBox="0 0 120 130">…</svg>
  </div>
  <h1 class="hero-title">猕猴桃订购</h1>
  <span class="hero-chip">太白山 · 产地直发</span>
</section>

<section class="glass-card">
  <form>…手机号 / 查询码 / 进入下单…</form>
</section>
```

### 4.2 关键 CSS（追加到 `custom.css`）

```css
.home-hero {
  position: relative;
  background: linear-gradient(180deg, #2E6B47 0%, #3D8B5F 46%, #5C9B70 100%);
  padding: 34px 20px 74px;
  text-align: center;
  overflow: hidden;
}
.hero-glow { position: absolute; border-radius: 50%; }
.hero-glow--a {
  width: 120px; height: 120px; top: 16px; left: -20px;
  background: radial-gradient(circle, rgba(255,255,255,.28), transparent);
}
.hero-glow--b {
  width: 140px; height: 140px; top: 80px; right: -26px;
  background: radial-gradient(circle, rgba(250,200,120,.30), transparent);
}
.hero-chip {
  background: rgba(255,255,255,.18);
  backdrop-filter: blur(8px);
  border: .5px solid rgba(255,255,255,.25);
  color: #F0F7F1; border-radius: 999px; padding: 6px 14px; font-size: 12px;
}
.glass-card {
  margin: -46px 14px 14px;
  background: rgba(255,255,255,.78);
  backdrop-filter: blur(16px);
  border: .5px solid rgba(255,255,255,.6);
  border-radius: 20px; padding: 18px 16px;
}
@supports not (backdrop-filter: blur(1px)) { .glass-card { background: #fff; } }
```

### 4.3 表情彩蛋（`main.js` 增补）

```js
var phone = document.getElementById('phone-input');
if (phone) {
  phone.addEventListener('focus', function () { mascot.set('focus'); });
  phone.addEventListener('blur', function () { mascot.set('normal'); });
}
```

> 吉祥物 SVG 建议直接内联（无图片请求，可随品牌色微调、可做表情切换）。

---

## 5. 落地优先级

| 级别 | 内容 |
|---|---|
| P0 | Hero 渐变 + 吉祥物（呼吸/漂浮）+ 毛玻璃卡片 + 移动端适配 |
| P1 | 表情彩蛋（focus 专注态）+ 眨眼动画 |
| P2 | 副标毛玻璃徽章微调 + 桌面端视觉复核 |

---

**设计版本**：v1.0
**实现状态**：待确认后落地（`index.html` + `custom.css` + `main.js`）
