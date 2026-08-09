'use client';

import { TransitionRouter } from 'next-transition-router';
import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';

const CONFIG = {
  bgStrokeColor: '#F4CABB',    // Soft pastel peach background wave
  fgStrokeColor: '#2ECC71',    // Neon emerald green foreground wave
  maxStrokeWidth: 350,        // Stroke thickness to block out screen
  drawDuration: 0.8,          // Snappy sweep-in duration
  fadeDuration: 0.3,          // Base background overlay fade time
  stagger: 0.12,              // Lag delay between the two wave sweeps
};

export default function TransitionWrapper({ children }) {
  const transitionOverlayRef = useRef(null);
  const svgPathRef1 = useRef(null);
  const svgPathRef2 = useRef(null);
  const pathLengthRef = useRef(0);

  // Pre-calculate path lengths and set initial stroke positions
  useEffect(() => {
    const path = svgPathRef1.current;
    if (path) {
      const length = path.getTotalLength();
      pathLengthRef.current = length;

      // Setup initial hidden state for both lines
      gsap.set([svgPathRef1.current, svgPathRef2.current], {
        strokeDasharray: length,
        strokeDashoffset: length,
        strokeWidth: 2,
      });
    }
  }, []);

  return (
    <TransitionRouter
      auto
      leave={(next) => {
        const tl = gsap.timeline({ onComplete: next });
        const p1 = svgPathRef1.current;
        const p2 = svgPathRef2.current;

        // 1. Fade in the dim backdrop overlay
        tl.to(transitionOverlayRef.current, {
          opacity: 1,
          duration: CONFIG.fadeDuration,
          ease: 'power2.inOut',
        })
        // 2. Sweep the background wave across
        .to(p1, {
          strokeDashoffset: 0,
          strokeWidth: CONFIG.maxStrokeWidth,
          duration: CONFIG.drawDuration,
          ease: 'power2.inOut',
        }, 0)
        // 3. Sweep the foreground wave across (lagged by stagger delay)
        .to(p2, {
          strokeDashoffset: 0,
          strokeWidth: CONFIG.maxStrokeWidth - 50,
          duration: CONFIG.drawDuration,
          ease: 'power2.inOut',
        }, CONFIG.stagger);

        return () => tl.kill();
      }}
      enter={(next) => {
        const tl = gsap.timeline({ onComplete: next });
        const p1 = svgPathRef1.current;
        const p2 = svgPathRef2.current;
        const len = pathLengthRef.current;

        // 1. Sweep background wave out with smooth power3 deceleration
        tl.to(p1, {
          strokeDashoffset: -len,
          strokeWidth: 2,
          duration: 0.9,
          ease: 'power3.out',
        })
        // 2. Sweep foreground wave out (staggered)
        .to(p2, {
          strokeDashoffset: -len,
          strokeWidth: 2,
          duration: 0.9,
          ease: 'power3.out',
        }, CONFIG.stagger)
        // 3. Gentle background opacity fade-out overlapping the sweeps
        .to(transitionOverlayRef.current, {
          opacity: 0,
          duration: 0.6,
          ease: 'power2.out',
        }, 0.1)
        // 4. Reset lines back to starting positions
        .set([p1, p2], {
          strokeDashoffset: len,
          strokeWidth: 2,
        });

        return () => tl.kill();
      }}
    >
      {/* Full screen layout overlay layer */}
      <div 
        ref={transitionOverlayRef} 
        className="fixed inset-0 pointer-events-none z-[9999] flex items-center justify-center opacity-0 bg-zinc-950/20 backdrop-blur-xs"
      >
        <svg
          width="100%"
          height="100%"
          viewBox="0 0 1316 664"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-full scale-130 h-full"
          preserveAspectRatio="xMidYMid slice"
        >
          {/* Layer 1: Background Wave Path */}
          <path
            ref={svgPathRef1}
            d="M13.4746 291.27C13.4746 291.27 100.646 -18.6724 255.617 16.8418C410.588 52.356 61.0296 431.197 233.017 546.326C431.659 679.299 444.494 21.0125 652.73 100.784C860.967 180.556 468.663 430.709 617.216 546.326C765.769 661.944 819.097 48.2722 988.501 120.156C1174.21 198.957 809.424 543.841 988.501 636.726C1189.37 740.915 1301.67 149.213 1301.67 149.213"
            stroke={CONFIG.bgStrokeColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Layer 2: Foreground Wave Path */}
          <path
            ref={svgPathRef2}
            d="M13.4746 291.27C13.4746 291.27 100.646 -18.6724 255.617 16.8418C410.588 52.356 61.0296 431.197 233.017 546.326C431.659 679.299 444.494 21.0125 652.73 100.784C860.967 180.556 468.663 430.709 617.216 546.326C765.769 661.944 819.097 48.2722 988.501 120.156C1174.21 198.957 809.424 543.841 988.501 636.726C1189.37 740.915 1301.67 149.213 1301.67 149.213"
            stroke={CONFIG.fgStrokeColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      {children}
    </TransitionRouter>
  );
}
