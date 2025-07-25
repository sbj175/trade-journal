#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, AppHandle, Emitter};
use std::thread;
use std::time::Duration;
use serde::Serialize;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

struct PythonServerState {
    child: Mutex<Option<Child>>,
}

#[derive(Clone, Serialize)]
struct SplashStatus {
    message: String,
    progress: Option<f32>,
    error: bool,
}

fn start_python_server(app_handle: &AppHandle) -> Result<Child, String> {
    // Try to get the resource directory, fallback to current directory for development
    let working_dir = if let Ok(resource_dir) = app_handle.path().resource_dir() {
        println!("Resource directory from Tauri: {:?}", resource_dir);
        if resource_dir.join("app.py").exists() {
            resource_dir
        } else {
            // Fallback: try the parent directory (for development)
            let exe_path = std::env::current_exe()
                .map_err(|e| format!("Failed to get executable path: {}", e))?;
            println!("Executable path: {:?}", exe_path);
            
            let parent = exe_path
                .parent()
                .ok_or("Failed to get executable parent directory")?;
            println!("Executable parent: {:?}", parent);
            
            // Check if we're in target/debug or target/release
            if parent.ends_with("debug") || parent.ends_with("release") {
                // Go up to the project root
                parent.parent()
                    .and_then(|p| p.parent())
                    .and_then(|p| p.parent())
                    .ok_or("Failed to get project root from target directory")?
                    .to_path_buf()
            } else {
                parent.to_path_buf()
            }
        }
    } else {
        // Fallback to current directory
        let current_dir = std::env::current_dir()
            .map_err(|e| format!("Failed to get current directory: {}", e))?;
        println!("Using current directory: {:?}", current_dir);
        current_dir
    };
    
    println!("Final working directory: {:?}", working_dir);
    
    // Check if app.py exists
    let app_py_path = working_dir.join("app.py");
    if !app_py_path.exists() {
        return Err(format!("app.py not found at: {:?}", app_py_path));
    }
    
    // Look for virtual environment
    let venv_python = if cfg!(target_os = "windows") {
        working_dir.join("venv").join("Scripts").join("python.exe")
    } else {
        working_dir.join("venv").join("bin").join("python")
    };
    
    println!("Looking for venv Python at: {:?}", venv_python);
    let python_cmd = if venv_python.exists() {
        println!("Found virtual environment Python!");
        venv_python.to_string_lossy().to_string()
    } else {
        println!("No virtual environment found at {:?}, using system Python", venv_python);
        // Also try .venv instead of venv
        let dot_venv_python = if cfg!(target_os = "windows") {
            working_dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            working_dir.join(".venv").join("bin").join("python")
        };
        
        if dot_venv_python.exists() {
            println!("Found .venv virtual environment at: {:?}", dot_venv_python);
            dot_venv_python.to_string_lossy().to_string()
        } else {
            println!("No .venv found either, using system Python");
            if cfg!(target_os = "windows") {
                "python".to_string()
            } else {
                "python3".to_string()
            }
        }
    };
    
    println!("Environment PATH: {:?}", std::env::var("PATH"));
    
    // Use launch script if available
    let launch_script = if cfg!(target_os = "windows") {
        working_dir.join("launch_server.bat")
    } else {
        working_dir.join("launch_server.sh")
    };
    
    println!("Checking for launch script at: {:?}", launch_script);
    
    // Create log file for Python output
    let log_path = working_dir.join("tauri_python_server.log");
    let log_file = std::fs::File::create(&log_path)
        .map_err(|e| format!("Failed to create log file: {}", e))?;
    let log_file_err = log_file.try_clone()
        .map_err(|e| format!("Failed to clone log file: {}", e))?;
    
    println!("Python server output will be logged to: {:?}", log_path);
    
    let mut child = if launch_script.exists() {
        println!("Found launch script! Using it to start server");
        if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.arg("/C")
                .arg(&launch_script)
                .current_dir(&working_dir);
            
            // Hide console on Windows
            #[cfg(windows)]
            {
                const CREATE_NO_WINDOW: u32 = 0x08000000;
                cmd.creation_flags(CREATE_NO_WINDOW);
            }
            
            cmd.spawn()
        } else {
            Command::new("bash")
                .arg(&launch_script)
                .current_dir(&working_dir)
                .stdout(log_file)
                .stderr(log_file_err)
                .spawn()
        }
    } else {
        println!("No launch script found, using Python directly: {}", python_cmd);
        let mut cmd = Command::new(&python_cmd);
        cmd.arg("app.py")
            .current_dir(&working_dir);
        
        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        
        cmd.spawn()
    }
        .map_err(|e| format!("Failed to start Python server: {}. Make sure Python is installed and in PATH.", e))?;
    
    // Wait for server to start
    println!("Waiting for server to start...");
    thread::sleep(Duration::from_secs(5));
    
    // Check if the process is still running
    match child.try_wait() {
        Ok(Some(status)) => {
            // Process exited, capture output for debugging
            let mut stdout_str = String::new();
            let mut stderr_str = String::new();
            
            if let Some(mut stdout) = child.stdout.take() {
                use std::io::Read;
                let _ = stdout.read_to_string(&mut stdout_str);
            }
            if let Some(mut stderr) = child.stderr.take() {
                use std::io::Read;
                let _ = stderr.read_to_string(&mut stderr_str);
            }
            
            return Err(format!(
                "Python process exited early with status: {}\n\nSTDOUT:\n{}\n\nSTDERR:\n{}",
                status, stdout_str, stderr_str
            ));
        }
        Ok(None) => {
            // Process is still running, good
        }
        Err(e) => {
            return Err(format!("Failed to check process status: {}", e));
        }
    }
    
    // Check if server is responding with multiple attempts
    let mut is_running = false;
    for attempt in 1..=20 {
        println!("Checking server availability (attempt {}/20)...", attempt);
        match reqwest::blocking::get("http://localhost:8000/api/health") {
            Ok(response) => {
                println!("Server responded with status: {}", response.status());
                if response.status().is_success() {
                    is_running = true;
                    break;
                }
            }
            Err(e) => {
                println!("Server check failed: {}", e);
                // Also try the root endpoint
                if let Ok(response) = reqwest::blocking::get("http://localhost:8000") {
                    if response.status().is_success() {
                        println!("Root endpoint responded successfully");
                        is_running = true;
                        break;
                    }
                }
            }
        }
        if attempt < 20 {
            thread::sleep(Duration::from_secs(2));
        }
    }
    
    if !is_running {
        return Err("Python server started but not responding properly on port 8000. Check for errors in the Python console.".to_string());
    }
    
    println!("Python server started successfully");
    Ok(child)
}

