/* lunar.js — 月相 · 节气 · 问候语 · Agent Harness 调性 */
(function () {
  "use strict";

  /* ===== 月相计算(基于天文朔望月) ===== */
  // 参考新月:2000-01-06 18:14 UTC
  const NEW_MOON_REF = Date.UTC(2000, 0, 6, 18, 14);
  const SYNODIC_MONTH = 29.53059 * 86400000; // 朔望月毫秒数

  // 月相名称(8 阶段)
  const PHASE_NAMES = [
    "新月", "蛾眉月", "上弦月", "盈凸月",
    "满月", "亏凸月", "下弦月", "残月",
  ];

  function moonPhase(date) {
    const t = date.getTime() - NEW_MOON_REF;
    let phase = (t % SYNODIC_MONTH) / SYNODIC_MONTH;
    if (phase < 0) phase += 1;
    return phase; // 0=新月, 0.5=满月
  }

  function moonAge(date) {
    return moonPhase(date) * 29.53;
  }

  function phaseIndex(phase) {
    // 映射到 0-7 八阶段
    const idx = Math.floor((phase + 0.0625) * 8) % 8;
    return idx;
  }

  function moonPhaseName(date) {
    return PHASE_NAMES[phaseIndex(moonPhase(date))];
  }

  // 生成月相 SVG 亮区 path
  function moonLitPath(phase) {
    if (phase < 0.02 || phase > 0.98) return ""; // 新月:无亮区
    if (Math.abs(phase - 0.5) < 0.02) {
      return "M -1,0 A 1,1 0 0,1 1,0 A 1,1 0 0,1 -1,0 Z"; // 满月整圆
    }
    const k = (1 - Math.cos(phase * 2 * Math.PI)) / 2; // 照亮比例 0-1
    const rx = Math.abs(1 - 2 * k);
    const waxing = phase < 0.5;
    const outerSweep = waxing ? 1 : 0;
    // Half-moon (phase ≈ 0.25 or 0.75): rx collapses to 0 and the inner arc
    // degenerates. SVG renderers handle A 0,1 inconsistently, so fall back to
    // a path that closes with a straight line (Z) along the vertical axis.
    // The outer arc still traces the lit semicircle; Z draws the terminator.
    if (rx < 0.001) {
      return `M 0,-1 A 1,1 0 0,${outerSweep} 0,1 Z`;
    }
    const innerSweep = k < 0.5 ? 1 - outerSweep : outerSweep;
    return `M 0,-1 A 1,1 0 0,${outerSweep} 0,1 A ${rx.toFixed(3)},1 0 0,${innerSweep} 0,-1 Z`;
  }

  function moonSVG(date, size) {
    const phase = moonPhase(date);
    const lit = moonLitPath(phase);
    const s = size || 20;
    const uid = "m" + Math.round(phase * 1000);
    // 固定月海/陨石坑（x, y, r, opacity）—— 模拟真实月面纹理
    const craters = [
      [-0.28, -0.18, 0.14, 0.16],
      [0.22, -0.32, 0.09, 0.13],
      [0.08, 0.28, 0.16, 0.15],
      [-0.42, 0.32, 0.08, 0.11],
      [0.38, 0.12, 0.11, 0.14],
      [-0.12, -0.42, 0.07, 0.10],
      [0.45, -0.08, 0.06, 0.12],
    ];
    const craterMarks = craters
      .map(([cx, cy, cr, co]) =>
        `<circle cx="${cx}" cy="${cy}" r="${cr}" fill="#1a1410" opacity="${co}"/>`)
      .join("");
    return `<svg viewBox="-1.12 -1.12 2.24 2.24" width="${s}" height="${s}" aria-hidden="true">
      <defs>
        <radialGradient id="${uid}-lit" cx="36%" cy="30%" r="80%">
          <stop offset="0%" stop-color="#fff8e4"/>
          <stop offset="48%" stop-color="#ece0bc"/>
          <stop offset="82%" stop-color="#a89868"/>
          <stop offset="100%" stop-color="#6b5e3e"/>
        </radialGradient>
        <radialGradient id="${uid}-dark" cx="42%" cy="36%" r="85%">
          <stop offset="0%" stop-color="#3a3d4a"/>
          <stop offset="100%" stop-color="#1a1c24"/>
        </radialGradient>
        <radialGradient id="${uid}-shade" cx="50%" cy="50%" r="50%">
          <stop offset="58%" stop-color="#000" stop-opacity="0"/>
          <stop offset="100%" stop-color="#000" stop-opacity="0.45"/>
        </radialGradient>
        <clipPath id="${uid}-c"><circle r="1"/></clipPath>
      </defs>
      <g clip-path="url(#${uid}-c)">
        <circle r="1" fill="url(#${uid}-dark)" opacity="0.85"/>
        ${lit ? `<path d="${lit}" fill="url(#${uid}-lit)"/>` : ""}
        ${craterMarks}
        <circle r="1" fill="url(#${uid}-shade)"/>
      </g>
      <circle r="1" fill="none" stroke="#9aa0b0" stroke-width="0.04" opacity="0.4"/>
    </svg>`;
  }

  /* ===== 节气(近似公历日期,±1 天精度) ===== */
  const SOLAR_TERMS = [
    [1, 6, "小寒"], [1, 20, "大寒"], [2, 4, "立春"], [2, 19, "雨水"],
    [3, 6, "惊蛰"], [3, 21, "春分"], [4, 5, "清明"], [4, 20, "谷雨"],
    [5, 6, "立夏"], [5, 21, "小满"], [6, 6, "芒种"], [6, 21, "夏至"],
    [7, 7, "小暑"], [7, 23, "大暑"], [8, 8, "立秋"], [8, 23, "处暑"],
    [9, 8, "白露"], [9, 23, "秋分"], [10, 8, "寒露"], [10, 24, "霜降"],
    [11, 7, "立冬"], [11, 22, "小雪"], [12, 7, "大雪"], [12, 22, "冬至"],
  ];

  function getSolarTerm(date) {
    const m = date.getMonth() + 1;
    const d = date.getDate();
    for (const [tm, td, name] of SOLAR_TERMS) {
      if (tm === m && Math.abs(td - d) <= 1) return name;
    }
    return null;
  }

  /* ===== 农历日期近似(基于月龄) ===== */
  function lunarDayLabel(date) {
    const age = moonAge(date);
    let day = Math.round(age) + 1; // 初一 = 月龄 0
    // moonAge is an approximation; clamp to the valid [1, 30] range so rounding
    // noise near the synodic-month boundary cannot produce day 0 or 31+.
    day = Math.min(30, Math.max(1, day));
    if (day === 1) return "初一";
    if (day === 15 || day === 16) return "十五";
    const cn = ["初一","初二","初三","初四","初五","初六","初七","初八","初九","初十",
      "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
      "廿一","廿二","廿三","廿四","廿五","廿六","廿七","廿八","廿九","三十"];
    return cn[day - 1] || `约初${day}`;
  }

  /* ===== 问候语生成(Agent Harness 调性) ===== */
  // 时段判定
  function timeSegment(date) {
    const h = date.getHours();
    if (h >= 5 && h < 10) return "morning";
    if (h >= 10 && h < 13) return "noon";
    if (h >= 13 && h < 17) return "afternoon";
    if (h >= 17 && h < 19) return "dusk";
    if (h >= 19 && h < 23) return "evening";
    return "lateNight";
  }

  // 普通问候语池 — harness 调性:做、推进、编排、计划
  const GREETINGS = {
    morning: [
      { main: "今天<em>做点什么</em>?", sub: "新的一天,从一条指令开始。" },
      { main: "清晨好,有何<em>计划</em>?", sub: "对话编排 · skill 工作流,本地运行。" },
      { main: "新的一天,<em>从哪开始</em>?", sub: "把任务交给编排,你只管发令。" },
    ],
    noon: [
      { main: "正午了,<em>推进什么</em>?", sub: "对话编排 · skill 工作流,本地运行。" },
      { main: "今天的工作流<em>就绪</em>了吗?", sub: "一条指令,多步编排。" },
    ],
    afternoon: [
      { main: "午后,<em>编排点什么</em>?", sub: "把零散任务串成一条流。" },
      { main: "有什么<em>要推进</em>?", sub: "对话编排 · skill 工作流,本地运行。" },
      { main: "下午的<em>任务</em>是什么?", sub: "发令,剩下的交给 harness。" },
    ],
    dusk: [
      { main: "黄昏时分,<em>收尾什么</em>?", sub: "把今天的编排做个了结。" },
      { main: "今天还有<em>什么计划</em>?", sub: "对话编排 · skill 工作流,本地运行。" },
    ],
    evening: [
      { main: "夜晚,<em>做点什么</em>?", sub: "把任务交给编排,你只管发令。" },
      { main: "夜深了,还有<em>什么要推进</em>?", sub: "对话编排 · skill 工作流,本地运行。" },
    ],
    lateNight: [
      { main: "凌晨了,<em>什么任务</em>未眠?", sub: "harness 不眠,随时待命。" },
      { main: "深夜,<em>还在编排</em>?", sub: "把任务交给它,你去休息。" },
    ],
  };

  // 特殊覆盖:节气 / 满月 / 新月 / 周末
  function specialGreeting(date, seg, term, phase) {
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;
    const isFullMoon = Math.abs(phase - 0.5) < 0.04;
    const isNewMoon = phase < 0.04 || phase > 0.96;
    const isCrescent = (phase > 0.06 && phase < 0.18) || (phase > 0.82 && phase < 0.94);

    // 节气优先
    if (term) {
      const subs = {
        morning: `${term}了,新一轮节气开始。`,
        noon: `${term},正午时分。`,
        afternoon: `${term},午后宜编排。`,
        dusk: `${term},黄昏。`,
        evening: `${term}之夜。`,
        lateNight: `${term},深夜未眠。`,
      };
      return {
        main: `${term}了,<em>做点什么</em>?`,
        sub: subs[seg] || `${term},宜开始新的编排。`,
      };
    }

    // 满月
    if (isFullMoon) {
      return {
        main: seg === "evening" || seg === "lateNight"
          ? "今夜<em>满月</em>,有何计划?"
          : "今日<em>满月</em>,做点什么?",
        sub: "圆月当空,适合收尾与复盘。",
      };
    }

    // 新月
    if (isNewMoon) {
      return {
        main: "<em>新月</em>当空,开始新的一轮?",
        sub: "新月宜启程,把计划交给编排。",
      };
    }

    // 弯月(蛾眉/残月)
    if (isCrescent) {
      return {
        main: "<em>弯月</em>斜挂,做点什么?",
        sub: "月牙清浅,宜轻量编排。",
      };
    }

    // 周末
    if (isWeekend && (seg === "morning" || seg === "afternoon")) {
      return {
        main: "周末,<em>做点什么</em>?",
        sub: "把搁置的计划交给 harness。",
      };
    }

    return null;
  }

  function getGreeting(date) {
    const seg = timeSegment(date);
    const term = getSolarTerm(date);
    const phase = moonPhase(date);
    const special = specialGreeting(date, seg, term, phase);
    if (special) return special;
    const pool = GREETINGS[seg] || GREETINGS.morning;
    // 按日期稳定取一条,避免每次刷新都变
    const idx = Math.floor(date.getDate() / 3) % pool.length;
    return pool[idx];
  }

  /* ===== 导出 ===== */
  window.LuminaLunar = {
    moonPhaseName,
    moonSVG,
    getSolarTerm,
    lunarDayLabel,
    getGreeting,
  };
})();
