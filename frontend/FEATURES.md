# Frontend feature boundaries

- `src/app.tsx`: sign-in gates, invitation handoff, workspace selection, and page composition.
- `src/features/appearance`: appearance controls and their local/account persistence. Layout, rails, header style, and sidebar choices remain independent.
- `src/features/workspace`: reusable membership administration and invitation acceptance.
- `src/features/settings`: composes appearance and administrator-only workspace controls.
- `src/features/demo`: sample home, records, and activity screens to replace when starting another application.
- `src/components`: shared shell, assistant, login, and UI primitives.
- `src/lib/app-config.ts`: branding, navigation, assistant presentation, and panel sizing defaults.

The demo records route remains `#projects`. Its `data-records-*` attributes are used by the assistant to verify that navigation has completed; update the assistant action contract if replacing this screen. API authentication and workspace scoping remain in `src/lib/auth-context.tsx`, with authorization enforced by the backend.

Appearance account preferences keep the existing API fields. Shell layout and sidebar dimensions remain device-local. This extraction does not add billing or feature entitlements.
