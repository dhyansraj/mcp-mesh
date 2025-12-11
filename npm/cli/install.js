"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const child_process = require("child_process");

const VERSION = require("./package.json").version;

// Platform mappings matching Go's GOOS/GOARCH
const knownPlatforms = {
  "darwin arm64": "@mcpmesh/cli-darwin-arm64",
  "darwin x64": "@mcpmesh/cli-darwin-x64",
  "linux arm64": "@mcpmesh/cli-linux-arm64",
  "linux x64": "@mcpmesh/cli-linux-x64",
  "win32 arm64": "@mcpmesh/cli-win32-arm64",
  "win32 x64": "@mcpmesh/cli-win32-x64",
};

function getPlatformPackage() {
  const platformKey = `${process.platform} ${os.arch()}`;
  const pkg = knownPlatforms[platformKey];

  if (!pkg) {
    console.error(`[meshctl] Unsupported platform: ${platformKey}`);
    console.error(`[meshctl] Supported platforms: ${Object.keys(knownPlatforms).join(", ")}`);
    console.error(`[meshctl] You can build from source: https://github.com/dhyansraj/mcp-mesh`);
    process.exit(1);
  }

  return {
    pkg,
    subpath: process.platform === "win32" ? "bin/meshctl.exe" : "bin/meshctl",
  };
}

function getBinaryPath(pkg, subpath) {
  // Try to find in node_modules (from optionalDependencies)
  const possiblePaths = [
    // Standard node_modules location
    path.join(__dirname, "..", pkg, subpath),
    // npm workspace location
    path.join(__dirname, "..", "..", pkg, subpath),
    // pnpm location
    path.join(__dirname, "..", "..", ".pnpm", "node_modules", pkg, subpath),
  ];

  for (const p of possiblePaths) {
    if (fs.existsSync(p)) {
      return p;
    }
  }

  // Try require.resolve as fallback
  try {
    return require.resolve(`${pkg}/${subpath}`);
  } catch (e) {
    return null;
  }
}

function downloadFromNpm(pkg, subpath) {
  const installDir = path.join(__dirname, ".npm-install-temp");

  console.error(`[meshctl] Platform package ${pkg} not found in node_modules`);
  console.error(`[meshctl] Installing ${pkg}@${VERSION}...`);

  try {
    // Clean up any previous failed install
    if (fs.existsSync(installDir)) {
      fs.rmSync(installDir, { recursive: true, force: true });
    }

    fs.mkdirSync(installDir, { recursive: true });
    fs.writeFileSync(path.join(installDir, "package.json"), JSON.stringify({ name: "temp" }));

    // Install the platform-specific package
    child_process.execSync(
      `npm install --loglevel=error --prefer-offline --no-audit --progress=false ${pkg}@${VERSION}`,
      {
        cwd: installDir,
        stdio: ["pipe", "pipe", "inherit"],
        timeout: 120000, // 2 minute timeout
      }
    );

    const installedPath = path.join(installDir, "node_modules", pkg, subpath);

    if (!fs.existsSync(installedPath)) {
      throw new Error(`Binary not found at expected path: ${installedPath}`);
    }

    return installedPath;
  } catch (e) {
    console.error(`[meshctl] Failed to install ${pkg}:`, e.message);
    console.error(`[meshctl] You can install manually from: https://github.com/dhyansraj/mcp-mesh/releases`);

    // Cleanup on error
    if (fs.existsSync(installDir)) {
      try {
        fs.rmSync(installDir, { recursive: true, force: true });
      } catch (cleanupErr) {
        // Ignore cleanup errors
      }
    }

    process.exit(1);
  }
}

function copyBinaryToTarget(sourcePath, targetPath) {
  // Ensure bin directory exists
  const binDir = path.dirname(targetPath);
  if (!fs.existsSync(binDir)) {
    fs.mkdirSync(binDir, { recursive: true });
  }

  // Remove existing target if it exists
  if (fs.existsSync(targetPath)) {
    fs.unlinkSync(targetPath);
  }

  // Try hard link first (more efficient, same inode)
  try {
    fs.linkSync(sourcePath, targetPath);
  } catch (e) {
    // Fall back to copy if hard link fails (e.g., cross-device)
    fs.copyFileSync(sourcePath, targetPath);
  }

  // Ensure executable permissions
  fs.chmodSync(targetPath, 0o755);
}

function validateBinary(binPath) {
  try {
    const result = child_process
      .execFileSync(binPath, ["--version"], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 10000,
      })
      .toString()
      .trim();

    console.log(`[meshctl] ✓ Installed meshctl ${result}`);
    return true;
  } catch (e) {
    // Version command might not exist, try --help
    try {
      child_process.execFileSync(binPath, ["--help"], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 10000,
      });
      console.log(`[meshctl] ✓ Installed meshctl successfully`);
      return true;
    } catch (e2) {
      console.error(`[meshctl] ⚠ Binary validation failed:`, e.message);
      return false;
    }
  }
}

async function install() {
  const { pkg, subpath } = getPlatformPackage();

  console.log(`[meshctl] Installing for ${process.platform} ${os.arch()}...`);

  // Check if binary already exists from optionalDependencies
  let binPath = getBinaryPath(pkg, subpath);
  let needsCleanup = false;

  if (!binPath) {
    binPath = downloadFromNpm(pkg, subpath);
    needsCleanup = true;
  }

  // Target path in our package's bin directory
  const targetBin = path.join(
    __dirname,
    "bin",
    process.platform === "win32" ? "meshctl.exe" : "meshctl"
  );

  // Copy binary to target location
  copyBinaryToTarget(binPath, targetBin);

  // Validate the binary works
  validateBinary(targetBin);

  // Clean up temporary install directory if we created one
  if (needsCleanup) {
    const installDir = path.join(__dirname, ".npm-install-temp");
    if (fs.existsSync(installDir)) {
      try {
        fs.rmSync(installDir, { recursive: true, force: true });
      } catch (e) {
        // Ignore cleanup errors
      }
    }
  }

  console.log(`[meshctl] Run 'meshctl --help' to get started`);
  console.log(`[meshctl] Run 'meshctl man' for comprehensive documentation`);
}

// Run installation
install().catch((e) => {
  console.error("[meshctl] Installation failed:", e.message);
  process.exit(1);
});
