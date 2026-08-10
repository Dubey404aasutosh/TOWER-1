/* ================================================================
   E-RAKSHAK · app.js v4
   Landing page + full dashboard.
   CrimeOS-matched visual style — orange accent, grid, arcs.
   Zajno-style polygon reveal hero animation.
   ================================================================ */

/* ── ZAJNO HERO REVEAL ANIMATION ────────────────────────────────── */
function initZajnoHero() {
  if (typeof gsap === 'undefined' || typeof CustomEase === 'undefined') return;
  if (!document.querySelector('.zajno-hero')) return;

  CustomEase.create("hop", "M0,0 C0.355,0.022 0.448,0.079 0.5,0.5 C0.542,0.846 0.615,1 1,1");

  function splitTextIntoSpans(selector) {
    const element = document.querySelector(selector);
    if (!element) return;
    const text = element.innerText;
    element.innerHTML = text
      .split("")
      .map((char) => `<span>${char === " " ? "&nbsp;" : char}</span>`)
      .join("");
  }

  splitTextIntoSpans(".zajno-title");

  function revealLandingPage() {
    // Title letters stagger in
    gsap.to(".zajno-title span", {
      y: 0,
      stagger: 0.08,
      duration: 1.5,
      ease: "power4.inOut",
      delay: 0.3,
      onComplete: () => {
        initTextCursorProximity();
      }
    });

    // Fade in the bottom bar (subtitle + CTA)
    gsap.to(".zajno-hero-bottom", {
      opacity: 1,
      duration: 1,
      ease: "power2.out",
      delay: 1.2,
    });
  }

  revealLandingPage();
}

/* ── TEXT CURSOR PROXIMITY ANIMATION ──────────────────────────────── */
function initTextCursorProximity() {
  const titleHeader = document.querySelector('.zajno-header');
  const letterSpans = document.querySelectorAll('.zajno-title span');
  if (!titleHeader || !letterSpans.length) return;

  let mouseX = -9999;
  let mouseY = -9999;

  window.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  const radius = 280; // Proximity radius in px
  const lerpFactor = 0.12; // Faster response, still smooth

  // Per-letter smoothed proximity values
  const smoothProximity = new Array(letterSpans.length).fill(0);

  function calculateDistance(x1, y1, x2, y2) {
    return Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
  }

  function calculateGaussianFalloff(distance) {
    if (distance >= radius) return 0;
    return Math.exp(-Math.pow(distance / (radius / 2), 2) / 2);
  }

  function animateProximity() {
    letterSpans.forEach((span, i) => {
      const rect = span.getBoundingClientRect();
      const letterCenterX = rect.left + rect.width / 2;
      const letterCenterY = rect.top + rect.height / 2;

      const distance = calculateDistance(mouseX, mouseY, letterCenterX, letterCenterY);
      const targetProximity = calculateGaussianFalloff(distance);

      // Lerp toward target for silky smooth easing
      smoothProximity[i] += (targetProximity - smoothProximity[i]) * lerpFactor;
      const p = smoothProximity[i];

      // Scale: 1 -> 1.28
      const scale = 1 + p * 0.28;

      // Lift: 0 -> -14px
      const translateY = -14 * p;

      span.style.transform = `translate3d(0, ${translateY}px, 0) scale(${scale})`;
      span.style.color = '';
      span.style.textShadow = 'none';
    });

    requestAnimationFrame(animateProximity);
  }

  requestAnimationFrame(animateProximity);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initZajnoHero);
} else {
  initZajnoHero();
}
/* ── LENIS SMOOTH SCROLL ENGINE ──────────────────────────────────── */
let lenisInstance = null;
function initLenisSmoothScroll() {
  if (!document.getElementById('landing-page')) return;
  if (typeof Lenis === 'undefined') return;

  lenisInstance = new Lenis({
    duration: 1.2,
    easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    smoothWheel: true,
    smoothTouch: false,
    wheelMultiplier: 1.0,
    touchMultiplier: 1.5,
  });

  function raf(time) {
    lenisInstance.raf(time);
    requestAnimationFrame(raf);
  }

  requestAnimationFrame(raf);

  lenisInstance.on('scroll', () => {
    if (typeof window.updateShowcaseScroll === 'function') {
      window.updateShowcaseScroll();
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initLenisSmoothScroll);
} else {
  initLenisSmoothScroll();
}

/* ── HAPPLY STICKY SHOWCASE SCROLL ENGINE ───────────────────────── */
function initShowcaseScroll() {
  const showcaseTrack = document.getElementById("how-it-works");
  if (!showcaseTrack) return;

  const slides = Array.from(showcaseTrack.querySelectorAll(".b-showcase__li"));
  if (!slides.length) return;

  const topbars = slides.map(slide => slide.querySelector(".b-showcase__item__topbar"));

  const totalSlides = slides.length;
  const transitionsCount = totalSlides - 1;
  const topbarHeight = 58;

  let ticking = false;

  function updateScrollAnimation() {
    const windowH = window.innerHeight;
    const showcaseRect = showcaseTrack.getBoundingClientRect();
    const showcaseOffsetTop = window.scrollY + showcaseRect.top;

    const slideDistance = windowH;

    slides.forEach((slide, idx) => {
      if (idx < transitionsCount) {
        const startY = showcaseOffsetTop + idx * slideDistance - topbarHeight;

        let p = (window.scrollY - startY) / slideDistance;
        p = Math.max(0, Math.min(1, p));

        // 1. Crop outgoing slide from bottom to top
        const clipPercent = p * 100;
        slide.style.clipPath = `inset(0% 0% ${clipPercent}% 0%)`;

        // 2. Translate incoming topbar from bottom edge to top edge
        const nextTopbar = topbars[idx + 1];
        if (nextTopbar) {
          const translateY = (1 - p) * (windowH - topbarHeight);
          nextTopbar.style.transform = `translate3d(0, ${translateY}px, 0)`;
        }
      }
    });

    ticking = false;
  }

  window.updateShowcaseScroll = updateScrollAnimation;

  function onScroll() {
    if (!ticking) {
      requestAnimationFrame(updateScrollAnimation);
      ticking = true;
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", updateScrollAnimation);

  updateScrollAnimation();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initShowcaseScroll);
} else {
  initShowcaseScroll();
}

/* ── STAGGERED DUAL SWEEP SVG PAGE TRANSITION ────────────────────── */
const SWEEP_CONFIG = {
  bgStrokeColor: '#F4CABB',    // Soft pastel peach background wave
  fgStrokeColor: '#2ECC71',    // Neon emerald green foreground wave
  maxStrokeWidth: 350,        // Stroke thickness to block out screen
  drawDuration: 0.8,          // Sweep-in duration
  fadeDuration: 0.3,          // Base background overlay fade time
  stagger: 0.12,              // Delay between background and foreground sweeps
};

let isSweepAnimating = false;

function playDualSweepTransition(onMidpoint) {
  if (typeof gsap === 'undefined' || isSweepAnimating) {
    if (typeof onMidpoint === 'function') onMidpoint();
    return;
  }

  let overlay = document.getElementById('dual-sweep-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'dual-sweep-overlay';
    overlay.className = 'sweep-overlay';
    overlay.innerHTML = `
      <svg width="100%" height="100%" viewBox="0 0 1316 664" fill="none" xmlns="http://www.w3.org/2000/svg" class="sweep-svg" preserveAspectRatio="xMidYMid slice">
        <path id="sweep-path-bg" d="M13.4746 291.27C13.4746 291.27 100.646 -18.6724 255.617 16.8418C410.588 52.356 61.0296 431.197 233.017 546.326C431.659 679.299 444.494 21.0125 652.73 100.784C860.967 180.556 468.663 430.709 617.216 546.326C765.769 661.944 819.097 48.2722 988.501 120.156C1174.21 198.957 809.424 543.841 988.501 636.726C1189.37 740.915 1301.67 149.213 1301.67 149.213" stroke="${SWEEP_CONFIG.bgStrokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path id="sweep-path-fg" d="M13.4746 291.27C13.4746 291.27 100.646 -18.6724 255.617 16.8418C410.588 52.356 61.0296 431.197 233.017 546.326C431.659 679.299 444.494 21.0125 652.73 100.784C860.967 180.556 468.663 430.709 617.216 546.326C765.769 661.944 819.097 48.2722 988.501 120.156C1174.21 198.957 809.424 543.841 988.501 636.726C1189.37 740.915 1301.67 149.213 1301.67 149.213" stroke="${SWEEP_CONFIG.fgStrokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>`;
    document.body.appendChild(overlay);
  }

  const p1 = overlay.querySelector('#sweep-path-bg');
  const p2 = overlay.querySelector('#sweep-path-fg');

  if (!p1 || !p2) {
    if (typeof onMidpoint === 'function') onMidpoint();
    return;
  }

  isSweepAnimating = true;
  const len = p1.getTotalLength();

  gsap.set([p1, p2], {
    strokeDasharray: len,
    strokeDashoffset: len,
    strokeWidth: 2,
  });

  const tl = gsap.timeline({
    onComplete: () => {
      isSweepAnimating = false;
    }
  });

  // 1. Leave: Backdrop fade & sweep in
  tl.to(overlay, {
    opacity: 1,
    duration: SWEEP_CONFIG.fadeDuration,
    ease: 'power2.inOut',
  })
  .to(p1, {
    strokeDashoffset: 0,
    strokeWidth: SWEEP_CONFIG.maxStrokeWidth,
    duration: SWEEP_CONFIG.drawDuration,
    ease: 'power2.inOut',
  }, 0)
  .to(p2, {
    strokeDashoffset: 0,
    strokeWidth: SWEEP_CONFIG.maxStrokeWidth - 50,
    duration: SWEEP_CONFIG.drawDuration,
    ease: 'power2.inOut',
    onComplete: () => {
      if (typeof onMidpoint === 'function') {
        onMidpoint();
      }
    }
  }, SWEEP_CONFIG.stagger)
  // 2. Enter: Sweep paths out & fade overlay
  .to(p1, {
    strokeDashoffset: -len,
    strokeWidth: 2,
    duration: 0.9,
    ease: 'power3.out',
  })
  .to(p2, {
    strokeDashoffset: -len,
    strokeWidth: 2,
    duration: 0.9,
    ease: 'power3.out',
  }, `-=${0.9 - SWEEP_CONFIG.stagger}`)
  .to(overlay, {
    opacity: 0,
    duration: 0.6,
    ease: 'power2.out',
  }, '<')
  .set([p1, p2], {
    strokeDashoffset: len,
    strokeWidth: 2,
  });
}

/* ── LANDING / DASHBOARD PAGE ROUTING ────────────────────────────── */
function enterDashboard(targetView) {
  const view = targetView || 'dashboard';
  const app = document.getElementById('app-shell');
  if (app) {
    playDualSweepTransition(() => {
      switchView(view);
    });
  } else {
    playDualSweepTransition(() => {
      window.location.href = `dashboard#${view}`;
    });
  }
}

function exitDashboard() {
  const landing = document.getElementById('landing-page');
  if (landing) {
    playDualSweepTransition(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      if (history.pushState) history.pushState(null, null, window.location.pathname);
    });
  } else {
    playDualSweepTransition(() => {
      window.location.href = '/';
    });
  }
}

/* ── HASH ROUTING & ANCHOR NAVIGATION ───────────────────────────── */
const DASHBOARD_VIEWS = ['dashboard', 'upload', 'cases', 'poi', 'evidence', 'reports', 'timeline', 'network', 'map', 'settings'];

function handleHashRouting() {
  const rawHash = window.location.hash.replace('#', '').trim();
  if (!rawHash) return;

  const app = document.getElementById('app-shell');
  if (app) {
    if (DASHBOARD_VIEWS.includes(rawHash)) {
      switchView(rawHash);
    }
  } else {
    if (DASHBOARD_VIEWS.includes(rawHash)) {
      window.location.href = `dashboard#${rawHash}`;
    } else {
      scrollToSection(rawHash);
    }
  }
}

function scrollToSection(sectionId) {
  const target = document.getElementById(sectionId);
  if (!target) return;
  if (typeof lenisInstance !== 'undefined' && lenisInstance) {
    lenisInstance.scrollTo(target);
  } else {
    target.scrollIntoView({ behavior: 'smooth' });
  }
}

function initAnchorClickHandlers() {
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    if (a._hashWired) return;
    a._hashWired = true;
    a.addEventListener('click', e => {
      const href = a.getAttribute('href');
      if (!href || href === '#') return;
      e.preventDefault();
      const targetId = href.replace('#', '').trim();
      if (!targetId) return;

      if (DASHBOARD_VIEWS.includes(targetId)) {
        enterDashboard(targetId);
      } else {
        const landing = document.getElementById('landing-page');
        if (landing) {
          scrollToSection(targetId);
        } else {
          window.location.href = `/#${targetId}`;
        }
      }
    });
  });
}

/* ── WORKFLOW STEP SWITCHING (landing) ──────────────────────────── */
function initWorkflowSteps() {
  const steps = document.querySelectorAll('.wf-step');
  if (!steps.length) return;
  steps.forEach(step => {
    step.addEventListener('click', () => {
      // deactivate all
      steps.forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.wf-panel').forEach(p => p.classList.remove('active'));
      // activate clicked
      step.classList.add('active');
      const panelId = step.getAttribute('data-panel');
      const panel = document.getElementById(panelId);
      if (panel) panel.classList.add('active');
    });
  });

  // auto-cycle every 3s
  let idx = 0;
  setInterval(() => {
    if (document.getElementById('landing-page').style.display === 'none') return;
    idx = (idx + 1) % steps.length;
    steps.forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.wf-panel').forEach(p => p.classList.remove('active'));
    steps[idx].classList.add('active');
    const panelId = steps[idx].getAttribute('data-panel');
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
  }, 3200);
}

/* ── THEME MANAGEMENT ────────────────────────────────────────────── */
function initTheme() {
  const saved = localStorage.getItem('erakhsak_theme') || 'dark';
  setTheme(saved);
}

function setTheme(theme) {
  const appShell = document.getElementById('app-shell');
  if (theme === 'light') {
    if (appShell) appShell.setAttribute('data-theme', 'light');
    document.documentElement.setAttribute('data-theme', 'light');
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.innerHTML = '<i class="fa-solid fa-moon"></i>';
    const settingsToggle = document.getElementById('theme-switch-checkbox');
    if (settingsToggle) settingsToggle.checked = true;
    const label = document.getElementById('theme-mode-label');
    if (label) label.textContent = 'Light Mode';
    localStorage.setItem('erakhsak_theme', 'light');
  } else {
    if (appShell) appShell.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-theme');
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.innerHTML = '<i class="fa-solid fa-sun"></i>';
    const settingsToggle = document.getElementById('theme-switch-checkbox');
    if (settingsToggle) settingsToggle.checked = false;
    const label = document.getElementById('theme-mode-label');
    if (label) label.textContent = 'Dark Mode';
    localStorage.setItem('erakhsak_theme', 'dark');
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  setTheme(current === 'light' ? 'dark' : 'light');
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();

  const isDashboardPage = !!document.getElementById('app-shell');
  const isLandingPage = !!document.getElementById('landing-page');

  if (isDashboardPage) {
    initDashboardOnce();
    animateKPICounters();
    populateDashboard();
    populateCaseTable();
    populatePOI();
    populateEvidence();
    populateReports();
    populateRuleGrid();
    populatePalette();
    fetchAPIStatus();
    initKBShortcuts();

    const initialHash = window.location.hash.replace('#', '').trim();
    if (DASHBOARD_VIEWS.includes(initialHash)) {
      switchView(initialHash);
    } else {
      switchView('dashboard');
    }
  }

  if (isLandingPage) {
    initWorkflowSteps();
    initKBShortcuts();
    initAnchorClickHandlers();
    setTimeout(handleHashRouting, 150);
  }
});

window.addEventListener('hashchange', handleHashRouting);

'use strict';

/* ── API CONFIG ─────────────────────────────────────────────────── */
const API_BASE = window.location.origin;

/* ── APP STATE ──────────────────────────────────────────────────── */
const appState = {
  currentView: 'dashboard',
  copilotOpen: false,
  slideOverOpen: false,
  paletteOpen: false,
  dataMode: 'demo',
  results: null,
  currentCase: null,
  networkInstance: null,
  mapInstance: null,
  rawNetworkNodes: [],
  rawNetworkEdges: [],
};

