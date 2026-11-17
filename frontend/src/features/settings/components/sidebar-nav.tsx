// Adapted from satnaing/shadcn-admin settings/components/sidebar-nav.tsx.
// MIT license retained in licenses/shadcn-admin.txt.
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type SettingsNavItem = { id: string; title: string; icon: LucideIcon };
export function SidebarNav({
  items,
  active,
}: {
  items: SettingsNavItem[];
  active: string;
}) {
  return (
    <>
      <div className="p-1 @3xl:hidden">
        <Select
          value={active}
          onValueChange={(value) => {
            window.location.hash = `settings?section=${value}`;
          }}
        >
          <SelectTrigger aria-label="Settings section" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {items.map(({ id, title, icon: Icon }) => (
              <SelectItem key={id} value={id}>
                <span className="flex items-center gap-2">
                  <Icon className="size-4" />
                  {title}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <nav
        aria-label="Settings sections"
        className="hidden flex-col space-y-1 @3xl:flex"
      >
        {items.map(({ id, title, icon: Icon }) => (
          <a
            key={id}
            href={`#settings?section=${id}`}
            aria-current={active === id ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: "ghost" }),
              active === id
                ? "bg-muted hover:bg-accent"
                : "hover:bg-accent hover:underline",
              "justify-start",
            )}
          >
            <Icon className="size-4" />
            {title}
          </a>
        ))}
      </nav>
    </>
  );
}
