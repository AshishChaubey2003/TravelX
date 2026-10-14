/**
 * FE-011/FE-019 — pure decision function extracted from ProtectedRoute so the
 * route-guard logic is unit-testable without importing react-router-dom
 * (react-router-dom v7's package.json `main` points at a non-existent file
 * and its `exports` map is not resolvable by the Jest 27 that CRA 5.0.1
 * ships — see docs/audit/FE_TESTING_OPTIONS.md).
 *
 * Contract: consumed ONLY by the thin wrapper in ProtectedRoute.js. The
 * wrapper re-attaches the full react-router `location` object to the
 * Navigate state (state.from), so navigation behaviour is byte-identical
 * to the pre-refactor component. `state.needAuth` lets the Home page open
 * the login modal automatically.
 */
export function protectedRouteDecision({ token, pathname }) {
  if (!token) {
    return {
      action: "redirect",
      to: "/",
      state: { needAuth: true, from: pathname },
    };
  }
  return { action: "render" };
}