/* ── MOCK DATA ──────────────────────────────────────────────────── */
const MOCK_CASES = [
  { id: 'CASE-2026-00412', title: 'Financial Fraud Network — Surat', status: 'critical', risk: 94, officer: 'SP Mehta', lastActivity: '12 min ago', entities: 7, rules: ['MUL-1', 'TCS-1', 'IDR-1'] },
  { id: 'CASE-2026-00389', title: 'Cyber Extortion Ring', status: 'escalated', risk: 82, officer: 'SP Mehta', lastActivity: '30 min ago', entities: 9, rules: ['TCS-1', 'TCS-2'] },
  { id: 'CASE-2026-00371', title: 'Money Mule Network — Surat East', status: 'active', risk: 71, officer: 'DI Sharma', lastActivity: '1h ago', entities: 3, rules: ['TCS-1', 'TCS-2'] },
  { id: 'CASE-2026-00344', title: 'UPI Passthrough Cluster', status: 'active', risk: 68, officer: 'SI Patel', lastActivity: '3h ago', entities: 12, rules: ['MUL-1'] },
  { id: 'CASE-2026-00321', title: 'UPI Fraud Cluster — Adajan', status: 'review', risk: 45, officer: 'DI Gupta', lastActivity: '1d ago', entities: 5, rules: ['STR-1'] },
  { id: 'CASE-2026-00298', title: 'IMEI Spoofing Operation', status: 'review', risk: 38, officer: 'SI Kumar', lastActivity: '2d ago', entities: 2, rules: ['IDR-1'] },
  { id: 'CASE-2026-00276', title: 'Bank Account Takeover Ring', status: 'closed', risk: 15, officer: 'DI Sharma', lastActivity: '5d ago', entities: 4, rules: [] },
  { id: 'CASE-2026-00251', title: 'Dark Web Asset Recovery', status: 'archived', risk: 0, officer: 'SI Patel', lastActivity: '2w ago', entities: 6, rules: [] },
];

/* Persons of Interest are filled from /api/results (rule-flagged entities only).
   The former hardcoded roster invented names, account numbers and risk
   percentages for entities the engine had never scored. */
const MOCK_POIS = [];
let POI_SUPPRESSED_LOW = 0;

/* Evidence files are NEVER mocked. This array is filled only from
   GET /api/evidence-files, where every size, row count and SHA-256 digest is
   measured server-side by hashlib. If the backend is unreachable the vault
   renders an explicit empty state instead of placeholder data. */
let EVIDENCE_FILES = [];

/* Filled from GET /api/download-trace — the actual decision_trace.jsonl the rule
   engine wrote this run, with its real explanations and evidence row refs. */
let DECISION_TRACE = [];

/* One entry per entity the engine actually escalated to HIGH/CRITICAL — the exact
   set the backend will build a report for. This replaced a hardcoded list whose
   case numbers, "23 Jul 2026" dates and "SEALED" statuses were all invented, whose
   tiers contradicted the engine (it called ENT-0042 HIGH; it is CRITICAL), and
   whose download links pointed at "ENT-0..." ids that 404 against an API keyed on
   "ENT_0...". Populated by fetchRealResults(). */
let REPORTS = [];

/* Pipeline Activity is derived from the current run (see buildActivityFeed).
   It used to be a hardcoded list that announced a CRITICAL entity and rule
   firings the engine had not produced — it now cannot contradict the KPI tiles
   because both read the same response. */
let ACTIVITY_FEED = [];

/* Static rule metadata only (ids + human names). Fired/not-fired is never
   asserted here — it comes from data.rule_firings on the live run. */
const RULE_CATALOG = [
  { id: 'IDR-1', name: 'Identity Fan-out' },
  { id: 'TCS-1', name: 'Temporal Coincidence' },
  { id: 'TCS-2', name: 'Pre-Transfer Call' },
  { id: 'STR-1', name: 'Structuring' },
  { id: 'LAY-1', name: 'Layering Chain' },
  { id: 'MUL-1', name: 'Mule Signature' },
  { id: 'LOC-1', name: 'Location Mismatch' },
];

const COPILOT_RESPONSES = [
  "Based on the current ingested data, ENT-0037 shows the strongest conviction signal: MUL-1 + TCS-1 + IDR-1 all fired. The account received ₹2.4L after 30 days dormancy, then 94% left within 8 hours. The 1-IMEI-to-3-phones linkage confirms identity fan-out.",
  "The STR-1 rule on ENT-0041 (Yashica Issac) shows 4 outgoing transfers clustered at ₹49,800–₹49,950 within 36 hours — a classic structuring pattern to stay below the ₹50,000 reporting threshold.",
  "The pipeline ran 7 deterministic forensic rules, generating 13 firings across 10 entities. No AI blending was applied — each risk designation is directly traceable to named rule logic and raw source row indices.",
  "LOC-1 on ENT-0045 (Wriddhish Bhardwaj) was triggered because the SIM was KYC-registered in Ahmedabad, but all CDR records show active cell towers in Surat. This spatial mismatch is logged in decision_trace.jsonl.",
  "To generate a Section 65B admissible report for ENT-0037, the forensic package includes: identity summary, exact rule firing explanations, direct evidence table rows, and the SHA-256 hash chain from ingestion to analysis.",
];

/* ── INIT (called inside enterDashboard) ────────────────────────── */
function initDashboardOnce() {
  if (window._dashInited) return;
  window._dashInited = true;
  initNavigation();
  initUploadZone();
  initModeToggle();
  initFilterBtns();
}

/* ── VIEW SWITCHING ─────────────────────────────────────────────── */
function switchView(viewId, navEl) {
  const targetId = viewId || 'dashboard';
  const app = document.getElementById('app-shell');

  if (!app) {
    window.location.href = `dashboard#${targetId}`;
    return;
  }

  // Deactivate all views and sidebar nav items
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  // Activate target view
  const view = document.getElementById(`view-${targetId}`);
  if (view) {
    view.classList.add('active');
  } else {
    const dashView = document.getElementById('view-dashboard');
    if (dashView) dashView.classList.add('active');
  }

  if (navEl) {
    navEl.classList.add('active');
  } else {
    const navItem = document.querySelector(`[data-view="${targetId}"]`);
    if (navItem) navItem.classList.add('active');
  }

  appState.currentView = targetId;

  if (window.location.hash !== `#${targetId}`) {
    if (history.pushState) {
      history.pushState(null, null, `#${targetId}`);
    } else {
      window.location.hash = targetId;
    }
  }

  // Lazy-init heavy views
  if (targetId === 'network') { setTimeout(initNetwork, 100); }
  // The timeline measures its own SVG width, so it can only be laid out once its
  // view is actually visible — same reason the network graph is built here.
  if (targetId === 'timeline') { setTimeout(initTimeline, 80); }
  if (targetId === 'map') { setTimeout(() => { if (appState.mapInstance) appState.mapInstance.invalidateSize(); }, 200); }
}

/* ── KPI COUNTERS ───────────────────────────────────────────────── */
/* Fills every supporting line on the KPI tiles from the live metrics object,
   so nothing on the tile survives a dataset swap unchanged. */
function updateKPIContext(m) {
  if (!m) return;
  const n = v => (v == null ? '—' : Number(v).toLocaleString());
  const set = (id, html) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  };

  set('kpi-entities-chip', `<i class="fa-solid fa-fingerprint"></i> ${n(m.kyc_anchored_entities)} KYC-anchored`);
  set('kpi-entities-sub', `From ${n(m.total_events)} Bank + CDR + IPDR events`);

  set('kpi-cases-chip', `<i class="fa-solid fa-gavel"></i> ${n(m.total_rule_firings)} rule firings`);
  set('kpi-cases-sub', `CRITICAL + HIGH + MEDIUM tiers · ${n(m.rules_fired_count)} of 7 rules fired`);

  const critEl = document.getElementById('kpi-critical-chip');
  if (critEl) critEl.className = m.critical_count > 0 ? 'kpi-trend danger' : 'kpi-trend';
  set('kpi-critical-chip', `<i class="fa-solid fa-triangle-exclamation"></i> ${n(m.critical_count)} CRITICAL`);
  set('kpi-critical-sub', `${n(m.critical_count)} CRITICAL · ${n(m.high_count)} HIGH — rule-gated tiers`);

  set('kpi-resolved-chip', `<i class="fa-solid fa-robot"></i> unsupervised`);
  set('kpi-resolved-sub', `IsolationForest · advisory flag, not a risk tier`);
}

function animateKPICounters() {
  document.querySelectorAll('[data-target]').forEach(el => {
    const target = parseInt(el.getAttribute('data-target'), 10);
    const duration = 900;
    const startTime = performance.now();

    function update(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(eased * target).toLocaleString();
      if (progress < 1) requestAnimationFrame(update);
      else el.textContent = target.toLocaleString();
    }
    requestAnimationFrame(update);
  });
}

/* ── DASHBOARD POPULATION ───────────────────────────────────────── */
function populateDashboard() {
  // Recent cases (top 5)
  const tbody = document.getElementById('dash-case-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  MOCK_CASES.slice(0, 5).forEach(c => {
    const tr = document.createElement('tr');
    tr.onclick = () => openSlideOver(c.id);
    tr.innerHTML = `
      <td class="case-id-cell">${c.id}</td>
      <td class="case-title-cell">${c.title}</td>
      <td>${statusBadge(c.status)}</td>
      <td>${riskBar(c.risk)}</td>
      <td style="color:var(--text-muted);font-size:12px;">${c.officer}</td>
    `;
    tbody.appendChild(tr);
  });

  // Activity feed
  const feed = document.getElementById('activity-feed');
  if (!feed) return;
  feed.innerHTML = '';
  if (!ACTIVITY_FEED.length) {
    feed.innerHTML = `<div class="tl-entry"><span class="tl-dot muted"></span><div class="tl-body">
      <div class="tl-action">No pipeline run in this session yet — activity is generated from the live run, not stored.</div>
      <div class="tl-time">idle</div></div></div>`;
    return;
  }
  ACTIVITY_FEED.forEach((a, i) => {
    const div = document.createElement('div');
    div.className = 'tl-entry';
    div.style.animationDelay = `${i * 60}ms`;
    div.innerHTML = `
      <span class="tl-dot ${a.type}"></span>
      <div class="tl-body">
        <div class="tl-action">${a.action}</div>
        <div class="tl-time">${a.time}</div>
      </div>
    `;
    feed.appendChild(div);
  });
}

/* Builds the Pipeline Activity feed out of the run that is actually loaded.
   Every line is traceable to a field in /api/results — no invented events,
   no invented "12 min ago" timings. */
function buildActivityFeed(data) {
  const m = data.metrics || {};
  const suspects = data.suspects || [];
  const firings = data.rule_firings || {};
  const items = [];

  const tierDot = { CRITICAL: 'red', HIGH: 'warn', MEDIUM: 'blue' };
  suspects
    .filter(s => ['CRITICAL', 'HIGH', 'MEDIUM'].includes(s.risk_tier) && (s.rules_fired || []).length)
    .slice(0, 6)
    .forEach(s => {
      items.push({
        type: tierDot[s.risk_tier] || 'muted',
        action: `<strong>${s.risk_tier}</strong> — ${s.entity_id}${s.name && s.name !== 'Unknown' ? ` (${s.name})` : ''} · ${s.rules_fired.join(' + ')} fired.`,
        time: 'this run',
      });
    });

  const firedList = Object.entries(firings).sort((a, b) => b[1] - a[1])
    .map(([r, c]) => `${r}×${c}`).join(', ');
  items.push({
    type: 'blue',
    action: `Rule engine — <strong>${(m.total_rule_firings || 0).toLocaleString()} firings</strong> across ${m.rules_fired_count || 0} of 7 rules${firedList ? ` (${firedList})` : ''}.`,
    time: 'this run',
  });
  items.push({
    type: 'blue',
    action: `Entity resolution — <strong>${(m.total_entities || 0).toLocaleString()} entities</strong> resolved from ${(m.total_events || 0).toLocaleString()} events (${(m.kyc_anchored_entities || 0).toLocaleString()} KYC-anchored).`,
    time: 'this run',
  });
  items.push({
    type: m.ml_anomalies ? 'green' : 'muted',
    action: `IsolationForest — <strong>${(m.ml_anomalies || 0).toLocaleString()} anomaly flags</strong> raised (advisory, not a risk tier).`,
    time: 'this run',
  });

  ACTIVITY_FEED = items;
}

/* ruleFirings: { "TCS-1": 12, ... } from the live run. Cached so re-renders
   triggered by view switches keep the real state. */
let RULE_FIRINGS = null;

function populateRuleGrid(ruleFirings) {
  if (ruleFirings) RULE_FIRINGS = ruleFirings;
  const grid = document.getElementById('rule-grid');
  if (!grid) return;
  const counts = RULE_FIRINGS;
  grid.innerHTML = RULE_CATALOG.map(r => {
    if (!counts) {
      return `
    <div class="rule-card">
      <span class="rule-card-id">${r.id}</span>
      <span class="rule-card-name">${r.name}</span>
      <span class="rule-dot clear" title="Awaiting pipeline run"></span>
    </div>`;
    }
    const n = counts[r.id] || 0;
    return `
    <div class="rule-card ${n > 0 ? 'fired' : ''}" title="${n > 0 ? `${n} entity firing(s) in the current run` : 'Did not fire on the current dataset'}">
      <span class="rule-card-id">${r.id}</span>
      <span class="rule-card-name">${r.name}${n > 0 ? ` · ${n}` : ''}</span>
      <span class="rule-dot ${n > 0 ? 'fired' : 'clear'}"></span>
    </div>`;
  }).join('');
}

/* ── CASE TABLE ─────────────────────────────────────────────────── */
function populateCaseTable() {
  renderCaseTable(MOCK_CASES);
  updateCaseCount(MOCK_CASES.length);
}

function renderCaseTable(cases) {
  const tbody = document.getElementById('full-case-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  cases.forEach(c => {
    const tr = document.createElement('tr');
    tr.onclick = () => openSlideOver(c.id);
    tr.innerHTML = `
      <td class="case-id-cell">${c.id}</td>
      <td class="case-title-cell" style="max-width:200px;">${c.title}</td>
      <td>${statusBadge(c.status)}</td>
      <td>${riskBar(c.risk)}</td>
      <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--text-muted);">${c.entities}</td>
      <td style="color:var(--text-muted);font-size:12px;">${c.officer}</td>
      <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">${c.lastActivity}</td>
      <td><button class="btn btn-ghost btn-xs" onclick="event.stopPropagation();openSlideOver('${c.id}')">Open <i class="fa-solid fa-arrow-right" style="font-size:10px;"></i></button></td>
    `;
    tbody.appendChild(tr);
  });
}

function updateCaseCount(n) {
  const el = document.getElementById('case-count');
  if (el) el.textContent = `${n} case${n !== 1 ? 's' : ''}`;
}

function filterCaseTable(query) {
  const q = query.toLowerCase().trim();
  const filtered = q ? MOCK_CASES.filter(c =>
    c.id.toLowerCase().includes(q) ||
    c.title.toLowerCase().includes(q) ||
    c.officer.toLowerCase().includes(q) ||
    c.status.toLowerCase().includes(q)
  ) : MOCK_CASES;
  renderCaseTable(filtered);
  updateCaseCount(filtered.length);
}

/* ── FILTER BUTTONS ─────────────────────────────────────────────── */
function initFilterBtns() {
  const group = document.getElementById('case-filters');
  if (!group) return;
  group.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const f = btn.getAttribute('data-filter');
      const filtered = f === 'all' ? MOCK_CASES : MOCK_CASES.filter(c => c.status === f);
      renderCaseTable(filtered);
      updateCaseCount(filtered.length);
    });
  });
}

