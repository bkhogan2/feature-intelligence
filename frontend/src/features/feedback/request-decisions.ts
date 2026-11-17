import { api } from "@/lib/auth-context";

export type RequestTriageState = {
  linked_opportunities?: { id: string }[];
  linked_opportunity: { id: string } | null;
  run: null | {
    id: string;
    status: string;
    result: null | { outcome: string };
  };
};

export async function rejectRequest(
  id: string,
  status: string,
  workspace: string,
) {
  await api(
    `/feedback/${id}/status`,
    {
      method: "PUT",
      body: JSON.stringify({ status: "rejected", expected_status: status }),
    },
    workspace,
  );
}

export type ApprovalJob = {
  status: "queued" | "running" | "complete" | "failed";
  error?: string | null;
};

// POST persists approval intent. Polling only observes; closing the browser
// cannot cancel the server job or prevent the opportunity from being linked.
export async function approveRequest(
  id: string,
  workspace: string,
  signal?: AbortSignal,
  expectedStatus = "new",
) {
  let job = await api<ApprovalJob>(
    `/feedback/${id}/approval`,
    {
      method: "POST",
      signal,
      body: JSON.stringify({ expected_status: expectedStatus }),
    },
    workspace,
  );
  while (["queued", "running"].includes(job.status)) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    signal?.throwIfAborted();
    job = await api<ApprovalJob>(
      `/feedback/${id}/approval`,
      { signal },
      workspace,
    );
  }
  if (job.status !== "complete")
    throw new Error(
      job.error || "Approval failed. Retry or link an opportunity manually.",
    );
}
