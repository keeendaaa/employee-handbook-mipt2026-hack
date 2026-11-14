import { useReducedMotion } from "motion/react";
/** Fast functional motion; state and API actions never wait for the animation. */
export function useUiTransition() {
  const reduce = useReducedMotion();
  return { duration: reduce ? 0 : 0.15, ease: [0.2, 0, 0, 1] as const };
}