/* ── POI GRID ───────────────────────────────────────────────────── */
function populatePOI() {
  const grid = document.getElementById('poi-grid');
  if (!grid) return;
  if (!MOCK_POIS.length) {
    grid.innerHTML = `<div style="padding:26px;color:var(--text-muted);font-size:13px;">
      No rule-flagged entities loaded yet — the list is built from the current pipeline run.</div>`;
    return;
  }
  grid.innerHTML = MOCK_POIS.map(p => {
    const riskClass = ['CRITICAL', 'HIGH'].includes(p.tier) ? 'high' : p.tier === 'MEDIUM' ? 'medium' : 'low';
    const identChips = p.phones.slice(0, 1).map(x => `<span class="ident-chip"><i class="fa-solid fa-phone" style="font-size:9px;color:var(--accent-primary);"></i> ${x}</span>`).join('') +
      p.accounts.slice(0, 1).map(x => `<span class="ident-chip"><i class="fa-solid fa-building-columns" style="font-size:9px;color:#a78bfa;"></i> ${x}</span>`).join('');
    const ruleChips = p.rules.map(r => `<span class="rule-chip">${r}</span>`).join('');
    return `
      <div class="poi-card ${riskClass === 'high' ? 'critical' : ''}" onclick="openSlideOver('${p.cases[0]}')">
        <div class="poi-header">
          <div style="display:flex;gap:12px;align-items:center;">
            <div class="poi-avatar"><i class="fa-solid fa-user-secret"></i></div>
            <div>
              <div class="poi-name">${p.name}</div>
              <div class="poi-alias">${p.alias}</div>
            </div>
          </div>
          ${statusBadge(p.tier.toLowerCase() === 'critical' ? 'critical' : p.tier.toLowerCase() === 'high' ? 'escalated' : 'review')}
        </div>
        <div class="poi-risk-row">
          <div>
            <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Risk Tier</div>
            <div class="poi-risk-score ${riskClass}" style="font-size:17px;" title="Rule-gated tier — the engine assigns tiers, not numeric scores">${p.risk != null ? p.risk + '%' : p.tier}</div>
            <div style="font-size:10px;color:var(--text-muted);margin-top:2px;">${p.rules.length} rule${p.rules.length === 1 ? '' : 's'} fired${p.mlAnomaly ? ' · ML flag' : ''}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Entity ID</div>
            <div style="font-family:var(--font-mono);font-size:12px;color:var(--accent-primary);">${p.id}</div>
          </div>
        </div>
        <div class="poi-idents">${identChips}</div>
        ${ruleChips ? `<div class="poi-rules">${ruleChips}</div>` : ''}
        <div class="poi-actions" onclick="event.stopPropagation();">
          <button class="btn btn-ghost btn-sm" onclick="downloadForensicReport('${p.id}')" title="Full Sec 65B forensic investigation report">
            <i class="fa-solid fa-file-word"></i> Forensic Report
          </button>
          <button class="btn btn-primary btn-sm" onclick="downloadSTRReport('${p.id}')" title="FIU-IND format Suspicious Transaction Report">
            <i class="fa-solid fa-triangle-exclamation"></i> Generate STR
          </button>
        </div>
      </div>
    `;
  }).join('');

  if (POI_SUPPRESSED_LOW > 0) {
    grid.insertAdjacentHTML('beforeend', `
      <div style="grid-column:1/-1;padding:12px 4px;color:var(--text-muted);font-size:12px;">
        Showing ${MOCK_POIS.length} rule-flagged entit${MOCK_POIS.length === 1 ? 'y' : 'ies'} ·
        ${POI_SUPPRESSED_LOW.toLocaleString()} LOW-tier entities (no rule fired) are not listed.
      </div>`);
  }
}

/* ── STR / FORENSIC REPORT EXPORTS ─────────────────────────────── */
function downloadForensicReport(entityId) {
  window.open(`${API_BASE}/api/download-report/${entityId}`, '_blank');
}

function downloadSTRReport(entityId) {
  window.open(`${API_BASE}/api/download-str-report/${entityId}`, '_blank');
}

/* ── EVIDENCE & TRACE ───────────────────────────────────────────── */
function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '— bytes';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function fileIconClass(ext) {
  if (ext === 'xlsx' || ext === 'xls') return 'fa-file-excel';
  if (ext === 'pdf') return 'fa-file-pdf';
  if (ext === 'csv') return 'fa-file-csv';
  return 'fa-file-lines';
}

/* Pulls the real chain-of-custody listing (hashlib SHA-256, true row counts). */
async function fetchEvidenceFiles() {
  try {
    const res = await fetch(`${API_BASE}/api/evidence-files`, { signal: AbortSignal.timeout(15000) });
    if (!res.ok) return;
    const data = await res.json();
    EVIDENCE_FILES = data.files || [];
    populateEvidence();
  } catch (e) {
    console.warn('fetchEvidenceFiles err:', e);
  }
}

function populateEvidence() {
  const evList = document.getElementById('evidence-list');
  if (evList) {
    if (!EVIDENCE_FILES.length) {
      evList.innerHTML = `
        <div class="evidence-empty" style="padding:22px;text-align:center;color:var(--text-muted);font-size:13px;">
          <i class="fa-solid fa-folder-open" style="display:block;font-size:20px;margin-bottom:8px;opacity:0.5;"></i>
          No ingested evidence files. Start the backend and run the pipeline —
          digests are computed at ingest and shown here, never pre-filled.
        </div>`;
    } else {
      evList.innerHTML = EVIDENCE_FILES.map(e => {
        const ext = (e.extension || '').toLowerCase();
        const rows = e.rows_parsed != null
          ? `${Number(e.rows_parsed).toLocaleString()} rows parsed` +
            (e.rows_skipped ? ` · <span style="color:var(--orange);">${Number(e.rows_skipped).toLocaleString()} skipped</span>` : '')
          : (e.status === 'REFERENCE' ? 'reference input · used by entity resolution' : 'not yet ingested');
        const digest = e.sha256
          ? `<div class="ev-hash" title="SHA-256 (hashlib): ${e.sha256}">SHA-256: ${e.sha256.slice(0, 16)}…</div>`
          : `<div class="ev-hash" title="Digest unavailable">SHA-256: unavailable</div>`;
        const tag = e.modified_since_ingest
          ? `<span class="tag tag-orange" style="flex-shrink:0;" title="File on disk no longer matches the digest recorded at ingest"><i class="fa-solid fa-triangle-exclamation"></i> CHANGED</span>`
          : (e.status === 'PARSED'
              ? `<span class="tag tag-green" style="flex-shrink:0;"><i class="fa-solid fa-check"></i> HASHED</span>`
              : e.status === 'REFERENCE'
                ? `<span class="tag" style="flex-shrink:0;opacity:0.75;"><i class="fa-solid fa-book"></i> REFERENCE</span>`
                : `<span class="tag tag-orange" style="flex-shrink:0;">${e.status || 'PENDING'}</span>`);
        return `
      <div class="evidence-item">
        <div class="ev-icon ${ext}">
          <i class="fa-solid ${fileIconClass(ext)}"></i>
        </div>
        <div>
          <div class="ev-name">${e.filename}</div>
          <div class="ev-meta">${formatBytes(e.size_bytes)} · ${rows}</div>
        </div>
        ${digest}
        ${tag}
      </div>`;
      }).join('');
    }
  }

  const traceList = document.getElementById('trace-list');
  if (traceList) {
    if (!DECISION_TRACE.length) {
      traceList.innerHTML = `
        <div style="padding:22px;text-align:center;color:var(--text-muted);font-size:13px;">
          <i class="fa-solid fa-file-lines" style="display:block;font-size:20px;margin-bottom:8px;opacity:0.5;"></i>
          decision_trace.jsonl is written by the rule engine on each run — run the pipeline to populate it.
        </div>`;
    } else {
      traceList.innerHTML = DECISION_TRACE.map(t => `
      <div class="trace-item" title="${escapeAttr(t.explanation || '')}">
        <span class="trace-rule">${t.rule_id || '—'}</span>
        <span class="trace-entity">${t.entity_id || '—'}</span>
        <span class="trace-desc">${escapeHTML((t.explanation || '').length > 180 ? (t.explanation || '').slice(0, 180) + '…' : (t.explanation || ''))}${
          (t.evidence_row_refs || []).length
            ? ` <span style="opacity:0.7;font-family:var(--font-mono);font-size:10.5px;">[${t.evidence_row_refs.slice(0, 4).join(', ')}]</span>`
            : ''}</span>
        <span class="trace-ts">${(t.timestamp || '').replace('T', ' ').slice(0, 19)}</span>
      </div>
    `).join('');
    }
  }
}

