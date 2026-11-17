import { expect, test } from "bun:test";
import { hasFeature } from "../src/features/billing/entitlement-policy";
import {
  billingRedirect,
  formatPrice,
} from "../src/features/billing/billing-policy";

test("feature gates fail closed without an explicit server grant", () => {
  expect(hasFeature(undefined, "records.write")).toBe(false);
  expect(
    hasFeature(
      { billing_enabled: true, plan: "pro", features: [] },
      "records.write",
    ),
  ).toBe(false);
  expect(
    hasFeature(
      { billing_enabled: true, plan: "pro", features: ["records.write"] },
      "records.write",
    ),
  ).toBe(true);
  expect(
    hasFeature(
      { billing_enabled: false, plan: null, features: ["records.write"] },
      "unknown",
    ),
  ).toBe(false);
});

test("billing redirects accept only the expected hosted Stripe origin", () => {
  expect(
    billingRedirect("https://checkout.stripe.com/c/pay/test", "checkout"),
  ).toBe("https://checkout.stripe.com/c/pay/test");
  expect(
    billingRedirect("https://billing.stripe.com/p/session/test", "portal"),
  ).toContain("billing.stripe.com");
  for (const url of [
    "javascript:alert(1)",
    "https://checkout.stripe.com.evil.com/",
    "https://evil.com/",
    "http://checkout.stripe.com/",
    "https://user@checkout.stripe.com/",
    "https://checkout.stripe.com:8443/",
  ]) {
    expect(() => billingRedirect(url, "checkout")).toThrow();
  }
  expect(() => billingRedirect(undefined, "checkout")).toThrow();
});

test("plan prices show minor units and interval", () => {
  expect(
    formatPrice({
      currency: "isk",
      unit_amount: 500,
      interval: "month",
      interval_count: 1,
    }),
  ).toMatch(/5\D/);
  expect(
    formatPrice({
      currency: "usd",
      unit_amount: 2000,
      interval: "month",
      interval_count: 1,
    }),
  ).toContain("20.00");
  expect(
    formatPrice({
      currency: "jpy",
      unit_amount: 2000,
      interval: "year",
      interval_count: 1,
    }),
  ).toContain("2,000");
  expect(
    formatPrice({
      currency: "usd",
      unit_amount: 6000,
      interval: "month",
      interval_count: 3,
    }),
  ).toContain("3 months");
});
