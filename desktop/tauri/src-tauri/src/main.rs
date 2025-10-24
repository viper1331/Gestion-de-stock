#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use once_cell::sync::Lazy;
use tauri::{Manager, Runtime};

static BACKEND: Lazy<Mutex<Option<Child>>> = Lazy::new(|| Mutex::new(None));

fn spawn_backend() {
    let mut guard = BACKEND.lock().expect("lock backend process");
    if guard.is_some() {
        return;
    }
    let child = Command::new("python")
        .args(["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .ok();
    *guard = child;
}

fn kill_backend() {
    if let Some(child) = BACKEND.lock().expect("lock backend process").as_mut() {
        let _ = child.kill();
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            spawn_backend();
            let app_handle = app.handle();
            app_handle.listen_global("tauri://close-requested", move |_| {
                kill_backend();
            });
            Ok(())
        })
        .on_window_event(|event| {
            if let tauri::WindowEvent::Destroyed = event.event() {
                kill_backend();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