function escapeHTML(s) {
  return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
function escapeAttr(s) {
  return escapeHTML(s).replace(/"/g, '&quot;');
}

/* Reads the real decision_trace.jsonl the rule engine wrote on this run. */
async function fetchDecisionTrace() {
  try {
    const res = await fetch(`${API_BASE}/api/download-trace`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return;
    const text = await res.text();
    DECISION_TRACE = text.split('\n')
      .filter(l => l.trim())
      .map(l => { try { return JSON.parse(l); } catch { return null; } })
      .filter(Boolean);
    populateEvidence();
  } catch (e) {
    console.warn('fetchDecisionTrace err:', e);
  }
}

/* ── REPORTS ────────────────────────────────────────────────────── */
function populateReports() {
  const grid = document.getElementById('reports-grid');
  if (!grid) return;

  if (!REPORTS.length) {
    grid.innerHTML = `
      <div class="report-card" style="opacity:0.7;">
        <i class="fa-solid fa-circle-info report-icon" style="color:#9BA1A8;font-size:24px;"></i>
        <div>
          <div class="report-title">No reports available</div>
          <div class="report-meta">No entity reached HIGH or CRITICAL in the current run,
            or the pipeline has not been executed yet.</div>
        </div>
      </div>`;
    return;
  }

  grid.innerHTML = REPORTS.map(r => {
    const tierClass = r.tier === 'CRITICAL' ? 'tag-danger' : r.tier === 'HIGH' ? 'tag-warn' : 'tag-blue';
    const rules = r.rules.length ? r.rules.join(' · ') : 'no rules fired';
    return `
      <div class="report-card">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <i class="fa-solid fa-file-word report-icon" style="color:#4da6ff;font-size:28px;"></i>
          <span class="tag ${tierClass}">${r.tier}</span>
        </div>
        <div>
          <div class="report-title">${r.entityId} — ${r.name}</div>
          <div class="report-meta">${rules}</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="tag tag-blue"><i class="fa-solid fa-bolt"></i> GENERATED ON DEMAND</span>
        </div>
        <div class="report-actions">
          <a href="${API_BASE}/api/download-report/${encodeURIComponent(r.entityId)}" class="btn btn-ghost btn-sm">
            <i class="fa-solid fa-file-word"></i> Forensic
          </a>
          <a href="${API_BASE}/api/download-str-report/${encodeURIComponent(r.entityId)}" class="btn btn-ghost btn-sm">
            <i class="fa-solid fa-file-shield"></i> STR
          </a>
        </div>
      </div>
    `;
  }).join('');
}

/* ── COMMAND PALETTE ────────────────────────────────────────────── */
function populatePalette() {
  const body = document.getElementById('palette-body');
  if (!body) return;

  const items = [
    ...MOCK_CASES.slice(0, 3).map(c => ({ type: 'case', icon: 'fa-folder-open', iconBg: 'rgba(61,124,255,0.1)', iconColor: 'var(--accent-primary)', title: c.id, sub: c.title, action: () => openSlideOver(c.id) })),
    ...MOCK_POIS.slice(0, 3).map(p => ({ type: 'poi', icon: 'fa-user-secret', iconBg: 'rgba(255,77,77,0.1)', iconColor: 'var(--accent-danger)', title: p.name, sub: `${p.id} · Risk ${p.risk}%`, action: () => switchView('poi') })),
    { type: 'view', icon: 'fa-gauge-high', iconBg: 'rgba(46,204,113,0.1)', iconColor: 'var(--accent-success)', title: 'Dashboard', sub: 'Overview & KPIs', action: () => switchView('dashboard') },
    { type: 'view', icon: 'fa-diagram-project', iconBg: 'rgba(167,139,250,0.1)', iconColor: '#a78bfa', title: 'Entity Graph', sub: 'Identity resolution network', action: () => switchView('network') },
  ];

  body.innerHTML = `<div class="palette-section-label">Quick Access</div>` + items.map((item, i) => `
    <div class="palette-item" tabindex="-1" onclick="handlePaletteItem(${i})">
      <div class="palette-item-icon" style="background:${item.iconBg};color:${item.iconColor};">
        <i class="fa-solid ${item.icon}"></i>
      </div>
      <div class="palette-item-text">
        <div class="palette-item-title">${item.title}</div>
        <div class="palette-item-sub">${item.sub}</div>
      </div>
      <i class="fa-solid fa-arrow-right palette-item-arrow"></i>
    </div>
  `).join('');

  window._paletteActions = items.map(i => i.action);
}

function handlePaletteItem(idx) {
  closePalette();
  if (window._paletteActions && window._paletteActions[idx]) {
    setTimeout(window._paletteActions[idx], 50);
  }
}

function filterPalette(q) {
  const body = document.getElementById('palette-body');
  if (!q.trim()) { populatePalette(); return; }
  q = q.toLowerCase();
  const allItems = [
    ...MOCK_CASES.map(c => ({ title: c.id, sub: c.title, icon: 'fa-folder-open', bg: 'rgba(61,124,255,0.1)', col: 'var(--accent-primary)', action: () => openSlideOver(c.id) })),
    ...MOCK_POIS.map(p => ({ title: p.name, sub: p.id, icon: 'fa-user-secret', bg: 'rgba(255,77,77,0.1)', col: 'var(--accent-danger)', action: () => switchView('poi') })),
  ].filter(i => i.title.toLowerCase().includes(q) || i.sub.toLowerCase().includes(q));

  if (!allItems.length) {
    body.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">No results for "${q}"</div>`;
    return;
  }
  body.innerHTML = `<div class="palette-section-label">Results</div>` + allItems.slice(0, 8).map((item, i) => `
    <div class="palette-item" onclick="closePalette();setTimeout(()=>{ window._searchActions[${i}]&&window._searchActions[${i}]() },50)">
      <div class="palette-item-icon" style="background:${item.bg};color:${item.col};">
        <i class="fa-solid ${item.icon}"></i>
      </div>
      <div class="palette-item-text">
        <div class="palette-item-title">${item.title}</div>
        <div class="palette-item-sub">${item.sub}</div>
      </div>
    </div>
  `).join('');
  window._searchActions = allItems.map(i => i.action);
}

function openPalette() {
  appState.paletteOpen = true;
  document.getElementById('palette-scrim').classList.add('open');
  document.getElementById('command-palette').classList.add('open');
  setTimeout(() => document.getElementById('palette-input').focus(), 50);
}

function closePalette() {
  appState.paletteOpen = false;
  document.getElementById('palette-scrim').classList.remove('open');
  document.getElementById('command-palette').classList.remove('open');
  document.getElementById('palette-input').value = '';
  populatePalette();
}

/* ── CASE SLIDE-OVER ────────────────────────────────────────────── */
function openSlideOver(caseId) {
  const c = MOCK_CASES.find(x => x.id === caseId);
  if (!c) return;
  appState.currentCase = c;

  document.getElementById('so-case-id').textContent = c.id;
  document.getElementById('so-case-title').textContent = c.title;

  const body = document.getElementById('slideover-body');
  body.innerHTML = `
    <div class="so-section">
      <div class="so-section-title">Case Overview</div>
      <div class="so-meta-grid">
        <div class="so-meta-item"><div class="so-meta-key">Status</div><div class="so-meta-val">${statusBadge(c.status)}</div></div>
        <div class="so-meta-item"><div class="so-meta-key">Risk Score</div><div class="so-meta-val">${riskBar(c.risk)}</div></div>
        <div class="so-meta-item"><div class="so-meta-key">Officer</div><div class="so-meta-val">${c.officer}</div></div>
        <div class="so-meta-item"><div class="so-meta-key">Entities</div><div class="so-meta-val mono">${c.entities} resolved</div></div>
        <div class="so-meta-item" style="grid-column:1/-1;"><div class="so-meta-key">Last Activity</div><div class="so-meta-val">${c.lastActivity}</div></div>
      </div>
    </div>

    <div class="so-section">
      <div class="so-section-title">Rules Fired</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">
        ${c.rules.length ? c.rules.map(r => `<span class="rule-chip">${r}</span>`).join('') : `<span style="font-size:12px;color:var(--text-muted);">No rules fired</span>`}
      </div>
    </div>

    <div class="so-section">
      <div class="so-section-title">Investigation Timeline</div>
      <div class="so-timeline">
        ${buildCaseTimeline(c).map(e => `
          <div class="so-tl-entry">
            <span class="so-tl-dot ${e.type}"></span>
            <div>
              <div class="so-tl-text">${e.text}</div>
              <div class="so-tl-time">${e.time}</div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>

    <div class="so-section">
      <div class="so-section-title">Evidence Files</div>
      <div class="evidence-chips">
        ${EVIDENCE_FILES.length
          ? EVIDENCE_FILES.map(e => `<div class="ev-chip"><i class="fa-solid ${fileIconClass((e.extension || '').toLowerCase())}"></i>${e.filename}</div>`).join('')
          : '<div class="ev-chip" style="opacity:0.6;"><i class="fa-solid fa-circle-info"></i>No ingested files</div>'}
      </div>
    </div>

    <div style="display:flex;gap:8px;margin-top:8px;">
      ${REPORTS.length
        // Was hardcoded to "ENT-0037" — a hyphenated id the API has never issued,
        // so this button 404'd on every click. It now targets the highest-tier
        // entity of the current run, and disappears when nothing is flagged.
        ? `<a href="${API_BASE}/api/download-report/${encodeURIComponent(REPORTS[0].entityId)}" class="btn btn-primary btn-sm">
             <i class="fa-solid fa-file-word"></i> Download Report (${REPORTS[0].entityId})
           </a>`
        : ''}
      <button class="btn btn-ghost btn-sm" onclick="closeCopilot();toggleCopilot()">
        <i class="fa-solid fa-robot"></i> Ask Copilot
      </button>
    </div>
  `;

  document.getElementById('slideover-scrim').classList.add('open');
  document.getElementById('case-slideover').classList.add('open');
  appState.slideOverOpen = true;
}

function buildCaseTimeline(c) {
  const events = [
    { type: 'blue', text: `Case <strong>${c.id}</strong> created and assigned to ${c.officer}.`, time: '2026-07-23 08:30:00' },
    { type: 'blue', text: `Raw data ingested — 2,372 events from 5 source files.`, time: '2026-07-23 08:45:12' },
    { type: 'blue', text: `Entity resolution complete — ${c.entities} entities from graph.`, time: '2026-07-23 09:00:04' },
  ];
  if (c.rules.length) {
    c.rules.forEach(r => events.push({ type: 'warn', text: `Rule <strong>${r}</strong> fired — see decision_trace.jsonl for evidence rows.`, time: '2026-07-23 09:14:22' }));
  }
  if (c.status === 'critical' || c.status === 'escalated') {
    events.push({ type: 'red', text: `Case escalated to CRITICAL — multiple high-conviction rules triggered.`, time: '2026-07-23 09:20:00' });
  }
  if (c.status === 'closed') {
    events.push({ type: 'green', text: `Case closed and archived. Forensic package sealed.`, time: '2026-07-23 11:00:00' });
  }
  return events.reverse();
}

function closeSlideOver() {
  document.getElementById('slideover-scrim').classList.remove('open');
  document.getElementById('case-slideover').classList.remove('open');
  appState.slideOverOpen = false;
}

/* ── AI COPILOT ─────────────────────────────────────────────────── */
function toggleCopilot() {
  if (appState.copilotOpen) closeCopilot();
  else openCopilot();
}

function openCopilot() {
  appState.copilotOpen = true;
  document.getElementById('copilot-scrim').classList.add('open');
  document.getElementById('copilot-panel').classList.add('open');
  setTimeout(() => document.getElementById('copilot-input').focus(), 300);
}

function closeCopilot() {
  appState.copilotOpen = false;
  document.getElementById('copilot-scrim').classList.remove('open');
  document.getElementById('copilot-panel').classList.remove('open');
}

function handleCopilotKey(e) {
  if (e.key === 'Enter') sendCopilotMessage();
  if (e.key === 'Escape') closeCopilot();
}

function sendCopilotMessage() {
  const input = document.getElementById('copilot-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  appendCopilotMessage('user', text);

  // Typing indicator
  const typingId = appendTypingIndicator();

  setTimeout(() => {
    removeTypingIndicator(typingId);
    const reply = COPILOT_RESPONSES[Math.floor(Math.random() * COPILOT_RESPONSES.length)];
    appendCopilotMessage('system', reply, 'Case Copilot');
  }, 900 + Math.random() * 600);
}

function appendCopilotMessage(role, text, sender = 'You') {
  const msgs = document.getElementById('copilot-messages');
  const div = document.createElement('div');
  div.className = `copilot-msg ${role}`;
  const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  div.innerHTML = `
    <div class="msg-bubble">${text}</div>
    <div class="msg-meta">${role === 'user' ? 'You' : sender} · ${now}</div>
  `;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function appendTypingIndicator() {
  const msgs = document.getElementById('copilot-messages');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'copilot-msg system';
  div.id = id;
  div.innerHTML = `<div class="msg-bubble" style="padding:12px 16px;"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

/* ── KEYBOARD SHORTCUTS ─────────────────────────────────────────── */
function initKBShortcuts() {
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      appState.paletteOpen ? closePalette() : openPalette();
    }
    if (e.key === 'Escape') {
      if (appState.paletteOpen) closePalette();
      if (appState.copilotOpen) closeCopilot();
      if (appState.slideOverOpen) closeSlideOver();
    }
  });
}

/* ── NAVIGATION ─────────────────────────────────────────────────── */
function initNavigation() {
  document.querySelectorAll('.nav-item').forEach(item => {
    if (item._navWired) return;
    item._navWired = true;
    item.addEventListener('click', e => {
      e.preventDefault();
      const viewId = item.getAttribute('data-view');
      if (viewId) {
        switchView(viewId, item);
      }
    });
  });
}

/* ── API STATUS ─────────────────────────────────────────────────── */
async function fetchAPIStatus() {
  const pill = document.getElementById('status-pill');
  const text = document.getElementById('status-text');
  try {
    const res = await fetch(`${API_BASE}/api/status`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      const data = await res.json();
      const count = data.entity_count || 0;
      text.textContent = count > 0 ? `${count.toLocaleString()} Entities Ready` : 'System Ready';
      pill.querySelector('.pulse-dot').className = 'pulse-dot green';
      // Populate with real data if available
      if (data.pipeline_run) {
        fetchRealResults();
        fetchVerificationSummary();
        fetchEvidenceFiles();
        fetchDecisionTrace();
      }
    }
  } catch {
    text.textContent = 'Backend Offline';
    pill.querySelector('.pulse-dot').className = 'pulse-dot blue';
    markKPIsUnavailable();
  }
}

/* With no backend there is no dataset — show an explicit dash rather than a
   plausible-looking number the panel would read as real. */
function markKPIsUnavailable() {
  ['kpi-entities', 'kpi-cases', 'kpi-critical', 'kpi-resolved'].forEach(id => {
    const el = document.getElementById(id);
    if (el && (el.textContent === '0' || el.textContent === '')) el.textContent = '—';
  });
}

async function fetchRealResults() {
  try {
    const res = await fetch(`${API_BASE}/api/results`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return;
    const data = await res.json();
    appState.results = data;

    // KPI tiles read the real API contract: everything lives under data.metrics.
    // Nothing below is hardcoded — swap the dataset and every tile moves.
    const m = data.metrics || {};
    const kpiMap = {
      'kpi-entities': m.total_entities,
      'kpi-cases': m.flagged_suspects,
      'kpi-critical': (m.critical_count || 0) + (m.high_count || 0),
      'kpi-resolved': m.ml_anomalies,
    };
    Object.entries(kpiMap).forEach(([id, val]) => {
      if (val != null) {
        const el = document.getElementById(id);
        if (el) { el.setAttribute('data-target', val); }
      }
    });
    animateKPICounters();
    updateKPIContext(m);
    populateRuleGrid(data.rule_firings);
    buildActivityFeed(data);
    populateDashboard();

    if (data.suspects && data.suspects.length > 0) {
      // The engine assigns a rule-gated TIER, never a numeric score — so no
      // percentage is synthesised here. Only rule-flagged entities are listed;
      // the LOW-tier remainder is reported as a count, not as 1,500 cards.
      MOCK_POIS.length = 0;
      const flagged = data.suspects.filter(s => s.risk_tier !== 'LOW');
      POI_SUPPRESSED_LOW = data.suspects.length - flagged.length;
      flagged.forEach(s => {
        MOCK_POIS.push({
          id: s.entity_id,
          name: s.name && s.name !== 'Unknown' ? s.name : `Suspect (${s.entity_id})`,
          alias: s.phones.length ? s.phones[0] : (s.accounts.length ? s.accounts[0] : s.entity_id),
          risk: null,
          tier: s.risk_tier,
          mlAnomaly: !!s.ml_anomaly,
          phones: s.phones || [],
          accounts: s.accounts || [],
          rules: s.rules_fired || [],
          cases: ['CASE-2026-00412']
        });
      });
      populatePOI();

      // The report set is exactly the entities the backend escalates to
      // HIGH/CRITICAL — the same predicate generate_reports_for_flagged() uses.
      REPORTS = data.suspects
        .filter(s => s.risk_tier === 'CRITICAL' || s.risk_tier === 'HIGH')
        .map(s => ({
          entityId: s.entity_id,
          name: s.name && s.name !== 'Unknown' ? s.name : 'Unnamed entity',
          tier: s.risk_tier,
          rules: s.rules_fired || [],
        }));
      populateReports();
    }
    /* Cache both graphs, but do NOT build the vis.Network here. This runs while the
       dashboard view is showing, so the network container is display:none — vis.js
       would measure it as zero-height and render a canvas nobody can see. The graph
       is built by initNetwork() when its view actually becomes visible. */
    if (data.network_views) networkViews = data.network_views;
  } catch (e) { console.warn("fetchRealResults err:", e); }
}

/* ── DETECTION ACCURACY (LIVE GROUND-TRUTH VERIFICATION) ──────────── */
async function fetchVerificationSummary() {
  const card = document.getElementById('kpi-accuracy-card');
  if (!card) return;
  try {
    const res = await fetch(`${API_BASE}/api/verification-summary`, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) {
      // No ground truth available (e.g. real uploaded case data) — hide the card
      // rather than show a stale/fabricated number.
      card.style.display = 'none';
      return;
    }
    const data = await res.json();
    card.style.display = '';

    const recallPct = Math.round((data.recall || 0) * 100);
    const precisionPct = Math.round((data.precision || 0) * 100);
    const typologyCount = (data.typology_breakdown || []).length;

    document.getElementById('kpi-accuracy-recall').textContent = `${recallPct}%`;
    document.getElementById('kpi-accuracy-precision').textContent = `${precisionPct}%`;
    document.getElementById('kpi-accuracy-count').textContent = typologyCount;

    const missed = (data.typology_breakdown || []).filter(t => t.missed > 0).map(t => t.label);
    const subEl = document.getElementById('kpi-accuracy-sub');
    if (subEl) {
      subEl.innerHTML = missed.length
        ? `Across ${typologyCount} planted typologies · missed: ${missed.join(', ')}`
        : `Across ${typologyCount} planted fraud typologies · all detected`;
    }

    card.title = `Live self-verification against ${data.total_gt_entities} planted ground-truth entities: ` +
      `${data.true_positives} true positives, ${data.false_positives} false positives, ` +
      `${data.false_negatives} false negatives. Recomputed on every pipeline run.`;
  } catch (e) {
    console.warn("fetchVerificationSummary err:", e);
    card.style.display = 'none';
  }
}

/* ── PIPELINE MODAL & EXECUTION ───────────────────────────────────── */
async function openPipeline() {
  const overlay = document.getElementById('pipeline-overlay');
  overlay.style.display = 'flex';

  const steps = [
    { label: '[1/8] Ingesting raw data files…', icon: 'fa-file-import' },
    { label: '[2/8] Resolving entity graph…', icon: 'fa-diagram-project' },
    { label: '[3/8] Temporal correlation…', icon: 'fa-clock' },
    { label: '[4/8] Running rule engine…', icon: 'fa-shield-halved' },
    { label: '[5/8] Computing risk scores…', icon: 'fa-chart-bar' },
    { label: '[6/8] Building network graph…', icon: 'fa-share-nodes' },
    { label: '[7/8] Generating reports…', icon: 'fa-file-lines' },
    { label: '[8/8] Self-verification…', icon: 'fa-circle-check' },
  ];

  const stepsEl = document.getElementById('pipeline-steps');
  stepsEl.innerHTML = steps.map((s, i) => `
    <div class="pipeline-step pending" id="ps-${i}">
      <i class="fa-solid ${s.icon}"></i> ${s.label}
    </div>
  `).join('');

  const bar = document.getElementById('pipeline-bar');
  bar.style.width = '0%';

  // Step 1: Upload staged files across all 4 buckets if present
  const b = appState.bucketFiles || {};
  const allStaged = [...(b.cdr || []), ...(b.ipdr || []), ...(b.bank || []), ...(b.other || [])];

  if (allStaged.length > 0) {
    try {
      const formData = new FormData();
      allStaged.forEach(f => formData.append('files', f));
      await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
    } catch (e) {
      console.warn("Upload API error:", e);
    }
  }

  // Step 2: Trigger real backend pipeline execution
  const pipelinePromise = fetch(`${API_BASE}/api/run-pipeline`, { method: 'POST' })
    .then(r => r.json())
    .catch(e => console.warn("Pipeline API error:", e));

  // Step 3: Animate steps visually
  for (let i = 0; i < steps.length; i++) {
    if (i > 0) {
      const prev = document.getElementById(`ps-${i - 1}`);
      if (prev) {
        prev.classList.remove('running');
        prev.classList.add('done');
        prev.querySelector('i').className = 'fa-solid fa-check';
      }
    }
    const cur = document.getElementById(`ps-${i}`);
    if (cur) {
      cur.classList.remove('pending');
      cur.classList.add('running');
    }
    bar.style.width = `${((i + 1) / steps.length) * 100}%`;
    await new Promise(r => setTimeout(r, 450));
  }

  const last = document.getElementById(`ps-${steps.length - 1}`);
  if (last) {
    last.classList.remove('running');
    last.classList.add('done');
    last.querySelector('i').className = 'fa-solid fa-check';
  }
  bar.style.width = '100%';

  // Await pipeline response & fetch real results
  await pipelinePromise;
  await fetchRealResults();
  await fetchAPIStatus();
  await fetchEvidenceFiles();
  await fetchDecisionTrace();
  await fetchVerificationSummary();

  // Auto-close modal after 700ms and transition to Dashboard
  setTimeout(() => {
    closePipelineOverlay();
  }, 700);
}

function closePipelineOverlay() {
  document.getElementById('pipeline-overlay').style.display = 'none';
  // Transition to Dashboard view to display results
  const dashNav = document.querySelector('[data-view="dashboard"]');
  switchView('dashboard', dashNav);
  animateKPICounters();
  populateDashboard();
  populateCaseTable();
  populatePOI();
  populateEvidence();
  populateReports();
  populateRuleGrid();
}

/* ── MAP ────────────────────────────────────────────────────────── */
function initMap() {
  const container = document.getElementById('surat-map');
  if (!container || appState.mapInstance) return;

  const map = L.map('surat-map', { center: [21.1702, 72.8311], zoom: 13, zoomControl: true, attributionControl: false });
  appState.mapInstance = map;

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

  const towers = [
    { lat: 21.1702, lon: 72.8311, area: 'Athwa Gate' },
    { lat: 21.1860, lon: 72.7933, area: 'Adajan' },
    { lat: 21.2148, lon: 72.8470, area: 'Katargam' },
    { lat: 21.1565, lon: 72.7710, area: 'Vesu' },
    { lat: 21.2050, lon: 72.8630, area: 'Varachha' },
    { lat: 21.1980, lon: 72.8150, area: 'Ring Road' },
    { lat: 21.1690, lon: 72.7880, area: 'Piplod' },
    { lat: 21.1780, lon: 72.8550, area: 'Udhna' },
    { lat: 21.1450, lon: 72.7650, area: 'Dumas Road' },
    { lat: 21.2280, lon: 72.8380, area: 'Sachin GIDC' },
  ];

  towers.forEach(t => {
    L.circle([t.lat, t.lon], { color: '#3D7CFF', fillColor: '#3D7CFF', fillOpacity: 0.07, radius: 500, weight: 1, dashArray: '4,6' }).addTo(map);
    L.circleMarker([t.lat, t.lon], { radius: 7, fillColor: '#3D7CFF', color: '#6ba3ff', weight: 2, fillOpacity: 1 })
      .bindPopup(`<strong style="color:#3D7CFF;">${t.area}</strong><br>Cell Tower`)
      .addTo(map);
  });
}

/* ══ UNIFIED EVIDENTIARY TIMELINE (S2.1 · FR-II.a) ═══════════════════
   One entity's whole story on a single time axis, in three lanes, with the
   temporal correlation windows drawn over it.

   Drawn as plain SVG rather than pulled from a charting library: the view needs
   focus+context, and that is the whole point of the screen. The demo dataset
   spans six weeks while a correlation window is ±10 minutes — roughly 0.02% of
   the axis. Rendered at full range the decisive moment is a hairline, so the
   context strip carries the whole range and the detail panel shows the slice, and
   the "Correlation windows" preset walks straight to the moments that matter. */

const TIMELINE_LANES = [
  { key: 'transaction', label: 'Transactions', color: '#3D7CFF' },
  { key: 'call', label: 'Calls / SMS', color: '#2ECC71' },
  { key: 'ip_session', label: 'IP Sessions', color: '#a78bfa' },
];
const TL_COLORS = {
  credit: '#2ECC71', debit: '#FF4D4D',
  call: '#3D7CFF', ip_session: '#a78bfa',
  window: '#FFB020',
};

const timelineState = {
  entityId: null,
  payload: null,
  t0: null, t1: null,      // visible window, ms
  fullT0: null, fullT1: null,
  correlationIndex: -1,
  selectedEventId: null,
  loading: false,
};

/* Jump straight from a node in the money-flow graph to that entity's timeline —
   the demo path is "the chain lights up" then "open its timeline", and making the
   judge re-find the entity in a dropdown between those two steps breaks it. */
function openEntityTimeline(entityId) {
  timelineState.entityId = entityId;
  timelineState.payload = null;
  switchView('timeline');
}

function initTimeline() {
  const select = document.getElementById('timeline-entity-select');
  if (!select) return;

  // Offer the entities the engine actually escalated. REPORTS is tier-sorted, so
  // the default is the highest-risk entity of whatever dataset is loaded — no
  // entity id is hardcoded here.
  let options = REPORTS.length
    ? REPORTS.slice()
    : (appState.results?.suspects || [])
      .filter(s => s.risk_tier !== 'LOW')
      .map(s => ({ entityId: s.entity_id, name: s.name, tier: s.risk_tier, rules: s.rules_fired || [] }));

  if (!options.length) {
    document.getElementById('timeline-summary').innerHTML =
      '<span class="tl-empty">No flagged entity in the current run. Run the pipeline, then return here.</span>';
    return;
  }

  const current = timelineState.entityId;
  // An entity opened from the graph may be MEDIUM tier and therefore absent from
  // the flagged list. Add it rather than silently loading a different entity.
  if (current && !options.some(o => o.entityId === current)) {
    const s = (appState.results?.suspects || []).find(x => x.entity_id === current);
    options = [{
      entityId: current,
      name: s?.name || '',
      tier: s?.risk_tier || 'LOW',
      rules: s?.rules_fired || [],
    }, ...options];
  }

  select.innerHTML = options.map(o =>
    `<option value="${escapeAttr(o.entityId)}" ${o.entityId === current ? 'selected' : ''}>
       ${escapeHTML(o.entityId)} — ${escapeHTML(o.tier)}${o.name && o.name !== 'Unnamed entity' ? ' · ' + escapeHTML(o.name) : ''}
     </option>`).join('');

  if (!select._wired) {
    select._wired = true;
    select.addEventListener('change', e => loadTimeline(e.target.value));
  }

  if (!timelineState.payload || timelineState.entityId !== select.value) {
    loadTimeline(select.value);
  } else {
    renderTimeline();
  }
}

async function loadTimeline(entityId) {
  if (!entityId || timelineState.loading) return;
  timelineState.loading = true;
  timelineState.entityId = entityId;
  timelineState.selectedEventId = null;
  timelineState.correlationIndex = -1;

  const summary = document.getElementById('timeline-summary');
  if (summary) summary.innerHTML = '<span class="tl-empty"><i class="fa-solid fa-spinner fa-spin"></i> Loading timeline…</span>';

  const link = document.getElementById('timeline-report-link');
  if (link) link.href = `${API_BASE}/api/download-report/${encodeURIComponent(entityId)}`;

  try {
    const res = await fetch(`${API_BASE}/api/entity/${encodeURIComponent(entityId)}/timeline`,
      { signal: AbortSignal.timeout(10000) });
    if (!res.ok) throw new Error(`timeline ${res.status}`);
    const payload = await res.json();
    // A late response for an entity the user has already moved off must not paint.
    if (timelineState.entityId !== entityId) return;

    timelineState.payload = payload;
    const stamps = (payload.events || []).map(e => Date.parse(e.t)).filter(Number.isFinite);
    if (stamps.length) {
      timelineState.fullT0 = Math.min(...stamps);
      timelineState.fullT1 = Math.max(...stamps);
      const pad = Math.max((timelineState.fullT1 - timelineState.fullT0) * 0.02, 60000);
      timelineState.fullT0 -= pad;
      timelineState.fullT1 += pad;
      timelineState.t0 = timelineState.fullT0;
      timelineState.t1 = timelineState.fullT1;
    }
    renderTimeline();
  } catch (e) {
    if (summary) summary.innerHTML =
      `<span class="tl-empty"><i class="fa-solid fa-triangle-exclamation"></i> Timeline unavailable (${escapeHTML(String(e.message || e))}).</span>`;
  } finally {
    timelineState.loading = false;
  }
}

function tlNiceTicks(t0, t1, target) {
  const span = t1 - t0;
  const MIN = 60000, HOUR = 3600000, DAY = 86400000;
  const steps = [MIN, 5 * MIN, 15 * MIN, 30 * MIN, HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR,
    DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY];
  let step = steps[steps.length - 1];
  for (const s of steps) { if (span / s <= target) { step = s; break; } }
  const ticks = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) ticks.push(t);
  return { ticks, step };
}

function tlFormatTick(ms, step) {
  const d = new Date(ms);
  const pad = n => String(n).padStart(2, '0');
  if (step < 86400000) return `${pad(d.getDate())} ${d.toLocaleString('en', { month: 'short' })}\n${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${pad(d.getDate())} ${d.toLocaleString('en', { month: 'short' })}`;
}

function tlFormatStamp(iso) {
  if (!iso) return '';
  return String(iso).slice(0, 19).replace('T', ' ');
}

function renderTimeline() {
  const payload = timelineState.payload;
  const svg = document.getElementById('timeline-detail');
  if (!payload || !svg) return;

  renderTimelineSummary(payload);
  renderTimelineZoomPresets(payload);
  renderTimelineLegend(payload);
  renderTimelineDetail(payload);
  renderTimelineContext(payload);
}

function renderTimelineSummary(payload) {
  const el = document.getElementById('timeline-summary');
  if (!el) return;
  const tierClass = payload.risk_tier === 'CRITICAL' ? 'tag-danger'
    : payload.risk_tier === 'HIGH' ? 'tag-warn' : 'tag-blue';
  const lanes = (payload.lanes || []).map(l => `${fmtNum(l.count)} ${l.label.toLowerCase()}`).join(' · ');
  el.innerHTML = `
    <span class="tl-entity">${escapeHTML(payload.entity_id)}</span>
    ${payload.name ? `<span class="tl-name">${escapeHTML(payload.name)}</span>` : ''}
    <span class="tag ${tierClass}">${escapeHTML(payload.risk_tier || 'LOW')}</span>
    ${(payload.rules_fired || []).map(r => `<span class="rule-chip">${escapeHTML(r)}</span>`).join('')}
    <span class="tl-counts">${escapeHTML(lanes)}${payload.correlations?.length
      ? ` · <b>${payload.correlations.length} correlation window${payload.correlations.length > 1 ? 's' : ''}</b>` : ''}</span>`;
}

function renderTimelineZoomPresets(payload) {
  const el = document.getElementById('timeline-zoom-presets');
  if (!el) return;
  const hasCorr = (payload.correlations || []).length > 0;
  el.innerHTML = `
    <button class="filter-btn" onclick="timelineZoom('all')">Full range</button>
    <button class="filter-btn" onclick="timelineZoom('day')">1 day</button>
    <button class="filter-btn" onclick="timelineZoom('hour')">1 hour</button>
    ${hasCorr ? `<button class="filter-btn tl-corr-btn" onclick="timelineZoom('correlation')">
        <i class="fa-solid fa-crosshairs"></i> Correlation window
        ${payload.correlations.length > 1 ? `<span class="tl-corr-count">${payload.correlations.length}</span>` : ''}
      </button>` : ''}`;
}

function renderTimelineLegend(payload) {
  const el = document.getElementById('timeline-legend');
  if (!el) return;
  const items = [
    [TL_COLORS.credit, 'Credit (money in)'],
    [TL_COLORS.debit, 'Debit (money out)'],
    [TL_COLORS.call, 'Call / SMS'],
    [TL_COLORS.ip_session, 'IP session'],
  ];
  el.innerHTML = items.map(([c, label]) =>
    `<span class="legend-item"><span style="width:8px;height:8px;border-radius:50%;background:${c};flex-shrink:0;"></span> ${label}</span>`
  ).join('') + (payload.correlations?.length
    ? `<span class="legend-item"><span style="width:14px;height:9px;background:${TL_COLORS.window};opacity:.45;flex-shrink:0;"></span> ±${payload.window_minutes} min correlation window</span>` : '')
    + (payload.flagged_row_refs?.length
      ? `<span class="legend-item"><span style="width:9px;height:9px;border-radius:50%;border:2px solid #fff;flex-shrink:0;"></span> Cited as evidence</span>` : '');
}

function timelineZoom(mode) {
  const s = timelineState;
  if (!s.payload) return;
  if (mode === 'all') {
    s.t0 = s.fullT0; s.t1 = s.fullT1; s.correlationIndex = -1;
  } else if (mode === 'correlation') {
    const bands = s.payload.correlations || [];
    if (!bands.length) return;
    // Step through the correlation windows one click at a time.
    s.correlationIndex = (s.correlationIndex + 1) % bands.length;
    const c = bands[s.correlationIndex];
    const centre = Date.parse(c.centre);
    const half = (s.payload.window_minutes || 10) * 60000 * 3;
    s.t0 = centre - half; s.t1 = centre + half;
  } else {
    const span = mode === 'day' ? 86400000 : 3600000;
    const centre = (s.t0 + s.t1) / 2;
    s.t0 = centre - span / 2; s.t1 = centre + span / 2;
  }
  renderTimelineDetail(s.payload);
  renderTimelineContext(s.payload);
}

function renderTimelineDetail(payload) {
  const svg = document.getElementById('timeline-detail');
  if (!svg) return;

  const W = svg.clientWidth || svg.parentElement.clientWidth || 900;
  const GUTTER = 96, PAD_R = 18, TOP = 16, LANE_H = 60, AXIS_H = 34;
  const H = TOP + LANE_H * TIMELINE_LANES.length + AXIS_H;
  const plotW = Math.max(W - GUTTER - PAD_R, 60);
  const { t0, t1 } = timelineState;
  const x = ms => GUTTER + ((ms - t0) / Math.max(t1 - t0, 1)) * plotW;
  const laneY = i => TOP + i * LANE_H + LANE_H / 2;

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  const parts = [];

  // Correlation bands behind everything else.
  (payload.correlations || []).forEach((c, i) => {
    const s = Date.parse(c.start), e = Date.parse(c.end);
    if (e < t0 || s > t1) return;
    const xs = Math.max(x(s), GUTTER), xe = Math.min(x(e), GUTTER + plotW);
    parts.push(`<rect x="${xs}" y="${TOP}" width="${Math.max(xe - xs, 1.5)}" height="${LANE_H * 3}"
      fill="${TL_COLORS.window}" opacity="${c.kind === 'tcs1' ? 0.22 : 0.11}"/>`);
    if (c.kind === 'tcs1') {
      const xc = x(Date.parse(c.centre));
      if (xc >= GUTTER && xc <= GUTTER + plotW) {
        parts.push(`<line x1="${xc}" y1="${TOP}" x2="${xc}" y2="${TOP + LANE_H * 3}"
          stroke="${TL_COLORS.window}" stroke-width="1" opacity="0.7"/>`);
      }
    }
  });

  // Lane rails + labels.
  TIMELINE_LANES.forEach((lane, i) => {
    const y = laneY(i);
    parts.push(`<line x1="${GUTTER}" y1="${y}" x2="${GUTTER + plotW}" y2="${y}"
      stroke="var(--border-dark)" stroke-width="1"/>`);
    const count = (payload.lanes || []).find(l => l.key === lane.key)?.count || 0;
    parts.push(`<text x="${GUTTER - 10}" y="${y - 2}" text-anchor="end"
      class="tl-lane-label">${lane.label}</text>`);
    parts.push(`<text x="${GUTTER - 10}" y="${y + 11}" text-anchor="end"
      class="tl-lane-count">${count}</text>`);
  });

  // Time axis.
  const { ticks, step } = tlNiceTicks(t0, t1, 7);
  const axisY = TOP + LANE_H * 3;
  ticks.forEach(t => {
    const tx = x(t);
    if (tx < GUTTER - 1 || tx > GUTTER + plotW + 1) return;
    parts.push(`<line x1="${tx}" y1="${TOP}" x2="${tx}" y2="${axisY}" stroke="var(--border-dark)"
      stroke-width="1" opacity="0.55"/>`);
    tlFormatTick(t, step).split('\n').forEach((line, li) => {
      parts.push(`<text x="${tx}" y="${axisY + 15 + li * 11}" text-anchor="middle" class="tl-tick">${line}</text>`);
    });
  });

  // Markers. Amount drives radius so a ₹5,00,000 inflow is visibly the event of
  // the day next to a ₹900 one.
  const amounts = (payload.events || [])
    .filter(e => e.lane === 'transaction' && e.amount).map(e => e.amount);
  const maxAmt = amounts.length ? Math.max(...amounts) : 0;
  const radius = ev => {
    if (ev.lane !== 'transaction' || !ev.amount || maxAmt <= 0) return 4.5;
    const r = Math.log10(Math.max(ev.amount, 1)) / Math.max(Math.log10(Math.max(maxAmt, 10)), 1);
    return 4 + 9 * Math.max(0, Math.min(r, 1));
  };

  let visible = 0;
  (payload.events || []).forEach(ev => {
    const laneIdx = TIMELINE_LANES.findIndex(l => l.key === ev.lane);
    if (laneIdx < 0) return;
    const ms = Date.parse(ev.t);
    if (!Number.isFinite(ms) || ms < t0 || ms > t1) return;
    visible++;
    const cx = x(ms), cy = laneY(laneIdx);

    // An IP session has a duration; draw it rather than pretending it is a point.
    if (ev.lane === 'ip_session' && ev.t_end) {
      const xe = x(Date.parse(ev.t_end));
      if (xe > cx + 1) {
        parts.push(`<line x1="${cx}" y1="${cy}" x2="${Math.min(xe, GUTTER + plotW)}" y2="${cy}"
          stroke="${TL_COLORS.ip_session}" stroke-width="4" opacity="0.4" stroke-linecap="round"/>`);
      }
    }

    const fill = ev.lane === 'transaction'
      ? (ev.direction === 'credit' ? TL_COLORS.credit : TL_COLORS.debit)
      : TL_COLORS[ev.lane];
    const selected = timelineState.selectedEventId === ev.id;
    const stroke = selected ? '#FFFFFF' : (ev.cited ? '#FFFFFF' : 'rgba(0,0,0,0.35)');
    const sw = selected ? 3 : (ev.cited ? 2 : 0.8);
    parts.push(`<circle class="tl-marker" data-event-id="${escapeAttr(ev.id)}"
      cx="${cx}" cy="${cy}" r="${radius(ev)}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}">
      <title>${escapeAttr(`${tlFormatStamp(ev.t)} · ${ev.label}${ev.counterparty ? ' → ' + ev.counterparty : ''}`)}</title>
    </circle>`);
  });

  if (!visible) {
    parts.push(`<text x="${GUTTER + plotW / 2}" y="${TOP + LANE_H * 1.5}" text-anchor="middle"
      class="tl-empty-note">No events in this window — widen it or choose "Full range".</text>`);
  }

  svg.innerHTML = parts.join('');

  if (!svg._wired) {
    svg._wired = true;
    svg.addEventListener('click', e => {
      const marker = e.target.closest('.tl-marker');
      if (!marker) return;
      selectTimelineEvent(marker.getAttribute('data-event-id'));
    });
    // Wheel zooms about the cursor, the way every map does.
    svg.addEventListener('wheel', e => {
      if (!timelineState.payload) return;
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const frac = Math.max(0, Math.min((e.clientX - rect.left - 96) / Math.max(rect.width - 114, 1), 1));
      const { t0: a, t1: b } = timelineState;
      const focus = a + (b - a) * frac;
      const factor = e.deltaY > 0 ? 1.25 : 0.8;
      const span = Math.max((b - a) * factor, 60000);
      timelineState.t0 = focus - span * frac;
      timelineState.t1 = focus + span * (1 - frac);
      renderTimelineDetail(timelineState.payload);
      renderTimelineContext(timelineState.payload);
    }, { passive: false });
  }
}

function renderTimelineContext(payload) {
  const svg = document.getElementById('timeline-context');
  if (!svg) return;

  const W = svg.clientWidth || svg.parentElement.clientWidth || 900;
  const H = 46, GUTTER = 96, PAD_R = 18;
  const plotW = Math.max(W - GUTTER - PAD_R, 60);
  const { fullT0, fullT1, t0, t1 } = timelineState;
  const x = ms => GUTTER + ((ms - fullT0) / Math.max(fullT1 - fullT0, 1)) * plotW;

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  const parts = [`<rect x="${GUTTER}" y="8" width="${plotW}" height="${H - 20}"
    fill="var(--dark)" stroke="var(--border-dark)" stroke-width="1" rx="3"/>`];

  (payload.correlations || []).forEach(c => {
    const xc = x(Date.parse(c.centre));
    parts.push(`<line x1="${xc}" y1="8" x2="${xc}" y2="${H - 12}"
      stroke="${TL_COLORS.window}" stroke-width="2" opacity="0.85"/>`);
  });

  (payload.events || []).forEach(ev => {
    const ms = Date.parse(ev.t);
    if (!Number.isFinite(ms)) return;
    const laneIdx = TIMELINE_LANES.findIndex(l => l.key === ev.lane);
    if (laneIdx < 0) return;
    const fill = ev.lane === 'transaction'
      ? (ev.direction === 'credit' ? TL_COLORS.credit : TL_COLORS.debit)
      : TL_COLORS[ev.lane];
    const y = 11 + laneIdx * 7;
    parts.push(`<rect x="${x(ms)}" y="${y}" width="1.6" height="5" fill="${fill}" opacity="0.85"/>`);
  });

  const xs = Math.max(x(t0), GUTTER), xe = Math.min(x(t1), GUTTER + plotW);
  parts.push(`<rect id="tl-brush" x="${xs}" y="8" width="${Math.max(xe - xs, 2)}" height="${H - 20}"
    fill="rgba(255,176,32,0.18)" stroke="${TL_COLORS.window}" stroke-width="1.5" rx="2"/>`);
  parts.push(`<text x="${GUTTER - 10}" y="${H / 2 + 3}" text-anchor="end" class="tl-lane-count">full range</text>`);

  svg.innerHTML = parts.join('');

  if (!svg._wired) {
    svg._wired = true;
    const jump = clientX => {
      const rect = svg.getBoundingClientRect();
      const frac = Math.max(0, Math.min((clientX - rect.left - GUTTER) / Math.max(rect.width - GUTTER - PAD_R, 1), 1));
      const centre = timelineState.fullT0 + (timelineState.fullT1 - timelineState.fullT0) * frac;
      const span = timelineState.t1 - timelineState.t0;
      timelineState.t0 = centre - span / 2;
      timelineState.t1 = centre + span / 2;
      renderTimelineDetail(timelineState.payload);
      renderTimelineContext(timelineState.payload);
    };
    let dragging = false;
    svg.addEventListener('mousedown', e => { dragging = true; jump(e.clientX); });
    window.addEventListener('mousemove', e => { if (dragging) jump(e.clientX); });
    window.addEventListener('mouseup', () => { dragging = false; });
  }
}

function selectTimelineEvent(eventId) {
  const payload = timelineState.payload;
  if (!payload) return;
  const ev = (payload.events || []).find(e => e.id === eventId);
  const panel = document.getElementById('timeline-detail-panel');
  if (!ev || !panel) return;

  timelineState.selectedEventId = eventId;
  renderTimelineDetail(payload);

  const rows = [
    ['Timestamp', tlFormatStamp(ev.t)],
    ev.t_end ? ['Session ended', tlFormatStamp(ev.t_end)] : null,
    ['Event type', ev.event_type],
    ev.amount != null ? ['Amount', `${ev.direction === 'credit' ? '+' : '−'}₹${Number(ev.amount).toLocaleString('en-IN')}`] : null,
    ev.counterparty ? ['Counterparty', ev.counterparty] : null,
    ev.location ? ['Location', ev.location] : null,
    ['Source file', ev.source_file || 'unknown'],
    ['Row reference', ev.row_ref != null ? `row ${ev.row_ref}` : 'not recorded'],
  ].filter(Boolean);

  panel.innerHTML = `
    ${ev.cited ? `<div class="tl-cited-flag"><i class="fa-solid fa-gavel"></i>
       This row is cited as evidence by a rule that fired on this entity.</div>` : ''}
    <table class="tl-detail-table">
      ${rows.map(([k, v]) => `<tr><th>${escapeHTML(k)}</th><td>${escapeHTML(String(v))}</td></tr>`).join('')}
    </table>`;
}

/* ── ENTITY NETWORK ─────────────────────────────────────────────── */
let rawNetworkNodes = [], rawNetworkEdges = [], networkVisData = {};

/* Both graphs from the last /api/results call, keyed by view name. */
let networkViews = null;
let activeNetworkView = 'money_flow';

const NETWORK_VIEW_META = {
  money_flow: {
    title: 'Money-Flow Network — Vis.js',
    breadcrumb: 'Money Flow',
    legend: [
      ['#FF4D4D', 'CRITICAL entity'],
      ['#FFB020', 'HIGH entity'],
      ['#3D7CFF', 'MEDIUM entity'],
      ['#2ECC71', 'LOW entity'],
      ['#FF4D4D', 'LAY-1 layering hop', 'edge'],
      ['#FFB020', 'TCS correlated transfer', 'edge'],
      ['rgba(61,124,255,0.55)', 'Transfer (width ∝ amount)', 'edge'],
      ['rgba(155,161,168,0.35)', 'Call / SMS (dashed)', 'edge'],
    ],
  },
  identity: {
    title: 'Identity Resolution Network — Vis.js',
    breadcrumb: 'Identity Graph',
    legend: [
      ['#3D7CFF', 'Phone'],
      ['#a78bfa', 'Account'],
      ['#2ECC71', 'VPA'],
      ['#FFB020', 'IMEI'],
      ['#f472b6', 'IP'],
    ],
  },
};

function initNetwork() {
  const container = document.getElementById('identity-network');
  if (!container) return;

  // Already built and the graphs are cached — just make sure vis.js re-measures the
  // container, which was hidden while another view was active.
  if (appState.networkInstance && networkViews) {
    appState.networkInstance.redraw();
    appState.networkInstance.fit();
    return;
  }

  if (networkViews) { setNetworkView(activeNetworkView); return; }

  // Try real data first
  fetch(`${API_BASE}/api/results`, { signal: AbortSignal.timeout(8000) })
    .then(r => r.json())
    .then(data => {
      if (data.network_views) {
        networkViews = data.network_views;
        setNetworkView(activeNetworkView);
      } else if (data.network) {
        // Older API shape — single graph, no toggle.
        initNetworkWithData(data.network);
      } else {
        initNetworkMock();
      }
    })
    .catch(() => initNetworkMock());
}

/* Switch between the money-flow and identity graphs. Both came from the same run;
   nothing is re-fetched or re-derived on the client. */
function setNetworkView(kind, btn) {
  if (!NETWORK_VIEW_META[kind]) return;
  activeNetworkView = kind;

  document.querySelectorAll('#network-view-toggle .filter-btn').forEach(b => {
    b.classList.toggle('active', b === btn || (!btn && b.dataset.view === kind));
  });

  const meta = NETWORK_VIEW_META[kind];
  const titleEl = document.getElementById('network-title');
  const crumbEl = document.getElementById('network-breadcrumb');
  if (titleEl) titleEl.textContent = meta.title;
  if (crumbEl) crumbEl.textContent = meta.breadcrumb;
  renderNetworkLegend(kind);

  if (!networkViews || !networkViews[kind]) return;

  // Force a rebuild — the two graphs have different node sets entirely.
  // Destroy the old vis.Network first; replacing the container's innerHTML alone
  // leaves its canvas, listeners and physics timer alive.
  if (appState.networkInstance) {
    try { appState.networkInstance.destroy(); } catch (e) { /* already gone */ }
    appState.networkInstance = null;
  }
  initNetworkWithData(networkViews[kind]);
  renderNetworkMeta(networkViews[kind].meta, kind);

  // Filters do not carry across a view switch: the two graphs share almost no
  // fields, so a tier filter left over from money-flow would blank the identity
  // graph for no visible reason.
  resetNetworkFilterState();
  const search = document.getElementById('network-search-input');
  if (search) search.value = '';
  const facets = (networkViews[kind].meta || {}).facets || {};
  buildNetworkQuickFilters(kind, facets);
  buildNetworkFilterBar(kind, facets);
  applyNetworkFilters();
}

function renderNetworkLegend(kind) {
  const el = document.getElementById('network-legend');
  if (!el) return;
  const items = (NETWORK_VIEW_META[kind] || {}).legend || [];
  el.innerHTML = items.map(([color, label, type]) => {
    const swatch = type === 'edge'
      ? `<span style="width:16px;height:0;border-top:3px solid ${color};flex-shrink:0;"></span>`
      : `<span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>`;
    return `<span class="legend-item">${swatch} ${label}</span>`;
  }).join('');
}

/* Counts come from the graph the backend returned — nothing here is a constant. */
function renderNetworkMeta(meta, kind) {
  const el = document.getElementById('network-meta');
  if (!el) return;
  if (!meta) { el.textContent = ''; return; }

  const parts = [];
  if (kind === 'money_flow') {
    parts.push(`${fmtNum(meta.rendered_nodes)} of ${fmtNum(meta.total_nodes)} entities`);
    parts.push(`${fmtNum(meta.transaction_edges)} transfers`);
    parts.push(`${fmtNum(meta.call_edges)} call links`);
    if (meta.total_value) parts.push(`₹${fmtNum(Math.round(meta.total_value))} tracked`);
    if (meta.layering_edges) parts.push(`${fmtNum(meta.layering_edges)} LAY-1 hops`);
    if (meta.hidden_isolated_nodes) parts.push(`${fmtNum(meta.hidden_isolated_nodes)} unconnected hidden`);
    if (meta.truncated) parts.push('truncated');
  } else {
    parts.push(`${fmtNum(meta.rendered_nodes)} identifiers`);
    parts.push(`${fmtNum(meta.rendered_edges)} KYC links`);
  }
  el.textContent = parts.join(' · ');
}

function fmtNum(n) {
  return (typeof n === 'number' ? n : 0).toLocaleString('en-IN');
}

function initNetworkMock() {
  // Build mock network from MOCK_POIS
  const nodes = [];
  const edges = [];
  let nodeId = 1;
  const idMap = {};

  MOCK_POIS.forEach(p => {
    const entityNodeId = nodeId++;
    idMap[p.id] = entityNodeId;
    nodes.push({ id: entityNodeId, label: p.name.split(' ')[0], title: `${p.name}\n${p.id}\nRisk: ${p.risk}%`, group: p.tier.toLowerCase(), shape: 'dot', size: 14 + p.risk / 10, font: { color: '#F2F3F4', size: 11 } });

    p.phones.slice(0, 1).forEach(ph => {
      const nid = nodeId++;
      nodes.push({ id: nid, label: ph.slice(-4), title: ph, group: 'phone', shape: 'dot', size: 10, font: { color: '#9BA1A8', size: 10 } });
      edges.push({ from: entityNodeId, to: nid, color: { color: 'rgba(61,124,255,0.3)' }, width: 1.5 });
    });

    p.accounts.slice(0, 1).forEach(ac => {
      const nid = nodeId++;
      nodes.push({ id: nid, label: ac.slice(-4), title: ac, group: 'account', shape: 'dot', size: 10, font: { color: '#9BA1A8', size: 10 } });
      edges.push({ from: entityNodeId, to: nid, color: { color: 'rgba(167,139,250,0.3)' }, width: 1.5 });
    });
  });

  // Cross-link related entities
  edges.push({ from: idMap['ENT-0037'], to: idMap['ENT-0041'], color: { color: 'rgba(255,77,77,0.3)' }, width: 2, dashes: true });
  edges.push({ from: idMap['ENT-0042'], to: idMap['ENT-0044'], color: { color: 'rgba(255,176,32,0.3)' }, width: 1.5, dashes: true });

  initNetworkWithData({ nodes, edges });
}

function initNetworkWithData(data) {
  const container = document.getElementById('identity-network');
  if (!container || !data || !data.nodes) return;

  rawNetworkNodes = data.nodes;
  rawNetworkEdges = data.edges;

  // Color scheme
  const groupColors = {
    critical: { background: 'rgba(255,77,77,0.8)', border: '#FF4D4D' },
    high: { background: 'rgba(255,176,32,0.8)', border: '#FFB020' },
    escalated: { background: 'rgba(255,176,32,0.8)', border: '#FFB020' },
    medium: { background: 'rgba(61,124,255,0.8)', border: '#3D7CFF' },
    low: { background: 'rgba(46,204,113,0.8)', border: '#2ECC71' },
    phone: { background: 'rgba(61,124,255,0.7)', border: '#3D7CFF' },
    account: { background: 'rgba(167,139,250,0.7)', border: '#a78bfa' },
    vpa: { background: 'rgba(46,204,113,0.7)', border: '#2ECC71' },
    imei: { background: 'rgba(255,176,32,0.7)', border: '#FFB020' },
    ip: { background: 'rgba(244,114,182,0.7)', border: '#f472b6' },
  };

  const styledNodes = rawNetworkNodes.map(n => ({
    ...n,
    color: groupColors[n.group] || { background: 'rgba(95,101,112,0.6)', border: '#5F6570' },
  }));

  const visNodes = new vis.DataSet(styledNodes);
  const visEdges = new vis.DataSet(rawNetworkEdges);
  networkVisData = { nodes: visNodes, edges: visEdges };

  // The money-flow graph is directed — an arrow is the difference between "these two
  // accounts transacted" and "this account paid that one". The identity graph is an
  // undirected ownership graph, so it keeps plain lines.
  const directed = activeNetworkView === 'money_flow';

  const options = {
    nodes: { borderWidth: 2, shadow: false },
    edges: {
      smooth: { type: 'cubicBezier', forceDirection: 'none' },
      // vis.js rejects the string 'none' here and logs an options error on every
      // load of the identity view; disabling the head is the supported way to draw
      // an undirected edge.
      arrows: { to: { enabled: directed, scaleFactor: 0.55 } },
      selectionWidth: 2,
    },
    physics: {
      stabilization: { iterations: directed ? 300 : 100 },
      // The money-flow graph is dense (≈150 nodes / 600 edges). Default repulsion
      // collapses it into a hairball where the flagged chain is unfindable, so push
      // the nodes much further apart and weaken the pull toward centre.
      barnesHut: directed
        ? { springLength: 260, springConstant: 0.02, gravitationalConstant: -14000,
            centralGravity: 0.12, damping: 0.4, avoidOverlap: 0.45 }
        : { springLength: 130, springConstant: 0.04 }
    },
    interaction: { hover: true, dragNodes: true, zoomView: true, tooltipDelay: 120 },
    layout: {},
  };

  container.innerHTML = '';
  appState.networkInstance = new vis.Network(container, { nodes: visNodes, edges: visEdges }, options);

  // Freeze physics after stabilization to eliminate GPU/CPU lag
  appState.networkInstance.once('stabilizationIterationsDone', () => {
    appState.networkInstance.setOptions({ physics: { enabled: false } });
  });
  appState.networkInstance.on('dragStart', () => {
    appState.networkInstance.setOptions({ physics: { enabled: true } });
  });
  appState.networkInstance.on('dragEnd', () => {
    appState.networkInstance.setOptions({ physics: { enabled: false } });
  });

  appState.networkInstance.on('selectNode', params => {
    const node = visNodes.get(params.nodes[0]);
    if (node) populateInspector(node);
  });
  appState.networkInstance.on('deselectNode', () => {
    document.getElementById('inspector-body').innerHTML = `<p class="inspector-hint"><i class="fa-solid fa-hand-pointer"></i> Click a node to inspect entity details.</p>`;
  });

  // Wiring up filters. The risk dropdown used to be wired here to an element that
  // did not exist anywhere in dashboard.html — it is now built by
  // buildNetworkFilterBar(), which also attaches its own listener.
  const searchInput = document.getElementById('network-search-input');
  if (searchInput && !searchInput._wired) {
    searchInput._wired = true;
    let debounce = null;
    searchInput.addEventListener('input', e => {
      networkFilterState.search = e.target.value;
      clearTimeout(debounce);
      debounce = setTimeout(applyNetworkFilters, 140);
    });
  }
  const resetBtn = document.getElementById('btn-reset-network');
  if (resetBtn && !resetBtn._wired) {
    resetBtn._wired = true;
    resetBtn.addEventListener('click', () => { if (appState.networkInstance) appState.networkInstance.fit(); });
  }
}

/* ── NETWORK FILTERS (S2.2) ───────────────────────────────────────────
   FR-IV.b. Every control below subsets the vis.js DataSets against a field the
   backend actually emits — edge.amount, edge.t_start/t_end, node.cities,
   node.rules_fired, node.risk_tier. Nothing here is decorative: if a facet is
   empty for the active graph, its control is not rendered at all.

   Filtering hides rather than removes, so the layout stays stable and clearing a
   filter restores the graph instantly without re-running physics. */

const networkFilterState = {
  quick: 'all', risk: 'all', rule: 'all', city: 'all', idType: 'all',
  amountMin: null, amountMax: null, timeFrom: null, timeTo: null, search: '',
};

function resetNetworkFilterState() {
  Object.assign(networkFilterState, {
    quick: 'all', risk: 'all', rule: 'all', city: 'all', idType: 'all',
    amountMin: null, amountMax: null, timeFrom: null, timeTo: null, search: '',
  });
}

const NETWORK_QUICK_FILTERS = {
  money_flow: [
    ['all', 'All entities'],
    ['flagged', 'Flagged only'],
    ['layering', 'Layering chain'],
    ['money', 'Transfers only'],
  ],
  identity: [['all', 'All identifiers']],
};

function buildNetworkQuickFilters(kind, facets) {
  const host = document.getElementById('network-quick-filters');
  if (!host) return;
  let defs = (NETWORK_QUICK_FILTERS[kind] || [['all', 'All']]).slice();
  if (kind === 'identity') {
    // Identity nodes are raw identifiers, so its quick filters are the identifier
    // types actually present in this run.
    (facets.id_types || []).forEach(t => defs.push([`type:${t}`, t.charAt(0).toUpperCase() + t.slice(1)]));
  }
  host.innerHTML = defs.map(([key, label]) =>
    `<button class="filter-btn ${networkFilterState.quick === key ? 'active' : ''}"
             data-quick="${escapeAttr(key)}"
             onclick="applyNetworkFilter('${escapeAttr(key)}',this)">${escapeHTML(label)}</button>`
  ).join('');
}

function buildNetworkFilterBar(kind, facets) {
  const host = document.getElementById('network-filter-bar');
  if (!host) return;
  facets = facets || {};

  const controls = [];

  if (kind === 'money_flow') {
    controls.push(`
      <label class="nf-field"><span>Risk tier</span>
        <select id="network-risk-filter">
          <option value="all">All tiers</option>
          <option value="CRITICAL">CRITICAL</option>
          <option value="HIGH">HIGH and above</option>
          <option value="MEDIUM">MEDIUM and above</option>
        </select>
      </label>`);

    if ((facets.rules || []).length) {
      controls.push(`
        <label class="nf-field"><span>Rule fired</span>
          <select id="network-rule-filter">
            <option value="all">Any rule</option>
            ${facets.rules.map(r => `<option value="${escapeAttr(r)}">${escapeHTML(r)}</option>`).join('')}
          </select>
        </label>`);
    }

    if (facets.amount_max > 0) {
      const max = Math.ceil(facets.amount_max);
      controls.push(`
        <label class="nf-field nf-wide"><span>Transfer amount ≥ <b id="nf-amount-label">₹0</b></span>
          <input type="range" id="network-amount-min" min="0" max="${max}" step="${Math.max(1, Math.round(max / 500))}" value="0">
        </label>`);
    }

    if (facets.time_min && facets.time_max) {
      const lo = String(facets.time_min).slice(0, 10);
      const hi = String(facets.time_max).slice(0, 10);
      controls.push(`
        <label class="nf-field"><span>From</span>
          <input type="date" id="network-time-from" min="${lo}" max="${hi}" value="${lo}"></label>
        <label class="nf-field"><span>To</span>
          <input type="date" id="network-time-to" min="${lo}" max="${hi}" value="${hi}"></label>`);
    }

    if ((facets.cities || []).length) {
      controls.push(`
        <label class="nf-field"><span>Location</span>
          <select id="network-city-filter">
            <option value="all">All cities</option>
            ${facets.cities.map(c => `<option value="${escapeAttr(c)}">${escapeHTML(c)}</option>`).join('')}
          </select>
        </label>`);
    }
  }

  controls.push(`<button class="btn btn-ghost btn-sm" id="network-clear-filters">
      <i class="fa-solid fa-filter-circle-xmark"></i> Clear filters</button>`);
  controls.push(`<span class="nf-status" id="network-filter-status"></span>`);

  host.innerHTML = controls.join('');

  const on = (id, evt, fn) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(evt, fn);
  };
  on('network-risk-filter', 'change', e => { networkFilterState.risk = e.target.value; applyNetworkFilters(); });
  on('network-rule-filter', 'change', e => { networkFilterState.rule = e.target.value; applyNetworkFilters(); });
  on('network-city-filter', 'change', e => { networkFilterState.city = e.target.value; applyNetworkFilters(); });
  on('network-amount-min', 'input', e => {
    networkFilterState.amountMin = Number(e.target.value) || 0;
    const label = document.getElementById('nf-amount-label');
    if (label) label.textContent = '₹' + Number(e.target.value || 0).toLocaleString('en-IN');
    applyNetworkFilters();
  });
  on('network-time-from', 'change', e => { networkFilterState.timeFrom = e.target.value || null; applyNetworkFilters(); });
  on('network-time-to', 'change', e => { networkFilterState.timeTo = e.target.value || null; applyNetworkFilters(); });
  on('network-clear-filters', 'click', () => {
    resetNetworkFilterState();
    const search = document.getElementById('network-search-input');
    if (search) search.value = '';
    buildNetworkQuickFilters(kind, facets);
    buildNetworkFilterBar(kind, facets);
    applyNetworkFilters();
  });
}

