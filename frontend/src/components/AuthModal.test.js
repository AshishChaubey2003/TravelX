/**
 * AuthModal — regression tests for FE-004 (login error branches), FE-005
 * (tab-switch resets form), FE-006 (DRF validation flatten), FE-013
 * (no console.log leaks).
 *
 * Local module mocks only. The ../api module is a project file — no
 * react-router-dom in sight, so no resolver issue.
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import toast from "react-hot-toast";

import AuthModal from "./AuthModal";
import { AuthProvider } from "../context/AuthContext";

// --- Mocks ---

jest.mock("../api", () => {
  const post = jest.fn();
  const login = jest.fn();
  const register = jest.fn();
  const API = { post };
  return {
    __esModule: true,
    default: API,
    login,
    register,
    createBooking: jest.fn(),
    createCheckout: jest.fn(),
    planTrip: jest.fn(),
    getCities: jest.fn(),
    getCity: jest.fn(),
    getHotels: jest.fn(),
    getAdventures: jest.fn(),
    getVehicles: jest.fn(),
  };
});

jest.mock("react-hot-toast", () => ({
  __esModule: true,
  default: {
    success: jest.fn(),
    error: jest.fn(),
  },
  Toaster: () => null,
}));

// Logo imports react-router-dom's `Link`, which Jest 27 cannot resolve
// against react-router-dom v7's broken package.json `main` field. Stubbing
// Logo as an empty component is non-invasive — AuthModal still renders
// everything else correctly.
jest.mock("./Logo", () => ({
  __esModule: true,
  default: () => null,
}));

const api = require("../api");

function _wrap(ui) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

beforeEach(() => {
  jest.clearAllMocks();
  try { localStorage.clear(); } catch (e) {}
});

// Both the login tab and the login submit button carry the word "Login".
// The submit button additionally contains "→" (arrow). Scope by that.
function _loginSubmit() {
  return screen.getByRole("button", { name: /Login →/ });
}
function _createAccountSubmit() {
  return screen.getByRole("button", { name: /Create Account/i });
}
function _loginTab() {
  return screen.getByRole("button", { name: /^Login$/i });
}
function _registerTab() {
  return screen.getByRole("button", { name: /^Sign Up$/i });
}

// --- Login error branching (FE-004) ---

test("login 401 shows 'Invalid username or password.'", async () => {
  api.login.mockRejectedValue({ response: { status: 401, data: { detail: "ignored" } } });
  _wrap(<AuthModal tab="login" onClose={() => {}} />);
  fireEvent.click(_loginSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith("Invalid username or password.");
});

test("login 429 surfaces the server's throttle detail", async () => {
  api.login.mockRejectedValue({
    response: {
      status: 429,
      data: { detail: "Request was throttled. Expected available in 42 seconds." },
    },
  });
  _wrap(<AuthModal tab="login" onClose={() => {}} />);
  fireEvent.click(_loginSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringContaining("throttled")
  );
});

test("login network error shows 'Network error' message", async () => {
  api.login.mockRejectedValue({ request: {} }); // no .response — axios shape for ECONNREFUSED
  _wrap(<AuthModal tab="login" onClose={() => {}} />);
  fireEvent.click(_loginSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringMatching(/network error/i)
  );
});

test("login 500 falls through to friendlyError fallback", async () => {
  api.login.mockRejectedValue({ response: { status: 500, data: {} } });
  _wrap(<AuthModal tab="login" onClose={() => {}} />);
  fireEvent.click(_loginSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringMatching(/login failed/i)
  );
});

// --- Register DRF error flattening (FE-006) ---

test("register 400 with DRF field errors surfaces the first field message", async () => {
  api.register.mockRejectedValue({
    response: {
      status: 400,
      data: { email: ["Enter a valid email address."] },
    },
  });
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  fireEvent.click(_createAccountSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringMatching(/email:.*valid email/i)
  );
});

test("register 400 with non_field_errors surfaces the message raw", async () => {
  api.register.mockRejectedValue({
    response: {
      status: 400,
      data: { non_field_errors: ["Pick a stronger password."] },
    },
  });
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  fireEvent.click(_createAccountSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith("Pick a stronger password.");
});

test("register 400 with legacy {error: ...} key is honoured", async () => {
  api.register.mockRejectedValue({
    response: { status: 400, data: { error: "Email already registered." } },
  });
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  fireEvent.click(_createAccountSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.error).toHaveBeenCalledWith("Email already registered.");
});

// --- Tab switch resets form (FE-005) ---

test("switching from register to login resets form state", () => {
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  const emailInput = screen.getByPlaceholderText(/enter email/i);
  fireEvent.change(emailInput, { target: { value: "x@y.z" } });
  expect(emailInput.value).toBe("x@y.z");
  fireEvent.click(_loginTab());
  const usernameInput = screen.getByPlaceholderText(/enter username/i);
  expect(usernameInput.value).toBe("");
});

// --- No console.log leaks (FE-013) ---

test("register success does not console.log the response payload", async () => {
  api.register.mockResolvedValue({ data: { message: "ok" } });
  const spy = jest.spyOn(console, "log").mockImplementation(() => {});
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  fireEvent.click(_createAccountSubmit());
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
  expect(spy).not.toHaveBeenCalled();
  spy.mockRestore();
});

test("register error does not console.log the error payload", async () => {
  api.register.mockRejectedValue({
    response: { status: 400, data: { email: ["bad"] } },
  });
  const spy = jest.spyOn(console, "log").mockImplementation(() => {});
  _wrap(<AuthModal tab="register" onClose={() => {}} />);
  fireEvent.click(_createAccountSubmit());
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(spy).not.toHaveBeenCalled();
  spy.mockRestore();
});
