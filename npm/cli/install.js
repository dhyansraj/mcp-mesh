"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const child_process = require("child_process");

const VERSION = require("./package.json").version;

// Platform mappings matching Go's GOOS/GOARCH (Linux and macOS only)
const knownPlatforms = {
  "darwin arm64": "@mcpmesh/cli-darwin-arm64",
  "darwin x64": "@mcpmesh/cli-darwin-x64",
  "linux arm64": "@mcpmesh/cli-linux-arm64",
  "linux x64": "@mcpmesh/cli-linux-x64",
};

// Binaries to install
const BINARIES = [
  { name: "meshctl", required: true },
  { name: "mcp-mesh-registry", required: true },
];

function getPlatformPackage() {
  const platformKey = `${process.platform} ${os.arch()}`;
  const pkg = knownPlatforms[platformKey];

  if (!pkg) {
    console.error(`[mcp-mesh] Unsupported platform: ${platformKey}`);
    console.error(`[mcp-mesh] Supported platforms: ${Object.keys(knownPlatforms).join(", ")}`);
    console.error(`[mcp-mesh] You can build from source: https://github.com/dhyansraj/mcp-mesh`);
    process.exit(1);
  }

  return pkg;
}

function getBinaryPath(pkg, binaryName) {
  const subpath = `bin/${binaryName}`;

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

function downloadFromNpm(pkg) {
  const installDir = path.join(__dirname, ".npm-install-temp");

  console.error(`[mcp-mesh] Platform package ${pkg} not found in node_modules`);
  console.error(`[mcp-mesh] Installing ${pkg}@${VERSION}...`);

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

    return path.join(installDir, "node_modules", pkg);
  } catch (e) {
    console.error(`[mcp-mesh] Failed to install ${pkg}:`, e.message);
    console.error(`[mcp-mesh] You can install manually from: https://github.com/dhyansraj/mcp-mesh/releases`);

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

function validateBinary(binPath, binaryName) {
  try {
    const result = child_process
      .execFileSync(binPath, ["--version"], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 10000,
      })
      .toString()
      .trim();

    console.log(`[mcp-mesh] Installed ${binaryName} ${result}`);
    return true;
  } catch (e) {
    // Version command might not exist, try --help
    try {
      child_process.execFileSync(binPath, ["--help"], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 10000,
      });
      console.log(`[mcp-mesh] Installed ${binaryName} successfully`);
      return true;
    } catch (e2) {
      console.error(`[mcp-mesh] Binary validation failed for ${binaryName}:`, e.message);
      return false;
    }
  }
}

async function install() {
  const pkg = getPlatformPackage();
  let needsCleanup = false;
  let pkgDir = null;

  console.log(`[mcp-mesh] Installing for ${process.platform} ${os.arch()}...`);

  // Check if any binary exists from optionalDependencies
  const testBinPath = getBinaryPath(pkg, "meshctl");
  if (!testBinPath) {
    // Need to download the package
    pkgDir = downloadFromNpm(pkg);
    needsCleanup = true;
  }

  let installedCount = 0;

  for (const binary of BINARIES) {
    const binaryName = binary.name;

    // Get source path
    let sourcePath;
    if (pkgDir) {
      sourcePath = path.join(pkgDir, "bin", binaryName);
    } else {
      sourcePath = getBinaryPath(pkg, binaryName);
    }

    // Check if binary exists in package
    if (!sourcePath || !fs.existsSync(sourcePath)) {
      if (binary.required) {
        console.error(`[mcp-mesh] Required binary ${binaryName} not found`);
        process.exit(1);
      } else {
        console.log(`[mcp-mesh] Optional binary ${binaryName} not available for this platform`);
        continue;
      }
    }

    // Target path in our package's bin directory
    const targetPath = path.join(__dirname, "bin", binaryName);

    // Copy binary to target location
    copyBinaryToTarget(sourcePath, targetPath);

    // Validate the binary works
    if (validateBinary(targetPath, binaryName)) {
      installedCount++;
    }
  }

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

  console.log(`[mcp-mesh] Installed ${installedCount} binaries`);
  console.log(`[mcp-mesh] Run 'meshctl --help' to get started`);
  console.log(`[mcp-mesh] Run 'mcp-mesh-registry --help' for registry options`);
}

// Run installation
install().catch((e) => {
  console.error("[mcp-mesh] Installation failed:", e.message);
  process.exit(1);
});