function applyNetworkFilter(type, btn) {
  networkFilterState.quick = type;
  document.querySelectorAll('#network-quick-filters .filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  applyNetworkFilters();
}

const TIER_AT_LEAST = {
  CRITICAL: ['CRITICAL'],
  HIGH: ['CRITICAL', 'HIGH'],
  MEDIUM: ['CRITICAL', 'HIGH', 'MEDIUM'],
};

function applyNetworkFilters() {
  const visNodes = networkVisData.nodes;
  const visEdges = networkVisData.edges;
  if (!visNodes || !visEdges) return;

  const f = networkFilterState;
  const term = (f.search || '').trim().toLowerCase();
  const fromTs = f.timeFrom ? Date.parse(f.timeFrom + 'T00:00:00') : null;
  const toTs = f.timeTo ? Date.parse(f.timeTo + 'T23:59:59') : null;

  // ---- which edges survive on their own properties ----
  const edgeVisible = new Map();
  rawNetworkEdges.forEach(e => {
    let ok = true;
    if (f.quick === 'money' && e.edge_type !== 'transaction') ok = false;
    if (f.quick === 'layering' && e.edge_class !== 'layering') ok = false;
    if (ok && f.amountMin && e.edge_type === 'transaction' && (e.amount || 0) < f.amountMin) ok = false;
    // A call edge carries no amount, so an amount filter would silently erase all
    // contact links; only transfers are subject to it.
    if (ok && (fromTs || toTs) && (e.t_start || e.t_end)) {
      const s = e.t_start ? Date.parse(e.t_start) : null;
      const en = e.t_end ? Date.parse(e.t_end) : s;
      // Keep an edge whose activity overlaps the range at all.
      if (fromTs && en != null && en < fromTs) ok = false;
      if (toTs && s != null && s > toTs) ok = false;
    }
    edgeVisible.set(e.id != null ? e.id : `${e.from}__${e.to}`, ok);
  });

  // ---- which nodes survive on their own properties ----
  const nodeVisible = new Map();
  rawNetworkNodes.forEach(n => {
    let ok = true;
    const tier = n.risk_tier;
    if (f.quick === 'flagged' && tier && tier === 'LOW') ok = false;
    if (ok && f.quick.startsWith('type:') && n.group !== f.quick.slice(5)) ok = false;
    if (ok && f.risk !== 'all' && tier) ok = (TIER_AT_LEAST[f.risk] || []).includes(tier);
    if (ok && f.rule !== 'all') ok = (n.rules_fired || []).includes(f.rule);
    if (ok && f.city !== 'all') ok = (n.cities || []).includes(f.city);
    nodeVisible.set(n.id, ok);
  });

  // ---- search: keep the hit and its immediate neighbourhood ----
  let searchHits = null;
  if (term) {
    searchHits = new Set();
    rawNetworkNodes.forEach(n => {
      const hay = [n.id, n.label, n.name, n.entity_id, ...(n.phones || []), ...(n.accounts || [])]
        .filter(Boolean).join(' ').toLowerCase();
      if (hay.includes(term)) searchHits.add(n.id);
    });
    // A lone matched dot with its edges stripped tells you nothing — keep the
    // node's direct counterparties so the hit stays in context.
    const keep = new Set(searchHits);
    rawNetworkEdges.forEach(e => {
      if (searchHits.has(e.from)) keep.add(e.to);
      if (searchHits.has(e.to)) keep.add(e.from);
    });
    rawNetworkNodes.forEach(n => {
      if (!keep.has(n.id)) nodeVisible.set(n.id, false);
    });
  }

  // ---- an edge also needs both of its endpoints ----
  const nodeUpdates = [];
  const edgeUpdates = [];
  let shownEdges = 0;
  rawNetworkEdges.forEach(e => {
    const key = e.id != null ? e.id : `${e.from}__${e.to}`;
    const ok = edgeVisible.get(key) && nodeVisible.get(e.from) && nodeVisible.get(e.to);
    edgeVisible.set(key, !!ok);
    if (ok) shownEdges++;
    // An edge without an id cannot be addressed in the DataSet; skip rather than
    // push an update keyed on undefined, which would throw.
    if (e.id != null) edgeUpdates.push({ id: e.id, hidden: !ok });
  });

  let shownNodes = 0;
  rawNetworkNodes.forEach(n => {
    const ok = !!nodeVisible.get(n.id);
    if (ok) shownNodes++;
    const update = { id: n.id, hidden: !ok };
    if (searchHits) {
      // Ring the actual matches so they are findable among their neighbours.
      update.borderWidth = searchHits.has(n.id) ? 4 : 2;
    } else {
      update.borderWidth = 2;
    }
    nodeUpdates.push(update);
  });

  visNodes.update(nodeUpdates);
  visEdges.update(edgeUpdates);

  const status = document.getElementById('network-filter-status');
  if (status) {
    const filtered = shownNodes !== rawNetworkNodes.length || shownEdges !== rawNetworkEdges.length;
    status.textContent = filtered
      ? `Showing ${fmtNum(shownNodes)} of ${fmtNum(rawNetworkNodes.length)} nodes · ${fmtNum(shownEdges)} of ${fmtNum(rawNetworkEdges.length)} edges`
      : `Showing all ${fmtNum(rawNetworkNodes.length)} nodes · ${fmtNum(rawNetworkEdges.length)} edges`;
    status.classList.toggle('active', filtered);
  }
}

/* ── EVIDENCE DRILL-DOWN (S2.3) ───────────────────────────────────────
   "Why this score?" answered with the source rows, not a paragraph.
   /api/entity/{id}/trace returns each rule's explanation, its evidence tokens and
   the raw event rows behind them. The endpoint has existed since day one and was
   called from nowhere; this is the click-through that uses it. */

const TRACE_CACHE = new Map();
let inspectorRequestId = 0;

/* Evidence tokens come in two shapes. A source reference — "row_219",
   "bank_row_219", "cdr_row_1018" — points at a line in an ingested file and is
   what an investigator needs to verify the claim. Everything else
   ("skim_pct:12.0", "chain:A>B>C") is structured metadata about the finding. */
const ROW_TOKEN_RE = /^(?:([a-z]+)_)?row_(.+)$/i;

function parseEvidenceToken(token) {
  const text = String(token);
  const m = text.match(ROW_TOKEN_RE);
  if (m) {
    // A row number is an integer; strip any float tail a pandas join introduced.
    const ref = m[2].replace(/\.0$/, '');
    return { kind: 'row', source: m[1] || null, ref, raw: text };
  }
  const idx = text.indexOf(':');
  if (idx > 0) return { kind: 'meta', key: text.slice(0, idx), value: text.slice(idx + 1), raw: text };
  return { kind: 'meta', key: null, value: text, raw: text };
}

async function fetchEntityTrace(entityId) {
  if (TRACE_CACHE.has(entityId)) return TRACE_CACHE.get(entityId);
  const res = await fetch(`${API_BASE}/api/entity/${encodeURIComponent(entityId)}/trace`,
    { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`trace ${res.status}`);
  const data = await res.json();
  TRACE_CACHE.set(entityId, data);
  return data;
}

async function loadInspectorEvidence(entityId) {
  // Clicking through nodes quickly must not let a slow earlier response paint
  // one entity's evidence under another entity's heading.
  const requestId = ++inspectorRequestId;
  try {
    const trace = await fetchEntityTrace(entityId);
    if (requestId !== inspectorRequestId) return;
    renderInspectorEvidence(trace);
  } catch (e) {
    if (requestId !== inspectorRequestId) return;
    const host = document.getElementById('inspector-evidence');
    if (host) {
      host.innerHTML = `<div style="font-size:11px;color:var(--text-muted);">
        <i class="fa-solid fa-triangle-exclamation"></i>
        Evidence rows unavailable (${escapeHTML(String(e.message || e))}).</div>`;
    }
  }
}

function renderInspectorEvidence(trace) {
  const host = document.getElementById('inspector-evidence');
  if (!host) return;

  const rules = trace.rules_fired || [];
  if (!rules.length) { host.innerHTML = ''; return; }

  // Index the entity's raw rows so an evidence token can be resolved to the
  // actual line it cites.
  const rowsByRef = new Map();
  (trace.raw_events || []).forEach(ev => {
    if (ev.raw_row_ref != null) rowsByRef.set(String(ev.raw_row_ref), ev);
  });

  const inr = v => '₹' + Math.abs(Number(v) || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

  const blocks = rules.map(ruleId => {
    const explanation = (trace.explanations || {})[ruleId] || '';
    const tokens = ((trace.evidence || {})[ruleId] || []).map(parseEvidenceToken);
    const rowTokens = tokens.filter(t => t.kind === 'row');
    const metaTokens = tokens.filter(t => t.kind === 'meta' && t.key &&
      !['severity', 'limbs', 'sub_level'].includes(t.key));

    const rowsHtml = rowTokens.length ? rowTokens.map(t => {
      const ev = rowsByRef.get(t.ref);
      const label = `${t.source ? t.source + ' ' : ''}row ${t.ref}`;
      if (!ev) {
        // The row belongs to a counterparty's file, not this entity's slice.
        return `<div class="ev-row"><span class="ev-row-ref">${escapeHTML(label)}</span>
                  <span class="ev-row-detail">referenced — not in this entity's rows</span></div>`;
      }
      const when = (ev.timestamp || '').slice(0, 19).replace('T', ' ');
      const bits = [when, ev.event_type];
      if (ev.amount) bits.push(`${(ev.direction === 'credit' || ev.amount > 0) ? '+' : '−'}${inr(ev.amount)}`);
      if (ev.counterparty) bits.push(`→ ${ev.counterparty}`);
      if (ev.location) bits.push(ev.location);
      return `<div class="ev-row">
                <span class="ev-row-ref" title="${escapeAttr(ev.source_file || '')}">${escapeHTML(label)}</span>
                <span class="ev-row-detail">${escapeHTML(bits.filter(Boolean).join(' · '))}</span>
              </div>`;
    }).join('') : `<div class="ev-row"><span class="ev-row-detail">No source row cited by this rule.</span></div>`;

    return `
      <div class="ev-rule-block">
        <div class="ev-rule-head">
          <span class="rule-chip">${escapeHTML(ruleId)}</span>
          ${metaTokens.map(t => `<span class="ev-tok" title="${escapeAttr(t.raw)}">${escapeHTML(t.key)}: ${escapeHTML(t.value)}</span>`).join('')}
        </div>
        ${explanation ? `<div class="ev-rule-expl">${escapeHTML(explanation)}</div>` : ''}
        <div class="ev-rows">${rowsHtml}</div>
      </div>`;
  }).join('');

  host.innerHTML = `
    <div style="font-size:11.5px;color:var(--text-muted);margin-bottom:6px;">
      Evidence — source rows behind each firing
    </div>
    ${blocks}
    <button class="btn btn-ghost btn-sm" style="margin-top:8px;width:100%;justify-content:center;"
            onclick="openEntityTimeline('${escapeAttr(trace.entity_id)}')">
      <i class="fa-solid fa-timeline"></i> Open timeline
    </button>
    <a class="btn btn-ghost btn-sm" style="margin-top:6px;width:100%;justify-content:center;"
       href="${API_BASE}/api/download-report/${encodeURIComponent(trace.entity_id)}">
      <i class="fa-solid fa-file-word"></i> Full forensic report
    </a>`;
}

function populateInspector(node) {
  const body = document.getElementById('inspector-body');
  if (!body) return;

  /* Money-flow nodes are resolved entities and carry their own real data — tier,
     the rules that actually fired, and the value that moved through them. Render
     that directly rather than looking the id up in a mock table. */
  if (node && node.risk_tier && node.entity_id) {
    const tier = node.risk_tier;
    const tierColor = tier === 'CRITICAL' ? 'var(--accent-danger)'
      : tier === 'HIGH' ? 'var(--accent-warning)'
        : tier === 'MEDIUM' ? 'var(--accent-primary)' : 'var(--accent-success)';
    const rules = node.rules_fired || [];
    const inr = v => '₹' + (Number(v) || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

    body.innerHTML = `
      <div style="margin-bottom:10px;">
        <div style="font-size:13px;font-weight:600;color:var(--text-primary);">${escapeHTML(node.name || node.entity_id)}</div>
        <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent-primary);margin-top:2px;">${escapeHTML(node.entity_id)}</div>
      </div>
      <div style="font-size:11.5px;color:var(--text-muted);">Risk Tier</div>
      <div style="font-size:18px;font-weight:800;font-family:var(--font-mono);color:${tierColor};">${escapeHTML(tier)}</div>
      <div style="margin-top:10px;font-size:11.5px;color:var(--text-muted);">Rules fired</div>
      <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">
        ${rules.length
          ? rules.map(r => {
              // IDR-1 grades itself HIGH/MEDIUM/LOW and that grade drives the tier,
              // so show which grade this firing carried.
              const sev = (node.rule_severities || {})[r];
              return `<span class="rule-chip" title="${escapeAttr(r + (sev ? ' — severity ' + sev : ''))}">${escapeHTML(r)}${sev ? ` <span style="opacity:.6;font-size:9px;">${escapeHTML(sev)}</span>` : ''}</span>`;
            }).join('')
          : '<span style="font-size:11.5px;color:var(--text-muted);">None — no rule fired on this entity</span>'}
      </div>
      ${node.ml_anomaly ? '<div style="margin-top:8px;font-size:11.5px;color:var(--accent-warning);"><i class="fa-solid fa-flask"></i> ML anomaly flagged</div>' : ''}
      <div style="margin-top:12px;font-size:11.5px;color:var(--text-muted);">Value through this entity</div>
      <div style="font-family:var(--font-mono);font-size:12px;margin-top:2px;">
        In ${inr(node.value_in)}<br>Out ${inr(node.value_out)}
      </div>
      <div style="margin-top:10px;font-size:11.5px;color:var(--text-muted);">Institution</div>
      <div style="font-size:12px;">${escapeHTML(node.institution || 'Unknown')}</div>
      <div id="inspector-evidence" style="margin-top:14px;border-top:1px solid var(--border-subtle);padding-top:10px;">
        ${rules.length
          ? '<div style="font-size:11px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Loading evidence rows…</div>'
          : ''}
      </div>
    `;
    if (rules.length) loadInspectorEvidence(node.entity_id);
    return;
  }

  const poi = MOCK_POIS.find(p => p.id === (node.entity_id || node.id));
  if (poi) {
    body.innerHTML = `
      <div style="margin-bottom:10px;">
        <div style="font-size:13px;font-weight:600;color:var(--text-primary);">${poi.name}</div>
        <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent-primary);margin-top:2px;">${poi.id}</div>
      </div>
      ${statusBadge(poi.tier.toLowerCase() === 'critical' ? 'critical' : poi.tier.toLowerCase() === 'high' ? 'escalated' : 'review')}
      <div style="margin-top:10px;font-size:11.5px;color:var(--text-muted);">Risk Tier</div>
      <div style="font-size:18px;font-weight:800;font-family:var(--font-mono);color:${['CRITICAL', 'HIGH'].includes(poi.tier) ? 'var(--accent-danger)' : poi.tier === 'MEDIUM' ? 'var(--accent-warning)' : 'var(--accent-success)'};">${poi.tier}</div>
      <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:4px;">${poi.rules.map(r => `<span class="rule-chip">${r}</span>`).join('')}</div>
      <button class="btn btn-ghost btn-sm" style="margin-top:12px;width:100%;justify-content:center;" onclick="openSlideOver('${poi.cases[0]}')">
        <i class="fa-solid fa-folder-open"></i> Open Case
      </button>
    `;
  } else {
    body.innerHTML = `
      <div style="font-size:12px;color:var(--text-secondary);">${node.label || node.id}</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:4px;font-family:var(--font-mono);">Type: ${node.group || 'unknown'}</div>
    `;
  }
}

/* ── MULTI-BUCKET UPLOAD ─────────────────────────────────────────── */
appState.bucketFiles = { cdr: [], ipdr: [], bank: [], other: [] };

function initUploadZone() {
  const buckets = ['cdr', 'ipdr', 'bank', 'other'];
  buckets.forEach(b => {
    const zone = document.getElementById(`zone-${b}`);
    const input = document.getElementById(`input-${b}`);
    if (!zone || !input) return;

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.style.borderColor = 'var(--orange)'; });
    zone.addEventListener('dragleave', () => { zone.style.borderColor = ''; });
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.style.borderColor = '';
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        handleBucketFiles(b, e.dataTransfer.files);
      }
    });
  });

  // Settings legacy single-zone support
  const legacyZone = document.getElementById('upload-zone');
  const legacyInput = document.getElementById('file-input');
  if (legacyZone && legacyInput) {
    legacyZone.addEventListener('dragover', e => { e.preventDefault(); legacyZone.style.borderColor = 'var(--orange)'; });
    legacyZone.addEventListener('dragleave', () => { legacyZone.style.borderColor = ''; });
    legacyZone.addEventListener('drop', e => { e.preventDefault(); legacyZone.style.borderColor = ''; handleBucketFiles('bank', e.dataTransfer.files); });
    legacyInput.addEventListener('change', () => handleBucketFiles('bank', legacyInput.files));
  }
}

