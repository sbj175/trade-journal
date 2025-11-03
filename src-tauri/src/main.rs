#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, AppHandle};
use std::thread;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
mod native_splash {
    use std::ptr::null_mut;
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use winapi::um::winuser::{
        CreateWindowExW, ShowWindow, UpdateWindow, DefWindowProcW, RegisterClassExW, 
        LoadCursorW, BeginPaint, EndPaint, FillRect, GetClientRect,
        WS_OVERLAPPED, WS_CAPTION, WS_SYSMENU, WS_VISIBLE,
        SW_SHOW, IDC_ARROW, CS_HREDRAW, CS_VREDRAW, WM_PAINT, WM_DESTROY,
        WNDCLASSEXW, PAINTSTRUCT
    };
    use winapi::um::wingdi::{RGB, CreateSolidBrush, TextOutW, SetBkColor, SetTextColor};
    use winapi::um::libloaderapi::GetModuleHandleW;
    use winapi::shared::windef::{HWND, RECT};
    use winapi::shared::minwindef::{UINT, WPARAM, LPARAM, LRESULT};
    use std::sync::{Arc, Mutex};

    static mut GLOBAL_STATUS: Option<Arc<Mutex<String>>> = None;
    static mut GLOBAL_PROGRESS: Option<Arc<Mutex<u32>>> = None;
    
    #[derive(Clone)]
    pub struct NativeSplash {
        hwnd: HWND,
        status_text: Arc<Mutex<String>>,
        progress: Arc<Mutex<u32>>,
    }
    
    // Make NativeSplash thread-safe
    unsafe impl Send for NativeSplash {}
    unsafe impl Sync for NativeSplash {}

    impl NativeSplash {
        pub fn new() -> Result<Self, String> {
            unsafe {
                let h_instance = GetModuleHandleW(null_mut());
                let class_name = to_wide_string("TradeSplashWindow");
                let window_title = to_wide_string("Trade Journal");

                // Register window class
                let wnd_class = WNDCLASSEXW {
                    cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
                    style: CS_HREDRAW | CS_VREDRAW,
                    lpfnWndProc: Some(window_proc),
                    cbClsExtra: 0,
                    cbWndExtra: 0,
                    hInstance: h_instance,
                    hIcon: null_mut(),
                    hCursor: LoadCursorW(null_mut(), IDC_ARROW),
                    hbrBackground: CreateSolidBrush(RGB(30, 41, 59)), // Dark background
                    lpszMenuName: null_mut(),
                    lpszClassName: class_name.as_ptr(),
                    hIconSm: null_mut(),
                };

                RegisterClassExW(&wnd_class);

                // Create window - larger size for better visibility
                let screen_width = winapi::um::winuser::GetSystemMetrics(winapi::um::winuser::SM_CXSCREEN);
                let screen_height = winapi::um::winuser::GetSystemMetrics(winapi::um::winuser::SM_CYSCREEN);
                let window_width = 600;
                let window_height = 350;
                let x = (screen_width - window_width) / 2;
                let y = (screen_height - window_height) / 2;
                
                let hwnd = CreateWindowExW(
                    0,
                    class_name.as_ptr(),
                    window_title.as_ptr(),
                    WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                    x, y, // centered position
                    window_width, window_height, // larger size
                    null_mut(),
                    null_mut(),
                    h_instance,
                    null_mut(),
                );

                if hwnd.is_null() {
                    return Err("Failed to create splash window".to_string());
                }

                ShowWindow(hwnd, SW_SHOW);
                UpdateWindow(hwnd);

                let status_text = Arc::new(Mutex::new("Starting...".to_string()));
                let progress = Arc::new(Mutex::new(0u32));
                GLOBAL_STATUS = Some(status_text.clone());
                GLOBAL_PROGRESS = Some(progress.clone());
                
                Ok(NativeSplash {
                    hwnd,
                    status_text,
                    progress,
                })
            }
        }

        pub fn update_status(&self, status: &str) {
            if let Ok(mut text) = self.status_text.lock() {
                *text = status.to_string();
            }
            
            unsafe {
                // Force window to repaint
                winapi::um::winuser::InvalidateRect(self.hwnd, null_mut(), 1);
                UpdateWindow(self.hwnd);
            }
        }

