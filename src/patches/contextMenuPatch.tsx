/**
 * Context menu patch — adds "Run with Console Log" to any game's popup menu.
 * Adapted from decky-steamgriddb's contextMenuPatch pattern.
 *
 * Flow:
 *  1. User opens game context menu → sees "Run with Console Log"
 *  2. Click → inject wrapper into current launch options → notify backend → launch game
 *  3. Game stops (lifecycle event) → strip wrapper from launch options → backend stops tailer
 */

import {
  afterPatch,
  fakeRenderComponent,
  findInReactTree,
  findModuleByExport,
  findInTree,
  MenuItem,
  Export,
} from "@decky/ui";
import { call } from "@decky/api";
import type { FC } from "react";
import type { Patch } from "@decky/ui";

const MENU_ITEM_KEY = "capydeploy-run-with-log";
const WRAPPER_MARKER = "capydeploy-game-wrapper.sh";

// Escape special regex characters in a string.
function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// AppIds currently running with the wrapper injected.
export const activeGameLogs = new Set<number>();

// Cached wrapper path (fetched once, reused).
let _wrapperPath: string | null = null;

/** Fetch and cache the wrapper script path from backend. */
export async function initWrapperPath(): Promise<void> {
  try {
    _wrapperPath = await call<[], string>("get_wrapper_path");
  } catch (e) {
    console.error("Failed to get wrapper path:", e);
  }
}

/**
 * Resolve the correct gameId string for RunGame.
 * For non-Steam shortcuts, gameid differs from String(appId).
 */
export function resolveGameId(appId: number): string {
  try {
    const overview = (window as any).appStore?.GetAppOverviewByAppID(appId);
    if (overview?.gameid) return String(overview.gameid);
  } catch { /* fall through */ }
  return String(appId);
}

/**
 * Inject wrapper into launch options, notify backend, and launch the game.
 * Fully synchronous after the first call (wrapper path is cached).
 */
export function runWithConsoleLog(appId: number): void {
  try {
    if (!_wrapperPath) {
      console.error("Wrapper path not initialized");
      return;
    }

    const gameId = resolveGameId(appId);
    const appDetails = (window as any).appDetailsStore?.GetAppDetails(appId);
    const currentOptions: string = appDetails?.strLaunchOptions ?? "";

    // Already injected (e.g. user clicked twice) — just launch.
    if (currentOptions.includes(WRAPPER_MARKER)) {
      activeGameLogs.add(appId);
      call("notify_game_log_start", appId).catch((e: unknown) =>
        console.error("Failed to notify game log start:", e)
      );
      SteamClient.Apps.RunGame(gameId, "", -1, 100);
      return;
    }

    // Combine wrapper with existing launch options.
    let newOptions: string;
    if (currentOptions && currentOptions.includes("%command%")) {
      newOptions = currentOptions.replace(
        "%command%",
        `${_wrapperPath} ${appId} %command%`
      );
    } else if (currentOptions) {
      newOptions = `${_wrapperPath} ${appId} ${currentOptions} %command%`;
    } else {
      newOptions = `${_wrapperPath} ${appId} %command%`;
    }

    SteamClient.Apps.SetAppLaunchOptions(appId, newOptions);
    activeGameLogs.add(appId);

    // Notify backend (fire-and-forget, don't block the launch).
    call("notify_game_log_start", appId).catch((e: unknown) =>
      console.error("Failed to notify game log start:", e)
    );

    // Small delay so Steam registers the new launch options before launching.
    setTimeout(() => {
      SteamClient.Apps.RunGame(gameId, "", -1, 100);
    }, 150);
  } catch (e) {
    console.error("Failed to run with console log:", e);
  }
}

/**
 * Strip the wrapper from current launch options after game exits.
 * Called from the game lifecycle handler in eventPoller.
 */
export function removeWrapperFromLaunchOptions(appId: number): void {
  if (!activeGameLogs.has(appId)) return;
  activeGameLogs.delete(appId);

  try {
    const appDetails = (window as any).appDetailsStore?.GetAppDetails(appId);
    const currentOptions: string = appDetails?.strLaunchOptions ?? "";

    if (!currentOptions.includes(WRAPPER_MARKER)) return;

    // Strip the wrapper path + appId from the current options.
    let cleaned = currentOptions
      .replace(
        new RegExp(
          `\\S*${escapeRegex(WRAPPER_MARKER)}\\s+${appId}\\s*`,
          "g"
        ),
        ""
      )
      .trim();

    // If only "%command%" remains (we added it), clear it entirely.
    if (cleaned === "%command%") {
      cleaned = "";
    }

    SteamClient.Apps.SetAppLaunchOptions(appId, cleaned);
  } catch (e) {
    console.error("Failed to remove wrapper from launch options:", e);
  }
}

// ── Context menu patching (adapted from decky-steamgriddb) ──────────────────

