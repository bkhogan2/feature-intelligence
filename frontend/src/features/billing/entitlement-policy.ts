export type EntitlementSnapshot = {
  billing_enabled: boolean;
  plan: string | null;
  features: string[];
};

export function hasFeature(
  snapshot: EntitlementSnapshot | undefined,
  feature: string,
) {
  return snapshot?.features.includes(feature) === true;
}
