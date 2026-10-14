/**
 * FE-011/FE-019 — unit tests for the pure route-guard decision, approved in
 * Milestone 11. These tests prove the redirect/render decision logic without
 * importing react-router-dom (blocked under Jest 27 — see
 * docs/audit/FE_TESTING_OPTIONS.md). The wrapper's Navigate wiring remains
 * verified by reading + browser QA, not by these tests.
 */
import { protectedRouteDecision } from "./protectedRouteDecision";

test("null token redirects to / with needAuth flag and from pathname", () => {
  const r = protectedRouteDecision({ token: null, pathname: "/my-bookings" });
  expect(r.action).toBe("redirect");
  expect(r.to).toBe("/");
  expect(r.state).toEqual({ needAuth: true, from: "/my-bookings" });
});

test("undefined token redirects (logged out before context hydrates)", () => {
  const r = protectedRouteDecision({ token: undefined, pathname: "/x" });
  expect(r.action).toBe("redirect");
});

test("empty-string token redirects (treated as logged out)", () => {
  const r = protectedRouteDecision({ token: "", pathname: "/x" });
  expect(r.action).toBe("redirect");
});

test("non-empty token renders children", () => {
  const r = protectedRouteDecision({ token: "any-jwt-value", pathname: "/x" });
  expect(r.action).toBe("render");
  expect(r.to).toBeUndefined();
  expect(r.state).toBeUndefined();
});

test("decision is pure — identical inputs give identical outputs", () => {
  const a = protectedRouteDecision({ token: null, pathname: "/a" });
  const b = protectedRouteDecision({ token: null, pathname: "/a" });
  expect(a).toEqual(b);
});
