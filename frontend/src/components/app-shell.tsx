import { Link, useMatches, useMatchRoute } from "@tanstack/react-router";
import {
  CalendarClockIcon,
  FolderKanbanIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  type LucideIcon,
  NewspaperIcon,
  RssIcon,
  ScrollTextIcon,
  SettingsIcon,
  TargetIcon,
  TrendingUpIcon,
} from "lucide-react";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import type { User } from "#/client/types.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";
import { Separator } from "#/components/ui/separator.tsx";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "#/components/ui/sidebar.tsx";
import { TooltipProvider } from "#/components/ui/tooltip.tsx";
import { UserMenu } from "./user-menu.tsx";

interface Page {
  to:
    | "/"
    | "/opportunities"
    | "/forecast"
    | "/projects"
    | "/feeds"
    | "/sources"
    | "/jobs"
    | "/runs"
    | "/audit"
    | "/settings";
  title:
    | "dashboard.title"
    | "opportunities.title"
    | "forecast.title"
    | "projects.title"
    | "feeds.title"
    | "sources.title"
    | "jobs.title"
    | "jobs.pages.runs"
    | "audit.title"
    | "settings.title";
  icon: LucideIcon;
  within?: "/jobs/$job" | "/sources/$sourceId" | "/forecast/$ags"; // a page under it, which keeps it highlighted
  admin?: true; // admins only
  soon?: true; // not built yet
}

interface Group {
  label:
    | "app.groups.projects"
    | "app.groups.collection"
    | "app.groups.operations"
    | "app.groups.general";
  pages: Page[];
}

const DASHBOARD: Page = {
  to: "/",
  title: "dashboard.title",
  icon: LayoutDashboardIcon,
};

// The sidebar's groups, in the order InfraSales works (CONTEXT.md): what it found, where it reads
// from, whether it runs, and the rest. Databricks groups its sidebar the same way.
const GROUPS: Group[] = [
  {
    label: "app.groups.projects",
    pages: [
      { to: "/opportunities", title: "opportunities.title", icon: TargetIcon },
      { to: "/forecast", title: "forecast.title", icon: TrendingUpIcon, within: "/forecast/$ags" },
      { to: "/projects", title: "projects.title", icon: FolderKanbanIcon, soon: true },
    ],
  },
  {
    label: "app.groups.collection",
    pages: [
      { to: "/feeds", title: "feeds.title", icon: RssIcon, admin: true },
      {
        to: "/sources",
        title: "sources.title",
        icon: NewspaperIcon,
        within: "/sources/$sourceId",
        admin: true,
      },
    ],
  },
  {
    label: "app.groups.operations",
    pages: [
      { to: "/jobs", title: "jobs.title", icon: CalendarClockIcon, within: "/jobs/$job" },
      { to: "/runs", title: "jobs.pages.runs", icon: HistoryIcon, admin: true },
    ],
  },
  {
    label: "app.groups.general",
    pages: [
      { to: "/audit", title: "audit.title", icon: ScrollTextIcon, admin: true },
      { to: "/settings", title: "settings.title", icon: SettingsIcon, admin: true },
    ],
  },
];

// One page's link: its icon and name, and Soon beside a page not built yet. It is marked as the
// page only on its own address; on a page under it (a job's page) it stays highlighted. On small
// screens, opening it also closes the menu it is in.
function PageLink({ page }: { page: Page }) {
  const { t } = useTranslation();
  const matchRoute = useMatchRoute();
  const { setOpenMobile } = useSidebar();
  const Icon = page.icon;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        render={
          <Link to={page.to} activeOptions={{ exact: true }} onClick={() => setOpenMobile(false)} />
        }
        isActive={Boolean(
          matchRoute({ to: page.to }) || (page.within && matchRoute({ to: page.within })),
        )}
        tooltip={t(page.title)}
      >
        <Icon aria-hidden={true} />
        <span className="truncate">{t(page.title)}</span>
        {page.soon ? (
          <>
            {" "}
            <Badge variant="outline" className="ms-auto text-muted-foreground">
              {t("app.soon")}
            </Badge>
          </>
        ) : null}
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

// A labelled group of pages; its label names the list for screen readers too.
function PageGroup({ group, pages }: { group: Group; pages: Page[] }) {
  const { t } = useTranslation();
  const label = useId();
  return (
    <SidebarGroup>
      <SidebarGroupLabel id={label}>{t(group.label)}</SidebarGroupLabel>
      <SidebarMenu aria-labelledby={label}>
        {pages.map((page) => (
          <PageLink key={page.to} page={page} />
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}

// The pages this user may open: the Dashboard on its own, then the groups. Viewers see only the
// pages they may open, and no group left empty.
export function PageLinks({ user }: { user: User }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("app.navigation")}>
      <SidebarGroup>
        <SidebarMenu>
          <PageLink page={DASHBOARD} />
        </SidebarMenu>
      </SidebarGroup>
      {GROUPS.map((group) => {
        const pages = group.pages.filter((page) => !page.admin || user.role === "admin");
        return pages.length > 0 ? (
          <PageGroup key={group.label} group={group} pages={pages} />
        ) : null;
      })}
    </nav>
  );
}

// The signed-in pages' frame: a sidebar with the pages this user may open and the user menu, a
// top bar with the sidebar's toggle and where the user is, and above the page its heading and
// what the page is for (its route's `staticData`). Pages use the full width beside the sidebar.
// Collapsed, the sidebar keeps its icons (each page named in a tooltip); its toggle, its edge (the
// rail, for the mouse only) and Ctrl+B collapse and expand it. On small screens it becomes a menu
// (a sheet) the toggle opens.
export function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const { t } = useTranslation();
  const page = useMatches({
    select: (matches) => matches.findLast((match) => match.staticData.title)?.staticData,
  });

  return (
    <TooltipProvider>
      <SidebarProvider>
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <p className="flex items-center gap-2 overflow-hidden whitespace-nowrap px-2 py-1 font-semibold transition-[padding] group-data-[collapsible=icon]:px-1">
              <img src="/favicon.svg" alt="" width={24} height={24} className="size-6 shrink-0" />
              {t("app.title")}
            </p>
          </SidebarHeader>
          <SidebarContent>
            <PageLinks user={user} />
          </SidebarContent>
          <SidebarFooter>
            <UserMenu user={user} />
          </SidebarFooter>
          <SidebarRail aria-hidden={true} />
        </Sidebar>
        <SidebarInset>
          <header className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b bg-background px-4">
            <SidebarTrigger className="-ms-1" />
            <Separator
              orientation="vertical"
              className="me-1 data-vertical:h-4 data-vertical:self-auto"
            />
            {page?.title ? (
              <p className="truncate text-muted-foreground text-sm">{t(page.title)}</p>
            ) : null}
          </header>
          <div className="flex flex-1 flex-col gap-6 px-4 py-6 md:px-8">
            {page?.title && !page.headed ? (
              <hgroup className="grid gap-1">
                <h1 className="font-heading font-semibold text-2xl tracking-tight">
                  {t(page.title)}
                </h1>
                {page.description ? (
                  <p className="text-muted-foreground text-sm">{t(page.description)}</p>
                ) : null}
              </hgroup>
            ) : null}
            {children}
          </div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
