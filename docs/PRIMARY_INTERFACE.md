# Primary interface promotion

`feature-intelligence-system` is the primary application. Its Requests and Opportunities screens use the promoted Tablecn tables and opportunity Kanban board, connected to the primary authenticated API. `feature-intelligence-table-prototype` remains a reference copy.

Migration `0014_table_bulk.sql` adds request priority, recoverable request archival, opportunity archival, and persisted board order. Bulk mutations are editor/admin-only, tenant-scoped, transactional, and audited. Opportunity lifecycle changes retain decision history and expected-status checks. Priority confirmation remains in the existing opportunity detail workflow.

The migration has **not been applied** to the running database. Run the existing migration workflow with the configured schema-owner connection before starting this backend version. Database integration verification remains pending: database credentials were unavailable in the current environment, the local Docker daemon was not running, and the installed local PostgreSQL binary could not start. No database/system repairs were performed.

Validation completed: primary frontend production build; 33 frontend tests (301 assertions); backend Ruff checks. Live browser visual QA remains pending because computer/browser access was unavailable. The new real-PostgreSQL bulk integration tests have been written but have not passed a database-backed run yet.

No Git rebase or commits were performed. Both application folders were untracked under the parent repository's `main` branch during promotion, so this was a file-level promotion rather than a branch rebase. Work now continues on `feature/opportunities-review`; the user must review it before any merge. No merge or push has been performed.