fn wait_for_server_ready(app_handle: &AppHandle) -> Result<(), String> {
    println!("Waiting for server to be fully ready...");
    
    // Send initial status
    let _ = app_handle.emit("splash-status", SplashStatus {
        message: "Starting Python server...".to_string(),
        progress: Some(10.0),
        error: false,
    });
    
    // Wait a bit more for server initialization
    thread::sleep(Duration::from_secs(2));
    
    let _ = app_handle.emit("splash-status", SplashStatus {
        message: "Initializing server components...".to_string(),
        progress: Some(30.0),
        error: false,
    });
    
    // Try to fetch the main page
    for attempt in 1..=10 {
        let progress = 30.0 + (attempt as f32 * 6.0);
        
        let _ = app_handle.emit("splash-status", SplashStatus {
            message: "Checking server health...".to_string(),
            progress: Some(progress),
            error: false,
        });
        
        match reqwest::blocking::get("http://localhost:8000") {
            Ok(response) => {
                if response.status().is_success() {
                    println!("Server is fully ready!");
                    
                    let _ = app_handle.emit("splash-status", SplashStatus {
                        message: "Loading application...".to_string(),
                        progress: Some(95.0),
                        error: false,
                    });
                    
                    thread::sleep(Duration::from_millis(500));
                    return Ok(());
                }
            }
            Err(_) => {}
        }
        thread::sleep(Duration::from_secs(1));
    }
    
    let _ = app_handle.emit("splash-status", SplashStatus {
        message: "Server failed to start. Please check the logs.".to_string(),
        progress: None,
        error: true,
    });
    
    Err("Server failed to become fully ready".to_string())
}

