import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type View = "board" | "list" | "table";
const names = { board: "Board", list: "List", table: "Table" };

export function ViewSwitch<T extends View>({ value, views, onChange, label }: {
  value: T;
  views: readonly T[];
  onChange: (view: T) => void;
  label: string;
}) {
  return (
    <Tabs value={value} onValueChange={(next) => {
      const view = views.find((candidate) => candidate === next);
      if (view) onChange(view);
    }}>
      <TabsList aria-label={label}>
        {views.map((view) => <TabsTrigger key={view} value={view}>{names[view]}</TabsTrigger>)}
      </TabsList>
    </Tabs>
  );
}
