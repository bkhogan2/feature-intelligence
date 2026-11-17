# Feature Intelligence manual QA checklist

Use the hosted demo or a local workspace with separate submitter and reviewer
accounts. Open each account in a separate browser profile. Use clearly labeled
synthetic requests, including two that describe the same problem, and archive test
records when finished. Record the build, account role, and steps for any failure.

## Demo walkthrough

- [ ] Open Opportunities before any approvals. The table headers, view switch, and filters are visible with zero rows.
- [ ] Submit a request with a title, customer problem, and example. Confirm the saved state and find it in Requests as New.
- [ ] Open Notifications as the submitter. Confirm one unread thank-you receipt, open it, and check that it lands on the request and marks the receipt read.
- [ ] Approve the request as the reviewer. Wait for AI linking to finish and verify the request is Approved and linked to a new opportunity with the original request as evidence.
- [ ] Submit and approve a related request. Verify it lands on the existing opportunity and the evidence count increases without creating a duplicate opportunity for the same problem.
- [ ] Reject a third request. Confirm it is Rejected and creates no opportunity.
- [ ] Check the submitter’s approval and rejection notifications. Each opens the matching request and marks itself read.
- [ ] Review opportunity evidence and priority. Draft priorities with AI, edit or exclude proposals, and save only the changes you intend.
- [ ] Move the opportunity to Planned. Draft sub-issues with AI, edit and deselect drafts, then create the selected tasks in Backlog.
- [ ] Move a task between board lanes and verify its status persists in the table and detail page. Move the opportunity to Shipped and record an outcome with evidence.
- [ ] Draft a submitter update, edit it, then publish. Confirm the published text appears in linked request conversations and eligible recipients’ Notifications.

## Regression passes

- [ ] **Session and permissions:** Sign in and out, refresh a deep link, and verify expiry returns to sign-in. Check viewer restrictions and workspace isolation with local test accounts.
- [ ] **Request validation and retries:** Try blank input, retry a submission with the same key, and refresh after submitting. Confirm one request and one receipt, with no receipt for failed submissions or unrelated users.
- [ ] **Discovery and support:** Search, filter, sort, paginate, and open requests. Toggle support and confirm counters persist. Test bulk selection across filtered views.
- [ ] **Decision edge cases:** Approve manually linked requests, including multiple links. Test bulk review with a subset, a failed AI run, a stale decision, and a retry. Check that pending or failed approvals produce no approval notice and repeats produce no duplicates.
- [ ] **Clarification and comments:** Ask a question, reply as the submitter, and confirm the request returns to review. Verify Markdown preview and persisted comments on requests, opportunities, and tasks where supported.
- [ ] **Notifications:** Verify receipts and decisions reach only the submitter; published updates also reach eligible supporters. Check unread counts, read/unread, archive/restore, and authorization from another account.
- [ ] **Opportunities:** Check table/list/board views, status and priority filters, inline and bulk edits, linking, description editing, and archival/restore. Recheck the table after clearing a filter and after archiving the final active row.
- [ ] **Tasks:** Create manually, edit details, filter by opportunity/status/assignee, use bulk operations, and verify reorder, cross-lane drag, and status persistence after refresh.
- [ ] **Assistant:** Ask an evidence question from a request or opportunity, follow a citation, and verify a fresh prompt and a failure state behave as expected.
- [ ] **Layout and navigation:** Check widths with the assistant open, keyboard focus, browser Back, direct links, and scrolling to the bottom of each detail view.
