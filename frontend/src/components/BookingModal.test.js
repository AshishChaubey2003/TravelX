/**
 * BookingModal — regression tests for FE-009 (Idempotency-Key sent + stable
 * across re-renders), FE-014 (past-date rejection), and F-017 behaviour
 * (no `nights` sent in request body).
 *
 * Local module mocks only. BookingModal does not import react-router-dom.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import toast from "react-hot-toast";

import BookingModal from "./BookingModal";

// --- Mocks ---

jest.mock("../api", () => {
  const post = jest.fn();
  return {
    __esModule: true,
    default: { post },
    createBooking: jest.fn(),
  };
});

jest.mock("../context/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ token: "fake-jwt-token", user: null }),
}));

jest.mock("react-hot-toast", () => ({
  __esModule: true,
  default: { success: jest.fn(), error: jest.fn() },
  Toaster: () => null,
}));

const api = require("../api");

beforeEach(() => {
  jest.clearAllMocks();
  // Stub window.Razorpay to prevent "new window.Razorpay is not a constructor"
  window.Razorpay = jest.fn().mockImplementation(() => ({ open: jest.fn() }));
});

// Helper queries. The modal inputs don't have id/htmlFor associations, so
// RTL's getByLabelText fails. We instead query by the stable DOM attribute
// `type="date"` for the two date fields, and by button text for the pay
// button. This matches the real selector a user's screen reader would use.
function _dateInputs(container) {
  return Array.from(container.querySelectorAll('input[type="date"]'));
}
function _confirmButton() {
  // Button text contains the arrow emoji + "Razorpay"; match on "Razorpay"
  // which is uniquely present on this one button.
  return screen.getByRole("button", { name: /Razorpay/i });
}

const hotelItem = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Test Hotel",
  price_per_night: 1000,
};

function _render(overrides = {}) {
  return render(
    <BookingModal
      type="hotel"
      item={overrides.item || hotelItem}
      onClose={overrides.onClose || (() => {})}
    />
  );
}

// --- FE-009: Idempotency-Key is sent on booking POST ---

test("booking POST includes an Idempotency-Key header shaped like a UUID", async () => {
  api.default.post.mockResolvedValueOnce({ data: { id: "booking-uuid" } });
  api.default.post.mockResolvedValueOnce({
    data: {
      order_id: "order_x", amount: 100000, currency: "INR",
      key_id: "rzp_key", user_email: "u@x", user_name: "u",
    },
  });

  _render();
  fireEvent.click(_confirmButton());

  await waitFor(() => expect(api.default.post).toHaveBeenCalled());
  const firstCall = api.default.post.mock.calls[0];
  expect(firstCall[0]).toBe("/bookings/");
  expect(firstCall[2]).toBeDefined();
  expect(firstCall[2].headers).toBeDefined();
  const key = firstCall[2].headers["Idempotency-Key"];
  // In production (modern browsers) this is a crypto.randomUUID() output;
  // under Jest/jsdom crypto.randomUUID may be unavailable and the Math.random
  // fallback runs — see _generateIdempotencyKey in BookingModal.js. Accept
  // either shape: non-empty, hyphenated, alphanumeric. Length >= 20 is
  // sufficient to establish uniqueness-per-modal.
  expect(typeof key).toBe("string");
  expect(key.length).toBeGreaterThan(20);
  expect(key).toMatch(/^[0-9a-z\-]+$/i);
});

test("Idempotency-Key stays the same when the user clicks Confirm twice", async () => {
  api.default.post.mockResolvedValue({
    data: {
      id: "b1", order_id: "o1", amount: 100000, currency: "INR",
      key_id: "k", user_email: "e", user_name: "n",
    },
  });

  _render();
  fireEvent.click(_confirmButton());
  await waitFor(() => expect(api.default.post).toHaveBeenCalled());

  const firstBookingCall = api.default.post.mock.calls.find(
    (c) => c[0] === "/bookings/"
  );
  const firstKey = firstBookingCall[2].headers["Idempotency-Key"];

  fireEvent.click(_confirmButton());
  await waitFor(() =>
    expect(
      api.default.post.mock.calls.filter((c) => c[0] === "/bookings/").length
    ).toBeGreaterThanOrEqual(2)
  );
  const retryBookingCall = api.default.post.mock.calls
    .filter((c) => c[0] === "/bookings/")[1];
  expect(retryBookingCall[2].headers["Idempotency-Key"]).toBe(firstKey);
});

// --- F-017: nights is NOT sent in the body ---

test("booking POST body does NOT include the `nights` key", async () => {
  api.default.post.mockResolvedValue({
    data: {
      id: "b2", order_id: "o2", amount: 100000, currency: "INR",
      key_id: "k", user_email: "e", user_name: "n",
    },
  });

  _render();
  fireEvent.click(_confirmButton());
  await waitFor(() => expect(api.default.post).toHaveBeenCalled());
  const bookingCall = api.default.post.mock.calls.find((c) => c[0] === "/bookings/");
  expect(bookingCall).toBeDefined();
  const body = bookingCall[1];
  expect(body).toHaveProperty("hotel_id");
  expect(body).toHaveProperty("check_in");
  expect(body).toHaveProperty("check_out");
  expect(body).not.toHaveProperty("nights");
});

// --- FE-014: past-date rejection on the client ---

test("past check_in blocks the submission with a toast, no API call", async () => {
  const { container } = _render();
  const yesterday = new Date(Date.now() - 2 * 86400000).toISOString().split("T")[0];
  const [checkIn] = _dateInputs(container);  // first date input is Check In
  fireEvent.change(checkIn, { target: { value: yesterday } });
  fireEvent.click(_confirmButton());
  expect(api.default.post).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringMatching(/past/i)
  );
});

test("check_out <= check_in blocks the submission with a toast", async () => {
  const { container } = _render();
  const today = new Date().toISOString().split("T")[0];
  const [_checkIn, checkOut] = _dateInputs(container);  // second = Check Out
  fireEvent.change(checkOut, { target: { value: today } });
  fireEvent.click(_confirmButton());
  expect(api.default.post).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith(
    expect.stringMatching(/check-out must be after check-in/i)
  );
});
