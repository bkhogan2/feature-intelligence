export const BILLING_SETTINGS_LINK = "#settings?section=billing";

export function focusBillingSettings() {
  const heading = document.getElementById("billing-heading");
  heading?.focus({ preventScroll: true });
  heading?.scrollIntoView({ block: "start" });
}

export function currentSubscriptions<T extends { status: string }>(
  subscriptions: T[],
) {
  return subscriptions.filter(
    (subscription) =>
      !["canceled", "incomplete_expired"].includes(subscription.status),
  );
}

export function billingRedirect(
  url: string | undefined,
  kind: "checkout" | "portal",
) {
  if (!url) throw new Error("Billing did not return a redirect URL.");
  const parsed = new URL(url);
  const expected =
    kind === "checkout" ? "checkout.stripe.com" : "billing.stripe.com";
  if (
    parsed.protocol !== "https:" ||
    parsed.hostname !== expected ||
    parsed.username ||
    parsed.password ||
    parsed.port
  ) {
    throw new Error("Billing returned an unexpected redirect URL.");
  }
  return parsed.href;
}

export function formatPrice(plan: {
  currency: string;
  unit_amount: number;
  interval: string;
  interval_count: number;
}) {
  const formatter = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: plan.currency,
  });
  // Stripe preserves two-decimal API amounts for ISK/UGX despite zero-decimal display.
  const digits = ["isk", "ugx"].includes(plan.currency.toLowerCase())
    ? 2
    : (formatter.resolvedOptions().maximumFractionDigits ?? 2);
  const amount = formatter.format(plan.unit_amount / 10 ** digits);
  return `${amount} / ${plan.interval_count > 1 ? `${plan.interval_count} ` : ""}${plan.interval}${plan.interval_count > 1 ? "s" : ""}`;
}
