# Third-party UI

Settings layout and sidebar navigation adapted from [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin), revision `e16c87f213a5ba5e45964e9b67c792105ec74d26`.

Sources: `src/features/settings/index.tsx` and `src/features/settings/components/sidebar-nav.tsx`. Adaptations use this app’s hash routing, existing settings panels, role-aware sections, and container-responsive navigation. The original MIT notice is retained in `shadcn-admin.txt`.

## Tablecn tables

Requests and Opportunities use the current upstream Radix Tablecn components at revision `44ac3879d0db81e92c011971cb43261fbbdc059a`, with TanStack React Table 9.2.4. The complete table dependency set (33 source files) is under `src/registry` and `src/lib`; `tablecn-source.json` records original hashes. Only the `cn` import path is mapped to the existing application utility. Table, toolbar, menus, filters, and pagination retain upstream implementations. The upstream shadcn CSS variants are loaded through `shadcn/tailwind.css`, including proper boolean selection selectors.

Application-specific columns, controlled state, permissions, clickable priorities, and bulk API mutations stay in feature components. Initial route filters are normalized through Tablecn's filter utility; app-specific selection controls subscribe to v9 state. The v8 components and types have been removed. The original MIT notice is retained.

## Kanban and view switch

Board drag and drop uses the MIT-licensed Kibo UI primitives in `src/components/ui/kanban.tsx`. The app supplies its own card and list views using existing shadcn UI components. See `kibo-ui-MIT.txt` and `shadcn-ui-MIT.txt`.

## Primer issue detail composition

Request and opportunity details import actual `@primer/react` 38.46.0 components, `@primer/primitives` 11.10.0 theme tokens, and `@primer/octicons-react` 19.42.0 icons from their official npm packages (MIT). The shared page composition, authored-description card, and application adapters are custom integration, not GitHub’s private issue-page source. ThemeProvider is local to detail views. Content boundaries reset the PageLayout internal `--spacing` variable to avoid collisions with embedded Tailwind controls. Existing triage, support, priority and decision persistence remain application-owned.

Request discussion uses official Primer UnderlineNav, Textarea, FormControl, Button, Timeline, Link and Octicons components. Comment storage and the author/content wrapper are application integration; this is not a GitHub-hosted comments integration or a claimed monolithic Primer Comment component.