/**
 * Insert our MenuItem before "Properties…" in the popup children array.
 */
const spliceMenuItem = (children: any[], appid: number): void => {
  const propertiesIdx = children.findIndex((item) =>
    findInReactTree(
      item,
      (x) =>
        x?.onSelected &&
        x.onSelected.toString().includes("AppProperties")
    )
  );

  const insertIdx = propertiesIdx !== -1 ? propertiesIdx : children.length;

  children.splice(
    insertIdx,
    0,
    <MenuItem
      key={MENU_ITEM_KEY}
      onSelected={() => runWithConsoleLog(appid)}
    >
      Run with Console Log
    </MenuItem>
  );
};

/** Check if this is a game context menu (not screenshots, etc.) */
const isOpeningAppContextMenu = (items: any[]): boolean => {
  if (!items?.length) return false;
  return !!findInReactTree(
    items,
    (x) =>
      x?.props?.onSelected &&
      x?.props?.onSelected.toString().includes("launchSource")
  );
};

/** Remove duplicate menu items injected by previous renders. */
const handleItemDupes = (items: any[]): void => {
  const idx = items.findIndex((x: any) => x?.key === MENU_ITEM_KEY);
  if (idx !== -1) items.splice(idx, 1);
};

/**
 * Resolve the correct appId (Steam caches context menus, so the appid
 * from the outer render can be stale).
 */
const patchMenuItems = (menuItems: any[], appid: number): void => {
  let updatedAppid = appid;

  // Check if a child has a fresher appid.
  const parentOverview = menuItems.find(
    (x: any) =>
      x?._owner?.pendingProps?.overview?.appid &&
      x._owner.pendingProps.overview.appid !== appid
  );
  if (parentOverview) {
    updatedAppid = parentOverview._owner.pendingProps.overview.appid;
  }

  // Oct 2025 client fallback.
  if (updatedAppid === appid) {
    const foundApp = findInTree(menuItems, (x) => x?.app?.appid, {
      walkable: ["props", "children"],
    });
    if (foundApp) {
      updatedAppid = foundApp.app.appid;
    }
  }

  spliceMenuItem(menuItems, updatedAppid);
};

/**
 * Patch the LibraryContextMenu component's render method to inject our
 * menu item into every game popup.
 */
const contextMenuPatch = (LibCtxMenu: any) => {
  const patches: {
    outer?: Patch;
    inner?: Patch;
    unpatch: () => void;
  } = { unpatch: () => null };

  patches.outer = afterPatch(
    LibCtxMenu.prototype,
    "render",
    (_: Record<string, unknown>[], component: any) => {
      let appid = 0;

      if (component._owner) {
        appid = component._owner.pendingProps.overview.appid;
      } else {
        // Oct 2025+ client.
        const foundApp = findInTree(
          component.props.children,
          (x) => x?.app?.appid,
          { walkable: ["props", "children"] }
        );
        if (foundApp) {
          appid = foundApp.app.appid;
        }
      }

      if (!patches.inner) {
        patches.inner = afterPatch(
          component,
          "type",
          (_: any, ret: any) => {
            // Patch initial render.
            afterPatch(
              ret.type.prototype,
              "render",
              (_: any, ret2: any) => {
                const menuItems = ret2.props.children[0];
                if (!isOpeningAppContextMenu(menuItems)) return ret2;
                try {
                  handleItemDupes(menuItems);
                } catch {
                  return ret2;
                }
                patchMenuItems(menuItems, appid);
                return ret2;
              }
            );

            // Patch subsequent updates.
            afterPatch(
              ret.type.prototype,
              "shouldComponentUpdate",
              ([nextProps]: any, shouldUpdate: any) => {
                try {
                  handleItemDupes(nextProps.children);
                } catch {
                  return shouldUpdate;
                }
                if (shouldUpdate === true) {
                  patchMenuItems(nextProps.children, appid);
                }
                return shouldUpdate;
              }
            );

            return ret;
          }
        );
      } else {
        spliceMenuItem(component.props.children, appid);
      }

      return component;
    }
  );

  patches.unpatch = () => {
    patches.outer?.unpatch();
    patches.inner?.unpatch();
  };

  return patches;
};

/**
 * Locate the LibraryContextMenu component from Steam's Webpack modules.
 * Lazy: runs on first call, not at import time, to avoid slowing plugin startup.
 */
let _libraryContextMenu: any = null;

export function getLibraryContextMenu(): any {
  if (!_libraryContextMenu) {
    _libraryContextMenu = fakeRenderComponent(
      Object.values(
        findModuleByExport((e: Export) =>
          e?.toString && e.toString().includes("().LibraryContextMenu")
        )
      ).find(
        (sibling) =>
          sibling?.toString().includes("createElement") &&
          sibling?.toString().includes("navigator:")
      ) as FC
    ).type;
  }
  return _libraryContextMenu;
}

export default contextMenuPatch;
