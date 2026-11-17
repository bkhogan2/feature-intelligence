import { useEffect, useRef, type ReactNode } from "react";
import { useTheme } from "next-themes";
import {
  BaseStyles,
  PageLayout,
  Heading,
  StateLabel,
  Breadcrumbs,
  Timeline,
} from "@primer/react";
import { ThemeProvider } from "@primer/react/next";
import { IssueOpenedIcon, PersonIcon } from "@primer/octicons-react";
import "@primer/primitives/dist/css/functional/themes/light.css";
import "@primer/primitives/dist/css/functional/themes/dark.css";
import "./issue-detail.css";

// Primer components are imported from the official package. Only the page
// composition and product-specific content are ours; no global Primer reset.
export function IssueDetail({
  id,
  title,
  status,
  backHref,
  backLabel,
  subtitle,
  actions,
  primaryActions,
  sidebar,
  children,
}: {
  id: string;
  title: string;
  status: string;
  backHref: string;
  backLabel: string;
  subtitle: ReactNode;
  actions?: ReactNode;
  primaryActions?: ReactNode;
  sidebar: ReactNode;
  children: ReactNode;
}) {
  const { resolvedTheme } = useTheme();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [id]);
  const state =
    status === "Archived"
      ? "archived"
      : ["Not pursuing", "Rejected"].includes(status)
        ? "issueClosedNotPlanned"
        : ["Triaged", "Approved", "Shipped"].includes(status)
          ? "issueClosed"
          : "issueOpened";
  return (
    <ThemeProvider colorMode={resolvedTheme === "dark" ? "dark" : "light"}>
      <BaseStyles className="github-detail">
        <PageLayout containerWidth="xlarge" padding="none" columnGap="normal">
          <PageLayout.Header divider="none">
            <div className="issue-breadcrumb-row">
              <Breadcrumbs>
                <Breadcrumbs.Item href={backHref}>{backLabel}</Breadcrumbs.Item>
                <Breadcrumbs.Item selected>Detail</Breadcrumbs.Item>
              </Breadcrumbs>
              <div className="issue-actions">{actions}</div>
            </div>
            <div className={primaryActions ? "issue-heading-row" : undefined}>
              <div className="issue-heading-copy">
                <Heading
                  as="h1"
                  ref={heading}
                  tabIndex={-1}
                  className="issue-title"
                >
                  {title}{" "}
                  <span className="issue-number">#{id.slice(0, 8)}</span>
                </Heading>
                <div className="issue-subtitle">
                  <StateLabel status={state}>{status}</StateLabel>
                  <span>{subtitle}</span>
                  {primaryActions && (
                    <div className="issue-primary-actions">
                      {primaryActions}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </PageLayout.Header>
          <PageLayout.Content as="div">
            <div className="issue-discussion">{children}</div>
          </PageLayout.Content>
          <PageLayout.Pane
            position="end"
            width="medium"
            aria-label="Properties"
          >
            <div className="issue-properties">{sidebar}</div>
          </PageLayout.Pane>
        </PageLayout>
      </BaseStyles>
    </ThemeProvider>
  );
}
export function IssueProperty({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <section className="issue-property">
      <h2>{label}</h2>
      <div>{children}</div>
    </section>
  );
}
export function IssueComment({
  id,
  author,
  date,
  label,
  verb = "opened on",
  headerActions,
  children,
  neutral = false,
}: {
  id?: string;
  neutral?: boolean;
  author: string;
  date: string;
  label: string;
  verb?: string;
  headerActions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <article id={id} className={`issue-comment${neutral ? " issue-comment-neutral" : ""}`} aria-label={label}>
      <header>
        <span className="issue-author-avatar" aria-hidden="true">
          <PersonIcon size={16} />
        </span>
        <strong>{author}</strong>
        <span>
          {verb}{" "}
          <time dateTime={date}>
            {new Date(date).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </time>
        </span>
        {headerActions && (
          <div style={{ marginLeft: "auto" }}>{headerActions}</div>
        )}
      </header>
      <div className="issue-comment-body">{children}</div>
    </article>
  );
}
export function IssueCreatedEvent({
  date,
  children,
}: {
  date: string;
  children: ReactNode;
}) {
  return (
    <Timeline>
      <Timeline.Item>
        <Timeline.Badge>
          <IssueOpenedIcon />
        </Timeline.Badge>
        <Timeline.Body>
          {children} ·{" "}
          <time dateTime={date}>{new Date(date).toLocaleDateString()}</time>
        </Timeline.Body>
      </Timeline.Item>
    </Timeline>
  );
}