        pub fn update_status_with_progress(&self, status: &str, progress_percent: u32) {
            if let Ok(mut text) = self.status_text.lock() {
                *text = status.to_string();
            }
            if let Ok(mut progress) = self.progress.lock() {
                *progress = progress_percent.min(100);
            }
            
            unsafe {
                // Force window to repaint
                winapi::um::winuser::InvalidateRect(self.hwnd, null_mut(), 1);
                UpdateWindow(self.hwnd);
            }
        }

        pub fn close(&self) {
            unsafe {
                // Hide the window immediately for instant visual feedback
                winapi::um::winuser::ShowWindow(self.hwnd, winapi::um::winuser::SW_HIDE);
                // Then destroy the window
                winapi::um::winuser::DestroyWindow(self.hwnd);
            }
        }
    }

    unsafe extern "system" fn window_proc(
        hwnd: HWND,
        msg: UINT,
        wparam: WPARAM,
        lparam: LPARAM,
    ) -> LRESULT {
        match msg {
            WM_PAINT => {
                let mut ps = PAINTSTRUCT {
                    hdc: null_mut(),
                    fErase: 0,
                    rcPaint: RECT { left: 0, top: 0, right: 0, bottom: 0 },
                    fRestore: 0,
                    fIncUpdate: 0,
                    rgbReserved: [0; 32],
                };
                
                let hdc = BeginPaint(hwnd, &mut ps);
                
                // Set colors
                SetBkColor(hdc, RGB(30, 41, 59)); // Dark background
                SetTextColor(hdc, RGB(241, 245, 249)); // Light text
                
                // Get window rect
                let mut rect = RECT { left: 0, top: 0, right: 0, bottom: 0 };
                GetClientRect(hwnd, &mut rect);
                
                // Fill background
                let brush = CreateSolidBrush(RGB(30, 41, 59));
                FillRect(hdc, &rect, brush);
                
                // Create larger fonts - negative values for proper scaling
                let title_font = winapi::um::wingdi::CreateFontW(
                    -32, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 0, 0,
                    to_wide_string("Segoe UI").as_ptr()
                );
                let status_font = winapi::um::wingdi::CreateFontW(
                    -18, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                    to_wide_string("Segoe UI").as_ptr()
                );
                
                // Draw title with larger font
                let old_font = winapi::um::wingdi::SelectObject(hdc, title_font as *mut winapi::ctypes::c_void);
                let title = to_wide_string("Trade Journal");
                TextOutW(hdc, 180, 50, title.as_ptr(), title.len() as i32 - 1);
                
                // Switch to status font
                winapi::um::wingdi::SelectObject(hdc, status_font as *mut winapi::ctypes::c_void);
                
                // Draw dynamic status text
                let status_text = if let Some(ref global_status) = GLOBAL_STATUS {
                    if let Ok(status) = global_status.lock() {
                        status.clone()
                    } else {
                        "Loading...".to_string()
                    }
                } else {
                    "Starting...".to_string()
                };
                
                let status = to_wide_string(&status_text);
                TextOutW(hdc, 50, 110, status.as_ptr(), status.len() as i32 - 1);
                
                // Restore original font and clean up
                winapi::um::wingdi::SelectObject(hdc, old_font);
                winapi::um::wingdi::DeleteObject(title_font as *mut winapi::ctypes::c_void);
                winapi::um::wingdi::DeleteObject(status_font as *mut winapi::ctypes::c_void);
                
                // Draw progress bar
                let progress_value = if let Some(ref global_progress) = GLOBAL_PROGRESS {
                    if let Ok(progress) = global_progress.lock() {
                        *progress
                    } else {
                        0
                    }
                } else {
                    0
                };
                
                // Progress bar background (positioned below status text) - larger size
                let progress_y = 160;
                let progress_x = 100; // Centered
                let progress_width = 400;
                let progress_height = 12;
                
                // Background
                let bg_brush = CreateSolidBrush(RGB(71, 85, 105)); // Slate-600
                let bg_rect = RECT {
                    left: progress_x,
                    top: progress_y,
                    right: progress_x + progress_width,
                    bottom: progress_y + progress_height,
                };
                FillRect(hdc, &bg_rect, bg_brush);
                
                // Progress fill
                if progress_value > 0 {
                    let fill_width = (progress_width as f32 * (progress_value as f32 / 100.0)) as i32;
                    let fill_brush = CreateSolidBrush(RGB(59, 130, 246)); // Blue-500
                    let fill_rect = RECT {
                        left: progress_x,
                        top: progress_y,
                        right: progress_x + fill_width,
                        bottom: progress_y + progress_height,
                    };
                    FillRect(hdc, &fill_rect, fill_brush);
                }
                
                EndPaint(hwnd, &ps);
                0
            }
            WM_DESTROY => {
                0
            }
            _ => DefWindowProcW(hwnd, msg, wparam, lparam),
        }
    }

