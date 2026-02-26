/**
 * Tauri 桌面环境检测与 IPC 桥接
 * @author Bamzc
 */

/** 是否运行在 Tauri 桌面环境中 */
export function isTauri(): boolean {
  return !!(window as any).__TAURI_INTERNALS__;
}

/** 调用 Tauri Rust 命令 */
async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

/** 监听 Tauri 事件 */
export async function listen<T>(
  event: string,
  handler: (payload: T) => void,
): Promise<() => void> {
  const { listen: tauriListen } = await import("@tauri-apps/api/event");
  const unlisten = await tauriListen<T>(event, (e) => handler(e.payload));
  return unlisten;
}

/** 获取后端 API 端口 */
export async function getApiPort(): Promise<number | null> {
  if (!isTauri()) return null;
  return invoke<number | null>("get_api_port");
}

/** 是否需要首次引导 */
export async function needsSetup(): Promise<boolean> {
  if (!isTauri()) return false;
  return invoke<boolean>("needs_setup");
}

export interface LauncherConfig {
  data_dir: string;
  env_file: string;
}

/** 获取当前启动配置 */
export async function getLauncherConfig(): Promise<LauncherConfig | null> {
  if (!isTauri()) return null;
  return invoke<LauncherConfig | null>("get_launcher_config");
}

/** 保存配置并启动后端，返回端口号 */
export async function saveConfigAndStart(
  dataDir: string,
  envFile: string,
): Promise<number> {
  return invoke<number>("save_config_and_start", {
    dataDir,
    envFile,
  });
}

/** 更新配置（不重启后端） */
export async function updateConfig(
  dataDir: string,
  envFile: string,
): Promise<void> {
  return invoke<void>("update_config", {
    dataDir,
    envFile,
  });
}

/** 打开文件夹选择对话框 */
export async function openFolderDialog(title: string): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({
    directory: true,
    title,
  });
  return typeof result === "string" ? result : null;
}

/** 打开文件选择对话框 */
export async function openFileDialog(
  title: string,
  filters?: { name: string; extensions: string[] }[],
): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({
    directory: false,
    title,
    filters,
  });
  return typeof result === "string" ? result : null;
}

/**
 * 全局 API 端口管理
 * 在 Tauri 模式下，等待后端就绪后才能使用 API。
 */
let _resolvedPort: number | null = null;
let _portPromise: Promise<number> | null = null;

export function resolveApiBase(): string {
  if (!isTauri()) {
    if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE;
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "http://localhost:8000";
    }
    return "/api";
  }
  if (_resolvedPort) {
    return `http://127.0.0.1:${_resolvedPort}`;
  }
  return import.meta.env.VITE_API_BASE || "http://localhost:8000";
}

export function setApiPort(port: number): void {
  _resolvedPort = port;
}

export function waitForBackend(): Promise<number> {
  if (_resolvedPort) return Promise.resolve(_resolvedPort);

  if (!_portPromise) {
    _portPromise = new Promise((resolve) => {
      const poll = async () => {
        const port = await getApiPort();
        if (port) {
          _resolvedPort = port;
          resolve(port);
        } else {
          setTimeout(poll, 500);
        }
      };
      poll();

      listen<number>("backend-ready", (port) => {
        _resolvedPort = port;
        resolve(port);
      });
    });
  }

  return _portPromise;
}
