import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import type { AppearanceController } from "./use-appearance";

const themes = [
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
] as const;

export function AppearanceSettings({
  appearance,
}: {
  appearance: AppearanceController;
}) {
  const { theme, setTheme, saveAppearance, loadError } = appearance;
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await saveAppearance();
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <h2 className="text-lg font-medium">Appearance</h2>
      <Separator />
      <section className="space-y-3" aria-label="Theme">
        <h3 className="text-sm font-medium">Theme</h3>
        <div className="flex flex-wrap gap-2">
          {themes.map(({ id, label, icon: Icon }) => (
            <Button
              key={id}
              variant={theme === id ? "default" : "outline"}
              aria-pressed={theme === id}
              disabled={saving}
              onClick={() => {
                setTheme(id);
                setSaved(false);
                setError("");
              }}
            >
              <Icon className="size-4" />
              {label}
            </Button>
          ))}
        </div>
      </section>
      <Button onClick={() => void save()} disabled={saving}>
        {saving ? "Saving…" : "Save theme"}
      </Button>
      {(error || loadError) && <p role="alert">{error || loadError}</p>}
      {saved && (
        <p role="status" className="text-sm text-muted-foreground">
          Theme saved to your account.
        </p>
      )}
    </>
  );
}
