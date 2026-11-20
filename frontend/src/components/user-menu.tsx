import { ChevronsUpDownIcon, LogOutIcon, UserRoundIcon } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { User } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import { Label } from "#/components/ui/label.tsx";
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "#/components/ui/select.tsx";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "#/components/ui/sidebar.tsx";
import { THEMES, type Theme, useTheme } from "#/lib/theme.ts";

// Who is signed in, the theme, and signing out: a native form post, as the backend expects
// (it ends the session and redirects to the app, which then asks to sign in). It opens beside the
// sidebar, so a collapsed one doesn't squeeze it; on small screens, above the button.
export function UserMenu({ user }: { user: User }) {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const { isMobile } = useSidebar();
  const themeLabel = useId();
  const role = t(`roles.${user.role}`);
  const themes = THEMES.map((value) => ({ value, label: t(`themes.${value}`) }));

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <Popover>
          <PopoverTrigger
            render={<SidebarMenuButton size="lg" />}
            aria-label={t("app.userMenu", { name: user.name, role })}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-sidebar-border">
              <UserRoundIcon aria-hidden={true} />
            </span>
            <span className="grid flex-1 text-start leading-tight">
              <span className="truncate font-medium">{user.name}</span>
              <span className="truncate text-muted-foreground text-xs">{role}</span>
            </span>
            <ChevronsUpDownIcon aria-hidden={true} className="ms-auto" />
          </PopoverTrigger>
          <PopoverContent side={isMobile ? "top" : "right"} align="end" className="w-64">
            <PopoverHeader>
              <PopoverTitle className="text-sm">
                {t("app.signedInAs", { name: user.name, role })}
              </PopoverTitle>
            </PopoverHeader>
            <div className="grid gap-1.5">
              <Label id={themeLabel}>{t("app.theme")}</Label>
              <Select
                items={themes}
                value={theme}
                onValueChange={(value: Theme | null) => value && setTheme(value)}
              >
                <SelectTrigger aria-labelledby={themeLabel} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {themes.map(({ value, label }) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <form method="post" action="/api/auth/logout">
              <Button type="submit" variant="outline" className="w-full">
                <LogOutIcon aria-hidden={true} />
                {t("app.signOut")}
              </Button>
            </form>
          </PopoverContent>
        </Popover>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