fn stop_python_server(mut child: Child) {
    println!("Stopping Python server...");
    
    #[cfg(target_os = "windows")]
    {
        // On Windows, we need to kill the process tree
        let _ = Command::new("taskkill")
            .args(&["/PID", &child.id().to_string(), "/T", "/F"])
            .output();
    }
    
    #[cfg(not(target_os = "windows"))]
    {
        // On Unix-like systems, send SIGTERM
        let _ = child.kill();
    }
    
    let _ = child.wait();
    println!("Python server stopped");
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Get splash window from configuration and show it
            let splash_window = app.get_webview_window("splash").unwrap();
            
            // Load splash screen HTML content directly
            let splash_html = r#"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trade Journal - Loading</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            overflow: hidden;
            user-select: none;
        }
        .splash-container { text-align: center; padding: 2rem; }
        .logo {
            width: 80px; height: 80px; margin: 0 auto 1rem;
            background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
            border-radius: 20px; display: flex; align-items: center; justify-content: center;
            font-size: 2.5rem; font-weight: bold;
            box-shadow: 0 10px 25px rgba(59, 130, 246, 0.3);
        }
        .app-title {
            font-size: 1.75rem; font-weight: 700; margin-bottom: 2rem;
            background: linear-gradient(to right, #3b82f6, #8b5cf6);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .loader {
            width: 50px; height: 50px; margin: 0 auto 2rem; position: relative;
        }
        .loader-circle {
            position: absolute; width: 100%; height: 100%;
            border: 3px solid transparent; border-top-color: #3b82f6;
            border-radius: 50%; animation: spin 1.2s linear infinite;
        }
        .status-text {
            font-size: 0.875rem; color: #94a3b8; min-height: 1.2rem;
        }
        .error-text { color: #ef4444; font-weight: 500; }
        .progress-bar {
            width: 200px; height: 2px; background: rgba(148, 163, 184, 0.1);
            border-radius: 1px; margin: 1rem auto 0; overflow: hidden;
        }
        .progress-fill {
            height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6);
            border-radius: 1px; width: 0%; transition: width 0.3s ease;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="splash-container">
        <div class="logo">TJ</div>
        <h1 class="app-title">Trade Journal</h1>
        <div class="loader"><div class="loader-circle"></div></div>
        <div class="status-text" id="status-text">Starting application...</div>
        <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
    </div>
    <script>
        if (window.__TAURI__) {
            window.__TAURI__.event.listen('splash-status', (event) => {
                const statusText = document.getElementById('status-text');
                const progressFill = document.getElementById('progress-fill');
                
                if (event.payload.error) {
                    statusText.innerHTML = '<span class="error-text">' + event.payload.message + '</span>';
                    document.querySelector('.loader').style.display = 'none';
                } else {
                    statusText.textContent = event.payload.message;
                    if (event.payload.progress !== undefined) {
                        progressFill.style.width = event.payload.progress + '%';
                    }
                }
            });
        }
    </script>
</body>
</html>
            "#;
            
            let _ = splash_window.eval(&format!("document.open(); document.write(`{}`); document.close();", splash_html.replace('`', "\\`")));
            let _ = splash_window.show();
            
            // Start Python server after app is initialized
            let python_child = match start_python_server(&app.handle()) {
                Ok(child) => {
                    // Update splash status
                    let _ = app.emit("splash-status", SplashStatus {
                        message: "Python server started successfully".to_string(),
                        progress: Some(20.0),
                        error: false,
                    });
                    child
                },
                Err(e) => {
                    eprintln!("Error starting Python server: {}", e);
                    
                    // Show error in splash screen
                    let _ = app.emit("splash-status", SplashStatus {
                        message: format!("Failed to start Python server: {}", e),
                        progress: None,
                        error: true,
                    });
                    
                    // Keep splash open for a while to show error
                    thread::sleep(Duration::from_secs(10));
                    
                    std::process::exit(1);
                }
            };

            let server_state = PythonServerState {
                child: Mutex::new(Some(python_child)),
            };
            
            app.manage(server_state);

            let main_window = app.get_webview_window("main").unwrap();
            
            // Wait for server to be ready, then show main window and close splash
            let main_window_clone = main_window.clone();
            let splash_window_clone = splash_window.clone();
            let app_handle_clone = app.handle().clone();
            
            thread::spawn(move || {
                match wait_for_server_ready(&app_handle_clone) {
                    Ok(_) => {
                        // Close splash and show main window
                        let _ = splash_window_clone.close();
                        let _ = main_window_clone.show();
                    }
                    Err(e) => {
                        // Update splash with error
                        let _ = app_handle_clone.emit("splash-status", SplashStatus {
                            message: format!("Failed to start: {}", e),
                            progress: None,
                            error: true,
                        });
                        
                        // Keep splash open to show error
                        thread::sleep(Duration::from_secs(5));
                    }
                }
            });
            
            // Set up close handler to stop Python server
            let app_handle = app.handle().clone();
            main_window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { .. } = event {
                    let state = app_handle.state::<PythonServerState>();
                    if let Ok(mut child_guard) = state.child.lock() {
                        if let Some(child) = child_guard.take() {
                            stop_python_server(child);
                        }
                    };
                }
            });
            
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn main() {
    run();
}