    fn to_wide_string(s: &str) -> Vec<u16> {
        OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect()
    }
}

struct PythonServerState {
    child: Mutex<Option<Child>>,
}


#[cfg(windows)]
fn check_python_startup_indicators(working_dir: &std::path::Path) -> (bool, String) {
    // Check for various startup indicators
    let db_file = working_dir.join("trade_journal.db");
    let pid_file = working_dir.join("tauri_python_server.log");
    
    if db_file.exists() {
        if let Ok(metadata) = std::fs::metadata(&db_file) {
            if let Ok(modified) = metadata.modified() {
                if let Ok(elapsed) = modified.elapsed() {
                    if elapsed.as_secs() < 10 {
                        return (true, "Database recently accessed".to_string());
                    }
                }
            }
        }
    }
    
    if pid_file.exists() {
        if let Ok(contents) = std::fs::read_to_string(&pid_file) {
            if contents.contains("Starting Trade Journal") {
                return (true, "FastAPI startup detected".to_string());
            }
            if contents.contains("INFO") && contents.len() > 100 {
                return (true, "Server logging active".to_string());
            }
        }
    }
    
    (false, "Starting up...".to_string())
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
            println!("Starting Trade Journal application...");
            
            // Create native splash window (Windows only)
            #[cfg(windows)]
            let splash = match native_splash::NativeSplash::new() {
                Ok(splash) => {
                    println!("Native splash window created");
                    Some(splash)
                },
                Err(e) => {
                    eprintln!("Failed to create splash window: {}", e);
                    None
                }
            };
            
            #[cfg(not(windows))]
            let _splash: Option<()> = None;
            
            // Update splash status and start Python server with granular progress
            #[cfg(windows)]
            if let Some(ref splash) = splash {
                splash.update_status_with_progress("Finding working directory...", 5);
                thread::sleep(Duration::from_millis(100));
                splash.update_status_with_progress("Checking for app.py...", 8);
                thread::sleep(Duration::from_millis(100));
                splash.update_status_with_progress("Looking for Python environment...", 12);
                thread::sleep(Duration::from_millis(100));
                splash.update_status_with_progress("Starting Python process...", 15);
            }
            
            let python_child = match start_python_server(&app.handle()) {
                Ok(child) => {
                    println!("Python server started successfully");
                    #[cfg(windows)]
                    if let Some(ref splash) = splash {
                        // Get working directory for startup monitoring
                        let working_dir = if let Ok(resource_dir) = app.handle().path().resource_dir() {
                            if resource_dir.join("app.py").exists() {
                                resource_dir
                            } else {
                                std::env::current_dir().unwrap_or_default()
                            }
                        } else {
                            std::env::current_dir().unwrap_or_default()
                        };
                        
                        // Detailed startup phase simulation with real indicator checks
                        splash.update_status_with_progress("Python process started...", 18);
                        thread::sleep(Duration::from_millis(300));
                        
                        splash.update_status_with_progress("Loading Python modules...", 20);
                        thread::sleep(Duration::from_millis(800));
                        
                        splash.update_status_with_progress("Initializing FastAPI...", 23);
                        thread::sleep(Duration::from_millis(600));
                        
                        // Check for actual startup indicators during database phase
                        splash.update_status_with_progress("Setting up database...", 26);
                        for i in 0..9 {
                            thread::sleep(Duration::from_millis(100));
                            let (detected, status) = check_python_startup_indicators(&working_dir);
                            if detected {
                                splash.update_status_with_progress(&status, 26 + i);
                                break;
                            }
                        }
                        
                        splash.update_status_with_progress("Configuring middleware...", 30);
                        thread::sleep(Duration::from_millis(400));
                        
                        splash.update_status_with_progress("Registering API routes...", 33);
                        thread::sleep(Duration::from_millis(500));
                        
                        splash.update_status_with_progress("Binding to port 8000...", 36);
                        thread::sleep(Duration::from_millis(600));
                        
                        splash.update_status_with_progress("Server startup complete", 38);
                        thread::sleep(Duration::from_millis(400));
                    }
                    child
                },
                Err(e) => {
                    eprintln!("Error starting Python server: {}", e);
                    #[cfg(windows)]
                    if let Some(ref splash) = splash {
                        splash.update_status(&format!("Error: {}", e));
                        thread::sleep(Duration::from_secs(3));
                    }
                    std::process::exit(1);
                }
            };

            let server_state = PythonServerState {
                child: Mutex::new(Some(python_child)),
            };
            
            app.manage(server_state);

            let main_window = app.get_webview_window("main").unwrap();
            
            // Wait for server to be fully ready, then show main window
            let main_window_clone = main_window.clone();
            
            #[cfg(windows)]
            let splash_for_thread = splash.clone();
            
            thread::spawn(move || {
                // Update splash during server checks
                for attempt in 1..=15 {
                    #[cfg(windows)]
                    if let Some(ref splash) = splash_for_thread {
                        let progress = 38 + ((attempt * 52) / 15); // Progress from 38% to 90%
                        let status = match attempt {
                            1..=3 => format!("Waiting for server to bind... ({}/15)", attempt),
                            4..=7 => format!("Testing HTTP endpoints... ({}/15)", attempt),
                            8..=12 => format!("Verifying database connection... ({}/15)", attempt),
                            _ => format!("Final connectivity check... ({}/15)", attempt),
                        };
                        splash.update_status_with_progress(&status, progress);
                    }
                    
                    println!("Checking server health (attempt {}/15)...", attempt);
                    
                    // Wait before first check
                    if attempt == 1 {
                        thread::sleep(Duration::from_secs(3));
                    }
                    
                    // Check login endpoint - returns 200 when server is ready (before authentication)
                    match reqwest::blocking::get("http://localhost:8000/login") {
                        Ok(response) => {
                            if response.status().is_success() {
                                println!("Server is fully ready!");
                                #[cfg(windows)]
                                if let Some(ref splash) = splash_for_thread {
                                    splash.update_status_with_progress("Connection established!", 95);
                                    thread::sleep(Duration::from_millis(200));
                                    splash.update_status_with_progress("Ready!", 100);
                                    thread::sleep(Duration::from_millis(300));
                                }

                                // Wait a bit longer to ensure server is fully ready
                                thread::sleep(Duration::from_secs(1));
                                let _ = main_window_clone.show();

                                // Close splash after main window is shown
                                #[cfg(windows)]
                                if let Some(ref splash) = splash_for_thread {
                                    thread::sleep(Duration::from_millis(200));
                                    splash.close();
                                }
                                return;
                            }
                        }
                        Err(_) => {
                            // Also try the root endpoint as fallback
                            if let Ok(response) = reqwest::blocking::get("http://localhost:8000/") {
                                // Accept 401 from root endpoint (authentication required) as sign server is ready
                                if response.status().is_success() || response.status() == reqwest::http::StatusCode::UNAUTHORIZED {
                                    println!("Root endpoint responded successfully");
                                    #[cfg(windows)]
                                    if let Some(ref splash) = splash_for_thread {
                                        splash.update_status_with_progress("Connection established!", 95);
                                        thread::sleep(Duration::from_millis(200));
                                        splash.update_status_with_progress("Ready!", 100);
                                        thread::sleep(Duration::from_millis(300));
                                    }
                                    
                                    thread::sleep(Duration::from_secs(1));
                                    let _ = main_window_clone.show();
                                    
                                    // Close splash after main window is shown
                                    #[cfg(windows)]
                                    if let Some(ref splash) = splash_for_thread {
                                        thread::sleep(Duration::from_millis(200));
                                        splash.close();
                                    }
                                    return;
                                }
                            }
                        }
                    }
                    // Break down the 2-second wait between attempts
                    if attempt < 15 {
                        for _sub_wait in 1..=4 {
                            thread::sleep(Duration::from_millis(500));
                            #[cfg(windows)]
                            if let Some(ref splash) = splash_for_thread {
                                let base_progress = 38 + ((attempt * 52) / 15);
                                let sub_progress = base_progress + (_sub_wait as u32) / 4; // Small increments during wait
                                splash.update_status_with_progress(&format!("Waiting before retry... ({}/15)", attempt), sub_progress);
                            }
                        }
                    }
                }
                
                // If we get here, server failed to start
                eprintln!("Failed to start server after 15 attempts");
                #[cfg(windows)]
                if let Some(ref splash) = splash_for_thread {
                    splash.update_status("Failed to start server");
                    thread::sleep(Duration::from_secs(3));
                }
                std::process::exit(1);
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