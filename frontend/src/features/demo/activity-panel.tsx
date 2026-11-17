import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
export function ActivityPanel({ workspace }: { workspace: string }) {
  const [rows, setRows] = useState<
    { id: string; action: string; created_at: string }[]
  >([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    api<typeof rows>("/activity", {}, workspace)
      .then((data) => {
        if (alive) setRows(data);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [workspace]);
  return (
    <div className="mx-auto w-full max-w-4xl">
      <h1 className="text-2xl font-semibold">Activity</h1>
      {error && <p role="alert">{error}</p>}
      <ul className="mt-6 divide-y rounded-lg border">
        {rows.length ? (
          rows.map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap justify-between gap-2 p-4 text-sm"
            >
              <span>{r.action.replaceAll(".", " ")}</span>
              <span className="text-muted-foreground">
                {new Date(r.created_at).toLocaleString()}
              </span>
            </li>
          ))
        ) : (
          <li className="p-6 text-sm text-muted-foreground">
            No activity yet.
          </li>
        )}
      </ul>
    </div>
  );
}
