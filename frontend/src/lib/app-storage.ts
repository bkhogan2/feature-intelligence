import { APP } from "./app-config";

export function storageKey(key: string) {
  return `${APP.id}:${key}`;
}
export function readSetting(key: string, fallback: string) {
  try {
    return localStorage.getItem(storageKey(key)) || fallback;
  } catch {
    return fallback;
  }
}
export function writeSetting(key: string, value: string) {
  try {
    localStorage.setItem(storageKey(key), value);
  } catch {
    /* Private browsing / full storage must not break the application. */
  }
}

export function migrateLegacySetting(key: string, legacyKey: string) {
  try {
    if (localStorage.getItem(storageKey(key)) === null) {
      const previous = localStorage.getItem(legacyKey);
      if (previous !== null) writeSetting(key, previous);
    }
  } catch {
    /* Optional migration must never block startup. */
  }
}