function handleBucketFiles(bucket, fileList) {
  if (!appState.bucketFiles) appState.bucketFiles = { cdr: [], ipdr: [], bank: [], other: [] };
  const newFiles = Array.from(fileList);
  appState.bucketFiles[bucket] = [...(appState.bucketFiles[bucket] || []), ...newFiles];

  renderBucketList(bucket);
  updateUploadSummary();
}

/* Real SHA-256 of the staged file, computed in-browser with WebCrypto over the
   actual bytes. Returns null where WebCrypto is unavailable (insecure context) —
   in that case the UI shows nothing rather than inventing a digest. */
async function computeFileSHA256(file) {
  try {
    if (!window.crypto || !window.crypto.subtle) return null;
    const buf = await file.arrayBuffer();
    const digest = await window.crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}

function renderBucketList(bucket) {
  const list = document.getElementById(`list-${bucket}`);
  if (!list) return;
  const files = appState.bucketFiles[bucket] || [];
  list.innerHTML = '';
  files.forEach((f, idx) => {
    const iconClass = bucket === 'cdr' ? 'fa-phone' : bucket === 'ipdr' ? 'fa-wifi' : bucket === 'bank' ? 'fa-file-invoice-dollar' : 'fa-file-shield';
    const color = bucket === 'cdr' ? 'var(--orange)' : bucket === 'ipdr' ? '#3D7CFF' : bucket === 'bank' ? '#2ECC71' : '#a78bfa';
    const hashId = `stage-hash-${bucket}-${idx}`;

    const li = document.createElement('li');
    li.className = 'bucket-file-item';
    li.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;overflow:hidden;">
        <i class="fa-solid ${iconClass}" style="color:${color};flex-shrink:0;"></i>
        <span style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${f.name}</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;">
        <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">${formatBytes(f.size)}</span>
        <span id="${hashId}" style="font-family:var(--font-mono);font-size:9.5px;background:rgba(148,163,184,0.12);color:var(--text-muted);padding:1px 5px;border-radius:3px;" title="Computing SHA-256…">hashing…</span>
        <button onclick="removeBucketFile('${bucket}', ${idx})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;" title="Remove"><i class="fa-solid fa-xmark"></i></button>
      </div>
    `;
    list.appendChild(li);

    // Digest is computed asynchronously from the real file bytes.
    computeFileSHA256(f).then(hex => {
      const el = document.getElementById(hashId);
      if (!el) return;
      if (hex) {
        el.textContent = `${hex.slice(0, 12)}…`;
        el.title = `SHA-256 (WebCrypto): ${hex}`;
        el.style.background = 'rgba(46,204,113,0.1)';
        el.style.color = '#2ECC71';
      } else {
        el.remove();
      }
    });
  });
}

function removeBucketFile(bucket, index) {
  if (appState.bucketFiles && appState.bucketFiles[bucket]) {
    appState.bucketFiles[bucket].splice(index, 1);
    renderBucketList(bucket);
    updateUploadSummary();
  }
}

function clearAllUploads() {
  appState.bucketFiles = { cdr: [], ipdr: [], bank: [], other: [] };
  ['cdr', 'ipdr', 'bank', 'other'].forEach(b => renderBucketList(b));
  updateUploadSummary();
}

function updateUploadSummary() {
  const summaryEl = document.getElementById('upload-summary-text');
  if (!summaryEl) return;
  const b = appState.bucketFiles || {};
  const cdrCount = (b.cdr || []).length;
  const ipdrCount = (b.ipdr || []).length;
  const bankCount = (b.bank || []).length;
  const otherCount = (b.other || []).length;
  const total = cdrCount + ipdrCount + bankCount + otherCount;

  if (total === 0) {
    summaryEl.textContent = '0 files staged across 4 categories. Ready for automated parsing and entity fusion.';
  } else {
    summaryEl.textContent = `${total} file(s) staged — CDR: ${cdrCount}, IPDR: ${ipdrCount}, Bank: ${bankCount}, Artifacts: ${otherCount}. Ready for automated pipeline execution.`;
  }
}

function handleFiles(files) {
  handleBucketFiles('bank', files);
}

/* ── MODE TOGGLE ────────────────────────────────────────────────── */
function initModeToggle() {
  const toggle = document.getElementById('mode-toggle');
  const label = document.getElementById('mode-label');
  if (!toggle || !label) return;
  toggle.addEventListener('change', () => {
    appState.dataMode = toggle.checked ? 'upload' : 'demo';
    label.textContent = toggle.checked ? 'Upload Mode' : 'Demo Mode (Surat)';
  });
}

/* ── HELPERS ────────────────────────────────────────────────────── */
function statusBadge(status) {
  const map = {
    critical: 'CRITICAL', escalated: 'ESCALATED', active: 'ACTIVE',
    review: 'UNDER REVIEW', closed: 'CLOSED', archived: 'ARCHIVED',
    high: 'HIGH', medium: 'MEDIUM', low: 'LOW',
  };
  const label = map[status] || status.toUpperCase();
  return `<span class="badge badge-${status}">${label}</span>`;
}

function riskBar(score) {
  const color = score >= 80 ? 'var(--accent-danger)' : score >= 50 ? 'var(--accent-warning)' : score >= 25 ? 'var(--accent-primary)' : 'var(--accent-success)';
  return `
    <div class="risk-bar-wrap">
      <div class="risk-bar-bg">
        <div class="risk-bar-fill" style="width:${score}%;background:${color};"></div>
      </div>
      <span class="risk-val">${score}%</span>
    </div>
  `;
}

/* ── SERVICES / DOMAINS HOVER MODAL ANIMATION ───────────────────── */
function initServicesHover() {
  const listWrap = document.querySelector('.services-list-wrap');
  const rows = document.querySelectorAll('.project-row');
  const modalContainer = document.getElementById('services-modal');
  const modalSlider = document.getElementById('services-slider');
  const cursorBadge = document.getElementById('services-cursor');

  if (!listWrap || !rows.length || !modalContainer || !modalSlider) return;
  if (typeof gsap === 'undefined') return;

  let xMoveModal = gsap.quickTo(modalContainer, "left", { duration: 0.6, ease: "power3.out" });
  let yMoveModal = gsap.quickTo(modalContainer, "top", { duration: 0.6, ease: "power3.out" });

  let xMoveCursor = gsap.quickTo(cursorBadge, "left", { duration: 0.45, ease: "power3.out" });
  let yMoveCursor = gsap.quickTo(cursorBadge, "top", { duration: 0.45, ease: "power3.out" });

  listWrap.addEventListener('mousemove', (e) => {
    const rect = listWrap.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    xMoveModal(x);
    yMoveModal(y);
    xMoveCursor(x);
    yMoveCursor(y);
  });

  rows.forEach((row, idx) => {
    row.addEventListener('mouseenter', () => {
      modalContainer.classList.add('active');
      cursorBadge.classList.add('active');
      modalSlider.style.top = `${idx * -100}%`;
    });
  });

  listWrap.addEventListener('mouseleave', () => {
    modalContainer.classList.remove('active');
    cursorBadge.classList.remove('active');
  });
}

/* ── GOOEY TECH STACK INTERACTIVE ENGINE ────────────────────────── */
function initGooeyTechStack() {
  const tabsContainer = document.getElementById('gooey-tabs-filter');
  const blob = document.getElementById('gooey-tab-blob');
  const tabs = document.querySelectorAll('.gooey-tab');
  const cards = document.querySelectorAll('.gooey-card');

  if (!tabsContainer || !blob || !tabs.length) return;

  function moveBlobTo(tab) {
    const tabRect = tab.getBoundingClientRect();
    const containerRect = tabsContainer.getBoundingClientRect();

    const left = tabRect.left - containerRect.left;
    const width = tabRect.width;

    blob.style.left = `${left}px`;
    blob.style.width = `${width}px`;
  }

  // Initialize blob position on active tab
  const activeTab = document.querySelector('.gooey-tab.active') || tabs[0];
  setTimeout(() => moveBlobTo(activeTab), 100);

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      moveBlobTo(tab);

      const category = tab.getAttribute('data-category');

      cards.forEach((card) => {
        const cardCat = card.getAttribute('data-category');
        if (category === 'all' || cardCat === category || cardCat === 'all') {
          card.style.display = 'flex';
          setTimeout(() => {
            card.style.opacity = '1';
            card.style.transform = 'translateY(0) scale(1)';
          }, 50);
        } else {
          card.style.opacity = '0';
          card.style.transform = 'translateY(15px) scale(0.95)';
          setTimeout(() => {
            card.style.display = 'none';
          }, 300);
        }
      });
    });
  });

  window.addEventListener('resize', () => {
    const currActive = document.querySelector('.gooey-tab.active');
    if (currActive) moveBlobTo(currActive);
  });
}

/* ── INTERACTIVE HOVER GRID FOOTER CANVAS ENGINE ──────────────────── */
function initHoverGridFooter() {
  const footer = document.getElementById('footer');
  const canvas = document.getElementById('hover-grid');
  if (!footer || !canvas) return;

  const ctx = canvas.getContext('2d');

  // CONFIG TOKENS (Single source of truth)
  const CELL = 42; // Grid cell size in px
  const COLORS = ['#FF5C00', '#F4CABB', '#BFE5DA', '#EEE1E8', '#FFB020']; // Brand palette
  const RADIUS = 260; // Glow radius in px
  const LINE_COLOR = 'rgba(0, 0, 0, 0.08)'; // Grid line color

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isTouch = window.matchMedia('(hover: none)').matches;

  let cols = 0, rows = 0, cells = [];
  let mouse = { x: -9999, y: -9999, active: false };
  let dpr = Math.min(window.devicePixelRatio || 1, 2);
  let isVisible = true;
  let animFrameId = null;

  function resize() {
    const w = footer.clientWidth;
    const h = footer.clientHeight;
    if (!w || !h) return;

    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    cols = Math.ceil(w / CELL) + 1;
    rows = Math.ceil(h / CELL) + 1;
    cells = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        cells.push({
          x: c * CELL,
          y: r * CELL,
          color: COLORS[Math.floor(Math.random() * COLORS.length)],
          glow: 0,
          target: 0
        });
      }
    }
  }

  function dist(ax, ay, bx, by) {
    const dx = ax - bx, dy = ay - by;
    return Math.sqrt(dx * dx + dy * dy);
  }

  let lastTime = performance.now();
  function frame(now) {
    if (!isVisible) {
      animFrameId = null;
      return;
    }

    const dt = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;

    const w = footer.clientWidth;
    const h = footer.clientHeight;
    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < cells.length; i++) {
      const cell = cells[i];
      const cx = cell.x + CELL / 2;
      const cy = cell.y + CELL / 2;

      if (mouse.active) {
        const d = dist(cx, cy, mouse.x, mouse.y);
        if (d < RADIUS) {
          const t = 1 - (d / RADIUS);
          cell.target = Math.max(cell.target, t * t);
        }
      }

      if (reduceMotion) {
        cell.glow = cell.target;
      } else {
        cell.glow += (cell.target - cell.glow) * Math.min(dt * 10, 1);
        cell.target *= Math.pow(0.001, dt);
      }

      // Draw grid cell hairline outline
      ctx.strokeStyle = LINE_COLOR;
      ctx.lineWidth = 1;
      ctx.strokeRect(cell.x + 0.5, cell.y + 0.5, CELL, CELL);

      // Draw illuminated cell fill on hover
      if (cell.glow > 0.01) {
        ctx.save();
        ctx.globalAlpha = cell.glow * 0.85;
        ctx.fillStyle = cell.color;
        const pad = 3;
        ctx.fillRect(cell.x + pad, cell.y + pad, CELL - pad * 2, CELL - pad * 2);
        ctx.restore();
      }
    }

    animFrameId = requestAnimationFrame(frame);
  }

  // Mouse tracking
  if (!isTouch) {
    footer.addEventListener('mousemove', (e) => {
      const rect = footer.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.active = true;
    });

    footer.addEventListener('mouseleave', () => {
      mouse.active = false;
    });
  }

  // Pause rAF when off-screen for performance
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        isVisible = entry.isIntersecting;
        if (isVisible && !animFrameId) {
          lastTime = performance.now();
          animFrameId = requestAnimationFrame(frame);
        }
      });
    }, { threshold: 0.05 });
    observer.observe(footer);
  }

  window.addEventListener('resize', resize);
  resize();
  animFrameId = requestAnimationFrame(frame);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initServicesHover();
    initGooeyTechStack();
    initHoverGridFooter();
  });
} else {
  initServicesHover();
  initGooeyTechStack();
  initHoverGridFooter();
}


