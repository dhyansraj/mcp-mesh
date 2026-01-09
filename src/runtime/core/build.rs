//! Build script for MCP Mesh Core.
//!
//! Generates C header file for FFI bindings using cbindgen.
//! Sets up napi-rs for TypeScript bindings.

use std::env;
use std::path::PathBuf;

fn main() {
    // napi-rs build setup (for TypeScript bindings)
    #[cfg(feature = "typescript")]
    napi_build::setup();

    // Always track these env vars so Cargo re-runs build.rs when they change
    println!("cargo:rerun-if-env-changed=MCP_MESH_GENERATE_FFI_HEADER");
    println!("cargo:rerun-if-env-changed=CARGO_FEATURE_FFI");

    // Only generate C bindings when the ffi feature is enabled
    // or when explicitly requested via environment variable
    let ffi_enabled = env::var("CARGO_FEATURE_FFI").is_ok()
        || env::var("MCP_MESH_GENERATE_FFI_HEADER").is_ok();

    if !ffi_enabled {
        return;
    }

    let crate_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let crate_dir = PathBuf::from(crate_dir);

    // Output directory for the header
    let include_dir = crate_dir.join("include");
    std::fs::create_dir_all(&include_dir).expect("Failed to create include directory");

    let header_path = include_dir.join("mcp_mesh_core.h");

    // Load cbindgen config (best-effort, fall back to defaults on error)
    let config_path = crate_dir.join("cbindgen.toml");
    let config = if config_path.exists() {
        match cbindgen::Config::from_file(&config_path) {
            Ok(cfg) => cfg,
            Err(e) => {
                println!("cargo:warning=Failed to load cbindgen.toml: {}, using defaults", e);
                cbindgen::Config::default()
            }
        }
    } else {
        cbindgen::Config::default()
    };

    // Generate the header
    match cbindgen::Builder::new()
        .with_crate(&crate_dir)
        .with_config(config)
        .generate()
    {
        Ok(bindings) => {
            bindings.write_to_file(&header_path);
            println!("cargo:warning=Generated C header: {}", header_path.display());
        }
        Err(e) => {
            // Don't fail the build, just warn
            println!("cargo:warning=Failed to generate C header: {}", e);
        }
    }

    // Tell Cargo to re-run if these files change
    println!("cargo:rerun-if-changed=src/ffi.rs");
    println!("cargo:rerun-if-changed=cbindgen.toml");
}
