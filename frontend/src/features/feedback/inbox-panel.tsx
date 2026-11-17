import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, useAuth } from "@/lib/auth-context";
import { useSelectedAssistantContext } from "@/lib/assistant-context";
import { Button } from "@/components/ui/button";
import { RequestDetail } from "./request-detail";
import { type FeedbackSupport } from "./feedback-support";

import {
  RequestTable,
  type RequestItem,
  type RequestPatch,
} from "./request-table";

type Feedback = RequestItem & FeedbackSupport;
type FeedbackPage = { items: Feedback[]; has_more: boolean };
function readRoute() {
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  return {
    id: params.get("id") || params.get("request"),
    status: params.get("status") || "all",
    search: params.get("search") || "",
  };
}
export function InboxPanel({
  workspace,
  userId,
}: {
  workspace: string;
  userId: string;
}) {
  const { active } = useAuth();
  const canEdit =
    active?.workspace_slug === workspace &&
    (active.role === "admin" || active.role === "editor");
  const [notice, setNotice] = useState("");
  const [route, setRoute] = useState(readRoute);
  const [selectedId, setSelectedId] = useState<string | null>(route.id);
  const [items, setItems] = useState<Feedback[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const navigate = () => {
      const next = readRoute();
      setRoute(next);
      setSelectedId(next.id);
      setNotice("");
    };
    window.addEventListener("hashchange", navigate);
    return () => window.removeEventListener("hashchange", navigate);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setItems([]);
    let poll: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const all: Feedback[] = [];
        let hasMore = true;
        while (hasMore) {
          const params = new URLSearchParams({
            status: "all",
            limit: "100",
            offset: String(all.length),
          });
          const page = await api<FeedbackPage>(
            `/feedback?${params}`,
            { signal: controller.signal },
            workspace,
          );
          if (controller.signal.aborted) return;
          if (page.has_more && !page.items.length)
            throw new Error(
              "The request list could not be fully loaded. Please retry.",
            );
          all.push(...page.items);
          hasMore = page.has_more;
        }
        if (!controller.signal.aborted) {
          setItems(all);
          if (
            all.some((item) =>
              ["queued", "running"].includes(item.approval_status ?? ""),
            )
          )
            poll = setTimeout(load, 2000);
        }
      } catch (err) {
        if (!controller.signal.aborted) setError((err as Error).message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(poll);
    };
  }, [workspace, revision]);
  const visibleItems = items;
  const selected = items.find((item) => item.id === selectedId);
  const selectedIndex = visibleItems.findIndex(
    (item) => item.id === selectedId,
  );
  const update = async (ids: string[], patch: RequestPatch) => {
    const saved = await api<{ items: Feedback[] }>(
      "/feedback/bulk",
      {
        method: "PATCH",
        body: JSON.stringify({ ids, ...patch }),
      },
      workspace,
    );
    setItems((current) =>
      current.map(
        (item) => saved.items.find((value) => value.id === item.id) || item,
      ),
    );
  };
  useSelectedAssistantContext(
    workspace,
    "feedback",
    selected?.id,
    selected?.title,
  );
  const openRequest = useCallback((id: string) => {
    const params = new URLSearchParams(
      window.location.hash.split("?")[1] || "",
    );
    params.set("id", id);
    window.location.hash = `inbox?${params}`;
    setSelectedId(id);
  }, []);
  const backParams = new URLSearchParams(
    window.location.hash.split("?")[1] || "",
  );
  backParams.delete("id");
  backParams.delete("request");
  const backHref = `#inbox${backParams.size ? `?${backParams}` : ""}`;
  return (
    <section
      className={`h-full min-w-0 overflow-y-auto ${selectedId ? "" : "p-4 md:p-6"}`}
      aria-label="Requests"
    >
      <div hidden={!!selectedId}>
        {loading ? (
          <p
            role="status"
            className="py-10 text-center text-sm text-muted-foreground"
          >
            Loading requests…
          </p>
        ) : error ? (
          <div role="alert" className="space-y-3 py-8">
            <p className="text-sm text-destructive">
              Could not load requests: {error}
            </p>
            <Button
              variant="outline"
              onClick={() => setRevision((value) => value + 1)}
            >
              Try again
            </Button>
          </div>
        ) : (
          <RequestTable
            key={`${workspace}:${route.status}:${route.search}`}
            workspace={workspace}
            onDecision={(id, status) =>
              setItems((current) =>
                current.map((item) =>
                  item.id === id
                    ? {
                        ...item,
                        status,
                        approval_status: null,
                        approval_error: null,
                      }
                    : item,
                ),
              )
            }
            onTriageConfirmed={(ids) =>
              setItems((current) =>
                current.map((item) =>
                  ids.includes(item.id) ? { ...item, status: "triaged" } : item,
                ),
              )
            }
            items={visibleItems}
            onBulkChange={update}
            canEdit={canEdit}
            onOpen={openRequest}
            initialStatus={route.status}
            initialSearch={route.search}
          />
        )}
        <div className="mt-4 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            Original feedback and recorded support. Decisions and archive
            changes are saved to this workspace.
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={loading}
            onClick={() => setRevision((value) => value + 1)}
          >
            <RefreshCw className="mr-2 size-3.5" />
            Refresh
          </Button>
        </div>
      </div>
      {selectedId &&
        (selected ? (
          <RequestDetail
            key={`${workspace}:${selected.id}`}
            item={selected}
            workspace={workspace}
            userId={userId}
            backHref={backHref}
            canEdit={canEdit}
            update={update}
            notice={notice}
            previous={
              selectedIndex > 0
                ? () => openRequest(visibleItems[selectedIndex - 1].id)
                : undefined
            }
            next={
              selectedIndex >= 0 && selectedIndex < visibleItems.length - 1
                ? () => openRequest(visibleItems[selectedIndex + 1].id)
                : undefined
            }
            onSupport={(support) =>
              setItems((current) =>
                current.map((item) =>
                  item.id === selected.id ? { ...item, ...support } : item,
                ),
              )
            }
            onConfirmed={() => {
              setNotice("Request updated.");
              setRevision((value) => value + 1);
            }}
          />
        ) : (
          <div className="p-6">
            <a href={backHref}>← Requests</a>
            <p role="status">
              {loading
                ? "Loading request…"
                : error
                  ? "Request unavailable while loading failed."
                  : "This request is not available in this workspace."}
            </p>
          </div>
        ))}
    </section>
  );
}
