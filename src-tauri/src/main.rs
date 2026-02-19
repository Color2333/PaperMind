// PaperMind Desktop — Tauri v2 主入口
// 用原生 tokio::process 管理 Python 后端进程，规避 Tauri sidecar 的 symlink 校验问题。
// @author Bamzc

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

/// launcher.json 配置
#[derive(Debug, Clone, Serialize, Deserialize)]
struct LauncherConfig {
    data_dir: String,
    env_file: String,
}

/// 应用全局状态
struct AppState {
    api_port: Mutex<Option<u16>>,
    launcher_config: Mutex<Option<LauncherConfig>>,
    child_pid: Mutex<Option<u32>>,
}

/// 获取 launcher.json 的路径
fn launcher_config_path() -> PathBuf {
    let base = dirs::data_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("PaperMind");
    fs::create_dir_all(&base).ok();
    base.join("launcher.json")
}

fn read_launcher_config() -> Option<LauncherConfig> {
    let path = launcher_config_path();
    if !path.exists() {
        return None;
    }
    let content = fs::read_to_string(&path).ok()?;
    serde_json::from_str(&content).ok()
}

fn write_launcher_config(config: &LauncherConfig) -> Result<(), String> {
    let path = launcher_config_path();
    let json = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(())
}

/// 定位 sidecar 二进制：与主程序在同一目录 (Contents/MacOS/)
fn resolve_sidecar_path() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| format!("current_exe failed: {}", e))?;

    // 解析 symlink（macOS /var -> /private/var）
    let exe_real = fs::canonicalize(&exe).unwrap_or(exe);
    let exe_dir = exe_real
        .parent()
        .ok_or("Cannot determine executable directory")?;

    let sidecar = exe_dir.join("papermind-server");
    if sidecar.exists() {
        return Ok(sidecar);
    }

    // dev 模式：尝试从项目根目录的 dist/ 找
    let project_sidecar = PathBuf::from("dist/papermind-server");
    if project_sidecar.exists() {
        return Ok(project_sidecar);
    }

    Err(format!(
        "Sidecar binary not found at {:?} or {:?}",
        sidecar, project_sidecar
    ))
}

#[tauri::command]
fn get_api_port(state: State<AppState>) -> Option<u16> {
    *state.api_port.lock().unwrap()
}

#[tauri::command]
fn needs_setup() -> bool {
    read_launcher_config().is_none()
}

#[tauri::command]
fn get_launcher_config(state: State<AppState>) -> Option<LauncherConfig> {
    state.launcher_config.lock().unwrap().clone()
}

#[tauri::command]
async fn save_config_and_start(
    app: AppHandle,
    state: State<'_, AppState>,
    data_dir: String,
    env_file: String,
) -> Result<u16, String> {
    let config = LauncherConfig {
        data_dir: data_dir.clone(),
        env_file: env_file.clone(),
    };
    write_launcher_config(&config)?;
    *state.launcher_config.lock().unwrap() = Some(config);

    start_backend(&app, &data_dir, &env_file).await
}

#[tauri::command]
fn update_config(
    state: State<AppState>,
    data_dir: String,
    env_file: String,
) -> Result<(), String> {
    let config = LauncherConfig {
        data_dir,
        env_file,
    };
    write_launcher_config(&config)?;
    *state.launcher_config.lock().unwrap() = Some(config);
    Ok(())
}

/// 启动 Python 后端进程，解析 stdout 获取端口
async fn start_backend(
    app: &AppHandle,
    data_dir: &str,
    env_file: &str,
) -> Result<u16, String> {
    let sidecar_path = resolve_sidecar_path()?;
    eprintln!("[tauri] Starting backend: {:?}", sidecar_path);

    let mut child = Command::new(&sidecar_path)
        .env("PAPERMIND_DATA_DIR", data_dir)
        .env("PAPERMIND_ENV_FILE", env_file)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {}", e))?;

    let pid = child.id().unwrap_or(0);
    {
        let state = app.state::<AppState>();
        *state.child_pid.lock().unwrap() = Some(pid);
    }
    eprintln!("[tauri] Backend PID: {}", pid);

    // 读 stdout 获取端口 JSON
    let stdout = child
        .stdout
        .take()
        .ok_or("Failed to capture backend stdout")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Failed to capture backend stderr")?;

    let mut stdout_reader = BufReader::new(stdout).lines();
    let mut stderr_reader = BufReader::new(stderr).lines();

    // 等待首行 JSON 端口信息
    let port: u16;
    loop {
        tokio::select! {
            line = stdout_reader.next_line() => {
                match line {
                    Ok(Some(text)) => {
                        let trimmed = text.trim();
                        if let Ok(info) = serde_json::from_str::<serde_json::Value>(trimmed) {
                            if let Some(p) = info.get("port").and_then(|v| v.as_u64()) {
                                port = p as u16;
                                break;
                            }
                        }
                        eprintln!("[backend stdout] {}", trimmed);
                    }
                    Ok(None) => {
                        return Err("Backend process exited before sending port".to_string());
                    }
                    Err(e) => {
                        return Err(format!("Error reading backend stdout: {}", e));
                    }
                }
            }
            line = stderr_reader.next_line() => {
                if let Ok(Some(text)) = line {
                    eprintln!("[backend stderr] {}", text.trim());
                }
            }
        }
    }

    // 存储端口并通知前端
    {
        let state = app.state::<AppState>();
        *state.api_port.lock().unwrap() = Some(port);
    }
    app.emit("backend-ready", port).ok();
    eprintln!("[tauri] Backend ready on port {}", port);

    // 后台转发日志 + 监控进程退出
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::select! {
                line = stdout_reader.next_line() => {
                    match line {
                        Ok(Some(text)) => eprintln!("[backend] {}", text.trim()),
                        _ => break,
                    }
                }
                line = stderr_reader.next_line() => {
                    match line {
                        Ok(Some(text)) => eprintln!("[backend] {}", text.trim()),
                        _ => break,
                    }
                }
                status = child.wait() => {
                    match status {
                        Ok(s) => eprintln!("[backend] Process exited: {}", s),
                        Err(e) => eprintln!("[backend] Wait error: {}", e),
                    }
                    break;
                }
            }
        }
    });

    Ok(port)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AppState {
            api_port: Mutex::new(None),
            launcher_config: Mutex::new(read_launcher_config()),
            child_pid: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            get_api_port,
            needs_setup,
            get_launcher_config,
            save_config_and_start,
            update_config,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            if let Some(config) = read_launcher_config() {
                let data_dir = config.data_dir.clone();
                let env_file = config.env_file.clone();

                tauri::async_runtime::spawn(async move {
                    match start_backend(&handle, &data_dir, &env_file).await {
                        Ok(port) => {
                            eprintln!("[tauri] Backend started on port {}", port);
                        }
                        Err(e) => {
                            eprintln!("[tauri] Failed to start backend: {}", e);
                            handle.emit("backend-error", e).ok();
                        }
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PaperMind");
}
